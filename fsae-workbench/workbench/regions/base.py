"""Shared plumbing for the region algebra.

A *region* is a closed subset of R^3 together with an ``allow`` flag. The flag
splits two distinct notions that the rest of the package keeps carefully apart:

``contains``
    Is the point inside the region's geometric volume? The ``allow`` flag is
    irrelevant here.
``permits``
    Is the point inside the *allowable set* the region describes? For
    ``allow=True`` that is the volume; for ``allow=False`` it is the complement.

Everything is vectorised over ``(N, 3)`` float arrays because the optimizer
calls ``contains`` and ``clamp`` on thousands of candidate points per iteration.
"""

from __future__ import annotations

import fnmatch
from abc import abstractmethod
from typing import Any, Iterable

import numpy as np
from numpy.random import Generator
from numpy.typing import ArrayLike, NDArray
from pydantic import BaseModel, ConfigDict

#: Points within this distance of a boundary count as inside the volume (mm).
CONTAINS_TOL = 1e-9

#: How far past a boundary ``clamp`` pushes a point when escaping a denied
#: volume (mm). Comfortably larger than ``CONTAINS_TOL`` and far below any
#: physically meaningful length in a suspension model.
PUSH_EPS = 1e-6

#: Default iteration budget for composite clamping.
MAX_CLAMP_ITER = 64

#: Default rejection-sampling budget, as a multiple of the requested count.
SAMPLE_ATTEMPT_FACTOR = 200

#: Rejection sampling gives up below this acceptance rate even if the attempt
#: budget has not been exhausted, so a near-empty region fails fast.
MIN_ACCEPTANCE = 1e-4


class RegionError(RuntimeError):
    """Base class for every error raised by the region algebra."""


class EmptyRegionError(RegionError):
    """The region's volume is provably empty."""


class UnboundedRegionError(RegionError):
    """The region's volume has no finite axis-aligned bounding box."""


class SamplingError(RegionError):
    """Rejection sampling exhausted its budget without filling the request."""


class ClampError(RegionError):
    """``clamp(..., strict=True)`` could not place every point in the set."""


def as_points(p: ArrayLike) -> tuple[NDArray[np.float64], bool]:
    """Normalise ``(3,)`` or ``(N, 3)`` input to ``(N, 3)``.

    Returns the array plus a flag recording whether the caller passed a single
    point, so the public methods can hand back a scalar/``(3,)`` result.
    """
    arr = np.asarray(p, dtype=np.float64)
    if arr.ndim == 1:
        if arr.shape != (3,):
            raise ValueError(f"expected a (3,) point, got {arr.shape}")
        return arr.reshape(1, 3), True
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"expected an (N, 3) array of points, got {arr.shape}")
    return arr, False


def aabb_contains(
    lo: NDArray[np.float64],
    hi: NDArray[np.float64],
    pts: NDArray[np.float64],
    tol: float = CONTAINS_TOL,
) -> NDArray[np.bool_]:
    return np.all((pts >= lo - tol) & (pts <= hi + tol), axis=1)


def _nearest_valid(
    pts: NDArray[np.float64],
    candidates: list[NDArray[np.float64]],
    valid: list[NDArray[np.bool_]],
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Pick, per point, the nearest candidate flagged valid.

    Returns the chosen points and a mask of which rows found any valid
    candidate at all. Rows with no valid candidate keep their original value.
    """
    out = pts.copy()
    best = np.full(len(pts), np.inf)
    found = np.zeros(len(pts), dtype=bool)
    for cand, ok in zip(candidates, valid):
        d = np.linalg.norm(cand - pts, axis=1)
        take = ok & (d < best)
        out[take] = cand[take]
        best[take] = d[take]
        found |= ok
    return out, found


class RegionBase(BaseModel):
    """Common behaviour for every primitive and composite region."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str = ""
    allow: bool = True
    source: str = "user"
    applies_to: list[str] | None = None
    """Optional node-id globs this region constrains. ``None`` means every node.

    An additive extension to ``contracts.md``: rule-derived regions such as the
    wheelbase minimum only bind a subset of the hardpoints, and a region object
    with no scoping cannot express that.
    """

    # ---- geometry, implemented per concrete region --------------------------

    @abstractmethod
    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        """Membership of the geometric volume, ignoring ``allow``."""

    @abstractmethod
    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        """Nearest point inside the volume."""

    @abstractmethod
    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        """Nearest point outside the volume."""

    def _escape_candidates(
        self, pts: NDArray[np.float64]
    ) -> list[NDArray[np.float64]]:
        """Every plausible nearest-exterior projection, not just the closest.

        A composite needs the full set: the closest way out of a subtracted box
        is often blocked by one of the positive children, and the second
        closest is the real answer.
        """
        return [self._clamp_out(pts)]

    @abstractmethod
    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Axis-aligned bounding box of the volume as ``(min, max)``."""

    @abstractmethod
    def to_mesh(self) -> dict[str, Any]:
        """Viewport mesh payload. See ``to_viewport`` for the wrapper."""

    # ---- public API ---------------------------------------------------------

    def contains(self, p: ArrayLike) -> bool | NDArray[np.bool_]:
        pts, single = as_points(p)
        res = self._contains(pts)
        return bool(res[0]) if single else res

    def permits(self, p: ArrayLike) -> bool | NDArray[np.bool_]:
        """Membership of the *allowable* set, i.e. ``contains`` XOR ``allow``."""
        pts, single = as_points(p)
        res = self._contains(pts)
        if not self.allow:
            res = ~res
        return bool(res[0]) if single else res

    def clamp(self, p: ArrayLike, *, strict: bool = False) -> NDArray[np.float64]:
        """Nearest point inside the allowable set.

        For ``allow=False`` regions that means pushing the point *out* of the
        volume. Composite clamping is iterative and therefore approximate; pass
        ``strict=True`` to raise :class:`ClampError` instead of returning a
        best-effort point when the result is still outside the allowable set.
        """
        pts, single = as_points(p)
        out = self._clamp_into(pts) if self.allow else self._clamp_out(pts)
        if strict:
            ok = self._contains(out)
            if not self.allow:
                ok = ~ok
            if not ok.all():
                bad = np.flatnonzero(~ok).tolist()
                raise ClampError(
                    f"region {self.id!r}: no allowable point found for "
                    f"{len(bad)} of {len(pts)} inputs (rows {bad[:10]})"
                )
        return out[0] if single else out

    def sample(
        self,
        n: int,
        rng: Generator,
        *,
        attempt_factor: int = SAMPLE_ATTEMPT_FACTOR,
    ) -> NDArray[np.float64]:
        """Draw ``n`` approximately uniform points from the allowable set.

        The default implementation is rejection sampling against the volume's
        AABB. The attempt budget is bounded and exhaustion raises
        :class:`SamplingError` rather than looping forever.
        """
        if n < 0:
            raise ValueError("n must be non-negative")
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)
        if not self.allow:
            raise UnboundedRegionError(
                f"region {self.id!r} is allow=False; its allowable set is the "
                "unbounded complement of its volume and cannot be sampled "
                "uniformly. Intersect it with a bounded allow region first."
            )
        lo, hi = self.bounds()
        return self._rejection_sample(n, rng, lo, hi, attempt_factor)

    def _rejection_sample(
        self,
        n: int,
        rng: Generator,
        lo: NDArray[np.float64],
        hi: NDArray[np.float64],
        attempt_factor: int,
    ) -> NDArray[np.float64]:
        budget = max(n * attempt_factor, 1000)
        kept: list[NDArray[np.float64]] = []
        have = 0
        used = 0
        while have < n and used < budget:
            batch = min(max(n - have, 1) * 8, budget - used, 1 << 16)
            cand = rng.uniform(lo, hi, size=(batch, 3))
            good = cand[self._contains(cand)]
            used += batch
            if len(good):
                kept.append(good)
                have += len(good)
        if have < n:
            rate = have / used if used else 0.0
            raise SamplingError(
                f"region {self.id!r}: drew {have} of {n} requested points in "
                f"{used} attempts (acceptance {rate:.2e}). The region may be "
                "empty, degenerate, or vanishingly thin inside its AABB."
            )
        return np.concatenate(kept)[:n]

    def to_viewport(self) -> dict[str, Any]:
        """The region entry of the viewport payload in ``contracts.md``."""
        return {
            "id": self.id,
            "kind": self.kind,  # type: ignore[attr-defined]
            "allow": self.allow,
            "label": self.label,
            "mesh": self.to_mesh(),
        }

    # ---- misc ---------------------------------------------------------------

    def applies_to_node(self, node_id: str) -> bool:
        """Whether this region constrains ``node_id``.

        ``applies_to`` entries are ``fnmatch`` globs over payload node ids such
        as ``"lf.lca_outboard"``. A pattern prefixed with ``!`` excludes
        instead of including. A list of only exclusions means "every node
        except these"; otherwise a node must match at least one inclusion.
        """
        if self.applies_to is None:
            return True
        includes = [p for p in self.applies_to if not p.startswith("!")]
        excludes = [p[1:] for p in self.applies_to if p.startswith("!")]
        if any(fnmatch.fnmatch(node_id, pat) for pat in excludes):
            return False
        if not includes:
            return True
        return any(fnmatch.fnmatch(node_id, pat) for pat in includes)

    def walk(self) -> Iterable["RegionBase"]:
        """Yield this region and, for composites, every descendant."""
        yield self

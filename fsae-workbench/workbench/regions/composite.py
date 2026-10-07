"""Composite regions: union, intersection, difference.

Composite semantics are the subtle part of the algebra, so they are spelled out
here once and tested hard.

A child with ``allow=False`` is *subtractive* no matter which composite it sits
in. Splitting the children into positives (``allow=True``) and negatives
(``allow=False``), the composite's volume ``V`` is:

``union``
    ``(union of positive volumes) \\ (union of negative volumes)``
``intersection``
    ``(intersection of positive volumes) \\ (union of negative volumes)``
``difference``
    ``children[0].volume \\ (union of the remaining children's volumes)``.
    The ``allow`` flag of the children is ignored here: the operator already
    says which side of the subtraction each child is on.

With no positive children a union or intersection degenerates to the complement
of the negatives, which is unbounded; ``bounds`` and ``sample`` then fail
loudly instead of inventing a box.

The composite's own ``allow`` flag applies on top of ``V`` exactly as it does
for a primitive: ``permits = contains`` when ``allow`` is true, ``~contains``
otherwise.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from .base import (
    CONTAINS_TOL,
    MAX_CLAMP_ITER,
    PUSH_EPS,
    EmptyRegionError,
    RegionBase,
    RegionError,
    UnboundedRegionError,
    _nearest_valid,
)

#: Halvings used by the escape march. 50 takes a metre-scale bracket down to
#: well below a nanometre.
_BISECTION_STEPS = 50

#: Directions the escape march tries, before the per-child suggestions.
_AXIS_DIRS = [
    np.array(d, dtype=np.float64)
    for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
]


class Composite(RegionBase):
    """Shared behaviour for the three set operators."""

    children: list["AnyRegion"]  # type: ignore[name-defined] # noqa: F821

    @model_validator(mode="after")
    def _check_children(self) -> "Composite":
        if not self.children:
            raise ValueError(f"composite {self.id!r}: needs at least one child")
        return self

    @property
    def positive(self) -> list[RegionBase]:
        return [c for c in self.children if c.allow]

    @property
    def negative(self) -> list[RegionBase]:
        return [c for c in self.children if not c.allow]

    def walk(self) -> Iterable[RegionBase]:
        yield self
        for child in self.children:
            yield from child.walk()

    def _outside_negatives(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        ok = np.ones(len(pts), dtype=bool)
        for child in self.negative:
            ok &= ~child._contains(pts)
        return ok

    def _push_out_of_negatives(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        out = pts
        for child in self.negative:
            out = child._clamp_out(out)
        return out

    def _iterate(
        self,
        pts: NDArray[np.float64],
        into: list[RegionBase],
        out_of: list[RegionBase],
        max_iter: int = MAX_CLAMP_ITER,
    ) -> NDArray[np.float64]:
        """Alternating projection: pull into ``into``, push out of ``out_of``.

        Exact for a single constraint and convergent for intersections of
        convex sets; with subtracted volumes in the mix it is a heuristic that
        may stall, which is why ``clamp(strict=True)`` exists.
        """
        cur = pts.copy()
        best = cur.copy()
        best_d = np.full(len(pts), np.inf)
        for _ in range(max_iter):
            done = self._contains(cur)
            if done.any():
                d = np.linalg.norm(cur - pts, axis=1)
                take = done & (d < best_d)
                best[take] = cur[take]
                best_d[take] = d[take]
            if np.isfinite(best_d).all() and done.all():
                break
            for child in into:
                cur = child._clamp_into(cur)
            for child in out_of:
                cur = child._clamp_out(cur)
        unresolved = ~np.isfinite(best_d)
        best[unresolved] = cur[unresolved]
        return best

    def _repair_into(
        self,
        pts: NDArray[np.float64],
        into: list[RegionBase],
        out_of: list[RegionBase],
    ) -> NDArray[np.float64]:
        """Clamp into ``into`` while staying clear of ``out_of``.

        The plain alternating projection is tried first, then every individual
        way out of each subtracted child is tried as a seed. That second pass
        matters: the closest exit from a keep-out volume is frequently blocked
        by one of the positive children, so taking the first exit the keep-out
        offers lands the point outside the allowable set entirely.
        """
        base = self._iterate(pts, into, out_of)
        if not out_of:
            return base
        # Seed the escapes from the point projected into the positive children
        # as well as from the raw input: a point that never entered the
        # keep-out still has to leave it once the positives pull it in.
        projected = pts
        for child in into:
            projected = child._clamp_into(projected)
        cands = [base]
        valid = [self._contains(base)]
        for child in out_of:
            for seed in (*child._escape_candidates(pts),
                         *child._escape_candidates(projected)):
                cand = self._iterate(seed, into, out_of, max_iter=16)
                cands.append(cand)
                valid.append(self._contains(cand))
        chosen, found = _nearest_valid(pts, cands, valid)
        chosen[~found] = base[~found]
        return chosen

    def _escape_march(
        self,
        pts: NDArray[np.float64],
        dirs: list[NDArray[np.float64]],
        max_dist: float,
    ) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        """Find the nearest exit along each of ``dirs`` by bisection.

        Composite volumes are not convex, so there is no closed form for the
        nearest exterior point. Marching along a fixed direction and bisecting
        on ``contains`` is shape-agnostic, vectorised, and the result is
        verified before it is returned.
        """
        cands: list[NDArray[np.float64]] = []
        valid: list[NDArray[np.bool_]] = []
        for d in dirs:
            far = pts + max_dist * d
            reachable = ~self._contains(far)
            lo_t = np.zeros(len(pts))
            hi_t = np.full(len(pts), max_dist)
            for _ in range(_BISECTION_STEPS):
                mid = 0.5 * (lo_t + hi_t)
                inside = self._contains(pts + mid[:, None] * d)
                lo_t = np.where(inside, mid, lo_t)
                hi_t = np.where(inside, hi_t, mid)
            cand = pts + (hi_t + PUSH_EPS)[:, None] * d
            cands.append(cand)
            valid.append(reachable & ~self._contains(cand))
        return _nearest_valid(pts, cands, valid)

    def _march_distance(self, pts: NDArray[np.float64]) -> float:
        try:
            lo, hi = self.bounds()
        except RegionError:
            lo, hi = pts.min(axis=0), pts.max(axis=0)
        span = float(np.linalg.norm(hi - lo))
        reach = float(np.abs(pts - (lo + hi) / 2.0).max()) if len(pts) else 0.0
        return max(span + reach, 1.0) * 2.0

    def to_mesh(self) -> dict[str, Any]:
        return {
            "type": "group",
            "op": self.kind,  # type: ignore[attr-defined]
            "children": [
                {
                    "id": c.id,
                    "kind": c.kind,  # type: ignore[attr-defined]
                    "allow": c.allow,
                    "label": c.label,
                    "mesh": c.to_mesh(),
                }
                for c in self.children
            ],
        }


class Union(Composite):
    """Everything in any positive child, minus every negative child."""

    kind: Literal["union"] = "union"

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        pos = self.positive
        if pos:
            inside = np.zeros(len(pts), dtype=bool)
            for child in pos:
                inside |= child._contains(pts)
        else:
            inside = np.ones(len(pts), dtype=bool)
        return inside & self._outside_negatives(pts)

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        pos = self.positive
        if not pos:
            return self._push_out_of_negatives(pts)
        # Try each branch of the union independently, repair it against the
        # subtracted volumes, then keep the nearest branch that actually lands
        # inside. Projecting onto a union cannot be done by iteration alone.
        cands: list[NDArray[np.float64]] = []
        valid: list[NDArray[np.bool_]] = []
        for child in pos:
            cand = child._clamp_into(pts)
            if self.negative:
                cand = self._repair_into(cand, [child], self.negative)
            cands.append(cand)
            valid.append(self._contains(cand))
        chosen, found = _nearest_valid(pts, cands, valid)
        if not found.all():
            # No branch worked; fall back to the geometrically nearest branch
            # so the caller still gets a sensible best effort.
            fallback, _ = _nearest_valid(
                pts, cands, [np.ones(len(pts), dtype=bool)] * len(cands)
            )
            chosen[~found] = fallback[~found]
        already = self._contains(pts)
        chosen[already] = pts[already]
        return chosen

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        # Leaving a union means leaving every branch at once, and pushing out
        # of them in turn just bounces between overlapping branches forever.
        # March instead.
        out = pts.copy()
        inside = self._contains(pts)
        if not inside.any():
            return out
        chosen, found = self._escape_march(
            pts, _AXIS_DIRS, self._march_distance(pts)
        )
        take = inside & found
        out[take] = chosen[take]
        return out

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        pos = self.positive
        if not pos:
            raise UnboundedRegionError(
                f"union {self.id!r} has no allow=True child, so its volume is "
                "the unbounded complement of its exclusions"
            )
        los, his = zip(*(c.bounds() for c in pos))
        return np.min(np.stack(los), axis=0), np.max(np.stack(his), axis=0)


class Intersection(Composite):
    """Everything in all positive children, minus every negative child."""

    kind: Literal["intersection"] = "intersection"

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        inside = np.ones(len(pts), dtype=bool)
        for child in self.positive:
            inside &= child._contains(pts)
        return inside & self._outside_negatives(pts)

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        return self._repair_into(pts, self.positive, self.negative)

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        # Leaving an intersection only takes violating one constraint, so the
        # exact answer is the nearest single-constraint escape.
        cands: list[NDArray[np.float64]] = []
        valid: list[NDArray[np.bool_]] = []
        for child in self.positive:
            for cand in child._escape_candidates(pts):
                cands.append(cand)
                valid.append(~self._contains(cand))
        for child in self.negative:
            cand = child._clamp_into(pts)
            cands.append(cand)
            valid.append(~self._contains(cand))
        if not cands:
            return pts.copy()
        chosen, found = _nearest_valid(pts, cands, valid)
        outside = ~self._contains(pts)
        chosen[outside] = pts[outside]
        return chosen

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        pos = self.positive
        if not pos:
            raise UnboundedRegionError(
                f"intersection {self.id!r} has no allow=True child, so its "
                "volume is the unbounded complement of its exclusions"
            )
        los, his = zip(*(c.bounds() for c in pos))
        lo = np.max(np.stack(los), axis=0)
        hi = np.min(np.stack(his), axis=0)
        if np.any(lo > hi + CONTAINS_TOL):
            raise EmptyRegionError(
                f"intersection {self.id!r}: children have disjoint bounding boxes"
            )
        return lo, np.maximum(hi, lo)


class Difference(Composite):
    """``children[0]`` minus the union of the remaining children."""

    kind: Literal["difference"] = "difference"

    @model_validator(mode="after")
    def _check_arity(self) -> "Difference":
        if len(self.children) < 2:
            raise ValueError(
                f"difference {self.id!r}: needs a minuend and at least one subtrahend"
            )
        return self

    @property
    def minuend(self) -> RegionBase:
        return self.children[0]

    @property
    def subtrahends(self) -> list[RegionBase]:
        return self.children[1:]

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        inside = self.minuend._contains(pts)
        for child in self.subtrahends:
            inside &= ~child._contains(pts)
        return inside

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        return self._repair_into(pts, [self.minuend], self.subtrahends)

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        cands = list(self.minuend._escape_candidates(pts))
        cands += [c._clamp_into(pts) for c in self.subtrahends]
        valid = [~self._contains(c) for c in cands]
        chosen, _ = _nearest_valid(pts, cands, valid)
        outside = ~self._contains(pts)
        chosen[outside] = pts[outside]
        return chosen

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return self.minuend.bounds()
"""Primitive regions: axis-aligned box, oriented box, sphere, convex polytope."""

from __future__ import annotations

import functools
from typing import Any, Literal

import numpy as np
from numpy.random import Generator
from numpy.typing import NDArray
from pydantic import Field, field_validator, model_validator

from .base import (
    CONTAINS_TOL,
    PUSH_EPS,
    EmptyRegionError,
    RegionBase,
    RegionError,
    UnboundedRegionError,
    aabb_contains,
)

Vec3 = tuple[float, float, float]


def _box_escape_candidates(
    lo: NDArray[np.float64], hi: NDArray[np.float64], pts: NDArray[np.float64]
) -> list[NDArray[np.float64]]:
    """One candidate per face: the projection of each point through that face."""
    inside = aabb_contains(lo, hi, pts)
    out: list[NDArray[np.float64]] = []
    for axis in range(3):
        for bound, eps in ((lo[axis], -PUSH_EPS), (hi[axis], +PUSH_EPS)):
            cand = pts.copy()
            cand[inside, axis] = bound + eps
            out.append(cand)
    return out


def _box_clamp_out(
    lo: NDArray[np.float64], hi: NDArray[np.float64], pts: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Nearest point outside the box ``[lo, hi]`` for each row of ``pts``.

    Points already outside are returned untouched. Interior points leave
    through whichever of the six faces is closest.
    """
    out = pts.copy()
    inside = aabb_contains(lo, hi, pts)
    if not inside.any():
        return out
    sub = pts[inside]
    # Cost of escaping through the low/high face on each axis.
    cost_lo = sub - lo
    cost_hi = hi - sub
    cost = np.concatenate([cost_lo, cost_hi], axis=1)  # (n, 6)
    pick = np.argmin(cost, axis=1)
    axis = pick % 3
    high = pick >= 3
    rows = np.arange(len(sub))
    target = np.where(high, hi[axis] + PUSH_EPS, lo[axis] - PUSH_EPS)
    sub[rows, axis] = target
    out[inside] = sub
    return out


class Box(RegionBase):
    """Axis-aligned box, inclusive of its faces.

    Degenerate boxes (zero extent on one or more axes) are permitted; they
    behave as the plane/line/point they describe. ``sample`` on one will fail
    loudly because rejection sampling can never hit a measure-zero set.
    """

    kind: Literal["box"] = "box"
    min: Vec3
    max: Vec3

    @model_validator(mode="after")
    def _check_ordering(self) -> "Box":
        if any(a > b for a, b in zip(self.min, self.max)):
            raise ValueError(f"box {self.id!r}: min {self.min} exceeds max {self.max}")
        return self

    @functools.cached_property
    def _lo(self) -> NDArray[np.float64]:
        return np.asarray(self.min, dtype=np.float64)

    @functools.cached_property
    def _hi(self) -> NDArray[np.float64]:
        return np.asarray(self.max, dtype=np.float64)

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        return aabb_contains(self._lo, self._hi, pts)

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.clip(pts, self._lo, self._hi)

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        return _box_clamp_out(self._lo, self._hi, pts)

    def _escape_candidates(
        self, pts: NDArray[np.float64]
    ) -> list[NDArray[np.float64]]:
        return _box_escape_candidates(self._lo, self._hi, pts)

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return self._lo.copy(), self._hi.copy()

    def sample(self, n: int, rng: Generator, **kwargs: Any) -> NDArray[np.float64]:
        if not self.allow:
            return super().sample(n, rng, **kwargs)
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)
        return rng.uniform(self._lo, self._hi, size=(n, 3))

    def to_mesh(self) -> dict[str, Any]:
        return {"type": "box", "min": list(self.min), "max": list(self.max)}


class Sphere(RegionBase):
    """Closed ball."""

    kind: Literal["sphere"] = "sphere"
    center: Vec3
    radius: float = Field(gt=0.0)

    @functools.cached_property
    def _c(self) -> NDArray[np.float64]:
        return np.asarray(self.center, dtype=np.float64)

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        d = np.linalg.norm(pts - self._c, axis=1)
        return d <= self.radius + CONTAINS_TOL

    def _radial(
        self, pts: NDArray[np.float64], target: float, mask: NDArray[np.bool_]
    ) -> NDArray[np.float64]:
        out = pts.copy()
        if not mask.any():
            return out
        delta = pts[mask] - self._c
        dist = np.linalg.norm(delta, axis=1, keepdims=True)
        # A point exactly at the centre has no preferred escape direction;
        # +X is as good as any and keeps the result deterministic.
        degenerate = dist[:, 0] == 0.0
        delta = np.where(degenerate[:, None], np.array([1.0, 0.0, 0.0]), delta)
        dist = np.where(degenerate[:, None], 1.0, dist)
        out[mask] = self._c + delta / dist * target
        return out

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        outside = ~self._contains(pts)
        return self._radial(pts, self.radius, outside)

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        inside = self._contains(pts)
        return self._radial(pts, self.radius + PUSH_EPS, inside)

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        r = np.full(3, float(self.radius))
        return self._c - r, self._c + r

    def sample(self, n: int, rng: Generator, **kwargs: Any) -> NDArray[np.float64]:
        if not self.allow:
            return super().sample(n, rng, **kwargs)
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)
        # Normalised Gaussian directions times r * U^(1/3) is exactly uniform
        # in the ball, so no rejection loop is needed.
        d = rng.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        r = self.radius * rng.random(n) ** (1.0 / 3.0)
        return self._c + d * r[:, None]

    def to_mesh(self) -> dict[str, Any]:
        return {
            "type": "sphere",
            "center": list(self.center),
            "radius": float(self.radius),
        }


_UNIT_BOX_CORNERS = np.array(
    [
        [-1, -1, -1],
        [+1, -1, -1],
        [+1, +1, -1],
        [-1, +1, -1],
        [-1, -1, +1],
        [+1, -1, +1],
        [+1, +1, +1],
        [-1, +1, +1],
    ],
    dtype=np.float64,
)

_BOX_FACES = [
    (0, 2, 1),
    (0, 3, 2),
    (4, 5, 6),
    (4, 6, 7),
    (0, 1, 5),
    (0, 5, 4),
    (1, 2, 6),
    (1, 6, 5),
    (2, 3, 7),
    (2, 7, 6),
    (3, 0, 4),
    (3, 4, 7),
]


class OrientedBox(RegionBase):
    """Box with an arbitrary orientation.

    ``rotation`` is a row-major 3x3 matrix mapping local axes to world axes:
    ``world = rotation @ local + center``. It must be orthonormal.
    """

    kind: Literal["oriented_box"] = "oriented_box"
    center: Vec3
    half_extents: Vec3
    rotation: tuple[
        float, float, float, float, float, float, float, float, float
    ] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

    @field_validator("half_extents")
    @classmethod
    def _non_negative(cls, v: Vec3) -> Vec3:
        if any(h < 0 for h in v):
            raise ValueError(f"half_extents must be non-negative, got {v}")
        return v

    @model_validator(mode="after")
    def _check_orthonormal(self) -> "OrientedBox":
        r = np.asarray(self.rotation, dtype=np.float64).reshape(3, 3)
        if not np.allclose(r.T @ r, np.eye(3), atol=1e-6):
            raise ValueError(f"oriented box {self.id!r}: rotation is not orthonormal")
        return self

    @functools.cached_property
    def _r(self) -> NDArray[np.float64]:
        return np.asarray(self.rotation, dtype=np.float64).reshape(3, 3)

    @functools.cached_property
    def _c(self) -> NDArray[np.float64]:
        return np.asarray(self.center, dtype=np.float64)

    @functools.cached_property
    def _h(self) -> NDArray[np.float64]:
        return np.asarray(self.half_extents, dtype=np.float64)

    def _to_local(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        return (pts - self._c) @ self._r

    def _to_world(self, local: NDArray[np.float64]) -> NDArray[np.float64]:
        return local @ self._r.T + self._c

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        return aabb_contains(-self._h, self._h, self._to_local(pts))

    def _clamp_into(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        local = np.clip(self._to_local(pts), -self._h, self._h)
        return self._to_world(local)

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        local = self._to_local(pts)
        moved = _box_clamp_out(-self._h, self._h, local)
        out = pts.copy()
        changed = np.any(moved != local, axis=1)
        out[changed] = self._to_world(moved[changed])
        return out

    def _escape_candidates(
        self, pts: NDArray[np.float64]
    ) -> list[NDArray[np.float64]]:
        local = self._to_local(pts)
        return [
            self._to_world(cand)
            for cand in _box_escape_candidates(-self._h, self._h, local)
        ]

    def corners(self) -> NDArray[np.float64]:
        return self._to_world(_UNIT_BOX_CORNERS * self._h)

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        c = self.corners()
        return c.min(axis=0), c.max(axis=0)

    def sample(self, n: int, rng: Generator, **kwargs: Any) -> NDArray[np.float64]:
        if not self.allow:
            return super().sample(n, rng, **kwargs)
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)
        local = rng.uniform(-self._h, self._h, size=(n, 3))
        return self._to_world(local)

    def to_mesh(self) -> dict[str, Any]:
        corners = self.corners()
        lo, hi = self.bounds()
        return {
            "type": "oriented_box",
            "center": list(self.center),
            "halfExtents": list(self.half_extents),
            "rotation": list(self.rotation),
            "vertices": corners.tolist(),
            "indices": [list(f) for f in _BOX_FACES],
            "min": lo.tolist(),
            "max": hi.tolist(),
        }


class Polytope(RegionBase):
    """Convex polytope as the intersection of half-spaces ``A @ x <= b``.

    May be unbounded, in which case ``bounds``, ``sample`` and ``to_mesh``
    raise :class:`UnboundedRegionError` -- ``contains`` and ``clamp`` still
    work, which is what rule-derived half-space exclusions need.
    """

    kind: Literal["polytope"] = "polytope"
    a: list[Vec3]
    b: list[float]

    @model_validator(mode="after")
    def _check_shapes(self) -> "Polytope":
        if len(self.a) != len(self.b):
            raise ValueError(
                f"polytope {self.id!r}: {len(self.a)} normals but {len(self.b)} offsets"
            )
        if not self.a:
            raise ValueError(f"polytope {self.id!r}: needs at least one half-space")
        norms = np.linalg.norm(np.asarray(self.a, dtype=np.float64), axis=1)
        if np.any(norms == 0.0):
            raise ValueError(f"polytope {self.id!r}: half-space normal cannot be zero")
        return self

    @functools.cached_property
    def _A(self) -> NDArray[np.float64]:
        return np.asarray(self.a, dtype=np.float64)

    @functools.cached_property
    def _b(self) -> NDArray[np.float64]:
        return np.asarray(self.b, dtype=np.float64)

    @functools.cached_property
    def _norms(self) -> NDArray[np.float64]:
        return np.linalg.norm(self._A, axis=1)

    @functools.cached_property
    def _An(self) -> NDArray[np.float64]:
        return self._A / self._norms[:, None]

    @functools.cached_property
    def _bn(self) -> NDArray[np.float64]:
        return self._b / self._norms

    def _slack(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        """Signed distance to each face plane; negative means outside."""
        return self._bn[None, :] - pts @ self._An.T

    def _contains(self, pts: NDArray[np.float64]) -> NDArray[np.bool_]:
        return np.all(self._slack(pts) >= -CONTAINS_TOL, axis=1)

    def _clamp_into(
        self, pts: NDArray[np.float64], max_iter: int = 256
    ) -> NDArray[np.float64]:
        # Cyclic projection onto the violated half-spaces. The feasible set is
        # convex, so this converges; a few hundred passes is plenty for the
        # handful of faces these polytopes carry.
        out = pts.copy()
        for _ in range(max_iter):
            slack = self._slack(out)
            worst = slack.min(axis=1)
            bad = worst < -CONTAINS_TOL
            if not bad.any():
                break
            idx = np.argmin(slack, axis=1)[bad]
            out[bad] += self._An[idx] * worst[bad, None]
        return out

    def _clamp_out(self, pts: NDArray[np.float64]) -> NDArray[np.float64]:
        out = pts.copy()
        inside = self._contains(pts)
        if not inside.any():
            return out
        slack = self._slack(pts[inside])
        # Leave through the face plane that is nearest, i.e. least slack.
        idx = np.argmin(slack, axis=1)
        dist = slack[np.arange(len(idx)), idx]
        out[inside] = pts[inside] + self._An[idx] * (dist + PUSH_EPS)[:, None]
        return out

    def _escape_candidates(
        self, pts: NDArray[np.float64]
    ) -> list[NDArray[np.float64]]:
        inside = self._contains(pts)
        slack = self._slack(pts)
        out: list[NDArray[np.float64]] = []
        for i in range(len(self._An)):
            cand = pts.copy()
            step = (slack[inside, i] + PUSH_EPS)[:, None] * self._An[i]
            cand[inside] = pts[inside] + step
            out.append(cand)
        return out

    @functools.cached_property
    def _interior_point(self) -> NDArray[np.float64]:
        """Chebyshev centre of the polytope, used to seed the vertex solve."""
        from scipy.optimize import linprog

        m = len(self._An)
        # maximise r subject to A_n x + r <= b_n
        res = linprog(
            c=np.array([0.0, 0.0, 0.0, -1.0]),
            A_ub=np.hstack([self._An, np.ones((m, 1))]),
            b_ub=self._bn,
            bounds=[(None, None)] * 3 + [(0.0, None)],
            method="highs",
        )
        if not res.success or res.x[3] <= CONTAINS_TOL:
            raise EmptyRegionError(
                f"polytope {self.id!r}: half-spaces have no interior "
                f"({res.message if not res.success else 'inradius is zero'})"
            )
        if not np.isfinite(res.fun):
            raise UnboundedRegionError(f"polytope {self.id!r} is unbounded")
        return np.asarray(res.x[:3], dtype=np.float64)

    @functools.cached_property
    def _hull(self):  # -> scipy.spatial.ConvexHull
        from scipy.spatial import ConvexHull, HalfspaceIntersection

        halfspaces = np.hstack([self._An, -self._bn[:, None]])
        try:
            hs = HalfspaceIntersection(halfspaces, self._interior_point)
        except RegionError:
            raise
        except Exception as exc:  # pragma: no cover - qhull error text varies
            raise UnboundedRegionError(
                f"polytope {self.id!r}: could not enumerate vertices, the "
                f"half-space set is probably unbounded ({exc})"
            ) from exc
        verts = np.asarray(hs.intersections, dtype=np.float64)
        if not np.all(np.isfinite(verts)):
            raise UnboundedRegionError(f"polytope {self.id!r} is unbounded")
        try:
            return ConvexHull(verts)
        except Exception as exc:  # pragma: no cover
            raise RegionError(
                f"polytope {self.id!r}: vertices are degenerate ({exc})"
            ) from exc

    def vertices(self) -> NDArray[np.float64]:
        hull = self._hull
        return np.asarray(hull.points[hull.vertices], dtype=np.float64)

    def bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        v = self.vertices()
        return v.min(axis=0), v.max(axis=0)

    def to_mesh(self) -> dict[str, Any]:
        hull = self._hull
        pts = np.asarray(hull.points, dtype=np.float64)
        centroid = pts[hull.vertices].mean(axis=0)
        tris: list[list[int]] = []
        for simplex in hull.simplices:
            i, j, k = (int(s) for s in simplex)
            normal = np.cross(pts[j] - pts[i], pts[k] - pts[i])
            # Qhull does not guarantee a consistent winding; orient outward so
            # the viewport can backface-cull.
            if float(normal @ (pts[i] - centroid)) < 0.0:
                i, k = k, i
            tris.append([i, j, k])
        return {
            "type": "mesh",
            "vertices": pts.tolist(),
            "indices": tris,
        }

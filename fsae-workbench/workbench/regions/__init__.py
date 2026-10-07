"""Region algebra for allowable and illegal design volumes.

Primitives (:class:`Box`, :class:`OrientedBox`, :class:`Sphere`,
:class:`Polytope`) and set operators (:class:`Union`, :class:`Intersection`,
:class:`Difference`) all expose the same vectorised interface: ``contains``,
``permits``, ``clamp``, ``sample``, ``bounds``, ``to_mesh``.

See :mod:`workbench.regions.base` for the ``contains``/``permits`` distinction
and :mod:`workbench.regions.composite` for the composite semantics.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterable, Sequence, Union as TUnion

import numpy as np
from numpy.typing import ArrayLike, NDArray
from pydantic import Field, TypeAdapter

from . import composite as _composite
from .base import (
    CONTAINS_TOL,
    MAX_CLAMP_ITER,
    PUSH_EPS,
    ClampError,
    EmptyRegionError,
    RegionBase,
    RegionError,
    SamplingError,
    UnboundedRegionError,
    as_points,
)
from .composite import Composite, Difference, Intersection, Union
from .primitives import Box, OrientedBox, Polytope, Sphere

#: Discriminated union of every concrete region, for use in pydantic models.
AnyRegion = Annotated[
    TUnion[Box, OrientedBox, Sphere, Polytope, Union, Intersection, Difference],
    Field(discriminator="kind"),
]

#: The abstract region interface, for type annotations in ordinary code.
Region = RegionBase

_composite.AnyRegion = AnyRegion  # type: ignore[attr-defined]
for _cls in (Composite, Union, Intersection, Difference):
    _cls.model_rebuild()

REGION_ADAPTER: TypeAdapter[RegionBase] = TypeAdapter(AnyRegion)


def parse_region(data: Any) -> RegionBase:
    """Build a region from a plain dict, dispatching on ``kind``."""
    return REGION_ADAPTER.validate_python(data)


def combine(
    regions: Sequence[RegionBase],
    *,
    id: str = "combined",
    label: str = "",
) -> Intersection:
    """Fold a list of regions into the single set a point must satisfy.

    ``allow=True`` regions are intersected, ``allow=False`` regions are
    subtracted -- exactly the composite semantics, which is what makes the
    user's allowable boxes and the ruleset's illegal volumes composable without
    any special casing in the optimizer.
    """
    if not regions:
        raise ValueError("combine() needs at least one region")
    return Intersection(id=id, label=label, children=list(regions))


def feasible(regions: Sequence[RegionBase], p: ArrayLike) -> bool | NDArray[np.bool_]:
    """Whether each point satisfies every region in ``regions``."""
    pts, single = as_points(p)
    ok = np.ones(len(pts), dtype=bool)
    for region in regions:
        ok &= np.asarray(region.permits(pts))
    return bool(ok[0]) if single else ok


def regions_for_node(
    regions: Iterable[RegionBase], node_id: str
) -> list[RegionBase]:
    """Filter ``regions`` down to those binding ``node_id`` via ``applies_to``."""
    return [r for r in regions if r.applies_to_node(node_id)]


__all__ = [
    "CONTAINS_TOL",
    "MAX_CLAMP_ITER",
    "PUSH_EPS",
    "AnyRegion",
    "Box",
    "ClampError",
    "Composite",
    "Difference",
    "EmptyRegionError",
    "Intersection",
    "OrientedBox",
    "Polytope",
    "REGION_ADAPTER",
    "Region",
    "RegionBase",
    "RegionError",
    "SamplingError",
    "Sphere",
    "UnboundedRegionError",
    "Union",
    "combine",
    "feasible",
    "parse_region",
    "regions_for_node",
]

"""Tolerant readers for the fields the rules need out of a ``Design``.

The rules package is built in parallel with ``workbench.core.design``, and the
exact spelling of the vehicle and tire fields is the scaffold's call. Rather
than hard-coding one guess, every accessor tries a short list of plausible
names and raises :class:`MissingData` when none is present. A rule that cannot
read its input reports ``INFO: not verifiable`` instead of silently passing.

Everything returned is in millimetres and degrees, the units ``contracts.md``
fixes at every boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

import numpy as np
from numpy.typing import NDArray

from .base import MissingData

if TYPE_CHECKING:  # pragma: no cover
    from ..core.design import Design

MM_PER_INCH = 25.4

#: Below this, a length claiming to be millimetres is almost certainly inches.
_IMPLAUSIBLE_MM = 60.0

#: Node keys the rules look for, in order of preference.
WHEEL_CENTER_KEYS = ("wheel_center", "wheel_centre", "wheel_center_static", "hub")
CONTACT_PATCH_KEYS = ("contact_patch", "tire_contact_patch", "contact_patch_static")

_MIRROR = {"lf": "rf", "rf": "lf", "lr": "rr", "rr": "lr"}


def _first_attr(obj: Any, names: tuple[str, ...]) -> tuple[str, Any] | None:
    for name in names:
        value = getattr(obj, name, None)
        if value is None and isinstance(obj, dict):
            value = obj.get(name)
        if value is not None:
            return name, value
    return None


def _length_mm(obj: Any, names: tuple[str, ...], what: str) -> float:
    """Read a length, honouring an explicit ``_in``/``_inch`` suffix."""
    inch_names = tuple(
        f"{n}_in" for n in names if not n.endswith(("_mm", "_in", "_inch"))
    ) + tuple(f"{n}_inch" for n in names if not n.endswith(("_mm", "_in", "_inch")))
    hit = _first_attr(obj, inch_names)
    if hit is not None:
        return float(hit[1]) * MM_PER_INCH
    hit = _first_attr(obj, names)
    if hit is None:
        raise MissingData(f"{what} (looked for {', '.join(names)})")
    name, value = hit
    value = float(value)
    if not name.endswith("_mm") and 0.0 < value < _IMPLAUSIBLE_MM:
        raise MissingData(
            f"{what}: {name}={value} is too small to be millimetres and the "
            "unit is not declared; name the field with an explicit _mm or _in "
            "suffix"
        )
    return value


# -- vehicle ------------------------------------------------------------------


def vehicle(design: "Design") -> Any:
    v = getattr(design, "vehicle", None)
    if v is None:
        raise MissingData("design.vehicle")
    return v


def wheelbase_mm(design: "Design") -> float:
    return _length_mm(vehicle(design), ("wheelbase_mm", "wheelbase"), "wheelbase")


def track_mm(design: "Design", axle: str) -> float:
    v = vehicle(design)
    names = (f"track_{axle}_mm", f"track_{axle}", f"{axle}_track_mm", f"{axle}_track")
    return _length_mm(v, names, f"{axle} track")


def cg_height_mm(design: "Design") -> float:
    return _length_mm(
        vehicle(design), ("cg_height_mm", "cg_height", "cog_height"), "CG height"
    )


# -- tire and wheel -----------------------------------------------------------


def tire(design: "Design") -> Any:
    t = getattr(design, "tire", None)
    if t is None:
        raise MissingData("design.tire")
    return t


def rim_diameter_mm(design: "Design") -> float:
    return _length_mm(
        tire(design),
        ("rim_diameter_mm", "rim_diameter", "wheel_diameter_mm", "wheel_diameter"),
        "rim (wheel) diameter",
    )


def tire_outer_diameter_mm(design: "Design") -> float:
    return _length_mm(
        tire(design),
        (
            "outer_diameter_mm",
            "outer_diameter",
            "overall_diameter_mm",
            "overall_diameter",
            "diameter_mm",
            "diameter",
        ),
        "tire outer diameter",
    )


def tire_width_mm(design: "Design") -> float:
    return _length_mm(
        tire(design), ("width_mm", "width", "section_width_mm"), "tire width"
    )


def suspension_travel_mm(design: "Design") -> float:
    """Usable wheel travel, read from the vehicle or tire spec."""
    for holder, names in (
        (
            vehicle(design),
            ("wheel_travel_mm", "wheel_travel", "suspension_travel_mm", "travel_mm"),
        ),
    ):
        try:
            return _length_mm(holder, names, "usable wheel travel")
        except MissingData:
            continue
    raise MissingData("usable wheel travel (vehicle.wheel_travel_mm)")


def angle_deg(obj: Any, names: tuple[str, ...], what: str) -> float:
    hit = _first_attr(obj, names)
    if hit is None:
        raise MissingData(f"{what} (looked for {', '.join(names)})")
    return float(hit[1])


# -- topology -----------------------------------------------------------------


def axles(design: "Design") -> dict[str, Any]:
    a = getattr(design, "axles", None)
    if not a:
        raise MissingData("design.axles")
    return dict(a)


def axle(design: "Design", name: str) -> Any:
    found = axles(design).get(name)
    if found is None:
        raise MissingData(f"design.axles[{name!r}]")
    return found


def _mirror_position(p: Any) -> tuple[float, float, float]:
    x, y, z = (float(c) for c in p)
    return x, -y, z


def iter_corners(design: "Design") -> Iterator[tuple[str, Any, bool]]:
    """Yield ``(corner_id, corner, mirrored)`` for all four corners.

    A ``None`` right corner is reported as the left corner flagged mirrored,
    per the ``Axle.right`` contract.
    """
    for axle_obj in axles(design).values():
        left = getattr(axle_obj, "left", None)
        if left is None:
            continue
        yield getattr(left, "id", "left"), left, False
        right = getattr(axle_obj, "right", None)
        if right is not None:
            yield getattr(right, "id", "right"), right, False
        else:
            left_id = getattr(left, "id", "left")
            yield _MIRROR.get(left_id, f"{left_id}_mirror"), left, True


def iter_nodes(design: "Design") -> Iterator[tuple[str, NDArray[np.float64], Any]]:
    """Yield ``(payload_node_id, position, node)`` across the whole design."""
    for corner_id, corner, mirrored in iter_corners(design):
        for key, node in getattr(corner, "nodes", {}).items():
            pos = node.position
            if mirrored:
                pos = _mirror_position(pos)
            yield f"{corner_id}.{key}", np.asarray(pos, dtype=np.float64), node
    for axle_id, axle_obj in axles(design).items():
        for key, node in (getattr(axle_obj, "center_nodes", None) or {}).items():
            yield (
                f"{axle_id}.center.{key}",
                np.asarray(node.position, dtype=np.float64),
                node,
            )


def _corner_axle(corner_id: str) -> str:
    return "front" if corner_id.endswith("f") else "rear"


def axle_corner_ids(design: "Design", axle_name: str) -> list[str]:
    return [
        cid for cid, _, _ in iter_corners(design) if _corner_axle(cid) == axle_name
    ]


def wheel_center_nodes(
    design: "Design", axle_name: str | None = None
) -> dict[str, NDArray[np.float64]]:
    """Static wheel-centre positions keyed by payload node id.

    Falls back to the contact patch when no wheel-centre node is modelled,
    since both pin the corner's longitudinal and lateral station.
    """
    out: dict[str, NDArray[np.float64]] = {}
    for corner_id, corner, mirrored in iter_corners(design):
        if axle_name is not None and _corner_axle(corner_id) != axle_name:
            continue
        nodes = getattr(corner, "nodes", {})
        for key in (*WHEEL_CENTER_KEYS, *CONTACT_PATCH_KEYS):
            if key in nodes:
                pos = nodes[key].position
                if mirrored:
                    pos = _mirror_position(pos)
                out[f"{corner_id}.{key}"] = np.asarray(pos, dtype=np.float64)
                break
    if not out:
        raise MissingData(
            f"wheel centre nodes for the {axle_name or 'whole'} axle "
            f"(looked for {', '.join(WHEEL_CENTER_KEYS + CONTACT_PATCH_KEYS)})"
        )
    return out


def design_bounds(design: "Design", pad: float = 1000.0) -> tuple[
    NDArray[np.float64], NDArray[np.float64]
]:
    """Padded AABB over every node, used to give rule regions finite extent."""
    pts = np.array([p for _, p, _ in iter_nodes(design)], dtype=np.float64)
    if not len(pts):
        raise MissingData("design has no nodes")
    return pts.min(axis=0) - pad, pts.max(axis=0) + pad

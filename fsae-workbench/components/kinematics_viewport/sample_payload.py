"""A four-corner double-wishbone payload used by the Streamlit demo script.

This is demo scaffolding, not part of the component contract: once
``workbench.core.design.Design`` lands, the real app builds the payload from it.
The numbers mirror the frontend dev harness so the two demos look alike.

ISO 8855 millimetres: +X forward, +Y left, +Z up.
"""

from __future__ import annotations

import math
from typing import Any

WHEELBASE = 1549.4
TRACK_FRONT = 1168.4
TRACK_REAR = 1143.0
WHEEL_CENTRE_Z = 223.52

Vec3 = list[float]

# corner id -> (axle x, half track, side sign, steered, actuation)
_CORNERS: dict[str, tuple[float, float, int, bool, str]] = {
    "lf": (WHEELBASE / 2, TRACK_FRONT / 2, 1, True, "pullrod"),
    "rf": (WHEELBASE / 2, TRACK_FRONT / 2, -1, True, "pullrod"),
    "lr": (-WHEELBASE / 2, TRACK_REAR / 2, 1, False, "pushrod"),
    "rr": (-WHEELBASE / 2, TRACK_REAR / 2, -1, False, "pushrod"),
}

# key -> (dx from axle line, |y| for inboard nodes, z)
_LAYOUT: dict[str, tuple[float, float, float]] = {
    "lca_fore_inboard": (125, 180, 110),
    "lca_aft_inboard": (-145, 180, 118),
    "lca_outboard": (4, 0, 112),
    "uca_fore_inboard": (105, 212, 268),
    "uca_aft_inboard": (-125, 212, 272),
    "uca_outboard": (-6, 0, 306),
    "steer_inboard": (92, 168, 136),
    "steer_outboard": (74, 0, 152),
    "rod_outboard": (-10, 0, 296),
    "rocker_pivot": (-62, 196, 352),
    "damper_inboard": (-168, 58, 338),
    "wheel_center": (0, 0, WHEEL_CENTRE_Z),
    "contact_patch": (0, 0, 0),
}

# Outboard nodes sit inboard of the wheel centre by these amounts.
_OUTBOARD_INSET: dict[str, float] = {
    "lca_outboard": 62,
    "uca_outboard": 88,
    "steer_outboard": 72,
    "rod_outboard": 96,
    "wheel_center": 0,
    "contact_patch": 0,
}

_LABELS: dict[str, str] = {
    "lca_fore_inboard": "LCA Fore Inboard",
    "lca_aft_inboard": "LCA Aft Inboard",
    "lca_outboard": "LCA Outboard",
    "uca_fore_inboard": "UCA Fore Inboard",
    "uca_aft_inboard": "UCA Aft Inboard",
    "uca_outboard": "UCA Outboard",
    "steer_inboard": "Tie Rod Inboard",
    "steer_outboard": "Tie Rod Outboard",
    "rod_outboard": "Rod Outboard",
    "rocker_pivot": "Rocker Pivot",
    "damper_inboard": "Damper Inboard",
    "wheel_center": "Wheel Centre",
    "contact_patch": "Contact Patch",
}

_FIXED = {
    "lca_fore_inboard",
    "lca_aft_inboard",
    "uca_fore_inboard",
    "uca_aft_inboard",
    "steer_inboard",
    "rocker_pivot",
    "damper_inboard",
}

_MOVING = [
    "lca_outboard",
    "uca_outboard",
    "steer_outboard",
    "rod_outboard",
    "wheel_center",
    "contact_patch",
]

_CORNER_LINKS: list[tuple[str, str, str]] = [
    ("lca_fore_inboard", "lca_outboard", "wishbone"),
    ("lca_aft_inboard", "lca_outboard", "wishbone"),
    ("uca_fore_inboard", "uca_outboard", "wishbone"),
    ("uca_aft_inboard", "uca_outboard", "wishbone"),
    ("steer_inboard", "steer_outboard", "tie_rod"),
    ("rod_outboard", "rocker_pivot", "pullrod"),
    ("rocker_pivot", "damper_inboard", "damper"),
    ("lca_outboard", "uca_outboard", "upright"),
    ("uca_outboard", "wheel_center", "upright"),
    ("lca_outboard", "wheel_center", "upright"),
    ("steer_outboard", "wheel_center", "upright"),
    ("wheel_center", "contact_patch", "upright"),
]

_CHASSIS_LINKS: list[tuple[str, str]] = [
    ("lf.lca_fore_inboard", "rf.lca_fore_inboard"),
    ("lr.lca_fore_inboard", "rr.lca_fore_inboard"),
    ("lf.lca_fore_inboard", "lr.lca_aft_inboard"),
    ("rf.lca_fore_inboard", "rr.lca_aft_inboard"),
    ("lf.uca_fore_inboard", "rf.uca_fore_inboard"),
    ("lr.uca_fore_inboard", "rr.uca_fore_inboard"),
    ("lf.uca_fore_inboard", "lr.uca_aft_inboard"),
    ("rf.uca_fore_inboard", "rr.uca_aft_inboard"),
]

_REGION_BINDINGS = {
    ("lf", "lca_fore_inboard"): "r_lf_lca_fore",
    ("lf", "uca_fore_inboard"): "r_lf_uca_fore",
    ("lf", "lca_outboard"): "r_lf_lca_outboard",
}


def _position(corner: str, key: str) -> Vec3:
    axle_x, half_track, side, _steered, _act = _CORNERS[corner]
    dx, abs_y, z = _LAYOUT[key]
    inset = _OUTBOARD_INSET.get(key)
    y = abs_y if inset is None else half_track - inset
    return [axle_x + dx, side * y, z]


def _label(corner: str, key: str) -> str:
    _, _, _, steered, actuation = _CORNERS[corner]
    if key == "steer_inboard":
        return "Tie Rod Inboard" if steered else "Toe Link Inboard"
    if key == "steer_outboard":
        return "Tie Rod Outboard" if steered else "Toe Link Outboard"
    if key == "rod_outboard":
        return "Pullrod Outboard" if actuation == "pullrod" else "Pushrod Outboard"
    return _LABELS.get(key, key)


def _nodes() -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for corner in _CORNERS:
        for key in _LAYOUT:
            nodes.append(
                {
                    "id": f"{corner}.{key}",
                    "p": _position(corner, key),
                    "fixed": key in _FIXED,
                    "corner": corner,
                    "label": _label(corner, key),
                    "regionId": _REGION_BINDINGS.get((corner, key)),
                }
            )
    nodes.append(
        {
            "id": "front.center.rack_center",
            "p": [WHEELBASE / 2 + 92, 0.0, 136.0],
            "fixed": True,
            "corner": None,
            "label": "Rack Centre",
            "regionId": None,
        }
    )
    return nodes


def _links() -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for corner, (_, _, _, steered, actuation) in _CORNERS.items():
        for a, b, kind in _CORNER_LINKS:
            resolved = "toe_link" if kind == "tie_rod" and not steered else kind
            if resolved == "pullrod" and actuation == "pushrod":
                resolved = "pushrod"
            links.append({"a": f"{corner}.{a}", "b": f"{corner}.{b}", "kind": resolved})
    links.extend({"a": a, "b": b, "kind": "chassis"} for a, b in _CHASSIS_LINKS)
    links.append(
        {"a": "lf.steer_inboard", "b": "front.center.rack_center", "kind": "chassis"}
    )
    links.append(
        {"a": "rf.steer_inboard", "b": "front.center.rack_center", "kind": "chassis"}
    )
    return links


def _box_around(p: Vec3, half: tuple[float, float, float]) -> dict[str, Any]:
    return {
        "type": "box",
        "min": [p[0] - half[0], p[1] - half[1], p[2] - half[2]],
        "max": [p[0] + half[0], p[1] + half[1], p[2] + half[2]],
    }


def _wedge(center: Vec3, half: tuple[float, float, float]) -> dict[str, Any]:
    """Axis-aligned wedge as a triangulated hull, to exercise the polytope path."""
    cx, cy, cz = center
    hx, hy, hz = half
    return {
        "type": "polytope",
        "vertices": [
            [cx - hx, cy - hy, cz - hz],
            [cx + hx, cy - hy, cz - hz],
            [cx + hx, cy + hy, cz - hz],
            [cx - hx, cy + hy, cz - hz],
            [cx - hx * 0.25, cy - hy * 0.35, cz + hz],
            [cx + hx * 0.25, cy + hy * 0.35, cz + hz],
        ],
        "faces": [
            [0, 2, 1],
            [0, 3, 2],
            [0, 1, 4],
            [1, 5, 4],
            [1, 2, 5],
            [2, 3, 5],
            [3, 4, 5],
            [3, 0, 4],
        ],
    }


def _regions() -> list[dict[str, Any]]:
    uca_fore = _position("lf", "uca_fore_inboard")
    uca_aft = _position("lf", "uca_aft_inboard")
    rocker = _position("lr", "rocker_pivot")
    return [
        {
            "id": "r_lf_lca_fore",
            "kind": "box",
            "allow": True,
            "label": "LF LCA fore pickup envelope",
            "source": "user",
            "applies_to": ["lf.lca_fore_inboard"],
            "mesh": _box_around(_position("lf", "lca_fore_inboard"), (70, 55, 45)),
        },
        {
            "id": "r_lf_uca_fore",
            "kind": "obox",
            "allow": True,
            "label": "LF UCA pickup envelope",
            "source": "user",
            "applies_to": ["lf.uca_*_inboard"],
            "mesh": {
                "type": "obox",
                "center": [
                    (uca_fore[0] + uca_aft[0]) / 2,
                    uca_fore[1],
                    (uca_fore[2] + uca_aft[2]) / 2,
                ],
                "half_extents": [160.0, 48.0, 58.0],
                # Degrees, XYZ order, matching the contracts' angle convention.
                "rotation": [0.0, -10.0, 14.0],
            },
        },
        {
            "id": "r_lf_lca_outboard",
            "kind": "sphere",
            "allow": True,
            "label": "LF LCA outboard upright envelope",
            "source": "user",
            "applies_to": ["lf.lca_outboard"],
            "mesh": {
                "type": "sphere",
                "center": _position("lf", "lca_outboard"),
                "radius": 55.0,
            },
        },
        {
            "id": "r_lr_rocker_bay",
            "kind": "difference",
            "allow": True,
            "label": "LR rocker bay minus airbox",
            "source": "user",
            "applies_to": ["lr.rocker_pivot", "rr.rocker_pivot"],
            "mesh": {
                "type": "difference",
                "children": [
                    _box_around(rocker, (150, 120, 95)),
                    {"type": "sphere", "center": rocker, "radius": 46.0},
                ],
            },
        },
        {
            "id": "r_cockpit",
            "kind": "box",
            "allow": False,
            "label": "Cockpit template exclusion",
            "source": "rule:T.2.4",
            "mesh": {"type": "box", "min": [-260, -175, 60], "max": [320, 175, 520]},
        },
        {
            "id": "r_ground",
            "kind": "box",
            "allow": False,
            "label": "Minimum ground clearance",
            "source": "rule:T.2.5",
            # Outboard nodes sweep through this band by design; only
            # chassis-side pickups are held above it.
            "applies_to": ["*_inboard", "*.rocker_pivot", "*.damper_inboard"],
            "mesh": {"type": "box", "min": [-900, -620, -40], "max": [900, 620, 28]},
        },
        {
            "id": "r_driver_feet",
            "kind": "polytope",
            "allow": False,
            "label": "Driver footwell exclusion",
            "source": "rule:T.2.6",
            "mesh": _wedge([520.0, 0.0, 190.0], (190, 150, 150)),
        },
    ]


def _findings() -> list[dict[str, Any]]:
    return [
        {
            "nodes": ["lf.uca_outboard", "rf.uca_outboard"],
            "severity": "WARNING",
            "message": "Front camber gain is below the target band at 25 mm bump.",
            "ruleId": "obj.camber_gain",
            "citation": "objective",
        },
        {
            "nodes": ["lf.steer_inboard"],
            "severity": "BLOCKER",
            "message": "Tie rod inboard pickup intrudes into the cockpit template exclusion.",
            "ruleId": "fsae_us.T.2.4",
            "citation": "T.2.4",
        },
        {
            "nodes": ["lr.rocker_pivot"],
            "severity": "INFO",
            "message": "Rear motion ratio 1.08; consider lowering the rocker pivot.",
            "ruleId": "obj.motion_ratio",
            "citation": "objective",
        },
    ]


def _frames(nodes: list[dict[str, Any]], steps: int = 41) -> list[dict[str, Any]]:
    """Synthetic bump sweep, so the scrubber has something to animate.

    The real app fills ``frames`` from ``solve_evaluated_sweep``.
    """
    by_id = {n["id"]: n["p"] for n in nodes}
    frames: list[dict[str, Any]] = []
    for i in range(steps):
        t = -25.0 + 50.0 * i / (steps - 1)
        positions: dict[str, Vec3] = {}
        for corner, (_, _, side, _steered, _act) in _CORNERS.items():
            pivot = by_id[f"{corner}.lca_fore_inboard"]
            lower = by_id[f"{corner}.lca_outboard"]
            arm = math.hypot(lower[1] - pivot[1], lower[2] - pivot[2])
            theta = math.asin(max(-0.95, min(0.95, t / arm)))
            cos_t, sin_t = math.cos(theta), math.sin(theta) * side
            for key in _MOVING:
                base = by_id[f"{corner}.{key}"]
                dy = base[1] - pivot[1]
                dz = base[2] - pivot[2]
                positions[f"{corner}.{key}"] = [
                    base[0],
                    pivot[1] + dy * cos_t - dz * sin_t,
                    pivot[2] + dy * sin_t + dz * cos_t,
                ]
        frames.append({"t": round(t, 2), "p": positions})
    return frames


def sample_payload() -> dict[str, Any]:
    """Build the demo payload."""
    nodes = _nodes()
    return {
        "schemaVersion": 1,
        "nodes": nodes,
        "links": _links(),
        "regions": _regions(),
        "findings": _findings(),
        "frames": _frames(nodes),
        "selection": ["lf.lca_fore_inboard"],
        "view": {"preset": "iso"},
        "frameUnit": "mm bump",
    }

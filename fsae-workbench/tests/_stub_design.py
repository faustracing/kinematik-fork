"""A minimal stand-in for ``workbench.core.design``.

The regions and rules branch is developed in parallel with the scaffold that
owns the real ``Design`` model, so the tests build against this stub instead.
It mirrors the shape fixed in ``contracts.md`` exactly -- same field names,
same literals, same nesting -- and nothing outside ``tests/`` imports it. When
``workbench.core.design`` lands, the stub should be deleted and the fixtures
re-pointed at the real model; if anything here disagrees with the real model,
the real model wins.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str
    position: tuple[float, float, float]
    fixed: bool = False
    region: str | None = None


class Corner(BaseModel):
    id: str
    nodes: dict[str, Node] = Field(default_factory=dict)
    actuation: Literal["direct", "pushrod_rocker", "pullrod_rocker"] = "direct"
    spring: Literal["none", "coilover", "torsion_bar"] = "coilover"


class Axle(BaseModel):
    id: str
    architecture: Literal[
        "double_wishbone", "macpherson", "multi_link", "trailing_arm"
    ] = "double_wishbone"
    steering: Literal["rack", "none"] = "none"
    left: Corner
    right: Corner | None = None
    center_nodes: dict[str, Node] = Field(default_factory=dict)


class TireSpec(BaseModel):
    rim_diameter_mm: float = 254.0  # 10 in
    outer_diameter_mm: float = 457.2  # 18 in
    width_mm: float = 190.5  # 7.5 in


class VehicleSpec(BaseModel):
    wheelbase_mm: float = 1549.4
    track_front_mm: float = 1168.4
    track_rear_mm: float = 1143.0
    cg_height_mm: float = 290.0
    mass_kg: float = 230.0
    front_mass_fraction: float = 0.47
    wheel_travel_mm: float | None = None
    steering_free_play_deg: float | None = None
    rear_steer_max_deg: float | None = None


class Design(BaseModel):
    schema_version: int = 1
    name: str = "stub"
    frame: Literal["iso8855"] = "iso8855"
    ruleset: tuple[str, int] | None = None
    tire: TireSpec = Field(default_factory=TireSpec)
    vehicle: VehicleSpec = Field(default_factory=VehicleSpec)
    axles: dict[str, Axle] = Field(default_factory=dict)
    regions: dict[str, object] = Field(default_factory=dict)
    objectives: list[object] = Field(default_factory=list)


# -- fixture builders ---------------------------------------------------------

#: Dimensions of the golden four-corner car from the project plan, in the
#: canonical ISO 8855 frame with the origin on the ground at the front axle.
WHEELBASE_MM = 1549.4
TRACK_FRONT_MM = 1168.4
TRACK_REAR_MM = 1143.0
WHEEL_CENTER_Z_MM = 223.52


def _corner(corner_id: str, x: float, y: float, *, spring: str = "coilover") -> Corner:
    side = 1.0 if y >= 0 else -1.0
    inboard_y = side * 180.0
    return Corner(
        id=corner_id,
        spring=spring,  # type: ignore[arg-type]
        actuation="pullrod_rocker" if corner_id.endswith("f") else "pushrod_rocker",
        nodes={
            "wheel_center": Node(id="wheel_center", position=(x, y, WHEEL_CENTER_Z_MM)),
            "contact_patch": Node(id="contact_patch", position=(x, y, 0.0)),
            "lca_outboard": Node(
                id="lca_outboard", position=(x, y - side * 40.0, 115.0)
            ),
            "uca_outboard": Node(
                id="uca_outboard", position=(x, y - side * 60.0, 300.0)
            ),
            "lca_fore_inboard": Node(
                id="lca_fore_inboard", position=(x + 120.0, inboard_y, 110.0), fixed=True
            ),
            "lca_aft_inboard": Node(
                id="lca_aft_inboard", position=(x - 120.0, inboard_y, 110.0), fixed=True
            ),
            "uca_fore_inboard": Node(
                id="uca_fore_inboard", position=(x + 100.0, inboard_y, 290.0), fixed=True
            ),
            "uca_aft_inboard": Node(
                id="uca_aft_inboard", position=(x - 100.0, inboard_y, 290.0), fixed=True
            ),
        },
    )


def golden_car(**vehicle_overrides: object) -> Design:
    """A legal four-corner double wishbone car, used as the baseline fixture."""
    front_x = 0.0
    rear_x = -WHEELBASE_MM
    yf = TRACK_FRONT_MM / 2.0
    yr = TRACK_REAR_MM / 2.0
    return Design(
        name="golden",
        ruleset=("fsae_us", 2026),
        vehicle=VehicleSpec(
            **{
                "wheel_travel_mm": 60.0,
                "steering_free_play_deg": 3.0,
                **vehicle_overrides,
            }  # type: ignore[arg-type]
        ),
        axles={
            "front": Axle(
                id="front",
                steering="rack",
                left=_corner("lf", front_x, yf),
                right=_corner("rf", front_x, -yf),
                center_nodes={
                    "rack_left": Node(id="rack_left", position=(80.0, 150.0, 120.0)),
                    "rack_right": Node(id="rack_right", position=(80.0, -150.0, 120.0)),
                },
            ),
            "rear": Axle(
                id="rear",
                steering="none",
                left=_corner("lr", rear_x, yr),
                right=_corner("rr", rear_x, -yr),
            ),
        },
    )


def mirrored_car() -> Design:
    """Same car with the right corners left implicit, per ``Axle.right = None``."""
    design = golden_car()
    for axle in design.axles.values():
        axle.right = None
    return design

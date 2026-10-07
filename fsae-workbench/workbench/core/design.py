"""The `Design` model: the single shared contract between every workstream.

A `Design` is the whole car as authored: topology, hardpoints, tire and wheel,
vehicle parameters, region bindings, and objectives. It is Pydantic v2, round
trips losslessly through JSON, and carries a stable `fingerprint` over the
fields that change a solve, which the solver cache and the optimizer key on.

Coordinates are ISO 8855 millimetres on the design datum: `+X` forward, `+Y`
left, `+Z` up, front axle centreline at `X = 0`, static ground plane at
`Z = 0`. Angles are degrees at this boundary, as everywhere else outside the
solver.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "NODE_LABELS",
    "SCHEMA_VERSION",
    "Axle",
    "Corner",
    "Design",
    "Node",
    "ObjectiveSpec",
    "RegionSpec",
    "TireSpec",
    "VehicleSpec",
]

SCHEMA_VERSION: Final[int] = 1

CornerId = Literal["lf", "rf", "lr", "rr"]
AxleId = Literal["front", "rear"]

NODE_LABELS: Final[dict[str, str]] = {
    "lca_fore_inboard": "LCA Fore Inboard",
    "lca_aft_inboard": "LCA Aft Inboard",
    "lca_outboard": "LCA Outboard",
    "uca_fore_inboard": "UCA Fore Inboard",
    "uca_aft_inboard": "UCA Aft Inboard",
    "uca_outboard": "UCA Outboard",
    "tie_rod_inboard": "Tie Rod Inboard",
    "tie_rod_outboard": "Tie Rod Outboard",
    "toe_link_inboard": "Toe Link Inboard",
    "toe_link_outboard": "Toe Link Outboard",
    "wheel_center": "Wheel Center",
    "contact_patch": "Contact Patch",
    "pushrod_outboard": "Pushrod Outboard",
    "rocker_pushrod": "Rocker Pushrod",
    "rocker_pivot": "Rocker Pivot",
    "rocker_damper": "Rocker Damper",
    "damper_inboard": "Damper Inboard",
    "rack_inboard": "Rack Inboard",
    "arb_pivot": "ARB Pivot",
}
"""Display labels for the canonical node ids.

The actuation nodes are named `pushrod_*` on both axles even when the corner is
a pullrod corner: a pullrod and a pushrod are the same two-joint link to the
kinematics, and `Corner.actuation` is what records the physical difference.
Call `Corner.node_label` for a label that says "Pullrod" where that is true.
"""

_PULLROD_LABELS: Final[dict[str, str]] = {
    "pushrod_outboard": "Pullrod Outboard",
    "rocker_pushrod": "Rocker Pullrod",
}


class Node(BaseModel):
    """One authored point in the design."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable snake_case key, e.g. 'lca_fore_inboard'")
    position: tuple[float, float, float] = Field(
        description="ISO 8855 millimetres on the design datum"
    )
    fixed: bool = Field(
        default=False,
        description="True for a chassis pickup; False for a solved or free node",
    )
    region: str | None = Field(
        default=None, description="Region.id this node must stay inside"
    )

    @field_validator("id")
    @classmethod
    def check_snake_case(cls, value: str) -> str:
        """Require a non-empty lowercase snake_case identifier."""
        if not value or not value.replace("_", "").isalnum() or value != value.lower():
            raise ValueError(f"Node id must be lowercase snake_case, got {value!r}")
        return value


class Corner(BaseModel):
    """One corner: its nodes and the hardware installed on them."""

    model_config = ConfigDict(extra="forbid")

    id: CornerId
    nodes: dict[str, Node]
    actuation: Literal["direct", "pushrod_rocker", "pullrod_rocker"] = "pushrod_rocker"
    spring: Literal["none", "coilover", "torsion_bar"] = "coilover"
    pushrod_mount: Literal["upright", "upper_wishbone", "lower_wishbone"] = "upright"
    """Which moving body carries the outboard pushrod/pullrod pickup.

    The locating linkage is unaffected by this choice but the motion ratio is
    not: on the reference car the front corner's ratio moves from 0.684
    (upper wishbone) to 0.737 (upright) to 0.317 (lower wishbone). The loader
    picks the nearest wishbone body and records it here so the assumption is
    visible and overridable.
    """

    @model_validator(mode="after")
    def check_node_keys(self) -> Corner:
        """Keep the mapping key and the node's own id in agreement."""
        for key, node in self.nodes.items():
            if key != node.id:
                raise ValueError(f"Node key {key!r} does not match node id {node.id!r}")
        return self

    @property
    def side(self) -> Literal["left", "right"]:
        """Physical side of the car."""
        return "left" if self.id[0] == "l" else "right"

    @property
    def has_rocker(self) -> bool:
        """True when actuation runs through a rocker."""
        return self.actuation in ("pushrod_rocker", "pullrod_rocker")

    def node_label(self, node_id: str) -> str:
        """Display label for one node, honouring pullrod naming."""
        if self.actuation == "pullrod_rocker" and node_id in _PULLROD_LABELS:
            return _PULLROD_LABELS[node_id]
        return NODE_LABELS.get(node_id, node_id.replace("_", " ").title())

    def position(self, node_id: str) -> tuple[float, float, float]:
        """Position of one node, raising a readable error when it is absent."""
        try:
            return self.nodes[node_id].position
        except KeyError:
            raise KeyError(
                f"Corner {self.id!r} has no node {node_id!r}; "
                f"available: {sorted(self.nodes)}"
            ) from None


class Axle(BaseModel):
    """One axle: two corners plus the hardware they share."""

    model_config = ConfigDict(extra="forbid")

    id: AxleId
    architecture: Literal[
        "double_wishbone", "macpherson", "multi_link", "trailing_arm"
    ] = "double_wishbone"
    steering: Literal["rack", "none"] = "none"
    left: Corner
    right: Corner | None = Field(
        default=None, description="None mirrors the left corner through Y = 0"
    )
    center_nodes: dict[str, Node] = Field(
        default_factory=dict, description="Shared rack, ARB, and heave nodes"
    )

    @model_validator(mode="after")
    def check_sides(self) -> Axle:
        """Require the declared corners to sit on the axle they claim."""
        expected_suffix = "f" if self.id == "front" else "r"
        if self.left.id != f"l{expected_suffix}":
            raise ValueError(
                f"Axle {self.id!r} left corner must be "
                f"'l{expected_suffix}', got {self.left.id!r}"
            )
        if self.right is not None and self.right.id != f"r{expected_suffix}":
            raise ValueError(
                f"Axle {self.id!r} right corner must be "
                f"'r{expected_suffix}', got {self.right.id!r}"
            )
        return self

    @property
    def corners(self) -> list[Corner]:
        """Present corners, left first."""
        return [self.left] if self.right is None else [self.left, self.right]


class TireSpec(BaseModel):
    """Tire and wheel size, and the radius the kinematics actually use."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    compound: str = ""
    overall_diameter_in: float = Field(gt=0.0)
    section_width_in: float = Field(gt=0.0)
    rim_diameter_in: float = Field(gt=0.0)
    loaded_radius_mm: float | None = Field(default=None, gt=0.0)
    wheel_offset_mm: float = 0.0

    @property
    def unloaded_radius_mm(self) -> float:
        """Unloaded radius in millimetres."""
        return self.overall_diameter_in * 25.4 / 2.0

    @property
    def outer_diameter_mm(self) -> float:
        """Unloaded overall diameter in millimetres."""
        return self.overall_diameter_in * 25.4

    @property
    def rim_diameter_mm(self) -> float:
        """Rim bead seat diameter in millimetres."""
        return self.rim_diameter_in * 25.4

    @property
    def kinematic_radius_mm(self) -> float:
        """Radius the solver resolves ground tangency against, millimetres."""
        return self.loaded_radius_mm or self.unloaded_radius_mm

    @property
    def section_width_mm(self) -> float:
        """Section width in millimetres."""
        return self.section_width_in * 25.4

    @model_validator(mode="after")
    def check_radius_exceeds_rim(self) -> TireSpec:
        """A tire radius below the bead seat radius is not a tire."""
        if self.kinematic_radius_mm <= self.rim_diameter_in * 25.4 / 2.0:
            raise ValueError(
                "Tire radius must exceed the rim radius; got "
                f"{self.kinematic_radius_mm:.2f} mm against a "
                f"{self.rim_diameter_in:.1f} in rim"
            )
        return self


class VehicleSpec(BaseModel):
    """Whole-car parameters the load-sensitive metrics and the rules read."""

    model_config = ConfigDict(extra="forbid")

    wheelbase_mm: float = Field(gt=0.0)
    front_track_mm: float = Field(gt=0.0)
    rear_track_mm: float = Field(gt=0.0)
    mass_kg: float = Field(default=290.0, gt=0.0)
    front_mass_fraction: float = Field(default=0.48, ge=0.0, le=1.0)
    cg_height_mm: float = Field(default=300.0, gt=0.0)
    front_brake_bias: float = Field(default=0.60, ge=0.0, le=1.0)
    driven_axle: Literal["front", "rear"] = "rear"

    # Scrutineering declarations. These are authored claims about the car, not
    # quantities derivable from the hardpoints, and `workbench.rules` checks
    # them against the rulebook. They default to None rather than to a
    # plausible number so an unstated value reports "not verifiable" instead of
    # passing a rule on a value nobody measured.
    wheel_travel_mm: float | None = Field(
        default=None,
        gt=0.0,
        description="Usable total vertical wheel travel, jounce plus rebound",
    )
    steering_free_play_deg: float | None = Field(
        default=None, ge=0.0, description="Free play measured at the steering wheel"
    )
    rear_steer_max_deg: float | None = Field(
        default=None, ge=0.0, description="Maximum commanded rear steer angle"
    )

    @property
    def cg_x_mm(self) -> float:
        """Longitudinal CG on the design datum: negative, behind the front axle."""
        return -(1.0 - self.front_mass_fraction) * self.wheelbase_mm


class RegionSpec(BaseModel):
    """Forward declaration of a region, as stored inside a `Design`.

    `workbench.regions` owns region behaviour — containment, clamping,
    sampling, meshing — and the kind-specific payload fields. `Design` only
    needs to carry regions losslessly, so this model holds the common header
    and accepts any extra payload fields unvalidated. `workbench.regions`
    validates a `RegionSpec` into a concrete region, which keeps `Design` free
    of a dependency on the region algebra.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    kind: Literal["box", "sphere", "polytope", "union", "intersection", "difference"]
    label: str = ""
    allow: bool = True
    source: str = "user"
    applies_to: list[str] | None = None
    """Node-id globs this region binds, `!`-prefixed to exclude. None binds all.

    Rules that constrain one axle need this: a wheelbase minimum emits a volume
    that only the wheel-centre nodes of one axle may be judged against, and an
    unscoped volume would wrongly constrain every hardpoint in the car.
    """


class ObjectiveSpec(BaseModel):
    """Forward declaration of an optimizer objective, as stored in a `Design`.

    Same arrangement as `RegionSpec`: `workbench.objectives` owns scoring and
    the band payload, `Design` only has to round trip it.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    metric: str
    weight: float = 1.0


class Design(BaseModel):
    """A complete suspension design. The single source of truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    name: str = "unnamed"
    frame: Literal["iso8855"] = "iso8855"
    ruleset: tuple[str, int] | None = None
    tire: TireSpec
    vehicle: VehicleSpec
    axles: dict[str, Axle]
    regions: dict[str, RegionSpec] = Field(default_factory=dict)
    objectives: list[ObjectiveSpec] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form import notes: source file, applied datum shift, "
        "and which values came from defaults rather than measurement",
    )

    @model_validator(mode="after")
    def check_axle_keys(self) -> Design:
        """Keep the mapping key and the axle's own id in agreement."""
        for key, axle in self.axles.items():
            if key != axle.id:
                raise ValueError(f"Axle key {key!r} does not match axle id {axle.id!r}")
        unknown = {
            node.region
            for axle in self.axles.values()
            for corner in axle.corners
            for node in corner.nodes.values()
            if node.region is not None
        } - set(self.regions)
        if unknown:
            raise ValueError(f"Nodes reference undefined regions: {sorted(unknown)}")
        return self

    def corner(self, corner_id: str) -> Corner:
        """Look a corner up by id across both axles."""
        for axle in self.axles.values():
            for corner in axle.corners:
                if corner.id == corner_id:
                    return corner
        raise KeyError(f"No corner {corner_id!r} in design {self.name!r}")

    def geometry_state(self) -> dict[str, Any]:
        """Return only the fields that change a solve, in a canonical order.

        Names, rulesets, regions, objectives, and provenance are all excluded:
        none of them move a hardpoint or alter a constraint.
        """
        return {
            "schema_version": self.schema_version,
            "frame": self.frame,
            "tire": self.tire.model_dump(mode="json"),
            "vehicle": self.vehicle.model_dump(mode="json"),
            "axles": {
                axle_id: {
                    "architecture": axle.architecture,
                    "steering": axle.steering,
                    "center_nodes": {
                        node_id: node.position
                        for node_id, node in sorted(axle.center_nodes.items())
                    },
                    "corners": {
                        corner.id: {
                            "actuation": corner.actuation,
                            "spring": corner.spring,
                            "pushrod_mount": corner.pushrod_mount,
                            "nodes": {
                                node_id: node.position
                                for node_id, node in sorted(corner.nodes.items())
                            },
                        }
                        for corner in axle.corners
                    },
                }
                for axle_id, axle in sorted(self.axles.items())
            },
        }

    def fingerprint(self) -> str:
        """Stable hash over the geometry-affecting fields only.

        Used as the solver and optimizer cache key. Two designs that differ
        only in name, regions, objectives, ruleset, or provenance share a
        fingerprint; moving any hardpoint by any amount changes it.
        """
        payload = json.dumps(
            self.geometry_state(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialise to JSON."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str | bytes) -> Design:
        """Deserialise from JSON."""
        return cls.model_validate_json(data)

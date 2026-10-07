"""The `Design` model: validation, JSON round trip, and the fingerprint."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from workbench.core.design import (
    Axle,
    Corner,
    Design,
    Node,
    RegionSpec,
    TireSpec,
    VehicleSpec,
)


def _corner(corner_id: str) -> Corner:
    return Corner(
        id=corner_id,
        nodes={
            "lca_outboard": Node(id="lca_outboard", position=(0.0, 500.0, 130.0)),
            "wheel_center": Node(id="wheel_center", position=(0.0, 584.0, 223.5)),
        },
        actuation="pullrod_rocker",
    )


def _design(**overrides) -> Design:
    axle = Axle(id="front", steering="rack", left=_corner("lf"), right=_corner("rf"))
    base = {
        "name": "unit",
        "tire": TireSpec(
            overall_diameter_in=18.0, section_width_in=6.0, rim_diameter_in=10.0
        ),
        "vehicle": VehicleSpec(
            wheelbase_mm=1549.4, front_track_mm=1168.4, rear_track_mm=1143.0
        ),
        "axles": {"front": axle},
    }
    return Design(**(base | overrides))


class TestValidation:
    def test_node_ids_must_be_snake_case(self):
        with pytest.raises(ValidationError, match="snake_case"):
            Node(id="LCA Outboard", position=(0.0, 0.0, 0.0))

    def test_node_key_must_match_its_own_id(self):
        with pytest.raises(ValidationError, match="does not match node id"):
            Corner(
                id="lf",
                nodes={"wrong": Node(id="lca_outboard", position=(0.0, 0.0, 0.0))},
            )

    def test_axle_rejects_a_corner_from_the_other_end_of_the_car(self):
        with pytest.raises(ValidationError, match="left corner must be 'lf'"):
            Axle(id="front", left=_corner("lr"))

    def test_design_rejects_a_node_bound_to_an_undefined_region(self):
        corner = _corner("lf")
        corner.nodes["lca_outboard"].region = "ghost"
        axle = Axle(id="front", left=corner, right=_corner("rf"))
        with pytest.raises(ValidationError, match="undefined regions"):
            _design(axles={"front": axle})

    def test_design_accepts_a_node_bound_to_a_defined_region(self):
        corner = _corner("lf")
        corner.nodes["lca_outboard"].region = "r1"
        design = _design(
            axles={"front": Axle(id="front", left=corner, right=_corner("rf"))},
            regions={"r1": RegionSpec(id="r1", kind="box")},
        )
        assert design.corner("lf").nodes["lca_outboard"].region == "r1"

    def test_a_tire_radius_below_the_rim_radius_is_rejected(self):
        with pytest.raises(ValidationError, match="must exceed the rim radius"):
            TireSpec(
                overall_diameter_in=18.0,
                section_width_in=6.0,
                rim_diameter_in=10.0,
                loaded_radius_mm=100.0,
            )


class TestSerialisation:
    def test_json_round_trip_is_lossless(self):
        design = _design()
        assert Design.from_json(design.to_json()) == design

    def test_json_round_trip_preserves_the_fingerprint(self, golden_design):
        restored = Design.from_json(golden_design.to_json())
        assert restored.fingerprint() == golden_design.fingerprint()

    def test_region_payload_fields_survive_the_round_trip(self):
        """`Design` carries region payloads it does not itself understand."""
        design = _design(
            regions={
                "r1": RegionSpec(
                    id="r1",
                    kind="box",
                    allow=False,
                    source="rule:V.1.1",
                    applies_to=["lf.wheel_center", "!*contact_patch*"],
                    min=[0.0, 0.0, 0.0],
                    max=[10.0, 10.0, 10.0],
                )
            }
        )
        restored = Design.from_json(design.to_json())
        region = restored.regions["r1"]
        assert region.applies_to == ["lf.wheel_center", "!*contact_patch*"]
        assert region.model_extra == {"min": [0.0] * 3, "max": [10.0] * 3}


class TestFingerprint:
    def test_is_stable_across_calls(self, golden_design):
        assert golden_design.fingerprint() == golden_design.fingerprint()

    def test_changes_when_a_hardpoint_moves(self, golden_design):
        moved = golden_design.model_copy(deep=True)
        node = moved.corner("lf").nodes["lca_outboard"]
        x, y, z = node.position
        node.position = (x + 0.001, y, z)
        assert moved.fingerprint() != golden_design.fingerprint()

    def test_changes_when_the_tire_changes(self, golden_design):
        other = golden_design.model_copy(
            update={
                "tire": golden_design.tire.model_copy(
                    update={"loaded_radius_mm": 228.6}
                )
            }
        )
        assert other.fingerprint() != golden_design.fingerprint()

    def test_changes_when_the_pushrod_mount_changes(self, golden_design):
        """The mount body moves the motion ratio, so it must be in the hash."""
        other = golden_design.model_copy(deep=True)
        other.axles["front"].left.pushrod_mount = "upright"
        assert other.fingerprint() != golden_design.fingerprint()

    @pytest.mark.parametrize(
        "field, value",
        [
            ("name", "something else"),
            ("ruleset", ("fsae_us", 2026)),
            ("objectives", []),
            ("provenance", {"note": "irrelevant"}),
        ],
    )
    def test_ignores_fields_that_cannot_change_a_solve(
        self, golden_design, field, value
    ):
        other = golden_design.model_copy(update={field: value})
        assert other.fingerprint() == golden_design.fingerprint()

    def test_ignores_regions(self, golden_design):
        other = golden_design.model_copy(
            update={"regions": {"r1": RegionSpec(id="r1", kind="box")}}
        )
        assert other.fingerprint() == golden_design.fingerprint()


class TestLabels:
    def test_a_pullrod_corner_says_pullrod(self, golden_design):
        front = golden_design.corner("lf")
        assert front.actuation == "pullrod_rocker"
        assert front.node_label("pushrod_outboard") == "Pullrod Outboard"
        assert front.node_label("rocker_pushrod") == "Rocker Pullrod"

    def test_a_pushrod_corner_says_pushrod(self, golden_design):
        rear = golden_design.corner("lr")
        assert rear.actuation == "pushrod_rocker"
        assert rear.node_label("pushrod_outboard") == "Pushrod Outboard"

    def test_an_unknown_node_falls_back_to_a_readable_label(self, golden_design):
        assert golden_design.corner("lf").node_label("heave_pivot") == "Heave Pivot"


class TestRulesFacingFields:
    """`workbench.rules._design_access` reads these names off the model.

    The rules package was written in parallel against `contracts.md` and reads
    the design through a tolerant accessor. These assertions pin the names that
    accessor resolves, so renaming a field here fails here rather than silently
    degrading every geometric rule to "not verifiable".
    """

    def test_vehicle_exposes_the_lengths_the_rules_read(self, golden_design):
        vehicle = golden_design.vehicle
        assert vehicle.wheelbase_mm == pytest.approx(1549.4)
        assert vehicle.front_track_mm == pytest.approx(1168.4)
        assert vehicle.rear_track_mm == pytest.approx(1143.0)
        assert vehicle.cg_height_mm > 0.0

    def test_tire_exposes_both_inch_and_millimetre_views(self, golden_design):
        tire = golden_design.tire
        assert tire.rim_diameter_in == pytest.approx(10.0)
        assert tire.rim_diameter_mm == pytest.approx(254.0)
        assert tire.outer_diameter_mm == pytest.approx(457.2)
        assert tire.section_width_mm == pytest.approx(152.4)

    def test_scrutineering_declarations_default_to_unstated(self, golden_design):
        """Unstated means "not verifiable", never a rule passed on a guess."""
        vehicle = golden_design.vehicle
        assert vehicle.wheel_travel_mm is None
        assert vehicle.steering_free_play_deg is None
        assert vehicle.rear_steer_max_deg is None

    def test_scrutineering_declarations_round_trip_when_stated(self, golden_design):
        stated = golden_design.model_copy(
            update={
                "vehicle": golden_design.vehicle.model_copy(
                    update={
                        "wheel_travel_mm": 50.8,
                        "steering_free_play_deg": 5.0,
                        "rear_steer_max_deg": 0.0,
                    }
                )
            }
        )
        restored = Design.from_json(stated.to_json())
        assert restored.vehicle.wheel_travel_mm == pytest.approx(50.8)
        assert restored.vehicle.rear_steer_max_deg == pytest.approx(0.0)


def test_cg_sits_behind_the_front_axle_on_the_design_datum(golden_design):
    """+X is forward and the front axle is the origin, so the CG is negative."""
    vehicle = golden_design.vehicle
    assert vehicle.cg_x_mm < 0.0
    assert abs(vehicle.cg_x_mm) < vehicle.wheelbase_mm

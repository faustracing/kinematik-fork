"""Behaviour of the encoded Formula SAE US clauses.

Every limit asserted here is also written out longhand so a reader can check
it against the rulebook without opening the source: 1525 mm wheelbase (V.1.2),
75% track ratio (V.1.3.2), 50 mm wheel travel (V.3.1.1), 7 degrees of steering
free play (V.3.2.5), 6 degrees of rear steer (V.3.2.10.a), 203.2 mm wheels
(V.4.1), 75 mm keep-out margin (V.1.1.c), 60 degree tilt (IN.11.2.2).
"""

from __future__ import annotations

import numpy as np
import pytest

from _stub_design import (
    TRACK_FRONT_MM,
    WHEELBASE_MM,
    Design,
    Node,
    golden_car,
    mirrored_car,
)
from workbench.regions import feasible, regions_for_node
from workbench.rules import Severity
from workbench.rules.registry import get


@pytest.fixture
def rules():  # noqa: ANN201
    return get("fsae_us", 2026)


def by_id(findings) -> dict[str, object]:  # noqa: ANN001
    return {f.rule_id: f for f in findings}


def blockers(findings) -> list[str]:  # noqa: ANN001
    return sorted(f.rule_id for f in findings if f.severity == Severity.BLOCKER)


def warnings(findings) -> list[str]:  # noqa: ANN001
    return sorted(f.rule_id for f in findings if f.severity == Severity.WARNING)


# -- the baseline car ---------------------------------------------------------


def test_a_legal_car_raises_nothing_but_the_advisory(rules) -> None:  # noqa: ANN001
    findings = rules.check_all(golden_car())
    assert blockers(findings) == []
    assert warnings(findings) == []
    assert [f.rule_id for f in findings] == ["steering_stops_present"]
    assert findings[0].severity == Severity.INFO


def test_the_mirrored_car_is_evaluated_as_four_corners(rules) -> None:  # noqa: ANN001
    design = mirrored_car()
    assert blockers(rules.check_all(design)) == []
    keep_outs = [
        r for r in rules.illegal_regions(design) if "open_wheel_keep_out" in r.id
    ]
    assert sorted(r.id.rsplit(".", 1)[1] for r in keep_outs) == ["lf", "lr", "rf", "rr"]


# -- V.1.2 wheelbase ----------------------------------------------------------


def test_short_wheelbase_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car(wheelbase_mm=1500.0)
    finding = by_id(rules.check_all(design))["wheelbase_min"]
    assert finding.severity == Severity.BLOCKER
    assert finding.citation == "V.1.2"
    assert finding.limit == 1525.0
    assert finding.measured == 1500.0


def test_wheelbase_exactly_at_the_limit_passes(rules) -> None:  # noqa: ANN001
    assert "wheelbase_min" not in by_id(rules.check_all(golden_car(wheelbase_mm=1525.0)))


def test_wheelbase_region_excludes_a_rear_axle_that_is_too_far_forward(
    rules,  # noqa: ANN001
) -> None:
    design = golden_car()
    region = next(r for r in rules.illegal_regions(design) if r.id.endswith("min.rear"))
    assert region.allow is False
    assert region.source == "rule:V.1.2"
    assert set(region.applies_to) == {"lr.wheel_center", "rr.wheel_center"}
    # The front wheel centres sit at x = 0, so a rear wheel centre forward of
    # x = -1525 mm is illegal and one behind it is not.
    assert region.contains([-1400.0, 571.5, 223.52])
    assert not region.contains([-1600.0, 571.5, 223.52])
    assert not region.contains([-WHEELBASE_MM, 571.5, 223.52])


def test_wheelbase_region_clamps_an_illegal_point_back_to_legal(
    rules,  # noqa: ANN001
) -> None:
    design = golden_car()
    region = next(r for r in rules.illegal_regions(design) if r.id.endswith("min.rear"))
    fixed = region.clamp([-1400.0, 571.5, 223.52])
    assert region.permits(fixed)
    assert fixed[0] <= -1525.0


# -- V.1.3.2 track ratio ------------------------------------------------------


def test_narrow_rear_track_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car(track_rear_mm=700.0)  # 59.9% of the 1168.4 mm front
    finding = by_id(rules.check_all(design))["track_ratio_min"]
    assert finding.severity == Severity.BLOCKER
    assert finding.citation == "V.1.3.2"
    assert finding.limit == 0.75
    assert finding.measured == pytest.approx(700.0 / TRACK_FRONT_MM)


def test_track_ratio_exactly_at_75_percent_passes(rules) -> None:  # noqa: ANN001
    design = golden_car(track_rear_mm=0.75 * TRACK_FRONT_MM)
    assert "track_ratio_min" not in by_id(rules.check_all(design))


def test_track_ratio_region_excludes_wheel_centres_near_the_centreline(
    rules,  # noqa: ANN001
) -> None:
    design = golden_car()
    region = next(r for r in rules.illegal_regions(design) if r.id == "rule.track_ratio_min")
    half = 0.75 * TRACK_FRONT_MM / 2.0
    assert region.contains([-WHEELBASE_MM, half - 10.0, 223.52])
    assert not region.contains([-WHEELBASE_MM, half + 10.0, 223.52])
    assert set(region.applies_to) == {"lr.wheel_center", "rr.wheel_center"}


# -- V.1.3.1 / IN.11.2.2 tilt -------------------------------------------------


def test_tall_cg_warns_about_the_tilt_test(rules) -> None:  # noqa: ANN001
    design = golden_car(cg_height_mm=400.0)
    finding = by_id(rules.check_all(design))["rollover_tilt_stability"]
    assert finding.severity == Severity.WARNING
    assert finding.citation == "V.1.3.1 / IN.11.2.2"
    assert finding.limit == pytest.approx(np.tan(np.radians(60.0)))
    assert finding.measured == pytest.approx((1143.0 / 2) / 400.0)


def test_low_cg_passes_the_tilt_criterion(rules) -> None:  # noqa: ANN001
    # 1143 / 2 / tan 60 = 330 mm, so 300 mm is comfortably upright.
    assert "rollover_tilt_stability" not in by_id(
        rules.check_all(golden_car(cg_height_mm=300.0))
    )


# -- V.1.4.1 ground clearance -------------------------------------------------


def test_a_hardpoint_below_the_ground_plane_warns(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.axles["front"].left.nodes["lca_outboard"] = Node(
        id="lca_outboard", position=(0.0, 540.0, -5.0)
    )
    finding = by_id(rules.check_all(design))["ground_contact_clearance"]
    assert finding.severity == Severity.WARNING
    assert finding.citation == "V.1.4.1"
    assert "lf.lca_outboard" in finding.nodes


def test_contact_patches_are_exempt_from_the_ground_rule(rules) -> None:  # noqa: ANN001
    # Every contact patch sits at z = 0 by construction and must not trip it.
    assert "ground_contact_clearance" not in by_id(rules.check_all(golden_car()))


def test_ground_region_excludes_everything_but_the_contact_patches(
    rules,  # noqa: ANN001
) -> None:
    design = golden_car()
    region = next(
        r for r in rules.illegal_regions(design) if r.id == "rule.ground_contact_clearance"
    )
    assert region.contains([0.0, 0.0, -50.0])
    assert not region.contains([0.0, 0.0, 50.0])
    assert region.applies_to_node("lf.lca_outboard")
    assert not region.applies_to_node("lf.contact_patch")
    fixed = region.clamp([0.0, 0.0, -50.0])
    assert fixed[2] > 0.0


# -- V.1.1.c open-wheel keep-out ----------------------------------------------


def test_keep_out_zone_spans_75_mm_past_the_tire(rules) -> None:  # noqa: ANN001
    design = golden_car()
    region = next(
        r for r in rules.illegal_regions(design) if r.id.endswith("keep_out.lf")
    )
    radius = design.tire.outer_diameter_mm / 2.0
    lo, hi = region.bounds()
    assert hi[0] == pytest.approx(0.0 + radius + 75.0)
    assert lo[0] == pytest.approx(0.0 - radius - 75.0)
    # Laterally it is exactly the wheel band.
    half_track = TRACK_FRONT_MM / 2.0
    assert lo[1] == pytest.approx(half_track - design.tire.width_mm / 2.0)
    assert hi[1] == pytest.approx(half_track + design.tire.width_mm / 2.0)


def test_keep_out_zone_binds_bodywork_not_hardpoints(rules) -> None:  # noqa: ANN001
    region = next(
        r for r in rules.illegal_regions(golden_car()) if r.id.endswith("keep_out.lf")
    )
    assert not region.applies_to_node("lf.lca_outboard")
    assert region.applies_to_node("lf.bodywork_nose_fairing")


# -- V.3.1.1 suspension -------------------------------------------------------


def test_insufficient_wheel_travel_is_a_blocker(rules) -> None:  # noqa: ANN001
    finding = by_id(rules.check_all(golden_car(wheel_travel_mm=40.0)))[
        "suspension_travel_min"
    ]
    assert finding.severity == Severity.BLOCKER
    assert (finding.citation, finding.limit) == ("V.3.1.1", 50.0)


def test_exactly_50_mm_of_travel_passes(rules) -> None:  # noqa: ANN001
    assert "suspension_travel_min" not in by_id(
        rules.check_all(golden_car(wheel_travel_mm=50.0))
    )


def test_unknown_travel_degrades_to_info_rather_than_passing(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.vehicle.wheel_travel_mm = None
    finding = by_id(rules.check_all(design))["suspension_travel_min"]
    assert finding.severity == Severity.INFO
    assert "not verifiable" in finding.message


def test_a_corner_without_a_spring_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.axles["rear"].left.spring = "none"
    finding = by_id(rules.check_all(design))["shock_absorbers_present"]
    assert finding.severity == Severity.BLOCKER
    assert finding.citation == "V.3.1.1"
    assert finding.nodes == ["lr"]


# -- V.3.2 steering -----------------------------------------------------------


def test_unsteered_front_axle_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.axles["front"].steering = "none"
    finding = by_id(rules.check_all(design))["front_steering_mechanical"]
    assert finding.severity == Severity.BLOCKER
    assert finding.citation == "V.3.2.1"


def test_excessive_steering_free_play_is_a_blocker(rules) -> None:  # noqa: ANN001
    finding = by_id(rules.check_all(golden_car(steering_free_play_deg=7.0)))[
        "steering_free_play_max"
    ]
    assert finding.limit == 7.0
    assert finding.measured == 7.0
    assert "less than" not in finding.message  # the clause is strict, not inclusive


def test_free_play_just_under_seven_degrees_passes(rules) -> None:  # noqa: ANN001
    assert "steering_free_play_max" not in by_id(
        rules.check_all(golden_car(steering_free_play_deg=6.9))
    )


def test_steering_stops_are_always_advisory(rules) -> None:  # noqa: ANN001
    finding = by_id(rules.check_all(golden_car()))["steering_stops_present"]
    assert finding.severity == Severity.INFO
    assert finding.citation == "V.3.2.4"
    assert "verify by hand" in finding.message


def test_rear_steer_rule_is_silent_on_an_unsteered_rear_axle(rules) -> None:  # noqa: ANN001
    assert "rear_steer_angle_max" not in by_id(rules.check_all(golden_car()))


def test_excessive_rear_steer_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car(rear_steer_max_deg=8.0)
    design.axles["rear"].steering = "rack"
    finding = by_id(rules.check_all(design))["rear_steer_angle_max"]
    assert (finding.citation, finding.limit, finding.measured) == ("V.3.2.10", 6.0, 8.0)


def test_six_degrees_of_rear_steer_passes(rules) -> None:  # noqa: ANN001
    design = golden_car(rear_steer_max_deg=6.0)
    design.axles["rear"].steering = "rack"
    assert "rear_steer_angle_max" not in by_id(rules.check_all(design))


# -- V.4.1 wheels -------------------------------------------------------------


def test_undersized_wheel_is_a_blocker(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.tire.rim_diameter_mm = 177.8  # 7 inch
    finding = by_id(rules.check_all(design))["wheel_diameter_min"]
    assert (finding.citation, finding.limit) == ("V.4.1", 203.2)


def test_eight_inch_wheels_pass(rules) -> None:  # noqa: ANN001
    design = golden_car()
    design.tire.rim_diameter_mm = 203.2
    assert "wheel_diameter_min" not in by_id(rules.check_all(design))


# -- missing data handling ----------------------------------------------------


def test_an_empty_design_produces_info_not_crashes_or_false_passes(rules) -> None:  # noqa: ANN001
    findings = rules.check_all(Design())
    assert blockers(findings) == []
    severities = {f.severity for f in findings}
    assert severities == {Severity.INFO}
    assert rules.illegal_regions(Design()) == []


def test_an_ambiguous_unit_is_refused_rather_than_guessed(rules) -> None:  # noqa: ANN001
    class SloppyTire:
        rim_diameter = 10.0  # inches, but not labelled as such

    design = golden_car()
    design.tire = SloppyTire()  # type: ignore[assignment]
    finding = by_id(rules.check_all(design))["wheel_diameter_min"]
    assert finding.severity == Severity.INFO
    assert "_mm or _in" in finding.message


def test_an_explicit_inch_field_is_converted(rules) -> None:  # noqa: ANN001
    class InchTire:
        rim_diameter_in = 7.0

    design = golden_car()
    design.tire = InchTire()  # type: ignore[assignment]
    finding = by_id(rules.check_all(design))["wheel_diameter_min"]
    assert finding.severity == Severity.BLOCKER
    assert finding.measured == pytest.approx(177.8)


# -- the region payload as the optimizer sees it ------------------------------


def test_every_illegal_region_is_denied_cited_and_serialisable(rules) -> None:  # noqa: ANN001
    for region in rules.illegal_regions(golden_car()):
        assert region.allow is False
        assert region.source.startswith("rule:")
        assert region.label
        view = region.to_viewport()
        assert set(view) == {"id", "kind", "allow", "label", "mesh"}


def test_illegal_regions_leave_the_legal_cars_hardpoints_alone(rules) -> None:  # noqa: ANN001
    design = golden_car()
    illegal = rules.illegal_regions(design)
    for axle in design.axles.values():
        for corner in (axle.left, axle.right):
            for key, node in corner.nodes.items():
                node_id = f"{corner.id}.{key}"
                scoped = regions_for_node(illegal, node_id)
                assert feasible(scoped, np.asarray(node.position)), node_id


def test_an_illegal_rear_wheel_centre_is_caught_by_the_region_set(rules) -> None:  # noqa: ANN001
    design = golden_car()
    illegal = rules.illegal_regions(design)
    scoped = regions_for_node(illegal, "lr.wheel_center")
    too_far_forward = np.array([-1000.0, 571.5, 223.52])
    assert not feasible(scoped, too_far_forward)


def test_2027_produces_the_same_verdicts_as_2026() -> None:
    design = golden_car(wheelbase_mm=1400.0, cg_height_mm=450.0)
    y26 = {(f.rule_id, f.severity, f.measured) for f in get("fsae_us", 2026).check_all(design)}
    y27 = {(f.rule_id, f.severity, f.measured) for f in get("fsae_us", 2027).check_all(design)}
    assert y26 == y27

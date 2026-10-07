"""Golden regression: the reference car through the solver bridge.

Every number here was produced by this code against
`tests/fixtures/golden-car-hardpoints.csv` and cross-checked against
KinematiK's independent double-wishbone solver where the two tools compute the
same quantity. The README records the comparison, including the two
definitional differences — "scrub radius" and the travel datum — that make a
naive comparison look like disagreement.

Tolerances are tight (1e-6 relative) because this pins *our* solver chain, not
a physical measurement: a change this size means the bridge changed.
"""

from __future__ import annotations

import math

import pytest
from workbench.core.defaults import GOLDEN_CAR
from workbench.solve import motion_ratio, solve, wheel_rate_n_per_mm

pytestmark = [pytest.mark.solver, pytest.mark.golden]

REL = 1e-6

#: Static metrics at the midpoint of a symmetric +/-25 mm bump sweep.
#:
#: Static camber and toe are zero *by construction*, not by measurement: the
#: hardpoint file carries no wheel spin axis, so `SpinAxisPolicy` supplies them
#: and defaults both to zero. See the README. Camber gain is real geometry.
FRONT_STATIC = {
    "camber_left": 0.0,
    "toe_angle_left": 0.0,
    "caster_left": 5.000981002847188,
    "kpi_left": 8.00448162513311,
    "scrub_radius_left": 35.915054463809966,
    "steering_axis_offset_ground_left": 25.38946070972384,
    "mechanical_trail_left": 25.402094835029366,
    "roll_center_z": 25.34896323602971,
    "fvic_y_left": -686.398119911743,
    "fvic_z_left": 55.13239475293658,
    "half_track_left": 584.2000019736714,
    "track": 1168.4,
    "anti_dive_left": 31.00546235327764,
    "deriv_camber_wrt_hub_z_left": -0.04484296229061067,
    "deriv_toe_angle_wrt_hub_z_left": 9.270231967346337e-05,
    "deriv_spring_length_wrt_hub_z_left": -0.6838663855955637,
}

REAR_STATIC = {
    "camber_left": 0.0,
    "toe_angle_left": 0.0,
    "caster_left": 0.0,
    "kpi_left": 5.99991966389831,
    "scrub_radius_left": 28.395564113872286,
    "steering_axis_offset_ground_left": 25.397205759004443,
    "mechanical_trail_left": 12.700000038575714,
    "roll_center_z": 71.99378212178596,
    "fvic_y_left": -469.00331241777843,
    "fvic_z_left": 131.075710697977,
    "half_track_left": 571.5000018162622,
    "track": 1143.0,
    "anti_squat_left": -27.64220927910989,
    "deriv_camber_wrt_hub_z_left": -0.055069976591429204,
    "deriv_toe_angle_wrt_hub_z_left": -0.0017467647834324494,
    "deriv_spring_length_wrt_hub_z_left": -0.7611318702506611,
}

#: Motion ratio (spring travel per mm of *wheel-centre* travel) and the wheel
#: rate the measured damper-end spring rate refers to through it.
MOTION_RATIO = {"front": 0.6838663855955637, "rear": 0.7611318702506611}
WHEEL_RATE_N_PER_MM = {"front": 20.47473415595531, "rear": 22.82527592210401}


def _assert_pinned(actual: dict[str, float], expected: dict[str, float]) -> None:
    for key, value in expected.items():
        assert key in actual, f"metric {key!r} disappeared from the solver output"
        if value == 0.0:
            # A metric that is zero by construction: assert it is numerically
            # zero rather than relatively close to zero.
            assert actual[key] == pytest.approx(0.0, abs=1e-6), key
        else:
            assert actual[key] == pytest.approx(value, rel=REL), key


class TestConvergence:
    def test_the_front_axle_bump_sweep_converges_at_every_step(self, front_bump):
        assert front_bump.converged
        assert front_bump.n_steps == 21
        assert front_bump.findings == ()

    def test_the_rear_axle_bump_sweep_converges_at_every_step(self, rear_bump):
        assert rear_bump.converged
        assert rear_bump.n_steps == 21
        assert rear_bump.findings == ()

    def test_every_step_reports_a_converged_solver(self, front_bump):
        assert all(info.converged for info in front_bump.evaluated.solver_stats)

    def test_no_metric_is_undefined_across_the_sweep(self, front_bump):
        """A `nan` mid-sweep means the solver lost a metric, not a bad design."""
        for key in FRONT_STATIC:
            values = front_bump.metrics[key]
            assert not any(math.isnan(v) for v in values), key

    @pytest.mark.parametrize("axle", ["front", "rear"])
    @pytest.mark.parametrize("sweep", ["bump", "droop", "roll"])
    def test_every_axle_agnostic_template_converges(
        self, golden_design, solver, axle, sweep
    ):
        result = solve(golden_design, axle, sweep, steps=11)
        assert result.converged, result.findings

    @pytest.mark.parametrize("sweep", ["steer", "combined"])
    def test_the_steering_templates_converge_on_the_front_axle(
        self, golden_design, solver, sweep
    ):
        result = solve(golden_design, "front", sweep, steps=11)
        assert result.converged, result.findings


class TestStaticMetrics:
    def test_front_static_metrics_are_pinned(self, front_bump):
        _assert_pinned(front_bump.static(), FRONT_STATIC)

    def test_rear_static_metrics_are_pinned(self, rear_bump):
        _assert_pinned(rear_bump.static(), REAR_STATIC)

    def test_the_front_corner_has_positive_caster_and_kpi(self, front_bump):
        """A sanity floor under the pins: the signs must be physical."""
        static = front_bump.static()
        assert 3.0 < static["caster_left"] < 8.0
        assert 5.0 < static["kpi_left"] < 12.0

    def test_the_rear_corner_has_no_caster(self, rear_bump):
        """Both rear outboard ball joints sit at X = -762, so the axis is upright."""
        assert rear_bump.static()["caster_left"] == pytest.approx(0.0, abs=1e-6)

    def test_both_axles_gain_negative_camber_in_bump(self, front_bump, rear_bump):
        for result in (front_bump, rear_bump):
            assert result.static()["deriv_camber_wrt_hub_z_left"] < 0.0

    def test_left_and_right_agree_on_a_mirrored_car(self, front_bump):
        """The fixture is exactly mirrored, so the two corners must match."""
        static = front_bump.static()
        for key in ("camber", "caster", "kpi", "scrub_radius", "half_track"):
            # abs covers the metrics that are zero by construction, where a
            # relative tolerance would only be comparing solver noise.
            assert static[f"{key}_left"] == pytest.approx(
                static[f"{key}_right"], rel=1e-9, abs=1e-6
            ), key

    def test_the_roll_centre_sits_on_the_centreline(self, front_bump, rear_bump):
        for result in (front_bump, rear_bump):
            assert result.static()["roll_center_y"] == pytest.approx(0.0, abs=1e-5)

    def test_the_rear_roll_centre_is_higher_than_the_front(self, front_bump, rear_bump):
        front = front_bump.static()["roll_center_z"]
        rear = rear_bump.static()["roll_center_z"]
        assert 0.0 < front < rear


class TestMotionRatio:
    @pytest.mark.parametrize("axle", ["front", "rear"])
    def test_the_motion_ratio_is_pinned(self, request, axle):
        result = request.getfixturevalue(f"{axle}_bump")
        assert motion_ratio(result) == pytest.approx(MOTION_RATIO[axle], rel=REL)

    @pytest.mark.parametrize("axle", ["front", "rear"])
    def test_the_motion_ratio_is_in_the_normal_fsae_range(self, request, axle):
        result = request.getfixturevalue(f"{axle}_bump")
        assert 0.4 < motion_ratio(result) < 0.9

    @pytest.mark.parametrize("axle", ["front", "rear"])
    def test_the_measured_spring_rate_refers_to_a_pinned_wheel_rate(
        self, request, axle
    ):
        """Spring rates are quoted at the damper, so the ratio squares in."""
        result = request.getfixturevalue(f"{axle}_bump")
        spring = GOLDEN_CAR.axle(axle).spring
        assert spring.measured_at == "damper"
        rate = wheel_rate_n_per_mm(result, spring.rate_n_per_mm)
        assert rate == pytest.approx(WHEEL_RATE_N_PER_MM[axle], rel=REL)
        assert rate < spring.rate_n_per_mm, "a ratio below 1 softens the wheel rate"

    def test_the_mount_body_moves_the_ratio_but_not_the_linkage(
        self, golden_design, solver
    ):
        """The one inference that changes a number, pinned so it stays visible."""
        on_upright = golden_design.model_copy(deep=True)
        for corner in on_upright.axles["front"].corners:
            corner.pushrod_mount = "upright"
        result = solve(on_upright, "front", "bump", steps=11)
        assert result.converged
        assert motion_ratio(result) == pytest.approx(0.7369384692427556, rel=1e-6)
        static = result.static()
        assert static["deriv_camber_wrt_hub_z_left"] == pytest.approx(
            FRONT_STATIC["deriv_camber_wrt_hub_z_left"], rel=1e-6
        )
        assert static["kpi_left"] == pytest.approx(FRONT_STATIC["kpi_left"], rel=1e-9)


class TestTireRadiusAndTheGroundPlane:
    def test_the_solved_contact_patch_lands_on_the_authored_one(
        self, golden_design, front_bump
    ):
        """End-to-end proof that frame, datum, and loaded radius all line up.

        The solver derives the contact patch from the hub points and the tire
        radius; the CSV states it explicitly. They agree to a micron, which
        only happens when the Z datum is the ground plane *and* the loaded
        radius is used rather than the unloaded one.
        """
        authored = golden_design.corner("lf").position("contact_patch")
        solved = front_bump.positions["lf.contact_patch"][front_bump.n_steps // 2]
        assert solved == pytest.approx(authored, abs=1e-5)

    def test_the_unloaded_radius_would_sink_the_ground_plane(
        self, golden_design, solver
    ):
        """Why `loaded_radius_mm` is not optional in practice."""
        unloaded = golden_design.model_copy(
            update={
                "tire": golden_design.tire.model_copy(update={"loaded_radius_mm": None})
            }
        )
        result = solve(unloaded, "front", "bump", steps=11)
        assert result.converged
        solved_z = result.positions["lf.contact_patch"][result.n_steps // 2][2]
        assert solved_z == pytest.approx(-5.08, abs=1e-4)
        shift = result.static()["roll_center_z"] - FRONT_STATIC["roll_center_z"]
        assert shift == pytest.approx(-2.744, abs=1e-3)

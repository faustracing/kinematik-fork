"""The solver bridge: geometry translation, reconstruction, error containment."""

from __future__ import annotations

import numpy as np
import pytest
from workbench.solve import sweeps
from workbench.solve.bridge import (
    WorkbenchSolveError,
    rocker_axis_points,
    solve,
    spin_axis_points,
    to_se_geometry,
)


class TestGeometryTranslation:
    def test_builds_an_axle_scope_geometry_with_both_corners(self, golden_design):
        geometry = to_se_geometry(golden_design, "front")
        assert geometry["scope"] == "axle"
        assert geometry["type"] == "double_wishbone"
        assert set(geometry["hardpoints"]) == {"left", "right", "center"}

    def test_translates_node_ids_to_solver_point_ids(self, golden_design):
        left = to_se_geometry(golden_design, "front")["hardpoints"]["left"]
        assert left["lower_wishbone_inboard_front"]["x"] == pytest.approx(87.808)
        assert "trackrod_inboard" in left
        assert "strut_bottom" in left and "strut_top" in left

    def test_a_pullrod_corner_is_a_pushrod_rocker_to_the_solver(self, golden_design):
        """One mechanism kinematically; the distinction lives in `actuation`."""
        geometry = to_se_geometry(golden_design, "front")
        assert golden_design.corner("lf").actuation == "pullrod_rocker"
        assert geometry["axle_config"]["actuation"]["type"] == "pushrod_rocker"
        assert geometry["axle_config"]["actuation"]["mount"] == "upper_wishbone"

    def test_the_rear_axle_is_unsteered(self, golden_design):
        geometry = to_se_geometry(golden_design, "rear")
        assert geometry["axle_config"]["steering"]["type"] == "none"
        assert "toe_link_inboard" in geometry["hardpoints"]["left"]

    def test_the_tire_aspect_ratio_reproduces_the_loaded_radius(self, golden_design):
        tire = to_se_geometry(golden_design, "front")["axle_config"]["wheel"]["tire"]
        rim_mm = tire["rim_diameter"] * 25.4
        radius = (rim_mm + 2 * tire["aspect_ratio"] * tire["section_width"]) / 2
        assert radius == pytest.approx(223.52)

    def test_wheel_centre_and_contact_patch_are_not_sent_as_hardpoints(
        self, golden_design
    ):
        """Both are solver outputs derived from the hub points and the tire."""
        left = to_se_geometry(golden_design, "front")["hardpoints"]["left"]
        assert "wheel_center" not in left
        assert "contact_patch" not in left
        assert {"axle_inboard", "axle_outboard"} <= set(left)

    def test_an_unknown_axle_is_a_readable_error(self, golden_design):
        with pytest.raises(WorkbenchSolveError, match="has no 'middle' axle"):
            to_se_geometry(golden_design, "middle")

    def test_mismatched_per_side_hardware_is_rejected(self, golden_design):
        """The solver configures actuation per axle, so the sides must agree."""
        design = golden_design.model_copy(deep=True)
        design.axles["front"].right.pushrod_mount = "upright"
        with pytest.raises(WorkbenchSolveError, match="disagree on 'pushrod_mount'"):
            to_se_geometry(design, "front")

    def test_an_axle_without_an_explicit_right_corner_is_rejected(self, golden_design):
        design = golden_design.model_copy(deep=True)
        design.axles["front"].right = None
        with pytest.raises(WorkbenchSolveError, match="no explicit right corner"):
            to_se_geometry(design, "front")


class TestSpinAxisReconstruction:
    def test_the_outboard_hub_point_is_the_authored_wheel_centre(self, golden_design):
        corner = golden_design.corner("lf")
        _, outboard = spin_axis_points(corner)
        assert outboard == pytest.approx(corner.position("wheel_center"))

    def test_zero_camber_and_toe_give_a_purely_lateral_axis(self, golden_design):
        inboard, outboard = spin_axis_points(golden_design.corner("lf"))
        direction = outboard - inboard
        assert direction[0] == pytest.approx(0.0)
        assert direction[2] == pytest.approx(0.0)
        assert direction[1] > 0.0, "the left wheel's outboard direction is +Y"

    def test_the_right_corner_axis_points_the_other_way(self, golden_design):
        inboard, outboard = spin_axis_points(golden_design.corner("rf"))
        assert (outboard - inboard)[1] < 0.0

    def test_negative_camber_raises_the_outboard_end_on_both_sides(self, golden_design):
        """Negative camber leans the wheel top inboard, whichever side it is."""
        for corner_id in ("lf", "rf"):
            inboard, outboard = spin_axis_points(
                golden_design.corner(corner_id), static_camber_deg=-1.5
            )
            assert (outboard - inboard)[2] > 0.0

    def test_the_axis_length_does_not_change_the_direction(self, golden_design):
        corner = golden_design.corner("lf")
        short = spin_axis_points(corner, half_length_mm=50.0)
        long = spin_axis_points(corner, half_length_mm=200.0)

        def unit(pair):
            delta = pair[1] - pair[0]
            return delta / np.linalg.norm(delta)

        assert unit(short) == pytest.approx(unit(long))

    @pytest.mark.solver
    def test_the_authored_camber_and_toe_are_what_the_solver_reports(
        self, golden_design, solver
    ):
        """The reconstruction's sign convention, pinned against the solver."""
        from workbench.core.defaults import (
            GOLDEN_CAR,
            AxleDefaults,
            CarDefaults,
            SpinAxisPolicy,
        )

        policy = SpinAxisPolicy(static_camber_deg=-1.5, static_toe_deg=0.25)
        cambered = CarDefaults(
            front=AxleDefaults(
                tire=GOLDEN_CAR.front.tire,
                spring=GOLDEN_CAR.front.spring,
                spin_axis=policy,
            ),
            rear=GOLDEN_CAR.rear,
        )
        result = solve(golden_design, "front", "bump", steps=5, car_defaults=cambered)
        assert result.converged
        static = result.static()
        assert static["camber_left"] == pytest.approx(-1.5, abs=1e-3)
        assert static["toe_angle_left"] == pytest.approx(0.25, abs=1e-3)


class TestRockerAxisReconstruction:
    def test_the_axis_is_normal_to_the_rocker_plane(self, golden_design):
        corner = golden_design.corner("lf")
        axis_a, axis_b = rocker_axis_points(corner)
        axis = axis_b - axis_a
        pivot = np.asarray(corner.position("rocker_pivot"))
        for node_id in ("rocker_pushrod", "rocker_damper"):
            arm = np.asarray(corner.position(node_id)) - pivot
            assert float(np.dot(axis, arm)) == pytest.approx(0.0, abs=1e-6)

    def test_the_axis_straddles_the_pivot(self, golden_design):
        corner = golden_design.corner("lf")
        axis_a, axis_b = rocker_axis_points(corner, half_length_mm=25.0)
        midpoint = (axis_a + axis_b) / 2.0
        assert midpoint == pytest.approx(corner.position("rocker_pivot"))

    def test_a_collinear_rocker_is_a_readable_error(self, golden_design):
        design = golden_design.model_copy(deep=True)
        corner = design.corner("lf")
        pivot = np.asarray(corner.position("rocker_pivot"))
        arm = np.asarray(corner.position("rocker_pushrod")) - pivot
        corner.nodes["rocker_damper"].position = tuple(pivot + 2.0 * arm)
        with pytest.raises(WorkbenchSolveError, match="collinear rocker"):
            rocker_axis_points(corner)


class TestSweepTemplates:
    def test_every_template_is_available(self):
        assert sweeps.available() == ["bump", "droop", "roll", "steer", "combined"]

    def test_bump_moves_both_wheels_the_same_way(self, golden_design):
        spec = sweeps.sweep_spec("bump", golden_design, "front", travel_mm=25.0)
        left, right = spec["targets"][0], spec["targets"][1]
        assert (left["start"], left["stop"]) == (-25.0, 25.0)
        assert (right["start"], right["stop"]) == (-25.0, 25.0)

    def test_roll_moves_them_in_opposition(self, golden_design):
        spec = sweeps.sweep_spec("roll", golden_design, "front", travel_mm=25.0)
        left, right = spec["targets"][0], spec["targets"][1]
        assert (left["start"], left["stop"]) == (-25.0, 25.0)
        assert (right["start"], right["stop"]) == (25.0, -25.0)

    def test_every_template_holds_the_rack(self, golden_design):
        for name in ("bump", "droop", "roll"):
            spec = sweeps.sweep_spec(name, golden_design, "front")
            racks = [t for t in spec["targets"] if t.get("actuator") == "rack"]
            assert len(racks) == 1 and racks[0]["hold"] is True

    def test_a_steering_sweep_is_refused_on_an_unsteered_axle(self, golden_design):
        with pytest.raises(WorkbenchSolveError, match="steering='none'"):
            sweeps.sweep_spec("steer", golden_design, "rear")

    def test_an_unknown_template_lists_the_real_ones(self, golden_design):
        with pytest.raises(WorkbenchSolveError, match="Unknown sweep template"):
            sweeps.sweep_spec("heave", golden_design, "front")

    def test_combined_pairs_roll_and_steer_by_index(self, golden_design):
        spec = sweeps.sweep_spec("combined", golden_design, "front", steps=11)
        swept = [t for t in spec["targets"] if not t.get("hold")]
        assert len(swept) == 3, "all three dimensions sweep together"
        assert spec["steps"] == 11


class TestErrorContainment:
    @pytest.mark.solver
    def test_non_convergence_returns_rather_than_raises(self, golden_design, solver):
        """An impossible design must be penalisable, not fatal.

        Stretching the front track rod far past any assembly it can reach
        leaves the constraint set unsatisfiable, which is exactly the condition
        an optimizer will wander into.
        """
        broken = golden_design.model_copy(deep=True)
        for corner in broken.axles["front"].corners:
            x, y, z = corner.position("tie_rod_inboard")
            corner.nodes["tie_rod_inboard"].position = (x, y, z + 5000.0)
        result = solve(broken, "front", "bump", steps=5)
        assert not result.converged
        assert result.findings
        assert any(f.severity == "BLOCKER" for f in result.findings)

    @pytest.mark.solver
    def test_a_result_carries_the_design_fingerprint(self, golden_design, front_bump):
        """So a cache can key solves on the geometry that produced them."""
        assert front_bump.fingerprint == golden_design.fingerprint()

    @pytest.mark.solver
    def test_positions_are_keyed_for_the_viewport_payload(self, front_bump):
        assert "lf.lca_outboard" in front_bump.positions
        assert "rf.wheel_center" in front_bump.positions
        assert len(front_bump.positions["lf.lca_outboard"]) == front_bump.n_steps

    @pytest.mark.solver
    def test_metrics_are_flat_lists_one_value_per_step(self, front_bump):
        for key, values in front_bump.metrics.items():
            assert len(values) == front_bump.n_steps, key
            assert all(isinstance(v, float) for v in values), key

"""The defaults module: real data, labelled units, replaceable records."""

from __future__ import annotations

import pytest
from workbench.core.defaults import (
    GOLDEN_CAR,
    HOOSIER_18X6_R25B,
    AxleDefaults,
    CarDefaults,
    SpringDefaults,
    TireDefaults,
)


class TestTire:
    def test_the_reference_car_runs_the_measured_hoosier(self):
        tire = HOOSIER_18X6_R25B
        assert tire.name == "Hoosier 18x6.0-10"
        assert tire.compound == "R25B"
        assert (
            tire.overall_diameter_in,
            tire.section_width_in,
            tire.rim_diameter_in,
        ) == (18.0, 6.0, 10.0)

    def test_an_18_inch_tire_has_a_228_6_mm_unloaded_radius(self):
        assert HOOSIER_18X6_R25B.unloaded_radius_mm == pytest.approx(228.6)

    def test_the_loaded_radius_is_what_the_kinematics_use(self):
        assert HOOSIER_18X6_R25B.kinematic_radius_mm == pytest.approx(223.52)

    def test_the_static_deflection_is_exactly_two_tenths_of_an_inch(self):
        assert HOOSIER_18X6_R25B.static_deflection_mm == pytest.approx(5.08, abs=1e-9)

    def test_without_a_loaded_radius_the_unloaded_one_is_used(self):
        tire = TireDefaults(
            name="unmeasured",
            compound="",
            overall_diameter_in=18.0,
            section_width_in=6.0,
            rim_diameter_in=10.0,
        )
        assert tire.kinematic_radius_mm == pytest.approx(228.6)
        assert tire.static_deflection_mm == pytest.approx(0.0)


class TestSpringRates:
    def test_the_measured_rates_are_quoted_at_the_damper(self):
        assert GOLDEN_CAR.front.spring.rate_n_per_mm == pytest.approx(43.78)
        assert GOLDEN_CAR.rear.spring.rate_n_per_mm == pytest.approx(39.40)
        assert GOLDEN_CAR.front.spring.measured_at == "damper"
        assert GOLDEN_CAR.rear.spring.measured_at == "damper"

    def test_a_damper_rate_squares_the_motion_ratio_in(self):
        spring = SpringDefaults(rate_n_per_mm=43.78, measured_at="damper")
        assert spring.wheel_rate_n_per_mm(0.5) == pytest.approx(43.78 * 0.25)

    def test_a_rate_already_at_the_wheel_is_left_alone(self):
        """The reason the location is stored rather than assumed."""
        spring = SpringDefaults(rate_n_per_mm=22.0, measured_at="wheel")
        assert spring.wheel_rate_n_per_mm(0.5) == pytest.approx(22.0)

    def test_the_sign_of_the_ratio_does_not_matter(self):
        spring = SpringDefaults(rate_n_per_mm=40.0)
        assert spring.wheel_rate_n_per_mm(-0.7) == pytest.approx(
            spring.wheel_rate_n_per_mm(0.7)
        )


class TestReplaceability:
    def test_an_axle_record_is_replaced_whole(self):
        """A caller swaps a record; no constant is hunted."""
        swapped = CarDefaults(
            front=AxleDefaults(
                tire=HOOSIER_18X6_R25B,
                spring=SpringDefaults(rate_n_per_mm=52.5, measured_at="damper"),
            ),
            rear=GOLDEN_CAR.rear,
        )
        assert swapped.front.spring.rate_n_per_mm == pytest.approx(52.5)
        assert swapped.rear.spring.rate_n_per_mm == pytest.approx(39.40)

    def test_the_records_are_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            GOLDEN_CAR.front.spring.rate_n_per_mm = 1.0  # type: ignore[misc]

    def test_axle_lookup_rejects_an_unknown_axle(self):
        with pytest.raises(KeyError, match="Unknown axle id"):
            GOLDEN_CAR.axle("middle")


class TestPlaceholders:
    def test_mass_properties_are_still_placeholders(self):
        """Flagged as such in the README rather than hidden in the geometry."""
        mass = GOLDEN_CAR.mass
        assert mass.mass_kg == pytest.approx(290.0)
        assert mass.front_mass_fraction == pytest.approx(0.48)

    def test_the_cg_sits_behind_the_front_axle(self):
        assert GOLDEN_CAR.mass.cg_x_mm(1549.4) == pytest.approx(-805.688)

    def test_the_spin_axis_policy_defaults_to_an_unmodified_reading(self):
        """Zero camber and toe keeps the loaded design faithful to the file."""
        policy = GOLDEN_CAR.front.spin_axis
        assert policy.static_camber_deg == 0.0
        assert policy.static_toe_deg == 0.0

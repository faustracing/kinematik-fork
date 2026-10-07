"""The integration ledger and its wiring to a `Design`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from workbench.integration import (
    SUBSYSTEMS,
    IntegrationLedger,
    Severity,
    SubsystemInterface,
    apply_rollup,
    blank_ledger,
    check_against_design,
    declare_suspension,
    findings_for,
    summarise,
    suspension_interface,
    unsprung_cg_mm,
)


def _checks(findings, check):
    return [finding for finding in findings if finding.check == check]


def _one(findings, check):
    matches = _checks(findings, check)
    assert len(matches) == 1, f"expected one {check!r} finding, got {matches}"
    return matches[0]


@pytest.fixture
def declared() -> IntegrationLedger:
    """A ledger where all eight subsystems have declared a mass and a CG."""
    ledger = blank_ledger(target_mass_kg=240.0)
    for index, name in enumerate(SUBSYSTEMS):
        ledger.declare(
            SubsystemInterface(
                name=name,
                mass_kg=25.0,
                cg_x_mm=-700.0 + index,
                cg_y_mm=0.0,
                cg_z_mm=280.0,
                is_estimate=False,
            )
        )
    return ledger


class TestSubsystemInterface:
    def test_an_unknown_subsystem_name_is_rejected(self):
        """A typo'd name used to declare a mass that silently never rolled up."""
        with pytest.raises(ValidationError):
            SubsystemInterface(name="suspenshun")

    def test_an_undeclared_interface_reports_no_channels(self):
        assert SubsystemInterface(name="brakes").declared_channels() == []
        assert not SubsystemInterface(name="brakes").is_declared()

    def test_a_declared_zero_is_distinct_from_undeclared(self):
        zero = SubsystemInterface(name="brakes", mass_kg=0.0)
        assert zero.declared_channels() == ["mass_kg"]
        assert zero.is_declared()

    def test_a_partial_cg_is_no_cg(self):
        assert SubsystemInterface(name="brakes", cg_x_mm=10.0).cg_mm is None

    def test_a_complete_cg_reads_as_a_point(self):
        interface = SubsystemInterface(
            name="brakes", cg_x_mm=1.0, cg_y_mm=2.0, cg_z_mm=3.0
        )
        assert interface.cg_mm == (1.0, 2.0, 3.0)

    def test_a_negative_mass_is_rejected(self):
        with pytest.raises(ValidationError):
            SubsystemInterface(name="brakes", mass_kg=-1.0)

    def test_an_unknown_channel_is_rejected_rather_than_dropped(self):
        """KinematiK's `from_dict` filtered unknown keys away in silence."""
        with pytest.raises(ValidationError):
            SubsystemInterface(name="brakes", mas_kg=12.0)


class TestRoundTrip:
    def test_a_ledger_round_trips_through_json(self, declared):
        restored = IntegrationLedger.model_validate_json(declared.model_dump_json())
        assert restored == declared

    def test_every_budget_survives_the_round_trip(self):
        """KinematiK's `as_dict` silently dropped `cooling_inlet_c`."""
        ledger = blank_ledger(
            target_mass_kg=240.0,
            includes_driver_kg=68.0,
            cooling_airflow_cms=0.42,
            cooling_air_rise_k=20.0,
            chassis_envelope_mm=(900.0, 500.0, 400.0),
            upright_design_load_n=6000.0,
            driveline_torque_limit_nm=900.0,
        )
        restored = IntegrationLedger.model_validate_json(ledger.model_dump_json())
        assert restored.model_dump() == ledger.model_dump()

    def test_an_interface_key_must_match_its_name(self):
        with pytest.raises(ValidationError):
            IntegrationLedger(interfaces={"brakes": SubsystemInterface(name="cooling")})

    def test_a_driver_allowance_larger_than_the_car_is_rejected(self):
        with pytest.raises(ValidationError):
            IntegrationLedger(target_mass_kg=230.0, includes_driver_kg=230.0)


class TestMassRollup:
    def test_a_blank_ledger_rolls_up_to_nothing(self):
        rollup = blank_ledger().mass_rollup()
        assert rollup.total_kg == 0.0
        assert rollup.cg_mm is None
        assert rollup.declared == ()
        assert set(rollup.missing_mass) == set(SUBSYSTEMS)
        assert not rollup.complete

    def test_declared_masses_sum(self, declared):
        rollup = declared.mass_rollup()
        assert rollup.total_kg == pytest.approx(200.0)
        assert rollup.declared == SUBSYSTEMS
        assert rollup.complete

    def test_the_combined_cg_is_mass_weighted(self):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(
                name="chassis", mass_kg=30.0, cg_x_mm=0.0, cg_y_mm=0.0, cg_z_mm=100.0
            )
        )
        ledger.declare(
            SubsystemInterface(
                name="powertrain",
                mass_kg=10.0,
                cg_x_mm=0.0,
                cg_y_mm=0.0,
                cg_z_mm=500.0,
            )
        )
        assert ledger.mass_rollup().cg_mm == pytest.approx((0.0, 0.0, 200.0))

    def test_a_mass_without_a_cg_withholds_the_combined_cg(self):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(
                name="chassis", mass_kg=30.0, cg_x_mm=0.0, cg_y_mm=0.0, cg_z_mm=100.0
            )
        )
        ledger.declare(SubsystemInterface(name="brakes", mass_kg=8.0))
        rollup = ledger.mass_rollup()
        assert rollup.total_kg == pytest.approx(38.0)
        assert rollup.cg_mm is None
        assert rollup.missing_cg == ("brakes",)

    def test_the_delta_is_measured_against_the_target_net_of_the_driver(self):
        ledger = blank_ledger(target_mass_kg=300.0, includes_driver_kg=70.0)
        ledger.declare(SubsystemInterface(name="chassis", mass_kg=240.0))
        rollup = ledger.mass_rollup()
        assert rollup.target_net_kg == pytest.approx(230.0)
        assert rollup.delta_kg == pytest.approx(10.0)


class TestMassChecks:
    def test_an_undeclared_mass_is_missing_not_passing(self):
        findings = blank_ledger().check_all()
        assert _one(findings, "mass-budget").severity is Severity.MISSING

    def test_a_mass_within_budget_passes(self, declared):
        assert _one(declared.check_all(), "mass-budget-total").severity is Severity.OK

    def test_a_small_overrun_warns(self, declared):
        declared.target_mass_kg = 198.0
        assert _one(declared.check_all(), "mass-budget-total").severity is Severity.WARN

    def test_an_overrun_past_five_percent_fails(self, declared):
        declared.target_mass_kg = 180.0
        finding = _one(declared.check_all(), "mass-budget-total")
        assert finding.severity is Severity.FAIL
        assert finding.detail["delta_kg"] == pytest.approx(20.0)

    def test_a_partial_rollup_says_the_real_total_is_higher(self):
        ledger = blank_ledger(target_mass_kg=100.0)
        ledger.declare(SubsystemInterface(name="chassis", mass_kg=30.0))
        message = _one(ledger.check_all(), "mass-budget-total").message
        assert "the real total is higher" in message

    def test_an_off_centre_cg_warns(self, declared):
        declared.declare(
            SubsystemInterface(
                name="brakes",
                mass_kg=25.0,
                cg_x_mm=-700.0,
                cg_y_mm=400.0,
                cg_z_mm=280.0,
            )
        )
        assert _one(declared.check_all(), "cg-lateral").severity is Severity.WARN


class TestEnvelopeChecks:
    def test_a_box_that_does_not_fit_fails(self):
        ledger = blank_ledger(chassis_envelope_mm=(900.0, 500.0, 400.0))
        ledger.declare(
            SubsystemInterface(name="cooling", envelope_mm=(400.0, 600.0, 200.0))
        )
        finding = _one(ledger.check_all(), "envelope-fit")
        assert finding.severity is Severity.FAIL
        assert set(finding.subsystems) == {"cooling", "chassis"}

    def test_a_box_that_fits_raises_nothing(self):
        ledger = blank_ledger(chassis_envelope_mm=(900.0, 500.0, 400.0))
        ledger.declare(
            SubsystemInterface(name="cooling", envelope_mm=(400.0, 300.0, 200.0))
        )
        assert _checks(ledger.check_all(), "envelope-fit") == []

    def test_the_chassis_declaration_stands_in_for_the_car_level_envelope(self):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(name="chassis", envelope_mm=(900.0, 500.0, 400.0))
        )
        ledger.declare(
            SubsystemInterface(name="cooling", envelope_mm=(400.0, 600.0, 200.0))
        )
        assert _one(ledger.check_all(), "envelope-fit").severity is Severity.FAIL

    def test_the_chassis_is_not_fit_checked_against_itself(self):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(name="chassis", envelope_mm=(900.0, 500.0, 400.0))
        )
        assert _checks(ledger.check_all(), "envelope-fit") == []

    def test_no_envelope_anywhere_is_missing(self):
        assert _one(blank_ledger().check_all(), "envelope").severity is Severity.MISSING


class TestCoolingChecks:
    def test_airflow_demand_without_a_declared_package_is_missing(self):
        ledger = blank_ledger()
        ledger.declare(SubsystemInterface(name="powertrain", cooling_airflow_cms=0.3))
        assert _one(ledger.check_all(), "cooling-airflow").severity is Severity.MISSING

    def test_demand_above_the_package_fails(self):
        ledger = blank_ledger(cooling_airflow_cms=0.2)
        ledger.declare(SubsystemInterface(name="powertrain", cooling_airflow_cms=0.3))
        assert _one(ledger.check_all(), "cooling-airflow").severity is Severity.FAIL

    def test_demand_within_the_package_passes(self):
        ledger = blank_ledger(cooling_airflow_cms=0.5)
        ledger.declare(SubsystemInterface(name="powertrain", cooling_airflow_cms=0.3))
        assert _one(ledger.check_all(), "cooling-airflow").severity is Severity.OK

    def test_heat_above_the_ideal_airflow_capacity_fails(self):
        """0.1 m^3/s at a 15 K rise can carry about 1.8 kW at best."""
        ledger = blank_ledger(cooling_airflow_cms=0.1)
        assert ledger.cooling_capacity_w() == pytest.approx(1809.0, rel=1e-3)
        ledger.declare(SubsystemInterface(name="powertrain", heat_reject_w=4000.0))
        finding = _one(ledger.check_all(), "cooling-heat")
        assert finding.severity is Severity.FAIL
        assert finding.detail["ideal_capacity_w"] == pytest.approx(1809.0, rel=1e-3)

    def test_heat_below_the_ideal_capacity_is_not_flagged(self):
        ledger = blank_ledger(cooling_airflow_cms=0.5)
        ledger.declare(SubsystemInterface(name="powertrain", heat_reject_w=4000.0))
        assert _checks(ledger.check_all(), "cooling-heat") == []

    def test_the_cooling_subsystems_own_airflow_declaration_counts(self):
        ledger = blank_ledger()
        ledger.declare(SubsystemInterface(name="cooling", cooling_airflow_cms=0.5))
        ledger.declare(SubsystemInterface(name="powertrain", cooling_airflow_cms=0.3))
        assert _one(ledger.check_all(), "cooling-airflow").severity is Severity.OK


class TestElectricalChecks:
    def test_lv_draw_above_the_supply_fails(self):
        ledger = blank_ledger(lv_supply_capacity_w=200.0)
        ledger.declare(
            SubsystemInterface(
                name="data-acquisition", power_draw_w=250.0, voltage_v=24.0
            )
        )
        assert _one(ledger.check_all(), "lv-power").severity is Severity.FAIL

    def test_an_hv_draw_is_not_counted_against_the_lv_supply(self):
        ledger = blank_ledger(lv_supply_capacity_w=200.0)
        ledger.declare(
            SubsystemInterface(name="powertrain", power_draw_w=4000.0, voltage_v=400.0)
        )
        assert _checks(ledger.check_all(), "lv-power") == []

    def test_a_draw_with_no_voltage_is_counted_as_lv_and_said_so(self):
        """KinematiK assumed LV silently; the assumption is now in the finding."""
        ledger = blank_ledger(lv_supply_capacity_w=200.0)
        ledger.declare(SubsystemInterface(name="data-acquisition", power_draw_w=50.0))
        finding = _one(ledger.check_all(), "lv-power")
        assert finding.detail["voltage_assumed_lv"] == ["data-acquisition"]
        assert "no bus voltage" in finding.message

    def test_a_powertrain_voltage_mismatch_warns(self):
        ledger = blank_ledger(accumulator_voltage_v=400.0)
        ledger.declare(SubsystemInterface(name="powertrain", voltage_v=600.0))
        assert _one(ledger.check_all(), "hv-voltage").severity is Severity.WARN

    def test_a_matching_powertrain_voltage_is_silent(self):
        ledger = blank_ledger(accumulator_voltage_v=400.0)
        ledger.declare(SubsystemInterface(name="powertrain", voltage_v=398.0))
        assert _checks(ledger.check_all(), "hv-voltage") == []


class TestDrivelineAndMounts:
    def test_torque_above_the_rating_fails(self):
        ledger = blank_ledger(driveline_torque_limit_nm=800.0)
        ledger.declare(SubsystemInterface(name="powertrain", peak_torque_nm=1200.0))
        assert _one(ledger.check_all(), "driveline-torque").severity is Severity.FAIL

    def test_torque_within_the_rating_passes(self):
        ledger = blank_ledger(driveline_torque_limit_nm=800.0)
        ledger.declare(SubsystemInterface(name="powertrain", peak_torque_nm=600.0))
        assert _one(ledger.check_all(), "driveline-torque").severity is Severity.OK

    def test_torque_with_no_rating_to_check_is_missing(self):
        ledger = blank_ledger()
        ledger.declare(SubsystemInterface(name="powertrain", peak_torque_nm=600.0))
        assert _one(ledger.check_all(), "driveline-torque").severity is Severity.MISSING

    def test_a_mount_load_above_the_upright_rating_fails(self):
        ledger = blank_ledger(upright_design_load_n=5000.0)
        ledger.declare(
            SubsystemInterface(
                name="brakes", mount_load_n=7000.0, mounts_on="suspension"
            )
        )
        assert _one(ledger.check_all(), "mount-load").severity is Severity.FAIL

    def test_a_mount_load_with_no_rating_is_informational(self):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(name="brakes", mount_load_n=7000.0, mount_points=4)
        )
        finding = _one(ledger.check_all(), "mount-load")
        assert finding.severity is Severity.INFO
        assert "4 mounts" in finding.message


class TestSummary:
    def test_the_worst_severity_leads(self, declared):
        declared.target_mass_kg = 100.0
        findings = declared.check_all()
        assert findings[0].severity is Severity.FAIL
        assert summarise(findings)["worst"] == "fail"

    def test_an_empty_finding_list_summarises_as_ok(self):
        summary = summarise([])
        assert summary == {
            "counts": {"fail": 0, "warning": 0, "missing": 0, "info": 0, "ok": 0},
            "worst": "ok",
            "total": 0,
        }

    def test_findings_can_be_filtered_to_one_subsystem(self, declared):
        findings = findings_for(declared.check_all(), "cooling")
        assert findings
        assert all("cooling" in finding.subsystems for finding in findings)

    def test_estimates_are_flagged_even_when_everything_passes(self):
        ledger = blank_ledger(target_mass_kg=500.0)
        ledger.declare(
            SubsystemInterface(name="chassis", mass_kg=30.0, is_estimate=True)
        )
        assert _one(ledger.check_all(), "data-provenance").severity is Severity.INFO


class TestSuspensionWiring:
    def test_the_estimated_cg_is_the_wheel_centre_centroid(self, golden_design):
        x, y, z = unsprung_cg_mm(golden_design)
        # Four mirrored corners: laterally centred, half a wheelbase back,
        # at the static wheel-centre height.
        assert y == pytest.approx(0.0, abs=1e-9)
        assert x == pytest.approx(-golden_design.vehicle.wheelbase_mm / 2.0, abs=1e-6)
        assert z == pytest.approx(223.52, abs=1e-6)

    def test_a_derived_cg_forces_the_estimate_flag(self, golden_design):
        interface = suspension_interface(golden_design, mass_kg=40.0, is_estimate=False)
        assert interface.is_estimate
        assert "centroid of the four wheel centres" in interface.rationale

    def test_a_declared_cg_can_be_confirmed(self, golden_design):
        interface = suspension_interface(
            golden_design,
            mass_kg=40.0,
            cg_mm=(-700.0, 0.0, 240.0),
            is_estimate=False,
        )
        assert not interface.is_estimate
        assert interface.cg_mm == (-700.0, 0.0, 240.0)
        assert interface.rationale == ""

    def test_declaring_suspension_puts_it_in_the_rollup(self, golden_design):
        ledger = declare_suspension(blank_ledger(), golden_design, mass_kg=40.0)
        rollup = ledger.mass_rollup()
        assert "suspension" in rollup.declared
        assert rollup.total_kg == pytest.approx(40.0)

    def test_suspension_mounts_on_the_chassis_by_default(self, golden_design):
        interface = suspension_interface(golden_design, mass_kg=40.0)
        assert interface.mounts_on == "chassis"


class TestApplyRollup:
    def test_the_rollup_replaces_the_placeholder_mass_properties(
        self, golden_design, declared
    ):
        updated = apply_rollup(golden_design, declared)
        assert updated.vehicle.mass_kg == pytest.approx(200.0)
        assert updated.vehicle.cg_height_mm == pytest.approx(280.0)
        assert updated.vehicle.front_mass_fraction == pytest.approx(
            1.0 - 696.5 / golden_design.vehicle.wheelbase_mm, abs=1e-6
        )

    def test_the_input_design_is_not_modified(self, golden_design, declared):
        before = golden_design.vehicle.mass_kg
        apply_rollup(golden_design, declared)
        assert golden_design.vehicle.mass_kg == before

    def test_the_source_of_the_mass_properties_is_recorded(
        self, golden_design, declared
    ):
        provenance = apply_rollup(golden_design, declared).provenance
        assert provenance["mass_properties"]["source"] == "integration ledger"
        assert provenance["mass_properties"]["any_estimate"] is False

    def test_the_geometry_is_untouched(self, golden_design, declared):
        updated = apply_rollup(golden_design, declared)
        assert updated.corner("lf").position("lca_outboard") == golden_design.corner(
            "lf"
        ).position("lca_outboard")

    def test_an_incomplete_rollup_cannot_be_applied(self, golden_design):
        with pytest.raises(ValueError, match="no combined mass and CG"):
            apply_rollup(golden_design, blank_ledger())

    def test_a_cg_outside_the_wheelbase_is_rejected_with_the_sign_convention(
        self, golden_design
    ):
        """A ledger filled in with SAE signs puts the CG ahead of the front axle."""
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(
                name="chassis",
                mass_kg=200.0,
                cg_x_mm=+760.0,
                cg_y_mm=0.0,
                cg_z_mm=280.0,
            )
        )
        with pytest.raises(ValueError, match="sign convention"):
            apply_rollup(golden_design, ledger)


class TestCheckAgainstDesign:
    def test_an_empty_ledger_says_the_design_is_still_assuming(self, golden_design):
        finding = _one(
            check_against_design(blank_ledger(), golden_design), "design-mass"
        )
        assert finding.severity is Severity.MISSING
        assert "290" in finding.message

    def test_a_mass_disagreement_warns(self, golden_design, declared):
        finding = _one(check_against_design(declared, golden_design), "design-mass")
        assert finding.severity is Severity.WARN
        assert finding.detail["delta_kg"] == pytest.approx(200.0 - 290.0)

    def test_an_agreeing_ledger_passes_every_check(self, golden_design, declared):
        reconciled = apply_rollup(golden_design, declared)
        findings = check_against_design(declared, reconciled)
        assert {finding.severity for finding in findings} == {Severity.OK}

    def test_a_cg_height_disagreement_warns(self, golden_design, declared):
        finding = _one(check_against_design(declared, golden_design), "design-cg")
        assert finding.severity is Severity.WARN
        assert finding.detail["delta_mm"] == pytest.approx(280.0 - 300.0)

    def test_an_incomplete_cg_withholds_the_comparison(self, golden_design):
        ledger = blank_ledger()
        ledger.declare(SubsystemInterface(name="chassis", mass_kg=290.0))
        finding = _one(check_against_design(ledger, golden_design), "design-cg")
        assert finding.severity is Severity.MISSING

    def test_an_incomplete_rollup_says_the_gap_is_larger(self, golden_design):
        ledger = blank_ledger()
        ledger.declare(
            SubsystemInterface(
                name="chassis",
                mass_kg=100.0,
                cg_x_mm=-700.0,
                cg_y_mm=0.0,
                cg_z_mm=280.0,
            )
        )
        message = _one(
            check_against_design(ledger, golden_design), "design-mass"
        ).message
        assert "the real gap is larger" in message

"""The integration ledger: one place the interfaces *between* subsystems live.

Eight sub-teams each optimise in their own tool and hand off a CAD file or a
number. The failures that cost a competition are not inside any one of those
tools — they are between them: the radiator that does not fit the duct aero
reserved, the motor torque that exceeds what the upright was designed for, the
eight "we're about 12 kg" estimates that sum to 18 kg over the number
suspension used for load transfer.

Each subsystem declares, in typed channels, what it *provides* to the rest of
the car (mass and CG, loads into its mounts, heat it dumps, power it draws) and
what it *requires* from it (envelope, cooling airflow, supply current). The
checks then validate those declarations against each other and against the
car-level budgets, and every finding names both subsystems involved so the
conflict has an owner.

Deliberate non-goal: nothing here simulates a subsystem. The ledger owns the
channels between them, and marks every declaration that is still an estimate,
so a clean board never means more than the data behind it.

Coordinates
-----------
CG positions are ISO 8855 millimetres on the workbench design datum — `+X`
forward, `+Y` left, `+Z` up, front axle centreline at `X = 0`, ground plane at
`Z = 0`. A CG behind the front axle therefore has a *negative* `cg_x_mm`. This
is the same frame `workbench.core.design.Design` uses, which is what lets
`workbench.integration.suspension` move numbers between the two without a
conversion.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AIR_DENSITY_KG_PER_M3",
    "CHANNEL_LABELS",
    "SUBSYSTEMS",
    "IntegrationFinding",
    "IntegrationLedger",
    "MassRollup",
    "Severity",
    "Subsystem",
    "SubsystemInterface",
    "blank_ledger",
    "findings_for",
    "summarise",
]

Subsystem = Literal[
    "aerodynamics",
    "brakes",
    "chassis",
    "cooling",
    "data-acquisition",
    "electrics",
    "powertrain",
    "suspension",
]

SUBSYSTEMS: Final[tuple[Subsystem, ...]] = (
    "aerodynamics",
    "brakes",
    "chassis",
    "cooling",
    "data-acquisition",
    "electrics",
    "powertrain",
    "suspension",
)
"""The eight subsystems, matching the team's channels.

`chassis` and `suspension` are the integrators most others hang off, but all
eight are peers here. The name is a `Literal`, so a typo is a validation error
rather than a declaration that silently never rolls up.
"""

AIR_DENSITY_KG_PER_M3: Final[float] = 1.2
AIR_CP_J_PER_KG_K: Final[float] = 1005.0

_Millimetres = Annotated[float, Field(description="millimetres")]
_PositiveMm = Annotated[float, Field(gt=0.0, description="millimetres")]


class Severity(StrEnum):
    """How bad a finding is, worst first.

    `MISSING` is deliberately neither a pass nor a fail: data nobody has
    declared yet is a different state from data that has been checked.
    """

    FAIL = "fail"
    """A hard incompatibility. The parts do not go together."""

    WARN = "warning"
    """A real conflict, fixable, that will not stop the car today."""

    MISSING = "missing"
    """Data the check needs has not been declared."""

    INFO = "info"
    """Something worth knowing that is not a problem."""

    OK = "ok"
    """Checked and consistent."""

    @property
    def rank(self) -> int:
        """Position in the worst-first ordering. Lower is worse."""
        return _SEVERITY_ORDER.index(self)


_SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.FAIL,
    Severity.WARN,
    Severity.MISSING,
    Severity.INFO,
    Severity.OK,
)


class IntegrationFinding(BaseModel):
    """One cross-subsystem check result.

    Field names line up with `workbench.rules.Finding` where the two overlap,
    so an app can render rule findings and integration findings in one list.

    Attributes:
        check: Stable id of the check that produced this, e.g. `"mass-budget"`.
        severity: How bad it is.
        message: Plain-language description naming the conflict.
        subsystems: Every subsystem implicated, so the finding has an owner.
        detail: The numbers behind the message, for a UI that wants to show
            them without re-parsing the prose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    check: str
    severity: Severity
    message: str
    subsystems: tuple[Subsystem, ...] = ()
    detail: dict[str, Any] = Field(default_factory=dict)


class SubsystemInterface(BaseModel):
    """One subsystem's declared interface to the rest of the car.

    Every channel is optional: `None` means "not declared yet", which the
    checks report as `MISSING` — honestly distinct from a declared zero. Not
    every channel applies to every subsystem; a check only fires when the
    channels it reads are present.

    `is_estimate` marks the whole declaration as placeholder data, so the board
    can never imply more certainty than the team actually has.

    Attributes:
        name: Which subsystem this is.
        mass_kg: Installed mass.
        cg_x_mm: CG on the design datum, positive forward of the front axle.
        cg_y_mm: CG lateral position, positive left of the centreline.
        cg_z_mm: CG height above the ground plane.
        envelope_mm: `(length, width, height)` of the bounding box it needs.
        envelope_origin_mm: Where that box sits, for a layout view. Not checked.
        mount_load_n: Peak force it puts into the structure it bolts to.
        mount_points: How many mounts carry that load.
        mounts_on: Which subsystem carries it. Defaults to the chassis.
        power_draw_w: Continuous electrical draw.
        voltage_v: Bus it draws from. `None` is assumed to be the LV bus.
        heat_reject_w: Heat it dumps into the cooling package.
        cooling_airflow_cms: Airflow it requires, cubic metres per second.
        peak_torque_nm: Peak torque it delivers into the driveline.
        is_estimate: True while any number here is a placeholder.
        rationale: Why these numbers — the justification design judges ask for.
        owner: Who on the sub-team owns this interface.
        updated_on: ISO date the declaration last changed.
        notes: Anything else worth recording.
    """

    model_config = ConfigDict(extra="forbid")

    name: Subsystem

    mass_kg: float | None = Field(default=None, ge=0.0)
    cg_x_mm: _Millimetres | None = None
    cg_y_mm: _Millimetres | None = None
    cg_z_mm: _Millimetres | None = None

    envelope_mm: tuple[_PositiveMm, _PositiveMm, _PositiveMm] | None = None
    envelope_origin_mm: tuple[float, float, float] | None = None

    mount_load_n: float | None = Field(default=None, ge=0.0)
    mount_points: int | None = Field(default=None, gt=0)
    mounts_on: Subsystem | None = None

    power_draw_w: float | None = Field(default=None, ge=0.0)
    voltage_v: float | None = Field(default=None, ge=0.0)

    heat_reject_w: float | None = Field(default=None, ge=0.0)
    cooling_airflow_cms: float | None = Field(default=None, ge=0.0)

    peak_torque_nm: float | None = Field(default=None, ge=0.0)

    is_estimate: bool = True
    rationale: str = ""
    owner: str = ""
    updated_on: str = ""
    notes: str = ""

    @property
    def cg_mm(self) -> tuple[float, float, float] | None:
        """The CG as a point, or `None` when any axis is undeclared."""
        if self.cg_x_mm is None or self.cg_y_mm is None or self.cg_z_mm is None:
            return None
        return (self.cg_x_mm, self.cg_y_mm, self.cg_z_mm)

    def declared_channels(self) -> list[str]:
        """Names of the numeric channels actually filled in, in field order."""
        return [
            field for field in CHANNEL_LABELS if getattr(self, field, None) is not None
        ]

    def is_declared(self) -> bool:
        """Whether this subsystem has declared anything numeric at all."""
        return bool(self.declared_channels())


CHANNEL_LABELS: Final[dict[str, tuple[str, str]]] = {
    "mass_kg": ("mass", "kg"),
    "cg_x_mm": ("CG x (forward)", "mm"),
    "cg_y_mm": ("CG y (left)", "mm"),
    "cg_z_mm": ("CG z (up)", "mm"),
    "envelope_mm": ("envelope l/w/h", "mm"),
    "mount_load_n": ("peak mount load", "N"),
    "mount_points": ("mount points", ""),
    "mounts_on": ("mounts on", ""),
    "power_draw_w": ("power draw", "W"),
    "voltage_v": ("voltage", "V"),
    "heat_reject_w": ("heat rejected", "W"),
    "cooling_airflow_cms": ("cooling airflow required", "m^3/s"),
    "peak_torque_nm": ("peak torque", "N*m"),
}
"""Human label and unit for every declared channel, in display order.

Drives the report tables and keeps a bare number from being shown without the
unit it was declared in.
"""


class MassRollup(BaseModel):
    """Summed subsystem mass and the combined CG.

    The single most important cross-subsystem number: it is what suspension's
    load-transfer model assumes, and it is where eight optimistic estimates
    quietly blow the budget.

    Attributes:
        total_kg: Sum of every declared mass.
        cg_mm: Mass-weighted CG, or `None` when a mass was declared without
            one and the combined CG would therefore be wrong.
        declared: Subsystems that declared a mass.
        missing_mass: Subsystems with no mass declared.
        missing_cg: Subsystems that declared a mass but no CG.
        any_estimate: Whether any contributing mass is still a placeholder.
        target_net_kg: The car mass target, net of any driver allowance.
        delta_kg: Declared total minus `target_net_kg`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_kg: float
    cg_mm: tuple[float, float, float] | None
    declared: tuple[Subsystem, ...]
    missing_mass: tuple[Subsystem, ...]
    missing_cg: tuple[Subsystem, ...]
    any_estimate: bool
    target_net_kg: float
    delta_kg: float

    @property
    def complete(self) -> bool:
        """Whether every subsystem has declared a mass and a CG."""
        return not self.missing_mass and not self.missing_cg


class IntegrationLedger(BaseModel):
    """One interface per subsystem plus the car-level budgets they check against.

    Construct it empty — usually through `blank_ledger` — then `declare` each
    subsystem's interface and call `check_all`.

    Attributes:
        target_mass_kg: Whole-car mass target.
        includes_driver_kg: Driver allowance already counted in that target.
            Subsystem masses are compared against the target net of it.
        accumulator_voltage_v: Tractive-system nominal voltage.
        lv_voltage_v: Low-voltage bus voltage.
        lv_supply_capacity_w: What the LV system can actually deliver.
        cooling_airflow_cms: Airflow the cooling package can move. Falls back
            to the cooling subsystem's own declaration when left at zero.
        cooling_air_rise_k: Air temperature rise allowed across the coolers,
            used to bound how much heat that airflow could ever carry.
        chassis_envelope_mm: Interior `(length, width, height)` the chassis
            offers. Falls back to the chassis subsystem's own declaration.
        upright_design_load_n: Load suspension designed its mounts for.
        driveline_torque_limit_nm: What the driveshafts and CVs are rated for.
        interfaces: The declarations, keyed by subsystem.
    """

    model_config = ConfigDict(extra="forbid")

    target_mass_kg: float = Field(default=230.0, gt=0.0)
    includes_driver_kg: float = Field(default=0.0, ge=0.0)
    accumulator_voltage_v: float = Field(default=400.0, gt=0.0)
    lv_voltage_v: float = Field(default=24.0, gt=0.0)
    lv_supply_capacity_w: float = Field(default=600.0, ge=0.0)
    cooling_airflow_cms: float = Field(default=0.0, ge=0.0)
    cooling_air_rise_k: float = Field(default=15.0, gt=0.0)
    chassis_envelope_mm: tuple[_PositiveMm, _PositiveMm, _PositiveMm] | None = None
    upright_design_load_n: float | None = Field(default=None, gt=0.0)
    driveline_torque_limit_nm: float | None = Field(default=None, gt=0.0)
    interfaces: dict[Subsystem, SubsystemInterface] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_interface_keys(self) -> IntegrationLedger:
        """Keep the mapping key and the interface's own name in agreement."""
        for key, interface in self.interfaces.items():
            if key != interface.name:
                raise ValueError(
                    f"Interface key {key!r} does not match its name {interface.name!r}"
                )
        return self

    @model_validator(mode="after")
    def check_driver_allowance(self) -> IntegrationLedger:
        """A driver allowance larger than the whole car is not a budget."""
        if self.includes_driver_kg >= self.target_mass_kg:
            raise ValueError(
                f"Driver allowance {self.includes_driver_kg} kg is not smaller "
                f"than the {self.target_mass_kg} kg car target"
            )
        return self

    @property
    def target_net_kg(self) -> float:
        """The mass target the subsystems are actually measured against."""
        return self.target_mass_kg - self.includes_driver_kg

    def declare(self, interface: SubsystemInterface) -> IntegrationLedger:
        """Record one subsystem's interface, replacing any previous one.

        Returns:
            This ledger, so declarations chain.
        """
        self.interfaces[interface.name] = interface
        return self

    def get(self, name: Subsystem) -> SubsystemInterface | None:
        """Return one subsystem's interface, or `None` if it has none."""
        return self.interfaces.get(name)

    # ---- physics bridge ---------------------------------------------------

    def mass_rollup(self) -> MassRollup:
        """Sum the declared masses and locate the combined CG."""
        total = 0.0
        moment = [0.0, 0.0, 0.0]
        declared: list[Subsystem] = []
        missing_mass: list[Subsystem] = []
        missing_cg: list[Subsystem] = []
        any_estimate = False

        for name in SUBSYSTEMS:
            interface = self.interfaces.get(name)
            if interface is None or interface.mass_kg is None:
                missing_mass.append(name)
                continue
            declared.append(name)
            total += interface.mass_kg
            any_estimate = any_estimate or interface.is_estimate
            cg = interface.cg_mm
            if cg is None:
                missing_cg.append(name)
            else:
                for axis in range(3):
                    moment[axis] += interface.mass_kg * cg[axis]

        combined = (
            (moment[0] / total, moment[1] / total, moment[2] / total)
            if not missing_cg and total > 0.0
            else None
        )
        return MassRollup(
            total_kg=total,
            cg_mm=combined,
            declared=tuple(declared),
            missing_mass=tuple(missing_mass),
            missing_cg=tuple(missing_cg),
            any_estimate=any_estimate,
            target_net_kg=self.target_net_kg,
            delta_kg=total - self.target_net_kg if declared else 0.0,
        )

    def cooling_capacity_w(self) -> float:
        """Upper bound on the heat the declared airflow could ever carry.

        `Q = m_dot * cp * dT` with the airflow fully exchanged and leaving at
        the allowed temperature rise — an *ideal* heat exchanger, so this is a
        ceiling no real radiator reaches. Declared heat above it therefore
        cannot be rejected by any package built around this airflow, which is
        what makes the bound worth checking even though it is optimistic.
        """
        airflow = self.cooling_airflow_cms
        cooling = self.interfaces.get("cooling")
        if cooling is not None and cooling.cooling_airflow_cms is not None:
            airflow = max(airflow, cooling.cooling_airflow_cms)
        return (
            airflow
            * AIR_DENSITY_KG_PER_M3
            * AIR_CP_J_PER_KG_K
            * self.cooling_air_rise_k
        )

    # ---- the checks -------------------------------------------------------

    def check_all(self) -> list[IntegrationFinding]:
        """Run every cross-subsystem check, worst findings first."""
        findings = [
            *self._check_mass_budget(),
            *self._check_cg(),
            *self._check_envelopes(),
            *self._check_cooling(),
            *self._check_electrical(),
            *self._check_driveline_torque(),
            *self._check_mount_loads(),
            *self._check_estimates(),
        ]
        return sorted(findings, key=lambda finding: finding.severity.rank)

    def _check_mass_budget(self) -> list[IntegrationFinding]:
        rollup = self.mass_rollup()
        out: list[IntegrationFinding] = []
        if rollup.missing_mass:
            out.append(
                IntegrationFinding(
                    check="mass-budget",
                    severity=Severity.MISSING,
                    message=(
                        f"{len(rollup.missing_mass)} subsystem(s) have not "
                        f"declared a mass: {', '.join(rollup.missing_mass)}. The "
                        "car total — and so suspension's load transfer — is "
                        "incomplete."
                    ),
                    subsystems=rollup.missing_mass,
                    detail={"declared": list(rollup.declared)},
                )
            )
        if not rollup.declared:
            return out

        allowance = (
            f" (target net of {self.includes_driver_kg:.0f} kg driver = "
            f"{rollup.target_net_kg:.0f} kg)"
            if self.includes_driver_kg > 0.0
            else ""
        )
        message = (
            f"Declared subsystem mass {rollup.total_kg:.1f} kg against a "
            f"{rollup.target_net_kg:.0f} kg target{allowance} "
            f"({rollup.delta_kg:+.1f} kg)."
        )
        if rollup.missing_mass:
            message += " Not everyone has reported, so the real total is higher."
        if rollup.delta_kg > 0.05 * rollup.target_net_kg:
            severity = Severity.FAIL
        elif rollup.delta_kg > 0.0:
            severity = Severity.WARN
        else:
            severity = Severity.OK
        out.append(
            IntegrationFinding(
                check="mass-budget-total",
                severity=severity,
                message=message,
                subsystems=rollup.declared,
                detail={
                    "total_kg": rollup.total_kg,
                    "target_net_kg": rollup.target_net_kg,
                    "delta_kg": rollup.delta_kg,
                },
            )
        )
        return out

    def _check_cg(self) -> list[IntegrationFinding]:
        rollup = self.mass_rollup()
        if rollup.cg_mm is None:
            if not rollup.declared:
                return []
            return [
                IntegrationFinding(
                    check="cg",
                    severity=Severity.MISSING,
                    message=(
                        "Combined CG is not computable: "
                        f"{', '.join(rollup.missing_cg)} declared a mass with no "
                        "CG location. Suspension is using an assumed CG height "
                        "nobody has confirmed against the real layout."
                    ),
                    subsystems=(*rollup.missing_cg, "suspension"),
                    detail={"missing_cg": list(rollup.missing_cg)},
                )
            ]
        x, y, z = rollup.cg_mm
        out = [
            IntegrationFinding(
                check="cg",
                severity=Severity.INFO,
                message=(
                    f"Combined CG of the declared subsystems: x={x:.0f}, "
                    f"y={y:.0f}, z={z:.0f} mm. Feed the {z:.0f} mm CG height "
                    "into the vehicle model so load transfer matches the build."
                ),
                subsystems=("suspension", "chassis"),
                detail={"cg_x_mm": x, "cg_y_mm": y, "cg_z_mm": z},
            )
        ]
        if abs(y) > 25.0:
            out.append(
                IntegrationFinding(
                    check="cg-lateral",
                    severity=Severity.WARN,
                    message=(
                        f"Combined CG is {y:+.0f} mm off the centreline. That is "
                        "a static lateral weight bias the corner weights have to "
                        "account for."
                    ),
                    subsystems=("suspension", "chassis"),
                    detail={"cg_y_mm": y},
                )
            )
        return out

    def _check_envelopes(self) -> list[IntegrationFinding]:
        envelope = self.chassis_envelope_mm
        if envelope is None:
            chassis = self.interfaces.get("chassis")
            envelope = chassis.envelope_mm if chassis is not None else None
        if envelope is None:
            return [
                IntegrationFinding(
                    check="envelope",
                    severity=Severity.MISSING,
                    message=(
                        "Chassis has not declared the interior envelope it "
                        "offers, so nothing can be fit-checked against it."
                    ),
                    subsystems=("chassis",),
                )
            ]
        out: list[IntegrationFinding] = []
        for name in SUBSYSTEMS:
            interface = self.interfaces.get(name)
            if name == "chassis" or interface is None:
                continue
            need = interface.envelope_mm
            if need is None:
                continue
            if any(n > e + 1e-6 for n, e in zip(need, envelope, strict=True)):
                out.append(
                    IntegrationFinding(
                        check="envelope-fit",
                        severity=Severity.FAIL,
                        message=(
                            f"{name} needs a {need[0]:.0f} x {need[1]:.0f} x "
                            f"{need[2]:.0f} mm box but the chassis offers "
                            f"{envelope[0]:.0f} x {envelope[1]:.0f} x "
                            f"{envelope[2]:.0f} mm. It does not fit."
                        ),
                        subsystems=(name, "chassis"),
                        detail={"need_mm": list(need), "have_mm": list(envelope)},
                    )
                )
        return out

    def _check_cooling(self) -> list[IntegrationFinding]:
        out: list[IntegrationFinding] = []
        airflow_need = 0.0
        heat_total = 0.0
        airflow_users: list[Subsystem] = []
        heat_sources: list[Subsystem] = []
        for name in SUBSYSTEMS:
            interface = self.interfaces.get(name)
            if interface is None or name == "cooling":
                continue
            if interface.cooling_airflow_cms is not None:
                airflow_need += interface.cooling_airflow_cms
                airflow_users.append(name)
            if interface.heat_reject_w is not None:
                heat_total += interface.heat_reject_w
                heat_sources.append(name)

        capacity_w = self.cooling_capacity_w()
        airflow_have = (
            capacity_w
            / (AIR_DENSITY_KG_PER_M3 * AIR_CP_J_PER_KG_K)
            / self.cooling_air_rise_k
        )

        if airflow_users:
            if airflow_have <= 0.0:
                out.append(
                    IntegrationFinding(
                        check="cooling-airflow",
                        severity=Severity.MISSING,
                        message=(
                            f"{', '.join(airflow_users)} require "
                            f"{airflow_need:.3f} m^3/s of cooling airflow, but "
                            "cooling has not declared what the package can move."
                        ),
                        subsystems=(*airflow_users, "cooling"),
                        detail={"need_cms": airflow_need},
                    )
                )
            elif airflow_need > airflow_have + 1e-9:
                out.append(
                    IntegrationFinding(
                        check="cooling-airflow",
                        severity=Severity.FAIL,
                        message=(
                            f"Cooling moves {airflow_have:.3f} m^3/s but "
                            f"{', '.join(airflow_users)} together need "
                            f"{airflow_need:.3f} m^3/s. The car is under-cooled."
                        ),
                        subsystems=(*airflow_users, "cooling"),
                        detail={"need_cms": airflow_need, "have_cms": airflow_have},
                    )
                )
            else:
                out.append(
                    IntegrationFinding(
                        check="cooling-airflow",
                        severity=Severity.OK,
                        message=(
                            f"Cooling airflow {airflow_have:.3f} m^3/s covers "
                            f"the {airflow_need:.3f} m^3/s required."
                        ),
                        subsystems=(*airflow_users, "cooling"),
                        detail={"need_cms": airflow_need, "have_cms": airflow_have},
                    )
                )

        if heat_sources and capacity_w > 0.0 and heat_total > capacity_w:
            out.append(
                IntegrationFinding(
                    check="cooling-heat",
                    severity=Severity.FAIL,
                    message=(
                        f"{', '.join(heat_sources)} reject {heat_total:.0f} W, "
                        f"above the {capacity_w:.0f} W that the declared airflow "
                        f"could carry even as a perfect heat exchanger at a "
                        f"{self.cooling_air_rise_k:.0f} K air rise. No radiator "
                        "sized to this airflow can do it."
                    ),
                    subsystems=(*heat_sources, "cooling"),
                    detail={"heat_w": heat_total, "ideal_capacity_w": capacity_w},
                )
            )
        return out

    def _check_electrical(self) -> list[IntegrationFinding]:
        out: list[IntegrationFinding] = []
        lv_draw = 0.0
        lv_users: list[Subsystem] = []
        assumed_lv: list[Subsystem] = []
        for name in SUBSYSTEMS:
            interface = self.interfaces.get(name)
            if interface is None or interface.power_draw_w is None:
                continue
            if interface.voltage_v is None:
                assumed_lv.append(name)
            elif abs(interface.voltage_v - self.lv_voltage_v) >= 5.0:
                continue
            lv_draw += interface.power_draw_w
            lv_users.append(name)

        if lv_users:
            over = lv_draw > self.lv_supply_capacity_w + 1e-6
            caveat = (
                f" {', '.join(assumed_lv)} declared a draw with no bus voltage "
                "and is counted as LV."
                if assumed_lv
                else ""
            )
            out.append(
                IntegrationFinding(
                    check="lv-power",
                    severity=Severity.FAIL if over else Severity.OK,
                    message=(
                        f"LV loads ({', '.join(lv_users)}) draw {lv_draw:.0f} W "
                        f"against a {self.lv_supply_capacity_w:.0f} W supply." + caveat
                    ),
                    subsystems=(*lv_users, "electrics"),
                    detail={
                        "draw_w": lv_draw,
                        "capacity_w": self.lv_supply_capacity_w,
                        "voltage_assumed_lv": list(assumed_lv),
                    },
                )
            )

        powertrain = self.interfaces.get("powertrain")
        if (
            powertrain is not None
            and powertrain.voltage_v is not None
            and powertrain.voltage_v > 60.0
            and abs(powertrain.voltage_v - self.accumulator_voltage_v)
            > 0.05 * self.accumulator_voltage_v
        ):
            out.append(
                IntegrationFinding(
                    check="hv-voltage",
                    severity=Severity.WARN,
                    message=(
                        f"Powertrain expects {powertrain.voltage_v:.0f} V but the "
                        f"accumulator is {self.accumulator_voltage_v:.0f} V. The "
                        "inverter or motor spec does not match the pack."
                    ),
                    subsystems=("powertrain", "electrics"),
                    detail={
                        "powertrain_v": powertrain.voltage_v,
                        "accumulator_v": self.accumulator_voltage_v,
                    },
                )
            )
        return out

    def _check_driveline_torque(self) -> list[IntegrationFinding]:
        powertrain = self.interfaces.get("powertrain")
        if powertrain is None or powertrain.peak_torque_nm is None:
            return []
        limit = self.driveline_torque_limit_nm
        if limit is None:
            suspension = self.interfaces.get("suspension")
            limit = suspension.peak_torque_nm if suspension is not None else None
        if limit is None:
            return [
                IntegrationFinding(
                    check="driveline-torque",
                    severity=Severity.MISSING,
                    message=(
                        f"Powertrain delivers {powertrain.peak_torque_nm:.0f} N*m "
                        "peak, but no driveline or CV torque rating has been "
                        "declared to check it against."
                    ),
                    subsystems=("powertrain", "suspension"),
                    detail={"torque_nm": powertrain.peak_torque_nm},
                )
            ]
        over = powertrain.peak_torque_nm > limit + 1e-6
        return [
            IntegrationFinding(
                check="driveline-torque",
                severity=Severity.FAIL if over else Severity.OK,
                message=(
                    f"Powertrain peak torque {powertrain.peak_torque_nm:.0f} N*m "
                    + (
                        f"exceeds the {limit:.0f} N*m driveline rating; the "
                        "driveshafts, CVs, and uprights will be overloaded."
                        if over
                        else f"is within the {limit:.0f} N*m driveline rating."
                    )
                ),
                subsystems=("powertrain", "suspension"),
                detail={"torque_nm": powertrain.peak_torque_nm, "limit_nm": limit},
            )
        ]

    def _check_mount_loads(self) -> list[IntegrationFinding]:
        out: list[IntegrationFinding] = []
        for name in SUBSYSTEMS:
            interface = self.interfaces.get(name)
            if interface is None or interface.mount_load_n is None:
                continue
            carrier: Subsystem = interface.mounts_on or "chassis"
            rating = self.upright_design_load_n if carrier == "suspension" else None
            mounts = (
                f"{interface.mount_points} mounts"
                if interface.mount_points is not None
                else "an undeclared number of mounts"
            )
            if rating is not None and interface.mount_load_n > rating + 1e-6:
                out.append(
                    IntegrationFinding(
                        check="mount-load",
                        severity=Severity.FAIL,
                        message=(
                            f"{name} puts {interface.mount_load_n:.0f} N into "
                            f"{carrier} mounts, above the {rating:.0f} N they "
                            "were designed for."
                        ),
                        subsystems=(name, carrier),
                        detail={
                            "load_n": interface.mount_load_n,
                            "rating_n": rating,
                        },
                    )
                )
                continue
            severity = Severity.OK if rating is not None else Severity.INFO
            tail = (
                f"within the {rating:.0f} N those mounts were designed for."
                if rating is not None
                else (
                    f"over {mounts}. {carrier} has declared no design load to "
                    "check that against."
                )
            )
            out.append(
                IntegrationFinding(
                    check="mount-load",
                    severity=severity,
                    message=(
                        f"{name} puts {interface.mount_load_n:.0f} N into "
                        f"{carrier}, {tail}"
                    ),
                    subsystems=(name, carrier),
                    detail={"load_n": interface.mount_load_n, "rating_n": rating},
                )
            )
        return out

    def _check_estimates(self) -> list[IntegrationFinding]:
        estimates = tuple(
            name
            for name in SUBSYSTEMS
            if (interface := self.interfaces.get(name)) is not None
            and interface.is_estimate
            and interface.is_declared()
        )
        if not estimates:
            return []
        return [
            IntegrationFinding(
                check="data-provenance",
                severity=Severity.INFO,
                message=(
                    f"{len(estimates)} subsystem(s) are still on estimated "
                    f"numbers: {', '.join(estimates)}. Every check above that "
                    "involves them is only as trustworthy as those estimates."
                ),
                subsystems=estimates,
            )
        ]


def blank_ledger(**budgets: Any) -> IntegrationLedger:
    """An empty ledger with all eight subsystems present but undeclared.

    Args:
        **budgets: Any `IntegrationLedger` field, to set the car-level budgets
            at construction.

    Returns:
        A ledger whose every check reports `MISSING` rather than passing.
    """
    ledger = IntegrationLedger(**budgets)
    for name in SUBSYSTEMS:
        ledger.declare(SubsystemInterface(name=name))
    return ledger


def summarise(findings: list[IntegrationFinding]) -> dict[str, Any]:
    """Count findings by severity and name the worst, for a board-level badge.

    Args:
        findings: Output of `IntegrationLedger.check_all`.

    Returns:
        `{"counts": {severity: n}, "worst": severity, "total": n}`. `worst` is
        `OK` for an empty list, which is the only honest reading of "nothing
        was checked and nothing failed".
    """
    counts = {severity.value: 0 for severity in _SEVERITY_ORDER}
    for finding in findings:
        counts[finding.severity.value] += 1
    worst = next(
        (s.value for s in _SEVERITY_ORDER if counts[s.value] > 0),
        Severity.OK.value,
    )
    return {"counts": counts, "worst": worst, "total": len(findings)}


def findings_for(
    findings: list[IntegrationFinding], subsystem: Subsystem
) -> list[IntegrationFinding]:
    """Every finding that implicates one subsystem, for its own tab view."""
    return [finding for finding in findings if subsystem in finding.subsystems]

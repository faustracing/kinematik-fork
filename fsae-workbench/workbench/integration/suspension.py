"""Wire the suspension `Design` into the integration ledger, both directions.

Two numbers cross this boundary and they go opposite ways.

*Out of the design*: suspension declares its own mass and CG into the ledger,
like every other subsystem, so the car total includes it.

*Into the design*: the ledger's combined mass and CG are what
`VehicleSpec.mass_kg`, `cg_height_mm`, and `front_mass_fraction` are *supposed*
to be. Until a ledger exists they are the placeholders in
`workbench.core.defaults`, and every load-transfer, anti-dive, and anti-squat
number computed from them inherits that. `apply_rollup` replaces the
placeholders with the declared build, and `check_against_design` reports the
gap when they disagree — which is the whole reason the ledger exists.

Both sides work in ISO 8855 millimetres on the design datum, so nothing is
converted here. See `workbench.integration.ledger` on the frame.
"""

from __future__ import annotations

import numpy as np

from workbench.core.design import Design
from workbench.integration.ledger import (
    IntegrationFinding,
    IntegrationLedger,
    Severity,
    SubsystemInterface,
)

__all__ = [
    "apply_rollup",
    "check_against_design",
    "declare_suspension",
    "suspension_interface",
    "unsprung_cg_mm",
]


def unsprung_cg_mm(design: Design) -> tuple[float, float, float]:
    """Estimate the suspension CG as the centroid of the wheel centres.

    An unsprung-mass CG sits close to the wheel centres: the uprights, hubs,
    bearings, and brakes are all clustered there, and the wishbones straddle
    the line between each wheel centre and the chassis. Taking the plain
    centroid assumes equal corner masses, which is wrong by the front-to-rear
    brake and upright difference but right to within a few tens of millimetres
    on a symmetric car.

    This is an *estimate*, and anything built on it should carry
    `is_estimate=True`. Weigh the corners and declare the real number.

    Args:
        design: The design to measure.

    Returns:
        `(x, y, z)` in ISO 8855 millimetres on the design datum.

    Raises:
        KeyError: When a corner has no wheel centre.
    """
    centres = [
        corner.position("wheel_center")
        for axle in design.axles.values()
        for corner in axle.corners
    ]
    centroid = np.mean(np.asarray(centres, dtype=np.float64), axis=0)
    return (float(centroid[0]), float(centroid[1]), float(centroid[2]))


def suspension_interface(
    design: Design,
    *,
    mass_kg: float,
    cg_mm: tuple[float, float, float] | None = None,
    mount_load_n: float | None = None,
    mount_points: int | None = None,
    is_estimate: bool = True,
    owner: str = "",
    rationale: str = "",
) -> SubsystemInterface:
    """Build suspension's ledger declaration from a design.

    Args:
        design: The design the mass belongs to.
        mass_kg: Total suspension mass — uprights, hubs, bearings, wishbones,
            rockers, pushrods, springs, dampers. A hardpoint file cannot imply
            this, so it has to be supplied.
        cg_mm: Where that mass acts. Defaults to `unsprung_cg_mm`, which
            forces `is_estimate` on because a centroid is not a measurement.
        mount_load_n: Peak force the inboard pickups put into the chassis.
        mount_points: How many pickups carry it.
        is_estimate: Whether these numbers are still placeholders.
        owner: Who on the sub-team owns this interface.
        rationale: Why these numbers. Appended to, not replaced, when the CG
            is derived rather than declared.

    Returns:
        A `SubsystemInterface` ready for `IntegrationLedger.declare`.
    """
    derived_cg = cg_mm is None
    cg = unsprung_cg_mm(design) if derived_cg else cg_mm
    assert cg is not None
    if derived_cg:
        note = (
            "CG estimated as the centroid of the four wheel centres of design "
            f"{design.name!r}; weigh the corners to replace it."
        )
        rationale = f"{rationale} {note}".strip()
    return SubsystemInterface(
        name="suspension",
        mass_kg=mass_kg,
        cg_x_mm=cg[0],
        cg_y_mm=cg[1],
        cg_z_mm=cg[2],
        mount_load_n=mount_load_n,
        mount_points=mount_points,
        mounts_on="chassis",
        is_estimate=is_estimate or derived_cg,
        owner=owner,
        rationale=rationale,
    )


def declare_suspension(
    ledger: IntegrationLedger, design: Design, **kwargs: object
) -> IntegrationLedger:
    """Declare one design's suspension into a ledger.

    Args:
        ledger: The ledger to record into. Modified in place.
        design: The design to declare.
        **kwargs: Forwarded to `suspension_interface`; `mass_kg` is required.

    Returns:
        The same ledger, so declarations chain.
    """
    return ledger.declare(suspension_interface(design, **kwargs))  # type: ignore[arg-type]


def apply_rollup(design: Design, ledger: IntegrationLedger) -> Design:
    """Return a copy of the design with the ledger's mass and CG applied.

    Replaces `VehicleSpec.mass_kg`, `cg_height_mm`, and `front_mass_fraction`
    with the declared build, and records in `Design.provenance` that they came
    from the ledger and whether they are still estimates. Geometry is
    untouched, so `Design.fingerprint` is unchanged only if the mass properties
    happened to already match — they feed anti-dive, anti-squat, and load
    transfer, so a change there is a change to the solve.

    Args:
        design: The design to update.
        ledger: A ledger with a complete mass rollup.

    Returns:
        A new `Design`. The input is not modified.

    Raises:
        ValueError: When the rollup has no mass or no combined CG, or when the
            combined CG falls outside the wheelbase, which would imply a mass
            fraction outside `[0, 1]` and means the declarations, the datum, or
            the sign convention are wrong.
    """
    rollup = ledger.mass_rollup()
    if rollup.cg_mm is None or rollup.total_kg <= 0.0:
        raise ValueError(
            "Ledger has no combined mass and CG to apply: "
            f"{rollup.total_kg:.1f} kg declared, "
            f"missing mass from {list(rollup.missing_mass)}, "
            f"missing CG from {list(rollup.missing_cg)}"
        )
    cg_x, _, cg_z = rollup.cg_mm
    wheelbase = design.vehicle.wheelbase_mm
    front_fraction = 1.0 + cg_x / wheelbase
    if not 0.0 <= front_fraction <= 1.0:
        raise ValueError(
            f"Combined CG at x={cg_x:.0f} mm is outside the {wheelbase:.0f} mm "
            "wheelbase, implying a front mass fraction of "
            f"{front_fraction:.2f}. On the design datum the front axle is at "
            "x = 0 and +x is forward, so a CG behind it is negative; check the "
            "sign convention of the declared CGs."
        )
    vehicle = design.vehicle.model_copy(
        update={
            "mass_kg": rollup.total_kg,
            "cg_height_mm": cg_z,
            "front_mass_fraction": front_fraction,
        }
    )
    provenance = dict(design.provenance)
    provenance["mass_properties"] = {
        "source": "integration ledger",
        "declared_by": list(rollup.declared),
        "missing": list(rollup.missing_mass),
        "any_estimate": rollup.any_estimate,
    }
    return design.model_copy(update={"vehicle": vehicle, "provenance": provenance})


def check_against_design(
    ledger: IntegrationLedger,
    design: Design,
    *,
    mass_tolerance_kg: float = 5.0,
    cg_tolerance_mm: float = 10.0,
) -> list[IntegrationFinding]:
    """Compare the ledger's rollup against the mass properties a design assumes.

    The design's `VehicleSpec` carries the mass, CG height, and front mass
    fraction that every load-transfer and anti-geometry number was computed
    from. When those are the `workbench.core.defaults` placeholders and the
    ledger holds the real build, every one of those numbers is wrong by the
    difference — silently, because the solve still converges.

    Args:
        ledger: The ledger holding the declared build.
        design: The design to compare against.
        mass_tolerance_kg: Difference below which the two agree.
        cg_tolerance_mm: CG height difference below which the two agree.

    Returns:
        Findings, worst first. An incomplete rollup yields one `MISSING`
        finding rather than a comparison against a partial total.
    """
    rollup = ledger.mass_rollup()
    if not rollup.declared:
        return [
            IntegrationFinding(
                check="design-mass",
                severity=Severity.MISSING,
                message=(
                    f"No subsystem has declared a mass, so design "
                    f"{design.name!r} is still running on its assumed "
                    f"{design.vehicle.mass_kg:.0f} kg and "
                    f"{design.vehicle.cg_height_mm:.0f} mm CG height. Anti-dive, "
                    "anti-squat, and load transfer all inherit that assumption."
                ),
                subsystems=("suspension",),
                detail={
                    "design_mass_kg": design.vehicle.mass_kg,
                    "design_cg_height_mm": design.vehicle.cg_height_mm,
                },
            )
        ]

    out: list[IntegrationFinding] = []
    mass_delta = rollup.total_kg - design.vehicle.mass_kg
    incomplete = (
        " The rollup is incomplete, so the real gap is larger."
        if rollup.missing_mass
        else ""
    )
    out.append(
        IntegrationFinding(
            check="design-mass",
            severity=(
                Severity.WARN if abs(mass_delta) > mass_tolerance_kg else Severity.OK
            ),
            message=(
                f"Design {design.name!r} assumes {design.vehicle.mass_kg:.1f} kg; "
                f"the ledger declares {rollup.total_kg:.1f} kg "
                f"({mass_delta:+.1f} kg)." + incomplete
            ),
            subsystems=("suspension",),
            detail={
                "design_mass_kg": design.vehicle.mass_kg,
                "ledger_mass_kg": rollup.total_kg,
                "delta_kg": mass_delta,
                "complete": not rollup.missing_mass,
            },
        )
    )

    if rollup.cg_mm is None:
        out.append(
            IntegrationFinding(
                check="design-cg",
                severity=Severity.MISSING,
                message=(
                    "The combined CG is not computable, so the design's assumed "
                    f"{design.vehicle.cg_height_mm:.0f} mm CG height cannot be "
                    f"confirmed. {', '.join(rollup.missing_cg)} declared a mass "
                    "with no CG."
                ),
                subsystems=(*rollup.missing_cg, "suspension"),
                detail={"design_cg_height_mm": design.vehicle.cg_height_mm},
            )
        )
        return sorted(out, key=lambda finding: finding.severity.rank)

    cg_x, _, cg_z = rollup.cg_mm
    cg_delta = cg_z - design.vehicle.cg_height_mm
    out.append(
        IntegrationFinding(
            check="design-cg",
            severity=(
                Severity.WARN if abs(cg_delta) > cg_tolerance_mm else Severity.OK
            ),
            message=(
                f"Design {design.name!r} assumes a "
                f"{design.vehicle.cg_height_mm:.0f} mm CG height; the ledger "
                f"puts it at {cg_z:.0f} mm ({cg_delta:+.0f} mm). CG height "
                "scales lateral load transfer directly."
            ),
            subsystems=("suspension", "chassis"),
            detail={
                "design_cg_height_mm": design.vehicle.cg_height_mm,
                "ledger_cg_height_mm": cg_z,
                "delta_mm": cg_delta,
            },
        )
    )

    ledger_fraction = 1.0 + cg_x / design.vehicle.wheelbase_mm
    fraction_delta = ledger_fraction - design.vehicle.front_mass_fraction
    out.append(
        IntegrationFinding(
            check="design-mass-distribution",
            severity=(Severity.WARN if abs(fraction_delta) > 0.02 else Severity.OK),
            message=(
                f"Design {design.name!r} assumes "
                f"{design.vehicle.front_mass_fraction:.1%} front; the declared "
                f"CG implies {ledger_fraction:.1%} ({fraction_delta:+.1%})."
            ),
            subsystems=("suspension", "chassis"),
            detail={
                "design_front_fraction": design.vehicle.front_mass_fraction,
                "ledger_front_fraction": ledger_fraction,
                "delta": fraction_delta,
            },
        )
    )
    return sorted(out, key=lambda finding: finding.severity.rank)

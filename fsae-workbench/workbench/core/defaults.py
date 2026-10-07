"""Documented defaults for data the hardpoint CSV does not carry.

A hardpoint file is only the linkage. Every number here is something a solve
needs but a hardpoint export cannot supply: tire size, spring rates, rack
travel, mass properties, and the two synthesis policies that reconstruct solver
inputs the CSV leaves implicit (the wheel spin axis and the rocker pivot axis).

Everything is declared as frozen dataclass *data*, not as scattered literals, so
a caller replaces a whole record rather than hunting constants:

    >>> from workbench.core import defaults
    >>> golden = defaults.GOLDEN_CAR
    >>> golden.front.spring.rate_n_per_mm
    43.78

Each record names its unit and, where a rate or a radius is only meaningful at a
particular place in the mechanism, the location it is measured at. A spring rate
at the damper and a spring rate at the wheel differ by the square of the motion
ratio; storing a bare number invites exactly that mistake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

__all__ = [
    "GOLDEN_CAR",
    "HOOSIER_18X6_R25B",
    "AxleDefaults",
    "CarDefaults",
    "RackDefaults",
    "RockerAxisPolicy",
    "SpinAxisPolicy",
    "SpringDefaults",
    "TireDefaults",
    "VehicleMassDefaults",
]

MM_PER_INCH: Final[float] = 25.4


@dataclass(frozen=True, slots=True)
class TireDefaults:
    """One tire's physical size and its kinematic rolling radius.

    Attributes:
        name: Manufacturer designation, for display and provenance.
        compound: Compound code, e.g. ``"R25B"`` for the Hoosier dry slick.
        overall_diameter_in: Nominal unloaded overall diameter, inches.
        section_width_in: Nominal section width, inches.
        rim_diameter_in: Rim bead seat diameter, inches.
        loaded_radius_mm: Static *loaded* radius measured at the design corner
            weight, millimetres, or ``None`` to fall back to the unloaded
            radius. This is the radius the kinematics must use: it fixes the
            ground plane the solver resolves contact patches, scrub radius, and
            roll centre height against.
    """

    name: str
    compound: str
    overall_diameter_in: float
    section_width_in: float
    rim_diameter_in: float
    loaded_radius_mm: float | None = None

    @property
    def unloaded_radius_mm(self) -> float:
        """Unloaded radius in millimetres, from the overall diameter."""
        return self.overall_diameter_in * MM_PER_INCH / 2.0

    @property
    def section_width_mm(self) -> float:
        """Section width in millimetres."""
        return self.section_width_in * MM_PER_INCH

    @property
    def kinematic_radius_mm(self) -> float:
        """Radius the solver should use for ground tangency, millimetres."""
        return (
            self.loaded_radius_mm
            if self.loaded_radius_mm is not None
            else self.unloaded_radius_mm
        )

    @property
    def static_deflection_mm(self) -> float:
        """Unloaded minus loaded radius, millimetres. Zero when unloaded."""
        return self.unloaded_radius_mm - self.kinematic_radius_mm


HOOSIER_18X6_R25B: Final[TireDefaults] = TireDefaults(
    name="Hoosier 18x6.0-10",
    compound="R25B",
    overall_diameter_in=18.0,
    section_width_in=6.0,
    rim_diameter_in=10.0,
    # Measured from the reference car: wheel centres sit 223.52 mm above the
    # contact-patch plane in the hardpoint file, against a 228.60 mm unloaded
    # radius, i.e. 5.08 mm (0.200 in) of static deflection. The loader derives
    # this from the file rather than trusting the literal; see
    # workbench.io.hardpoint_csv.
    loaded_radius_mm=223.52,
)
"""The reference car's dry slick. Loaded radius confirmed against the CSV."""


@dataclass(frozen=True, slots=True)
class SpringDefaults:
    """A coil spring rate, with the location the rate is quoted at.

    Attributes:
        rate_n_per_mm: Linear rate in newtons per millimetre.
        measured_at: Where the rate acts. ``"damper"`` means along the
            spring/damper axis, which is what a supplier quotes and what the
            reference car's numbers are; ``"wheel"`` means already referred to
            vertical wheel travel. Convert between them with the motion ratio:
            ``rate_wheel = rate_damper * motion_ratio ** 2`` where the motion
            ratio is spring travel per unit wheel travel.
        free_length_mm: Free length, millimetres, when known.
    """

    rate_n_per_mm: float
    measured_at: Literal["damper", "wheel"] = "damper"
    free_length_mm: float | None = None

    def wheel_rate_n_per_mm(self, motion_ratio: float) -> float:
        """Refer this rate to vertical wheel travel.

        Args:
            motion_ratio: Spring travel per unit wheel travel (dimensionless,
                typically 0.4 to 0.9 on an FSAE rocker car). Sign is ignored.

        Returns:
            The vertical wheel rate in newtons per millimetre.
        """
        if self.measured_at == "wheel":
            return self.rate_n_per_mm
        return self.rate_n_per_mm * motion_ratio**2


@dataclass(frozen=True, slots=True)
class RackDefaults:
    """Steering rack travel and ratio.

    Attributes:
        travel_mm: Rack displacement available either side of centre.
        steering_wheel_lock_deg: Steering wheel rotation to reach ``travel_mm``.
    """

    travel_mm: float
    steering_wheel_lock_deg: float


@dataclass(frozen=True, slots=True)
class SpinAxisPolicy:
    """How to reconstruct a wheel spin axis the hardpoint file omits.

    The solver locates the wheel from two hub points on the spin axis. A
    hardpoint export that only gives a wheel centre carries no information
    about the axis *orientation*, so static camber and static toe have to be
    supplied. Defaulting both to zero keeps the loaded design a faithful
    reading of the file: the solved contact patch then lands exactly on the
    file's contact-patch row, and any non-zero static camber or toe reported
    afterwards is real linkage behaviour rather than an assumption.

    Attributes:
        static_camber_deg: Negative leans the wheel top inboard, matching both
            the racing convention and the solver's sign.
        static_toe_deg: Positive is toe-in on the solver's convention. Note
            KinematiK reports toe with the opposite sign (positive is toe-out).
        half_length_mm: Separation from the wheel centre to the inboard hub
            point. Arbitrary: the axis direction is what matters, and every
            metric is invariant to this value.
    """

    static_camber_deg: float = 0.0
    static_toe_deg: float = 0.0
    half_length_mm: float = 100.0


@dataclass(frozen=True, slots=True)
class RockerAxisPolicy:
    """How to reconstruct a rocker pivot axis the hardpoint file omits.

    The solver needs two points defining the rocker's rotation axis. A file
    that gives a single rocker pivot point leaves the axis *direction* implicit.
    A rocker is a planar body: its pushrod and damper pickups both swing in a
    plane normal to the pivot pin, so the normal of the plane through the pivot
    and those two pickups recovers the pin direction. This is a reconstruction,
    not a measurement — if a rocker has deliberately non-planar pickups, author
    the axis explicitly instead.

    Attributes:
        half_length_mm: Separation of the two authored axis points either side
            of the pivot. Arbitrary; only the direction is used.
    """

    half_length_mm: float = 25.0


@dataclass(frozen=True, slots=True)
class VehicleMassDefaults:
    """Mass properties used by the load-sensitive metrics.

    Only the anti-geometry family and the roll/load-transfer work read these;
    pure linkage metrics (camber, toe, caster, KPI, scrub, motion ratio) do not.

    Attributes:
        mass_kg: Total mass with driver.
        front_mass_fraction: Share of static vertical load on the front axle.
        cg_height_mm: Centre of gravity height above the ground plane.
        front_brake_bias: Share of total braking force at the front axle.
        driven_axle: Which axle delivers tractive effort.
    """

    mass_kg: float = 290.0
    front_mass_fraction: float = 0.48
    cg_height_mm: float = 300.0
    front_brake_bias: float = 0.60
    driven_axle: Literal["front", "rear"] = "rear"

    def cg_x_mm(self, wheelbase_mm: float) -> float:
        """Longitudinal CG position on the design datum, millimetres.

        The datum puts the front axle at ``X = 0`` with ``+X`` forward, so the
        CG sits at a negative X, ``(1 - front_mass_fraction)`` of the wheelbase
        behind the front axle.
        """
        return -(1.0 - self.front_mass_fraction) * wheelbase_mm


@dataclass(frozen=True, slots=True)
class AxleDefaults:
    """Per-axle data the hardpoint file does not carry."""

    tire: TireDefaults
    spring: SpringDefaults
    wheel_offset_mm: float = 0.0
    """ET offset from hub face to wheel centre plane.

    Zero means the file's wheel-centre row *is* the hub face, which is how the
    loader places the hub points. Change it only alongside a wheel-centre
    definition that actually distinguishes the two.
    """

    spin_axis: SpinAxisPolicy = field(default_factory=SpinAxisPolicy)
    rocker_axis: RockerAxisPolicy = field(default_factory=RockerAxisPolicy)


@dataclass(frozen=True, slots=True)
class CarDefaults:
    """Whole-car defaults: one record per axle plus shared vehicle data."""

    front: AxleDefaults
    rear: AxleDefaults
    mass: VehicleMassDefaults = field(default_factory=VehicleMassDefaults)
    rack: RackDefaults = field(default_factory=lambda: RackDefaults(50.0, 180.0))

    def axle(self, axle_id: str) -> AxleDefaults:
        """Return the defaults for ``"front"`` or ``"rear"``."""
        if axle_id not in ("front", "rear"):
            raise KeyError(f"Unknown axle id {axle_id!r}; expected 'front' or 'rear'")
        return self.front if axle_id == "front" else self.rear


GOLDEN_CAR: Final[CarDefaults] = CarDefaults(
    front=AxleDefaults(
        tire=HOOSIER_18X6_R25B,
        spring=SpringDefaults(rate_n_per_mm=43.78, measured_at="damper"),
    ),
    rear=AxleDefaults(
        tire=HOOSIER_18X6_R25B,
        spring=SpringDefaults(rate_n_per_mm=39.40, measured_at="damper"),
    ),
)
"""Measured data for the reference four-corner car.

Tires and spring rates are real team data. Mass properties and rack travel are
still placeholders, flagged by the ``VehicleMassDefaults`` / ``RackDefaults``
field defaults rather than by being hidden in the geometry.
"""

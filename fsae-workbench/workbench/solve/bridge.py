"""The solver bridge: `Design` in, solved metrics out.

This is the only module in the workbench that knows the Suspension Explorer
geometry schema. Everything above it works in `Design` terms and reads
`SolveResult`.

Two solver inputs a hardpoint file cannot carry are reconstructed here, both
under policies declared in `workbench.core.defaults`:

* **The wheel spin axis.** The solver locates the wheel from two hub points.
  A file with one wheel-centre row fixes the axis position but not its
  orientation, so static camber and toe come from `SpinAxisPolicy`.
* **The rocker pivot axis.** The solver needs two points on the rocker's
  rotation axis. A file with one rocker-pivot row leaves the direction
  implicit, so it is recovered as the normal of the plane through the pivot and
  the rocker's two pickups — a rocker is a planar body, so that normal is the
  pin direction.

Non-convergence is contained here. The solver raises `RuntimeError` when a
sweep step fails; `solve` catches it and returns `converged=False` with the
failure as a finding, so an optimizer can penalise a design instead of
crashing on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np

from workbench.core.defaults import GOLDEN_CAR, CarDefaults
from workbench.core.design import Axle, Corner, Design

if TYPE_CHECKING:  # pragma: no cover - typing only
    from kinematics.core.sweep import EvaluatedSweep

__all__ = [
    "NODE_ID_TO_SE_POINT",
    "SolveFinding",
    "SolveResult",
    "WorkbenchSolveError",
    "motion_ratio",
    "rocker_axis_points",
    "solve",
    "spin_axis_points",
    "to_se_geometry",
    "wheel_rate_n_per_mm",
]

NODE_ID_TO_SE_POINT: Final[dict[str, str]] = {
    "lca_fore_inboard": "lower_wishbone_inboard_front",
    "lca_aft_inboard": "lower_wishbone_inboard_rear",
    "lca_outboard": "lower_wishbone_outboard",
    "uca_fore_inboard": "upper_wishbone_inboard_front",
    "uca_aft_inboard": "upper_wishbone_inboard_rear",
    "uca_outboard": "upper_wishbone_outboard",
    "tie_rod_inboard": "trackrod_inboard",
    "tie_rod_outboard": "trackrod_outboard",
    "toe_link_inboard": "toe_link_inboard",
    "toe_link_outboard": "toe_link_outboard",
    "pushrod_outboard": "pushrod_outboard",
    "rocker_pushrod": "pushrod_inboard",
    "rocker_damper": "strut_bottom",
    "damper_inboard": "strut_top",
}
"""Canonical node ids to Suspension Explorer point ids.

`wheel_center`, `contact_patch`, and `rocker_pivot` are deliberately absent:
the first two are solver *outputs* derived from the hub points and the tire
radius, and the third expands into the two-point rocker axis. See
`spin_axis_points` and `rocker_axis_points`.
"""

_MOTION_RATIO_KEY: Final[str] = "deriv_spring_length_wrt_hub_z"


class WorkbenchSolveError(ValueError):
    """Raised when a `Design` cannot be expressed as a solvable geometry.

    This is a *modelling* error — a missing node, an unsupported architecture,
    a degenerate rocker — and is distinct from non-convergence, which is
    reported through `SolveResult.converged` rather than raised.
    """


@dataclass(frozen=True, slots=True)
class SolveFinding:
    """One problem observed while solving.

    Field names line up with `workbench.rules.Finding` where the two overlap,
    so the app can render solver findings and rule findings in one list.

    Attributes:
        severity: `"BLOCKER"`, `"WARNING"`, or `"INFO"`.
        message: Human-readable description.
        step: Sweep step index, or `None` for a sweep-wide finding.
        measured: Salient numeric value, when there is one.
    """

    severity: Literal["BLOCKER", "WARNING", "INFO"]
    message: str
    step: int | None = None
    measured: float | None = None


@dataclass(frozen=True, slots=True)
class SolveResult:
    """A solved sweep, flattened for charts, scoring, and the viewport.

    Attributes:
        axle: Which axle was solved.
        sweep: Name of the sweep template, or `"custom"`.
        converged: True only when every step converged.
        findings: Non-convergence and solver diagnostics.
        metrics: Flat metric key to one value per step. Corner metrics carry a
            `_left` / `_right` suffix, matching the solver's own flat export.
            Steps where a metric is undefined hold `nan`.
        positions: Node id to one `(3,)` position per step, keyed
            `"{corner}.{node}"` exactly as the viewport payload expects.
        sweep_values: The commanded sweep coordinate per step, per dimension.
        fingerprint: `Design.fingerprint()` of the solved design.
        evaluated: The underlying solver result, for callers that need more
            than the flattened view. `None` when the solve failed outright.
    """

    axle: str
    sweep: str
    converged: bool
    findings: tuple[SolveFinding, ...] = ()
    metrics: dict[str, list[float]] = field(default_factory=dict)
    positions: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    sweep_values: dict[str, list[float]] = field(default_factory=dict)
    fingerprint: str = ""
    evaluated: EvaluatedSweep | None = None

    @property
    def n_steps(self) -> int:
        """Number of solved steps."""
        return len(next(iter(self.metrics.values()), []))

    def at(self, step: int) -> dict[str, float]:
        """Return every metric at one step index."""
        return {key: values[step] for key, values in self.metrics.items()}

    def static(self) -> dict[str, float]:
        """Return every metric at the step nearest the static condition.

        For a symmetric sweep this is the midpoint, which is the authored ride
        height. Templates that do not straddle static report their first step.
        """
        return self.at(self.n_steps // 2 if self.n_steps > 1 else 0)


def spin_axis_points(
    corner: Corner,
    *,
    static_camber_deg: float = 0.0,
    static_toe_deg: float = 0.0,
    half_length_mm: float = 100.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct the two hub points on the wheel spin axis.

    The outboard hub point coincides with the authored wheel centre, which is
    what a zero wheel offset means to the solver. The inboard point is placed
    back along the spin axis, whose direction carries the static camber and toe.

    Args:
        corner: The corner to build the axis for.
        static_camber_deg: Negative leans the wheel top inboard.
        static_toe_deg: Positive is toe-in.
        half_length_mm: Hub point separation. Arbitrary — the direction is all
            the solver uses, and no metric depends on the magnitude.

    Returns:
        `(axle_inboard, axle_outboard)` as ISO 8855 millimetre arrays.
    """
    wheel_center = np.asarray(corner.position("wheel_center"), dtype=np.float64)
    side_sign = 1.0 if corner.side == "left" else -1.0
    outboard_x = side_sign * math.sin(math.radians(static_toe_deg))
    outboard_z = -math.sin(math.radians(static_camber_deg))
    lateral = 1.0 - outboard_x**2 - outboard_z**2
    if lateral <= 0.0:
        raise WorkbenchSolveError(
            f"Static camber {static_camber_deg} deg and toe {static_toe_deg} deg "
            "do not define a spin axis"
        )
    direction = np.array(
        [outboard_x, side_sign * math.sqrt(lateral), outboard_z], dtype=np.float64
    )
    return wheel_center - direction * half_length_mm, wheel_center


def rocker_axis_points(
    corner: Corner, *, half_length_mm: float = 25.0
) -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct two points on the rocker's rotation axis.

    Args:
        corner: A corner with `rocker_pivot`, `rocker_pushrod`, and
            `rocker_damper` nodes.
        half_length_mm: Separation of the returned points either side of the
            pivot. Arbitrary — only the direction is used.

    Returns:
        `(axis_a, axis_b)` as ISO 8855 millimetre arrays, straddling the pivot.

    Raises:
        WorkbenchSolveError: When the pivot and the two pickups are collinear,
            which leaves the rocker plane — and so the pin direction —
            undefined.
    """
    pivot = np.asarray(corner.position("rocker_pivot"), dtype=np.float64)
    pushrod = np.asarray(corner.position("rocker_pushrod"), dtype=np.float64)
    damper = np.asarray(corner.position("rocker_damper"), dtype=np.float64)
    normal = np.cross(pushrod - pivot, damper - pivot)
    magnitude = float(np.linalg.norm(normal))
    if magnitude < 1e-6:
        raise WorkbenchSolveError(
            f"Corner {corner.id!r} has a collinear rocker: the pivot, pushrod "
            "pickup, and damper pickup do not define a plane, so the pivot "
            "axis cannot be reconstructed. Author the axis explicitly."
        )
    normal = normal / magnitude
    return pivot - normal * half_length_mm, pivot + normal * half_length_mm


def _se_tire_config(design: Design) -> dict[str, float]:
    """Express the design's tire as a Suspension Explorer tire config.

    The solver derives its ground plane from
    `(rim_diameter + 2 * aspect_ratio * section_width) / 2`, so the aspect
    ratio is solved backwards from the radius the kinematics should use — the
    *loaded* radius when one is known. Using the unloaded radius instead would
    place the ground plane below the authored contact patches and shift every
    ground-referenced metric: on the reference car by 5.08 mm, which moves the
    front roll centre by 2.7 mm and the scrub radius by 0.7 mm.
    """
    tire = design.tire
    rim_mm = tire.rim_diameter_in * 25.4
    section_mm = tire.section_width_mm
    aspect_ratio = (2.0 * tire.kinematic_radius_mm - rim_mm) / (2.0 * section_mm)
    if not 0.0 <= aspect_ratio <= 1.0:
        raise WorkbenchSolveError(
            f"Tire radius {tire.kinematic_radius_mm:.2f} mm cannot be expressed "
            f"on a {tire.rim_diameter_in:.1f} in rim with a "
            f"{tire.section_width_in:.1f} in section width: the implied aspect "
            f"ratio is {aspect_ratio:.3f}, outside [0, 1]"
        )
    return {
        "rim_diameter": tire.rim_diameter_in,
        "section_width": section_mm,
        "aspect_ratio": aspect_ratio,
    }


def _se_corner_hardpoints(
    corner: Corner, car_defaults: CarDefaults, axle_id: str
) -> dict[str, dict[str, float]]:
    axle_defaults = car_defaults.axle(axle_id)
    points: dict[str, np.ndarray] = {}
    for node_id, node in corner.nodes.items():
        se_point = NODE_ID_TO_SE_POINT.get(node_id)
        if se_point is not None:
            points[se_point] = np.asarray(node.position, dtype=np.float64)
    spin = axle_defaults.spin_axis
    inboard, outboard = spin_axis_points(
        corner,
        static_camber_deg=spin.static_camber_deg,
        static_toe_deg=spin.static_toe_deg,
        half_length_mm=spin.half_length_mm,
    )
    points["axle_inboard"] = inboard
    points["axle_outboard"] = outboard
    if corner.has_rocker:
        axis_a, axis_b = rocker_axis_points(
            corner, half_length_mm=axle_defaults.rocker_axis.half_length_mm
        )
        points["rocker_axis_a"] = axis_a
        points["rocker_axis_b"] = axis_b
    return {
        name: {"x": float(p[0]), "y": float(p[1]), "z": float(p[2])}
        for name, p in sorted(points.items())
    }


def to_se_geometry(
    design: Design, axle: str, *, car_defaults: CarDefaults = GOLDEN_CAR
) -> dict[str, Any]:
    """Build the Suspension Explorer axle geometry dict for one axle.

    Args:
        design: The design to translate.
        axle: `"front"` or `"rear"`.
        car_defaults: Source of the spin-axis and rocker-axis policies and the
            per-axle wheel offset.

    Returns:
        A dict ready for `kinematics.core.input.build_suspension`.

    Raises:
        WorkbenchSolveError: On an unknown axle, an unsupported architecture,
            an axle without an explicit right corner, or a mechanism mismatch
            between the two corners.
    """
    try:
        axle_model = design.axles[axle]
    except KeyError:
        raise WorkbenchSolveError(
            f"Design {design.name!r} has no {axle!r} axle; "
            f"available: {sorted(design.axles)}"
        ) from None
    if axle_model.architecture != "double_wishbone":
        raise WorkbenchSolveError(
            f"The bridge supports double_wishbone axles only; {axle!r} is "
            f"{axle_model.architecture!r}"
        )
    if axle_model.right is None:
        raise WorkbenchSolveError(
            f"Axle {axle!r} has no explicit right corner. Mirroring through "
            "Y = 0 is a solver feature the bridge does not use, because the "
            "workbench supports asymmetric designs."
        )
    _check_mechanisms_match(axle_model)

    left = axle_model.left
    axle_defaults = car_defaults.axle(axle)
    vehicle = design.vehicle
    return {
        "type": "double_wishbone",
        "scope": "axle",
        "name": f"{design.name}-{axle}",
        "version": "1.0.0",
        "units": "millimeters",
        "vehicle_config": {
            "cg_position": {"x": vehicle.cg_x_mm, "y": 0.0, "z": vehicle.cg_height_mm},
            "wheelbase": vehicle.wheelbase_mm,
            "front_brake_bias": vehicle.front_brake_bias,
            "driven_axle": vehicle.driven_axle,
        },
        "axle_config": {
            "axle_position": axle,
            "steering": {"type": axle_model.steering},
            # A pullrod and a pushrod are one mechanism to the solver; the
            # distinction lives in Corner.actuation for display and reporting.
            "actuation": {
                "type": "pushrod_rocker" if left.has_rocker else "direct",
                "mount": left.pushrod_mount,
            },
            "spring": {"type": left.spring},
            "damper": {"type": "none"},
            "anti_roll": {"type": "none"},
            "heave_link": {"type": "none"},
            "wheel": {
                "offset": axle_defaults.wheel_offset_mm,
                "tire": _se_tire_config(design),
            },
        },
        "hardpoints": {
            "left": _se_corner_hardpoints(left, car_defaults, axle),
            "right": _se_corner_hardpoints(axle_model.right, car_defaults, axle),
            "center": {
                name: {
                    "x": float(node.position[0]),
                    "y": float(node.position[1]),
                    "z": float(node.position[2]),
                }
                for name, node in sorted(axle_model.center_nodes.items())
            },
        },
    }


def _check_mechanisms_match(axle_model: Axle) -> None:
    """Reject per-side hardware the solver can only configure axle-wide."""
    left, right = axle_model.left, axle_model.right
    assert right is not None
    for attribute in ("has_rocker", "spring", "pushrod_mount"):
        if getattr(left, attribute) != getattr(right, attribute):
            raise WorkbenchSolveError(
                f"Axle {axle_model.id!r} corners disagree on {attribute!r} "
                f"({getattr(left, attribute)!r} vs {getattr(right, attribute)!r}). "
                "The solver configures actuation and springs per axle, not per "
                "corner."
            )


def solve(
    design: Design,
    axle: str,
    sweep: str | dict[str, Any] = "bump",
    *,
    car_defaults: CarDefaults = GOLDEN_CAR,
    **sweep_kwargs: Any,
) -> SolveResult:
    """Solve one axle through one sweep.

    Uses `solve_evaluated_sweep`, which solves once. `analyze_sweep` solves
    twice and must not appear in anything loop-shaped.

    Args:
        design: The design to solve.
        axle: `"front"` or `"rear"`.
        sweep: A template name from `workbench.solve.sweeps`, or a ready sweep
            dict.
        car_defaults: Source of the reconstruction policies.
        **sweep_kwargs: Forwarded to the named template.

    Returns:
        A `SolveResult`. Non-convergence sets `converged=False` and records a
        `BLOCKER` finding rather than raising.

    Raises:
        WorkbenchSolveError: When the design cannot be expressed as a solvable
            geometry, or the named template does not exist. Modelling errors
            are the caller's bug; non-convergence is a property of the design.
    """
    from kinematics.core.input import build_suspension, build_sweep
    from kinematics.core.sweep import solve_evaluated_sweep

    from workbench.solve.sweeps import sweep_spec

    geometry = to_se_geometry(design, axle, car_defaults=car_defaults)
    sweep_name = sweep if isinstance(sweep, str) else "custom"
    spec = (
        sweep_spec(sweep, design, axle, **sweep_kwargs)
        if isinstance(sweep, str)
        else sweep
    )
    fingerprint = design.fingerprint()

    try:
        suspension = build_suspension(geometry)
        sweep_config = build_sweep(spec, suspension)
    except (ValueError, TypeError, KeyError) as error:
        raise WorkbenchSolveError(
            f"Design {design.name!r} axle {axle!r} is not a valid solver "
            f"geometry or sweep: {error}"
        ) from error

    try:
        evaluated = solve_evaluated_sweep(suspension, sweep_config)
    except RuntimeError as error:
        # The solver raises RuntimeError when a sweep step fails to converge.
        # Contain it here so optimizers can penalise rather than crash.
        return SolveResult(
            axle=axle,
            sweep=sweep_name,
            converged=False,
            findings=(
                SolveFinding(
                    severity="BLOCKER",
                    message=f"Solver did not converge: {error}",
                ),
            ),
            fingerprint=fingerprint,
        )

    return _wrap(evaluated, axle=axle, sweep=sweep_name, fingerprint=fingerprint)


def _wrap(
    evaluated: EvaluatedSweep, *, axle: str, sweep: str, fingerprint: str
) -> SolveResult:
    rows = [_flat_row(row) for row in evaluated.metrics.rows]
    keys = sorted({key for row in rows for key in row})
    metrics = {key: [_as_float(row.get(key)) for row in rows] for key in keys}

    findings: list[SolveFinding] = [
        SolveFinding(
            severity="BLOCKER",
            message=f"Step {index} did not converge "
            f"(max residual {info.max_residual:.3e})",
            step=index,
            measured=float(info.max_residual),
        )
        for index, info in enumerate(evaluated.solver_stats)
        if not info.converged
    ]
    findings.extend(
        SolveFinding(
            severity="BLOCKER" if issue.severity == "error" else "WARNING",
            message=f"{issue.category}: {issue.message}",
            step=issue.step,
            measured=None if issue.value is None else float(issue.value),
        )
        for issue in evaluated.diagnostics
    )

    return SolveResult(
        axle=axle,
        sweep=sweep,
        converged=all(info.converged for info in evaluated.solver_stats),
        findings=tuple(findings),
        metrics=metrics,
        positions=_positions(evaluated, axle),
        sweep_values={},
        fingerprint=fingerprint,
        evaluated=evaluated,
    )


def _flat_row(row: Any) -> dict[str, Any]:
    """Flatten an axle metric row, or pass a corner row straight through."""
    return dict(row.flat_row() if hasattr(row, "flat_row") else row)


def _as_float(value: Any) -> float:
    """Render a metric value as a float, mapping undefined metrics to `nan`."""
    return float("nan") if value is None else float(value)


def _positions(
    evaluated: EvaluatedSweep, axle: str
) -> dict[str, list[tuple[float, float, float]]]:
    """Flatten solved positions to viewport-shaped `"{corner}.{node}"` keys."""
    corner_suffix = "f" if axle == "front" else "r"
    se_to_node = {value: key for key, value in NODE_ID_TO_SE_POINT.items()}
    se_to_node.update(
        {
            "wheel_center": "wheel_center",
            "wheel_contact_center": "contact_patch",
            "axle_inboard": "axle_inboard",
            "axle_outboard": "axle_outboard",
        }
    )
    tracks: dict[str, list[tuple[float, float, float]]] = {}
    for state in evaluated.states:
        for key, point in state.positions.items():
            side = getattr(key, "side", None)
            point_id = getattr(key, "point", key)
            node_id = se_to_node.get(getattr(point_id, "name", "").lower())
            if node_id is None or side is None:
                continue
            data = np.asarray(getattr(point, "data", point), dtype=np.float64)
            label = f"{side.name[0].lower()}{corner_suffix}.{node_id}"
            tracks.setdefault(label, []).append(
                (float(data[0]), float(data[1]), float(data[2]))
            )
    return tracks


def motion_ratio(result: SolveResult, side: str = "left") -> float:
    """Return the static motion ratio: spring travel per unit wheel travel.

    Reported unsigned. The solver's own value is negative because a spring
    shortens as its wheel rises; the sign carries no extra information once
    you know which way bump goes.

    Args:
        result: A solved sweep that straddles static.
        side: `"left"` or `"right"`.

    Returns:
        Spring travel per millimetre of *wheel-centre* travel. Note this is
        wheel-centre travel, not lower-ball-joint travel: see the README on the
        KinematiK comparison, where the two differ by 3 to 4 percent.
    """
    key = f"{_MOTION_RATIO_KEY}_{side}"
    try:
        return abs(result.static()[key])
    except KeyError:
        raise WorkbenchSolveError(
            f"Result has no {key!r}; the corner has no spring, so it has no "
            "motion ratio"
        ) from None


def wheel_rate_n_per_mm(
    result: SolveResult,
    spring_rate_n_per_mm: float,
    side: str = "left",
) -> float:
    """Refer a spring rate quoted at the damper to vertical wheel travel.

    `rate_wheel = rate_damper * motion_ratio ** 2`. Quoting a spring rate
    without the motion ratio is meaningless on a rocker car: the same spring
    gives wildly different wheel rates at different ratios.
    """
    return spring_rate_n_per_mm * motion_ratio(result, side) ** 2

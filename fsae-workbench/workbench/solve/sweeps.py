"""Named sweep templates as Suspension Explorer sweep dicts.

Every template is a coordinated multi-target sweep. The solver has no
special-cased "bump" or "roll" entry point: a roll sweep is two opposed wheel-Z
targets, a steer sweep is a rack target with the wheels held, and so on. Target
dimensions are paired by step index, never crossed into a grid.

All five templates hold the rack. On an unsteered axle the solver drops that
hold automatically, since an axle with no rack degree of freedom already
satisfies it, so the same bump template works on both axles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

__all__ = [
    "SWEEP_TEMPLATES",
    "available",
    "bump",
    "combined",
    "droop",
    "roll",
    "steer",
    "sweep_spec",
]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from workbench.core.design import Design

DEFAULT_TRAVEL_MM: Final[float] = 25.0
DEFAULT_RACK_MM: Final[float] = 25.0
DEFAULT_STEPS: Final[int] = 21


def _wheel_z(
    side: str,
    start: float,
    stop: float,
) -> dict[str, Any]:
    return {
        "type": "point",
        "point": "wheel_center",
        "side": side,
        "direction": {"axis": "z"},
        "mode": "relative",
        "start": start,
        "stop": stop,
    }


def _wheel_z_held(side: str) -> dict[str, Any]:
    return {
        "type": "point",
        "point": "wheel_center",
        "side": side,
        "direction": {"axis": "z"},
        "hold": True,
    }


def _rack(start: float | None = None, stop: float | None = None) -> dict[str, Any]:
    target: dict[str, Any] = {
        "type": "actuator_position",
        "actuator": "rack",
        "direction": {"axis": "y"},
    }
    if start is None:
        target["hold"] = True
    else:
        target.update(mode="relative", start=start, stop=stop)
    return target


def bump(
    travel_mm: float = DEFAULT_TRAVEL_MM, steps: int = DEFAULT_STEPS
) -> dict[str, Any]:
    """Symmetric wheel travel through static, from full droop to full bump.

    Args:
        travel_mm: Travel either side of static.
        steps: Number of solved steps. An odd count puts a step exactly at
            static, which is what the pinned static metrics are read from.
    """
    return {
        "version": 1,
        "steps": steps,
        "targets": [
            _wheel_z("left", -travel_mm, travel_mm),
            _wheel_z("right", -travel_mm, travel_mm),
            _rack(),
        ],
    }


def droop(
    travel_mm: float = DEFAULT_TRAVEL_MM, steps: int = DEFAULT_STEPS
) -> dict[str, Any]:
    """Symmetric wheel travel from static down into droop only."""
    return {
        "version": 1,
        "steps": steps,
        "targets": [
            _wheel_z("left", 0.0, -travel_mm),
            _wheel_z("right", 0.0, -travel_mm),
            _rack(),
        ],
    }


def roll(
    travel_mm: float = DEFAULT_TRAVEL_MM, steps: int = DEFAULT_STEPS
) -> dict[str, Any]:
    """Opposed wheel travel: pure roll about the axle centreline.

    The left wheel rises as the right falls, so the axle rolls with no net
    heave. This is the sweep roll centre height and migration are read from.
    """
    return {
        "version": 1,
        "steps": steps,
        "targets": [
            _wheel_z("left", -travel_mm, travel_mm),
            _wheel_z("right", travel_mm, -travel_mm),
            _rack(),
        ],
    }


def steer(
    rack_mm: float = DEFAULT_RACK_MM, steps: int = DEFAULT_STEPS
) -> dict[str, Any]:
    """Rack travel through centre at fixed ride height.

    Only valid on a steered axle: an axle with no rack has no coordinate to
    sweep. `sweep_spec` rejects it early with that explanation.
    """
    return {
        "version": 1,
        "steps": steps,
        "targets": [
            _rack(-rack_mm, rack_mm),
            _wheel_z_held("left"),
            _wheel_z_held("right"),
        ],
    }


def combined(
    travel_mm: float = DEFAULT_TRAVEL_MM,
    rack_mm: float = DEFAULT_RACK_MM,
    steps: int = DEFAULT_STEPS,
) -> dict[str, Any]:
    """Roll and steer together, paired step by step.

    The corner condition: the axle rolls into the corner while the rack winds
    on. Targets pair by index, so step `i` applies the `i`-th roll angle *and*
    the `i`-th rack position, rather than sweeping a grid of the two.
    """
    return {
        "version": 1,
        "steps": steps,
        "targets": [
            _wheel_z("left", -travel_mm, travel_mm),
            _wheel_z("right", travel_mm, -travel_mm),
            _rack(-rack_mm, rack_mm),
        ],
    }


SWEEP_TEMPLATES: Final[dict[str, Any]] = {
    "bump": bump,
    "droop": droop,
    "roll": roll,
    "steer": steer,
    "combined": combined,
}
"""Template name to builder. `sweep_spec` is the validated way in."""

_REQUIRES_RACK: Final[frozenset[str]] = frozenset({"steer", "combined"})


def available() -> list[str]:
    """Template names, in a stable order."""
    return list(SWEEP_TEMPLATES)


def sweep_spec(name: str, design: Design, axle: str, **kwargs: Any) -> dict[str, Any]:
    """Build one named template, checked against the axle it will run on.

    Args:
        name: A name from `available()`.
        design: The design the sweep will be solved against.
        axle: `"front"` or `"rear"`.
        **kwargs: Forwarded to the template builder.

    Returns:
        A sweep dict for `kinematics.core.input.build_sweep`.

    Raises:
        WorkbenchSolveError: On an unknown template name, or a steering sweep
            requested for an axle with no rack.
    """
    from workbench.solve.bridge import WorkbenchSolveError

    builder = SWEEP_TEMPLATES.get(name)
    if builder is None:
        raise WorkbenchSolveError(
            f"Unknown sweep template {name!r}; available: {available()}"
        )
    axle_model = design.axles.get(axle)
    if axle_model is None:
        raise WorkbenchSolveError(
            f"Design {design.name!r} has no {axle!r} axle; "
            f"available: {sorted(design.axles)}"
        )
    if name in _REQUIRES_RACK and axle_model.steering != "rack":
        raise WorkbenchSolveError(
            f"Sweep {name!r} drives the steering rack, but axle {axle!r} has "
            f"steering={axle_model.steering!r}. Use 'bump', 'droop', or 'roll' "
            "on an unsteered axle."
        )
    return builder(**kwargs)

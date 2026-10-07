"""Shared fixtures.

The `kinematics` solver is not installable from an index yet, so tests that
need it skip rather than fail when it is absent. See README "Solver
dependency"; the TODO(solver-pin) there removes these guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

GOLDEN_CSV = Path(__file__).parent / "fixtures" / "golden-car-hardpoints.csv"


@pytest.fixture(scope="session")
def golden_csv() -> Path:
    """Path to the reference four-corner hardpoint file."""
    return GOLDEN_CSV


@pytest.fixture(scope="session")
def golden_design(golden_csv: Path):
    """The reference car loaded into a `Design`."""
    from workbench.io import load_design

    return load_design(golden_csv, name="golden-car")


@pytest.fixture(scope="session")
def solver():
    """The solver package, skipping the test when it is not installed."""
    return pytest.importorskip(
        "kinematics",
        reason="the `kinematics` solver is not installed; see README "
        "'Solver dependency'",
    )


@pytest.fixture(scope="session")
def front_bump(golden_design, solver):
    """A solved 21-step front bump sweep, +/-25 mm."""
    from workbench.solve import solve

    return solve(golden_design, "front", "bump", travel_mm=25.0, steps=21)


@pytest.fixture(scope="session")
def rear_bump(golden_design, solver):
    """A solved 21-step rear bump sweep, +/-25 mm."""
    from workbench.solve import solve

    return solve(golden_design, "rear", "bump", travel_mm=25.0, steps=21)

"""The solver bridge and the named sweep templates."""

from __future__ import annotations

from workbench.solve.bridge import (
    SolveFinding,
    SolveResult,
    WorkbenchSolveError,
    motion_ratio,
    solve,
    to_se_geometry,
    wheel_rate_n_per_mm,
)
from workbench.solve.sweeps import available, sweep_spec

__all__ = [
    "SolveFinding",
    "SolveResult",
    "WorkbenchSolveError",
    "available",
    "motion_ratio",
    "solve",
    "sweep_spec",
    "to_se_geometry",
    "wheel_rate_n_per_mm",
]

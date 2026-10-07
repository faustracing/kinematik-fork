"""DXF sketches and solved-design reports.

DXF export is one axle per file: front and rear overlap in a shared plan view.
The report reads static metrics and sweep curves off a :class:`SolveResult`,
including ``anti_dive`` on the front axle and ``anti_squat`` on the rear.
"""

from __future__ import annotations

from workbench.export.dxf import (
    AxleSketch,
    View,
    axle_sketch,
    sketch_to_dxf,
    write_axle_dxfs,
)
from workbench.export.report import (
    AxleReport,
    DesignReport,
    StaticMetric,
    SweepFigure,
    SweepSeries,
    build_report,
    render_pdf,
)

__all__ = [
    "AxleReport",
    "AxleSketch",
    "DesignReport",
    "StaticMetric",
    "SweepFigure",
    "SweepSeries",
    "View",
    "axle_sketch",
    "build_report",
    "render_pdf",
    "sketch_to_dxf",
    "write_axle_dxfs",
]

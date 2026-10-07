"""Import and export adapters for external geometry formats.

Two ways in. `load_design` reads the canonical four-corner CSV layout, where
the point names are already the project's own. `import_design` reads everything
else — OptimumK exports, team Excel workbooks, CSVs with the columns in another
order — resolving names and units first and then handing the points to the same
assembly path, so neither can drift from the other on frames or defaults.
"""

from __future__ import annotations

from workbench.io.hardpoint_csv import (
    FrameReport,
    HardpointCsvError,
    design_from_points,
    load_design,
    read_points,
    verify_frame,
)
from workbench.io.hardpoint_import import (
    HardpointImportError,
    ImportIssue,
    ImportReport,
    RawPoint,
    import_design,
    import_points,
)

__all__ = [
    "FrameReport",
    "HardpointCsvError",
    "HardpointImportError",
    "ImportIssue",
    "ImportReport",
    "RawPoint",
    "design_from_points",
    "import_design",
    "import_points",
    "load_design",
    "read_points",
    "verify_frame",
]

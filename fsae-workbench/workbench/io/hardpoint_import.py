"""Import hardpoints from whatever spreadsheet the team already has.

The switching cost that keeps a team on its old workflow is re-typing
hardpoints. `hardpoint_csv` reads one specific layout — `Point Name,X (mm),
Y (mm),Z (mm)`, one row per point, canonical point names. This module reads
everything else: an OptimumK point export, a team Excel workbook, a CSV with
the columns in a different order and a title block above them.

It is a front end, not a second loader. Once the rows are parsed and the names
resolved, the points go through `hardpoint_csv.design_from_points`, so frame
verification, SAE conversion, datum normalisation, and the documented defaults
are shared with the canonical path and cannot drift from it.

Honesty contract
----------------
* A name that could mean two different hardpoints is reported **ambiguous and
  left unmapped**, never coin-flipped. So is one hardpoint claimed by two rows.
* Units come from the column headers when the file states them, and otherwise
  from the *span* of the coordinates, with the basis for the inference
  reported for the caller to override.
* The coordinate frame is never asked for and never assumed. It is measured
  from the geometry by `hardpoint_csv.verify_frame`, which rejects a file whose
  axes are mutually contradictory instead of guessing. A file in SAE axes is
  detected and converted through `workbench.core.frames`.
* Nothing is mirrored and nothing is re-origined by heuristic. The workbench
  holds four explicit corners, so a file that only describes one corner is an
  incomplete car and is reported as such rather than reflected into one.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np

from workbench.core import defaults as wb_defaults
from workbench.core.design import Design
from workbench.core.frames import Frame
from workbench.io.hardpoint_csv import (
    POINT_NAME_TO_NODE_ID,
    HardpointCsvError,
    design_from_points,
)

__all__ = [
    "CORNER_ALIASES",
    "NODE_CONCEPTS",
    "UNIT_SCALE_TO_MM",
    # `HardpointCsvError` is re-exported: `import_design` raises it from
    # `design_from_points`, and a caller should not have to import the CSV
    # module to catch it.
    "HardpointCsvError",
    "HardpointImportError",
    "ImportIssue",
    "ImportReport",
    "RawPoint",
    "import_design",
    "import_points",
    "infer_unit",
    "parse_rows",
    "read_table",
    "resolve_corner",
    "resolve_node_id",
]


class HardpointImportError(ValueError):
    """Raised when a source cannot be read as a set of hardpoints at all."""


IssueKind = Literal["unrecognised", "ambiguous", "duplicate"]

UNIT_SCALE_TO_MM: Final[dict[str, float]] = {"mm": 1.0, "m": 1000.0, "in": 25.4}
"""Length units the importer understands, and their conversion to millimetres."""


@dataclass(frozen=True, slots=True)
class RawPoint:
    """One row of a source table, before any interpretation.

    Attributes:
        name: The point name exactly as the file spells it.
        xyz: The three coordinates, in the file's own units and frame.
        sheet: Worksheet name, or `"csv"` for a delimited file.
        row: 1-based row number within the sheet, for error messages.
    """

    name: str
    xyz: tuple[float, float, float]
    sheet: str = "csv"
    row: int = 0

    @property
    def location(self) -> str:
        """Human-readable source location, for a message that has to be acted on."""
        return f"{self.sheet} row {self.row}"


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """One row the importer refused to interpret.

    An issue is never fatal on its own: the rest of the file still imports, and
    the caller decides whether what came through is enough.

    Attributes:
        kind: `"unrecognised"`, `"ambiguous"`, or `"duplicate"`.
        point: The row in question.
        candidates: Node ids the name could have meant, for an ambiguity.
        message: What to do about it.
    """

    kind: IssueKind
    point: RawPoint
    candidates: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Everything one import produced, mapped and unmapped alike.

    Attributes:
        points: `{"<corner>.<node_id>": xyz}` in millimetres, in the file's own
            frame and datum. This is exactly what `design_from_points` takes.
        unit: The length unit the source was read in.
        unit_basis: Why that unit was chosen.
        issues: Rows that were not mapped, and why.
        rows_read: How many data rows were parsed, mapped or not.
        sheets: Worksheets that contributed rows.
    """

    points: dict[str, np.ndarray]
    unit: str
    unit_basis: str
    issues: tuple[ImportIssue, ...] = ()
    rows_read: int = 0
    sheets: tuple[str, ...] = ()

    @property
    def corners(self) -> tuple[str, ...]:
        """Corner ids that received at least one point, in a stable order."""
        seen = {key.split(".", 1)[0] for key in self.points}
        return tuple(c for c in ("lf", "rf", "lr", "rr") if c in seen)

    def summary(self) -> str:
        """One line naming what was mapped and what was refused."""
        parts = [f"{len(self.points)} points mapped"]
        for kind in ("unrecognised", "ambiguous", "duplicate"):
            count = sum(1 for issue in self.issues if issue.kind == kind)
            if count:
                parts.append(f"{count} {kind}")
        parts.append(f"corners: {', '.join(self.corners) or 'none'}")
        parts.append(f"units: {self.unit} ({self.unit_basis})")
        return "; ".join(parts)


# --------------------------------------------------------------------------- #
#  Reading rows out of a CSV or a workbook
# --------------------------------------------------------------------------- #

_HEADER_NAME = re.compile(r"^\s*(point|name|label|description|hardpoint|pt)\b", re.I)
_HEADER_X = re.compile(r"^\s*x\b|\blong", re.I)
_HEADER_Y = re.compile(r"^\s*y\b|\blat", re.I)
_HEADER_Z = re.compile(r"^\s*z\b|\bvert", re.I)
_HEADER_UNIT = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")

_UNIT_WORDS: Final[dict[str, str]] = {
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "in": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
}

_XLSX_SUFFIXES: Final[frozenset[str]] = frozenset({".xlsx", ".xlsm", ".xltx"})
_CSV_SUFFIXES: Final[frozenset[str]] = frozenset({".csv", ".tsv", ".txt"})


def _as_float(value: Any) -> float | None:
    """Parse one cell as a finite number, or return `None`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _unit_from_header(cells: Sequence[Any]) -> str | None:
    """Read a declared unit out of a header row's bracketed suffixes."""
    for cell in cells:
        for match in _HEADER_UNIT.finditer(str(cell or "")):
            word = (match.group(1) or match.group(2) or "").strip().lower()
            if word in _UNIT_WORDS:
                return _UNIT_WORDS[word]
    return None


def _csv_rows(text: str) -> list[tuple[str, int, list[Any]]]:
    """Split delimited text, choosing the delimiter by frequency.

    `csv.Sniffer` fails on the narrow, title-blocked tables these exports
    produce, so the delimiter is whichever of comma, semicolon, or tab occurs
    most in the head of the file. Semicolons are what OptimumK and euro-locale
    spreadsheets emit.
    """
    head = "\n".join(text.splitlines()[:10])
    delimiter = max(",;\t", key=head.count) if any(d in head for d in ",;\t") else ","
    return [
        ("csv", index, list(row))
        for index, row in enumerate(
            csv.reader(io.StringIO(text), delimiter=delimiter), 1
        )
    ]


def _xlsx_rows(data: bytes) -> list[tuple[str, int, list[Any]]]:
    """Read every worksheet of a workbook into rows."""
    try:
        import openpyxl
    except ImportError as error:  # pragma: no cover - depends on the extra
        raise HardpointImportError(
            "Reading .xlsx needs openpyxl; install the 'excel' extra "
            "(pip install 'fsae-workbench[excel]')"
        ) from error
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    try:
        return [
            (sheet.title, index, list(row))
            for sheet in workbook.worksheets
            for index, row in enumerate(sheet.iter_rows(values_only=True), 1)
        ]
    finally:
        workbook.close()


def read_table(
    source: Path | str | bytes, *, filename: str = ""
) -> list[tuple[str, int, list[Any]]]:
    """Read a CSV or workbook into `(sheet, row_number, cells)` tuples.

    Args:
        source: A path, or the file's bytes.
        filename: Original file name, used to pick the reader when `source` is
            bytes. Without it the ZIP magic number decides.

    Returns:
        Every row of every sheet, in file order.

    Raises:
        HardpointImportError: When the file cannot be read at all.
    """
    if isinstance(source, Path | str) and not isinstance(source, bytes):
        path = Path(source)
        if not path.is_file():
            raise HardpointImportError(f"No such hardpoint file: {path}")
        data = path.read_bytes()
        filename = filename or path.name
    else:
        data = source
    suffix = Path(filename).suffix.lower()
    if suffix in _XLSX_SUFFIXES:
        return _xlsx_rows(data)
    if suffix in _CSV_SUFFIXES:
        return _csv_rows(data.decode("utf-8-sig", errors="replace"))
    # An unknown or absent extension: a workbook is a ZIP, so its magic number
    # settles it without trusting the name.
    if data[:2] == b"PK":
        return _xlsx_rows(data)
    return _csv_rows(data.decode("utf-8-sig", errors="replace"))


def parse_rows(
    rows: Iterable[tuple[str, int, list[Any]]],
) -> tuple[list[RawPoint], str | None]:
    """Find the point tables in a sheet of rows.

    Tolerant of layout, because these files have title blocks, merged cells,
    and several tables per sheet. A header row is one carrying X, Y, and Z
    column markers in any order with anything between them; rows beneath it are
    read positionally until a blank row ends the table. With no header at all,
    any row shaped `[text, number, number, number]` is taken as a point.

    Args:
        rows: Output of `read_table`.

    Returns:
        `(points, declared_unit)`, where the unit is `None` unless a header
        row stated one.
    """
    points: list[RawPoint] = []
    declared_unit: str | None = None
    columns: dict[str, int] | None = None
    current_sheet: str | None = None

    for sheet, number, raw_cells in rows:
        if sheet != current_sheet:
            current_sheet, columns = sheet, None  # a header never crosses sheets
        cells = ["" if cell is None else cell for cell in raw_cells]
        if not any(str(cell).strip() for cell in cells):
            columns = None  # a blank row ends the table
            continue

        header = _header_columns(cells)
        if header is not None:
            columns = header
            declared_unit = declared_unit or _unit_from_header(cells)
            continue

        point = (
            _data_row(cells, columns, sheet, number)
            if columns is not None
            else _headerless_row(cells, sheet, number)
        )
        if point is not None:
            points.append(point)
    return points, declared_unit


def _header_columns(cells: Sequence[Any]) -> dict[str, int] | None:
    """Return the column indices of a header row, or `None` if it is not one."""
    found: dict[str, int] = {}
    for index, cell in enumerate(cells):
        text = str(cell)
        if "name" not in found and _HEADER_NAME.search(text):
            found["name"] = index
        elif "x" not in found and _HEADER_X.search(text) and _as_float(cell) is None:
            found["x"] = index
        elif "y" not in found and _HEADER_Y.search(text) and _as_float(cell) is None:
            found["y"] = index
        elif "z" not in found and _HEADER_Z.search(text) and _as_float(cell) is None:
            found["z"] = index
    if not {"x", "y", "z"} <= found.keys():
        return None
    if "name" not in found:
        axes = {found["x"], found["y"], found["z"]}
        for index, cell in enumerate(cells):
            if index not in axes and str(cell).strip():
                found["name"] = index
                break
    return found if "name" in found else None


def _data_row(
    cells: Sequence[Any], columns: Mapping[str, int], sheet: str, number: int
) -> RawPoint | None:
    """Read one row positionally under a known header."""
    if max(columns.values()) >= len(cells):
        return None
    name = str(cells[columns["name"]]).strip()
    coordinates = [_as_float(cells[columns[axis]]) for axis in ("x", "y", "z")]
    if not name or any(value is None for value in coordinates):
        return None
    x, y, z = coordinates
    assert x is not None and y is not None and z is not None
    return RawPoint(name=name, xyz=(x, y, z), sheet=sheet, row=number)


def _headerless_row(cells: Sequence[Any], sheet: str, number: int) -> RawPoint | None:
    """Read a row shaped `[text, number, number, number]` with no header above it."""
    name: str | None = None
    numbers: list[float] = []
    for cell in cells:
        value = _as_float(cell)
        if value is not None:
            numbers.append(value)
        elif str(cell).strip() and name is None:
            name = str(cell).strip()
    if name is None or len(numbers) < 3:
        return None
    return RawPoint(
        name=name, xyz=(numbers[0], numbers[1], numbers[2]), sheet=sheet, row=number
    )


# --------------------------------------------------------------------------- #
#  Corner and name resolution
# --------------------------------------------------------------------------- #

CORNER_ALIASES: Final[dict[str, str]] = {
    "lf": "lf",
    "fl": "lf",
    "frontleft": "lf",
    "leftfront": "lf",
    "rf": "rf",
    "fr": "rf",
    "frontright": "rf",
    "rightfront": "rf",
    "lr": "lr",
    "rl": "lr",
    "rearleft": "lr",
    "leftrear": "lr",
    "rr": "rr",
    "rearright": "rr",
    "rightrear": "rr",
}
"""Corner labels a file might use, in either order, to workbench corner ids.

`RR` is the one token that reads the same in both orders and means the same
corner either way. Everything else is listed both ways round because teams and
tools disagree: OptimumK writes `FL`, this project's own exports write `LF`.
"""

_CONCEPTS: Final[dict[str, frozenset[str]]] = {
    "upper": frozenset({"upper", "top", "uca", "uwb", "upperarm"}),
    "lower": frozenset({"lower", "bottom", "lca", "lwb", "lowerarm"}),
    "fore": frozenset({"fore", "front", "fwd", "forward", "leading"}),
    "aft": frozenset({"aft", "rear", "rearward", "back", "trailing"}),
    "inboard": frozenset({"inboard", "inner", "chassis", "frame", "in"}),
    "outboard": frozenset(
        {"outboard", "outer", "upright", "knuckle", "balljoint", "bj", "out"}
    ),
    "tierod": frozenset({"tie", "tierod", "trackrod", "steering", "steer", "track"}),
    "toelink": frozenset({"toe", "toelink"}),
    "wheel": frozenset({"wheel", "wc", "wheelcenter", "wheelcentre"}),
    "centre": frozenset({"center", "centre", "ctr"}),
    "patch": frozenset({"patch", "contact", "contactpatch", "cp", "ground"}),
    "rod": frozenset({"pushrod", "pullrod", "push", "pull", "prod"}),
    "rocker": frozenset({"rocker", "bellcrank", "bell", "crank"}),
    "damper": frozenset({"damper", "shock", "spring", "coilover", "coil"}),
    "pivot": frozenset({"pivot", "axis"}),
}

NODE_CONCEPTS: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "uca_fore_inboard": (
        ("upper", "fore", "inboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "outboard"),
    ),
    "uca_aft_inboard": (
        ("upper", "aft", "inboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "outboard"),
    ),
    "lca_fore_inboard": (
        ("lower", "fore", "inboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "outboard"),
    ),
    "lca_aft_inboard": (
        ("lower", "aft", "inboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "outboard"),
    ),
    "uca_outboard": (
        ("upper", "outboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "inboard"),
    ),
    "lca_outboard": (
        ("lower", "outboard"),
        ("tierod", "toelink", "rod", "rocker", "damper", "inboard"),
    ),
    "tie_rod_inboard": (
        ("tierod", "inboard"),
        ("toelink", "rod", "rocker", "damper", "outboard"),
    ),
    "tie_rod_outboard": (
        ("tierod", "outboard"),
        ("toelink", "rod", "rocker", "damper", "inboard"),
    ),
    "toe_link_inboard": (
        ("toelink", "inboard"),
        ("tierod", "rod", "rocker", "damper", "outboard"),
    ),
    "toe_link_outboard": (
        ("toelink", "outboard"),
        ("tierod", "rod", "rocker", "damper", "inboard"),
    ),
    "wheel_center": (("wheel", "centre"), ("patch",)),
    "contact_patch": (("patch",), ("wheel",)),
    "pushrod_outboard": (("rod", "outboard"), ("rocker", "inboard")),
    "rocker_pushrod": (("rocker", "rod"), ("damper", "pivot")),
    "rocker_pivot": (("rocker", "pivot"), ("rod", "damper")),
    "rocker_damper": (("rocker", "damper"), ("rod", "inboard", "pivot")),
    "damper_inboard": (("damper", "inboard"), ("rocker", "outboard", "rod")),
}
"""Canonical node id to `(required concepts, forbidden concepts)`.

A name resolves to a node only when it hits every required concept and no
forbidden one. Hitting two nodes is an ambiguity and is reported, not resolved
by priority order — a coin flip here mirrors a car or swaps a tie rod for a toe
link, and both read as plausible geometry afterwards.

Only the double-wishbone node set `workbench.core.design` defines is listed.
KinematiK's vocabulary also covered MacPherson, multi-link, trailing-arm, and
solid-axle points; those come back when the solver bridge supports those
architectures, and recognising them now would map points into a `Design` that
cannot be solved.
"""

_FUSED_WORDS: Final[tuple[str, ...]] = (
    "tierod",
    "trackrod",
    "toelink",
    "wheelcenter",
    "wheelcentre",
    "bellcrank",
    "pushrod",
    "pullrod",
    "balljoint",
    "contactpatch",
    "upperarm",
    "lowerarm",
)


def _tokens(name: str) -> frozenset[str]:
    """Normalise a point name into a set of concept tokens."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    tokens = set(words)
    joined = "".join(words)
    tokens.update(fused for fused in _FUSED_WORDS if fused in joined)
    # "Track rod" is a tie rod; "track bar" is a Panhard rod. Once the fused
    # "trackrod" form is confirmed the bare token has done its job, and leaving
    # it in would read as the "track" of a track bar.
    if "trackrod" in tokens:
        tokens.discard("track")
    return frozenset(tokens)


def _hits(tokens: frozenset[str], concept: str) -> bool:
    return bool(tokens & _CONCEPTS[concept])


def resolve_corner(name: str) -> tuple[str | None, str, tuple[str, ...]]:
    """Split a corner label off a point name.

    Args:
        name: The point name as the file spells it.

    Returns:
        `(corner_id, remaining_name, all_matched_corners)`. `corner_id` is
        `None` when no corner is named, and the match list has more than one
        entry when the name claims two corners at once, which the caller must
        refuse.
    """
    words = re.sub(r"[^a-zA-Z0-9]+", " ", name).split()
    matched: list[str] = []
    keep: list[str] = []
    index = 0
    while index < len(words):
        pair = (
            (words[index] + words[index + 1]).lower() if index + 1 < len(words) else ""
        )
        if pair in CORNER_ALIASES:
            matched.append(CORNER_ALIASES[pair])
            index += 2
            continue
        single = words[index].lower()
        if single in CORNER_ALIASES:
            matched.append(CORNER_ALIASES[single])
            index += 1
            continue
        keep.append(words[index])
        index += 1
    unique = tuple(dict.fromkeys(matched))
    corner = unique[0] if len(unique) == 1 else None
    return corner, " ".join(keep), unique


def resolve_node_id(name: str) -> tuple[str | None, tuple[str, ...]]:
    """Resolve a point name to a canonical node id.

    Tries the exact table `hardpoint_csv` already uses, then falls back to
    concept matching for names it has never seen.

    Args:
        name: A point name with any corner label already removed.

    Returns:
        `(node_id, candidates)`. `node_id` is `None` when nothing matched or
        when several did, and `candidates` lists what it could have been.

        When nothing matches outright, `candidates` holds the nodes the name
        falls *one concept short* of. That is what an underspecified name looks
        like: "UCA Inboard" is plainly a wishbone pickup and plainly does not
        say which one, and naming both is far more use than reporting the name
        as unrecognised.
    """
    normalised = " ".join(name.lower().split())
    exact = POINT_NAME_TO_NODE_ID.get(normalised)
    if exact is not None:
        return exact, (exact,)

    tokens = _tokens(name)
    hits = tuple(
        node_id
        for node_id, (required, forbidden) in NODE_CONCEPTS.items()
        if all(_hits(tokens, concept) for concept in required)
        and not any(_hits(tokens, concept) for concept in forbidden)
    )
    if len(hits) == 1:
        return hits[0], hits
    if hits:
        return None, hits
    if _hits(tokens, "wheel") and not _hits(tokens, "patch"):
        # A bare "Wheel" or "WC" column is a wheel centre; nothing else in the
        # vocabulary is named for the wheel itself.
        return "wheel_center", ("wheel_center",)
    return None, _near_misses(tokens)


def _near_misses(tokens: frozenset[str]) -> tuple[str, ...]:
    """Nodes a name is exactly one concept short of naming.

    A node is a near miss only when every concept the name *does* hit is one
    the node requires. Without that, "UCA Inboard" would also suggest the tie
    rod and the damper, which are inboard pickups too but are not upper arms —
    a suggestion list long enough to be no help is the same as no list.
    """
    hit = frozenset(concept for concept in _CONCEPTS if _hits(tokens, concept))
    if not hit:
        return ()
    return tuple(
        node_id
        for node_id, (required, forbidden) in NODE_CONCEPTS.items()
        if not any(_hits(tokens, concept) for concept in forbidden)
        and hit <= frozenset(required)
        and len(required) - len(hit) == 1
    )


# --------------------------------------------------------------------------- #
#  Units
# --------------------------------------------------------------------------- #


def infer_unit(
    points: Sequence[RawPoint], declared: str | None = None
) -> tuple[str, str]:
    """Decide what length unit a set of coordinates is in.

    A declared unit from the column headers always wins. Otherwise the unit is
    inferred from the largest **span** of the coordinates along any axis, not
    from their magnitude: a span is invariant to where the file put its origin,
    and a car drawn about a CAD global origin metres away from the chassis has
    magnitudes that say nothing about its units.

    The spans that separate the three cases are far apart. One corner spans
    roughly 0.6 m, 600 mm, or 24 in; a whole car spans roughly 1.6 m, 1600 mm,
    or 63 in. Nothing real lands near the boundaries.

    Args:
        points: The parsed rows.
        declared: A unit read from the column headers, if the file stated one.

    Returns:
        `(unit, basis)` where the basis explains the choice in one sentence.
    """
    if declared in UNIT_SCALE_TO_MM:
        assert declared is not None
        return declared, "declared in the file's column headers"
    if not points:
        return "mm", "no coordinates to measure; defaulted to millimetres"
    data = np.asarray([point.xyz for point in points], dtype=np.float64)
    span = float(np.max(np.ptp(data, axis=0)))
    if span <= 0.0:
        return "mm", "every coordinate is identical; defaulted to millimetres"
    if span < 5.0:
        return "m", (
            f"the coordinates span {span:.2f}, which is car-sized only in metres"
        )
    if span < 120.0:
        return "in", (
            f"the coordinates span {span:.0f}, which is car-sized only in inches"
        )
    return "mm", (f"the coordinates span {span:.0f}, which is car-sized in millimetres")


# --------------------------------------------------------------------------- #
#  The pipeline
# --------------------------------------------------------------------------- #


def import_points(
    source: Path | str | bytes,
    *,
    filename: str = "",
    unit: str | None = None,
) -> ImportReport:
    """Read a spreadsheet into canonical hardpoints, reporting what it refused.

    Args:
        source: A path, or the file's bytes.
        filename: Original file name, used to pick the reader for bytes.
        unit: Override the unit instead of reading or inferring it.

    Returns:
        An `ImportReport`. Points that could not be resolved appear in
        `issues` rather than being dropped or guessed at.

    Raises:
        HardpointImportError: When the file cannot be read, holds no point
            table at all, or names a unit that is not a length.
    """
    if unit is not None and unit not in UNIT_SCALE_TO_MM:
        raise HardpointImportError(
            f"Unknown unit {unit!r}; expected one of {sorted(UNIT_SCALE_TO_MM)}"
        )
    rows = read_table(source, filename=filename)
    raw_points, declared_unit = parse_rows(rows)
    if not raw_points:
        raise HardpointImportError(
            "No point table found. The file needs a name column and X, Y, and "
            "Z columns, or rows shaped [name, x, y, z]."
        )

    chosen_unit, basis = (
        (unit, "set by the caller")
        if unit is not None
        else infer_unit(raw_points, declared_unit)
    )
    scale = UNIT_SCALE_TO_MM[chosen_unit]

    claims: dict[str, list[RawPoint]] = {}
    issues: list[ImportIssue] = []
    for point in raw_points:
        corner, remainder, matched_corners = resolve_corner(point.name)
        if len(matched_corners) > 1:
            issues.append(
                ImportIssue(
                    kind="ambiguous",
                    point=point,
                    candidates=matched_corners,
                    message=(
                        f"{point.location}: {point.name!r} names more than one "
                        f"corner ({', '.join(matched_corners)}). Left unmapped."
                    ),
                )
            )
            continue
        node_id, candidates = resolve_node_id(remainder)
        if node_id is None and len(candidates) > 1:
            issues.append(
                ImportIssue(
                    kind="ambiguous",
                    point=point,
                    candidates=candidates,
                    message=(
                        f"{point.location}: {point.name!r} could be any of "
                        f"{', '.join(candidates)}. Left unmapped rather than "
                        "guessed at."
                    ),
                )
            )
            continue
        if node_id is None:
            suggestion = (
                f" Did you mean {candidates[0]}? Say which one in the name."
                if candidates
                else ""
            )
            issues.append(
                ImportIssue(
                    kind="unrecognised",
                    point=point,
                    candidates=candidates,
                    message=(
                        f"{point.location}: {point.name!r} is not a hardpoint "
                        "name this importer knows." + suggestion
                    ),
                )
            )
            continue
        if corner is None:
            issues.append(
                ImportIssue(
                    kind="unrecognised",
                    point=point,
                    candidates=(node_id,),
                    message=(
                        f"{point.location}: {point.name!r} reads as {node_id} "
                        "but names no corner, and the workbench holds four "
                        "explicit corners. Label it LF, RF, LR, or RR."
                    ),
                )
            )
            continue
        claims.setdefault(f"{corner}.{node_id}", []).append(point)

    points: dict[str, np.ndarray] = {}
    for key, claimants in sorted(claims.items()):
        if len(claimants) == 1:
            points[key] = np.asarray(claimants[0].xyz, dtype=np.float64) * scale
            continue
        where = ", ".join(point.location for point in claimants)
        issues.extend(
            ImportIssue(
                kind="duplicate",
                point=point,
                candidates=(key,),
                message=(
                    f"{len(claimants)} rows claim {key} ({where}). All left "
                    "unmapped; delete or rename the duplicates."
                ),
            )
            for point in claimants
        )

    return ImportReport(
        points=points,
        unit=chosen_unit,
        unit_basis=basis,
        issues=tuple(issues),
        rows_read=len(raw_points),
        sheets=tuple(dict.fromkeys(sheet for sheet, _, _ in rows)),
    )


def import_design(
    source: Path | str | bytes,
    *,
    name: str = "",
    filename: str = "",
    unit: str | None = None,
    car_defaults: wb_defaults.CarDefaults = wb_defaults.GOLDEN_CAR,
    frame: Frame | None = None,
    normalise_datum: bool = True,
) -> tuple[Design, ImportReport]:
    """Import a spreadsheet of hardpoints into a `Design`.

    The points go through `hardpoint_csv.design_from_points`, so the frame is
    verified from the geometry, an SAE file is converted, the datum is
    normalised, and the documented defaults are applied exactly as they are
    for the canonical CSV layout.

    Args:
        source: A path, or the file's bytes.
        name: Design name; defaults to the file stem.
        filename: Original file name, used to pick the reader for bytes.
        unit: Override the unit instead of reading or inferring it.
        car_defaults: Data for the values a hardpoint file cannot carry.
        frame: Force a source frame instead of detecting one.
        normalise_datum: Shift onto the design datum.

    Returns:
        `(design, report)`. The report is returned alongside rather than folded
        into provenance so the caller can show the user every row that was
        refused, which is the point of refusing them.

    Raises:
        HardpointImportError: When the file is unreadable, or does not describe
            a complete four-corner car.
        HardpointCsvError: When the frame is self-contradictory or a corner
            is missing a required node.
    """
    report = import_points(source, filename=filename, unit=unit)
    if len(report.corners) < 4:
        missing = [c for c in ("lf", "rf", "lr", "rr") if c not in report.corners]
        raise HardpointImportError(
            f"Imported {len(report.points)} points covering corners "
            f"{list(report.corners)}, but a Design needs all four: "
            f"{missing} are absent. {report.summary()}"
        )
    stem = Path(filename or (source if isinstance(source, Path | str) else "")).stem
    design = design_from_points(
        report.points,
        name=name or stem or "imported",
        car_defaults=car_defaults,
        frame=frame,
        normalise_datum=normalise_datum,
        provenance={
            "source_file": filename
            or (Path(source).name if isinstance(source, Path | str) else "<bytes>"),
            "source_unit": report.unit,
            "source_unit_basis": report.unit_basis,
            "import_issues": [issue.message for issue in report.issues],
        },
    )
    return design, report

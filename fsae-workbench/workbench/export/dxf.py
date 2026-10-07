"""Per-axle 2D DXF sketches of the suspension.

Three orthographic views — front, side, and top — written as an R12 ASCII DXF
in ISO 8855 millimetres, so a CAD package can open the file as a sketch. Each
file is one axle. Front and rear are never drawn together: once each linkage
is placed on a common plan-view origin the two overlap, and a single top view
of the whole car is that collision.

Sheet coordinates are the projected vehicle coordinates plus the view origin
recorded on :class:`PlacedView`. Measuring a vertex and subtracting that origin
recovers the design point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Literal

from workbench.core.design import Axle, Corner, Design

__all__ = [
    "AxleSketch",
    "PlacedView",
    "SketchCircle",
    "SketchLine",
    "View",
    "axle_sketch",
    "sketch_to_dxf",
    "write_axle_dxfs",
]

_AXIS: dict[str, int] = {"x": 0, "y": 1, "z": 2}
_MARGIN_MM = 40.0
_GAP_MM = 120.0
_NODE_RADIUS_MM = 2.5
_GROUND_PAD_MM = 25.0
_MIN_SEGMENT_MM = 1e-6

_LAYER_COLOR: dict[str, int] = {
    "0": 7,
    "UPPER_WISHBONE": 5,
    "LOWER_WISHBONE": 1,
    "TIE_ROD": 3,
    "TOE_LINK": 3,
    "ACTUATION": 4,
    "ROCKER": 6,
    "DAMPER": 2,
    "UPRIGHT": 8,
    "WHEEL": 8,
    "TIRE": 8,
    "GROUND": 9,
    "CENTRELINE": 1,
    "NODES": 7,
    "ANNOTATION": 7,
}


class View(StrEnum):
    """One orthographic view, in unmirrored vehicle axes.

    Horizontal and vertical are ISO 8855 axes. A CAD measurement is that
    vehicle coordinate plus the view's sheet origin.
    """

    FRONT = "front"
    """Horizontal +Y (left), vertical +Z (up)."""

    SIDE = "side"
    """Horizontal +X (forward), vertical +Z (up)."""

    TOP = "top"
    """Horizontal +X (forward), vertical +Y (left)."""


_VIEW_AXES: dict[View, tuple[Literal["x", "y", "z"], Literal["x", "y", "z"]]] = {
    View.FRONT: ("y", "z"),
    View.SIDE: ("x", "z"),
    View.TOP: ("x", "y"),
}


@dataclass(frozen=True, slots=True)
class _Link:
    """A polyline through corner node ids. Missing nodes drop the whole link."""

    layer: str
    nodes: tuple[str, ...]
    closed: bool = False


_LINKS: tuple[_Link, ...] = (
    _Link(
        "LOWER_WISHBONE",
        ("lca_fore_inboard", "lca_outboard", "lca_aft_inboard"),
        closed=True,
    ),
    _Link(
        "UPPER_WISHBONE",
        ("uca_fore_inboard", "uca_outboard", "uca_aft_inboard"),
        closed=True,
    ),
    _Link("TIE_ROD", ("tie_rod_inboard", "tie_rod_outboard")),
    _Link("TOE_LINK", ("toe_link_inboard", "toe_link_outboard")),
    _Link("ACTUATION", ("pushrod_outboard", "rocker_pushrod")),
    _Link("ROCKER", ("rocker_pushrod", "rocker_pivot", "rocker_damper")),
    _Link("DAMPER", ("rocker_damper", "damper_inboard")),
    _Link("WHEEL", ("wheel_center", "contact_patch")),
    _Link("UPRIGHT", ("wheel_center", "lca_outboard")),
    _Link("UPRIGHT", ("wheel_center", "uca_outboard")),
    _Link("UPRIGHT", ("wheel_center", "tie_rod_outboard")),
    _Link("UPRIGHT", ("wheel_center", "toe_link_outboard")),
)


@dataclass(frozen=True, slots=True)
class _Segment:
    """One link edge in vehicle coordinates, before projection."""

    layer: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class SketchLine:
    """One projected edge, in the view's own axes and before the sheet origin.

    Attributes:
        layer: DXF layer name.
        start: ``(horizontal, vertical)`` millimetres in the view axes.
        end: ``(horizontal, vertical)`` millimetres in the view axes.
    """

    layer: str
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True, slots=True)
class SketchCircle:
    """A projected circle: a node marker or a tire in front or side view.

    Attributes:
        layer: DXF layer name.
        center: ``(horizontal, vertical)`` millimetres in the view axes.
        radius: Radius in millimetres.
    """

    layer: str
    center: tuple[float, float]
    radius: float


@dataclass(frozen=True, slots=True)
class PlacedView:
    """One view, projected and shifted so it does not land on its neighbours.

    Attributes:
        view: Which orthographic view.
        horizontal: Vehicle axis mapped to the sheet's X.
        vertical: Vehicle axis mapped to the sheet's Y.
        origin: Added to projected coordinates to reach sheet millimetres.
        lines: Link, ground, and centreline edges in view axes.
        circles: Node markers and tire circles in view axes.
    """

    view: View
    horizontal: Literal["x", "y", "z"]
    vertical: Literal["x", "y", "z"]
    origin: tuple[float, float]
    lines: tuple[SketchLine, ...]
    circles: tuple[SketchCircle, ...]

    def sheet(self, point: tuple[float, float]) -> tuple[float, float]:
        """Return a view-axis point in sheet millimetres."""
        return (point[0] + self.origin[0], point[1] + self.origin[1])

    def sheet_bbox(self) -> tuple[float, float, float, float]:
        """Axis-aligned bounds of the geometry on the sheet, millimetres.

        Returns:
            ``(min_x, min_y, max_x, max_y)``.

        Raises:
            ValueError: When the view has no geometry.
        """
        xs: list[float] = []
        ys: list[float] = []
        for line in self.lines:
            for point in (line.start, line.end):
                placed = self.sheet(point)
                xs.append(placed[0])
                ys.append(placed[1])
        for circle in self.circles:
            center = self.sheet(circle.center)
            xs.extend((center[0] - circle.radius, center[0] + circle.radius))
            ys.extend((center[1] - circle.radius, center[1] + circle.radius))
        if not xs:
            raise ValueError(f"View {self.view.value!r} has no geometry")
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True, slots=True)
class AxleSketch:
    """The three views of one axle.

    Attributes:
        name: Design name, stamped into the DXF title.
        axle: ``"front"`` or ``"rear"``.
        notes: Title-block lines. ASCII, one line each.
        views: Front, side, and top, in that order.
    """

    name: str
    axle: str
    notes: tuple[str, ...]
    views: tuple[PlacedView, ...]

    def view(self, name: View | str) -> PlacedView:
        """Return one view by name.

        Raises:
            KeyError: When the sketch has no such view.
        """
        wanted = View(name)
        for item in self.views:
            if item.view is wanted:
                return item
        raise KeyError(wanted)


def axle_sketch(design: Design, axle: str) -> AxleSketch:
    """Project one axle into front, side, and top views.

    The other axle is not drawn. A plan view that contained both, each shifted
    onto its own wheel centre, would stack the two linkages on top of each
    other.

    Args:
        design: The design to draw. Coordinates are already ISO 8855
            millimetres on the design datum.
        axle: ``"front"`` or ``"rear"``.

    Returns:
        The three views, separated on a sheet so their geometry does not meet.

    Raises:
        ValueError: When the design has no such axle, or the axle has no
            drawable links.
    """
    axle_model = _require_axle(design, axle)
    segments = _segments(axle_model)
    if not segments:
        raise ValueError(
            f"Axle {axle!r} of design {design.name!r} has no drawable links"
        )
    raw = {
        view: _project_view(design, axle_model, segments, view, horizontal, vertical)
        for view, (horizontal, vertical) in _VIEW_AXES.items()
    }
    placed = _place(raw)
    return AxleSketch(
        name=design.name,
        axle=axle,
        notes=_notes(design, axle_model),
        views=placed,
    )


def sketch_to_dxf(sketch: AxleSketch) -> bytes:
    """Render a sketch to an R12 ASCII DXF, in millimetres.

    The file is an even number of lines and does not end with a blank line,
    which is what a strict pair reader requires. Units are ``$INSUNITS = 4``.
    """
    dxf = _Dxf()
    dxf.add(999, "fsae-workbench suspension sketch")
    dxf.add(999, f"{_ascii(sketch.name)} / {sketch.axle} axle only")
    dxf.add(999, "ISO 8855 millimetres. +X forward, +Y left, +Z up.")
    dxf.add(
        999,
        "One axle per file. The other axle is a separate drawing; "
        "the two collide if overlaid in plan.",
    )
    dxf.add(999, "FRONT horizontal +Y vertical +Z. SIDE +X +Z. TOP +X +Y.")
    for note in sketch.notes:
        dxf.add(999, _ascii(note))

    extents = _sheet_extents(sketch)
    dxf.add(0, "SECTION")
    dxf.add(2, "HEADER")
    dxf.add(9, "$ACADVER")
    dxf.add(1, "AC1009")
    dxf.add(9, "$INSUNITS")
    dxf.add(70, "4")
    dxf.add(9, "$EXTMIN")
    dxf.add_float(10, extents[0])
    dxf.add_float(20, extents[1])
    dxf.add_float(30, 0.0)
    dxf.add(9, "$EXTMAX")
    dxf.add_float(10, extents[2])
    dxf.add_float(20, extents[3])
    dxf.add_float(30, 0.0)
    dxf.add(0, "ENDSEC")

    layers = _layers(sketch)
    dxf.add(0, "SECTION")
    dxf.add(2, "TABLES")
    dxf.add(0, "TABLE")
    dxf.add(2, "LAYER")
    dxf.add(70, str(len(layers)))
    for name in layers:
        dxf.add(0, "LAYER")
        dxf.add(2, name)
        dxf.add(70, "0")
        dxf.add(62, str(_LAYER_COLOR.get(name, 7)))
        dxf.add(6, "CONTINUOUS")
    dxf.add(0, "ENDTAB")
    dxf.add(0, "ENDSEC")

    dxf.add(0, "SECTION")
    dxf.add(2, "ENTITIES")
    for view in sketch.views:
        for line in view.lines:
            start = view.sheet(line.start)
            end = view.sheet(line.end)
            _emit_line(dxf, line.layer, start, end)
        for circle in view.circles:
            _emit_circle(dxf, circle.layer, view.sheet(circle.center), circle.radius)
        title_x, _, _, title_top = view.sheet_bbox()
        _emit_text(
            dxf,
            title_x,
            title_top + 16.0,
            10.0,
            _view_title(view),
        )
    header_y = extents[3] - 8.0
    for index, note in enumerate(sketch.notes):
        _emit_text(dxf, extents[0], header_y - index * 14.0, 8.0, note)
    dxf.add(0, "ENDSEC")
    dxf.add(0, "EOF")
    return dxf.bytes()


def write_axle_dxfs(design: Design, directory: str | Path) -> dict[str, Path]:
    """Write one DXF per axle. Front and rear never share a file.

    Args:
        design: The design to draw.
        directory: Created if it does not exist. Files are named
            ``{design}-{axle}.dxf``.

    Returns:
        Mapping of axle id to the path written.
    """
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for axle_id in design.axles:
        sketch = axle_sketch(design, axle_id)
        path = folder / f"{_slug(design.name)}-{axle_id}.dxf"
        path.write_bytes(sketch_to_dxf(sketch))
        written[axle_id] = path
    return written


def _require_axle(design: Design, axle: str) -> Axle:
    """Return one axle, or raise a readable error naming the ones that exist."""
    try:
        return design.axles[axle]
    except KeyError:
        raise ValueError(
            f"Design {design.name!r} has no {axle!r} axle; "
            f"available: {sorted(design.axles)}"
        ) from None


def _notes(design: Design, axle_model: Axle) -> tuple[str, ...]:
    """Title-block lines for one axle."""
    left = axle_model.left
    right = axle_model.right
    if right is not None and right.actuation != left.actuation:
        actuation = f"Actuation: {left.actuation} (left), {right.actuation} (right)"
    else:
        actuation = f"Actuation: {left.actuation}"
    return (
        f"{design.name} - {axle_model.id} axle",
        "ISO 8855 mm. +X forward, +Y left, +Z up.",
        f"{axle_model.id} axle only. The other axle is a separate drawing.",
        actuation,
        f"Steering: {axle_model.steering}",
    )


def _segments(axle_model: Axle) -> list[_Segment]:
    """Link edges of every present corner. An absent node drops its link."""
    segments: list[_Segment] = []
    for corner in axle_model.corners:
        segments.extend(_corner_segments(corner))
    return segments


def _corner_segments(corner: Corner) -> list[_Segment]:
    """Link edges of one corner, in vehicle coordinates."""
    segments: list[_Segment] = []
    for link in _LINKS:
        if not all(node_id in corner.nodes for node_id in link.nodes):
            continue
        points = [corner.position(node_id) for node_id in link.nodes]
        pairs = list(pairwise(points))
        if link.closed and len(points) >= 2:
            pairs.append((points[-1], points[0]))
        segments.extend(_Segment(link.layer, start, end) for start, end in pairs)
    return segments


def _project_view(
    design: Design,
    axle_model: Axle,
    segments: list[_Segment],
    view: View,
    horizontal: Literal["x", "y", "z"],
    vertical: Literal["x", "y", "z"],
) -> tuple[tuple[SketchLine, ...], tuple[SketchCircle, ...]]:
    """Project link edges into one view and add the datum furniture."""
    lines: list[SketchLine] = []
    for segment in segments:
        start = _project(segment.start, horizontal, vertical)
        end = _project(segment.end, horizontal, vertical)
        if math.hypot(end[0] - start[0], end[1] - start[1]) < _MIN_SEGMENT_MM:
            continue
        lines.append(SketchLine(segment.layer, start, end))
    if not lines:
        raise ValueError(
            f"Axle {axle_model.id!r} projects to nothing in the {view.value} view"
        )
    circles = _node_circles(lines)
    tire_lines, tire_circles = _tire_marks(
        design, axle_model, view, horizontal, vertical
    )
    lines.extend(tire_lines)
    circles.extend(tire_circles)
    _add_datum(lines, view)
    return (tuple(lines), tuple(circles))


def _project(
    position: tuple[float, float, float],
    horizontal: str,
    vertical: str,
) -> tuple[float, float]:
    """Map a vehicle point onto a view's horizontal and vertical axes."""
    return (position[_AXIS[horizontal]], position[_AXIS[vertical]])


def _node_circles(lines: list[SketchLine]) -> list[SketchCircle]:
    """One small circle at each distinct link vertex."""
    points: dict[tuple[float, float], None] = {}
    for line in lines:
        points.setdefault(line.start, None)
        points.setdefault(line.end, None)
    return [SketchCircle("NODES", point, _NODE_RADIUS_MM) for point in points]


def _tire_marks(
    design: Design,
    axle_model: Axle,
    view: View,
    horizontal: str,
    vertical: str,
) -> tuple[list[SketchLine], list[SketchCircle]]:
    """Tire outline in this view.

    Front and side views see the tire as a circle of the kinematic radius.
    The top view sees a line across the section width, through the wheel
    centre. A circle in plan would be the wrong shape.
    """
    lines: list[SketchLine] = []
    circles: list[SketchCircle] = []
    half_width = design.tire.section_width_mm / 2.0
    radius = design.tire.kinematic_radius_mm
    for corner in axle_model.corners:
        if "wheel_center" not in corner.nodes:
            continue
        center = _project(corner.position("wheel_center"), horizontal, vertical)
        if view is View.TOP:
            lines.append(
                SketchLine(
                    "TIRE",
                    (center[0], center[1] - half_width),
                    (center[0], center[1] + half_width),
                )
            )
        else:
            circles.append(SketchCircle("TIRE", center, radius))
    return lines, circles


def _add_datum(lines: list[SketchLine], view: View) -> None:
    """Ground line and centreline, spanning the linkage already projected."""
    xs = [point[0] for line in lines for point in (line.start, line.end)]
    ys = [point[1] for line in lines for point in (line.start, line.end)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if view in (View.FRONT, View.SIDE):
        lines.append(
            SketchLine(
                "GROUND",
                (min_x - _GROUND_PAD_MM, 0.0),
                (max_x + _GROUND_PAD_MM, 0.0),
            )
        )
    if view is View.FRONT:
        lines.append(SketchLine("CENTRELINE", (0.0, min_y), (0.0, max_y)))
    if view is View.TOP:
        lines.append(SketchLine("CENTRELINE", (min_x, 0.0), (max_x, 0.0)))


def _place(
    raw: dict[View, tuple[tuple[SketchLine, ...], tuple[SketchCircle, ...]]],
) -> tuple[PlacedView, ...]:
    """Shift the three views apart. Front sits low-left, side to its right, top above.

    The gap is large enough for a view title and, by construction, the three
    geometry boxes cannot meet: side is a gap to the right of front, and top
    is a gap above the taller of front and side.
    """
    boxes = {view: _raw_bbox(lines, circles) for view, (lines, circles) in raw.items()}
    front_box = boxes[View.FRONT]
    side_box = boxes[View.SIDE]
    top_box = boxes[View.TOP]
    front_width = front_box[2] - front_box[0]
    front_height = front_box[3] - front_box[1]
    side_height = side_box[3] - side_box[1]
    row_height = max(front_height, side_height)
    origins = {
        View.FRONT: _shift(front_box, _MARGIN_MM, _MARGIN_MM),
        View.SIDE: _shift(side_box, _MARGIN_MM + front_width + _GAP_MM, _MARGIN_MM),
        View.TOP: _shift(top_box, _MARGIN_MM, _MARGIN_MM + row_height + _GAP_MM),
    }
    placed: list[PlacedView] = []
    for view in (View.FRONT, View.SIDE, View.TOP):
        horizontal, vertical = _VIEW_AXES[view]
        lines, circles = raw[view]
        placed.append(
            PlacedView(
                view=view,
                horizontal=horizontal,
                vertical=vertical,
                origin=origins[view],
                lines=lines,
                circles=circles,
            )
        )
    return tuple(placed)


def _raw_bbox(
    lines: tuple[SketchLine, ...], circles: tuple[SketchCircle, ...]
) -> tuple[float, float, float, float]:
    """Bounds of projected geometry, before the sheet origin is applied."""
    xs: list[float] = []
    ys: list[float] = []
    for line in lines:
        xs.extend((line.start[0], line.end[0]))
        ys.extend((line.start[1], line.end[1]))
    for circle in circles:
        xs.extend((circle.center[0] - circle.radius, circle.center[0] + circle.radius))
        ys.extend((circle.center[1] - circle.radius, circle.center[1] + circle.radius))
    return (min(xs), min(ys), max(xs), max(ys))


def _shift(
    box: tuple[float, float, float, float], target_x: float, target_y: float
) -> tuple[float, float]:
    """Origin that moves a box's minimum corner to ``(target_x, target_y)``."""
    return (target_x - box[0], target_y - box[1])


def _view_title(view: PlacedView) -> str:
    """One-line description of a view's axes, stamped above the view."""
    return (
        f"{view.view.value} view: horizontal +{view.horizontal}, "
        f"vertical +{view.vertical}"
    )


def _layers(sketch: AxleSketch) -> tuple[str, ...]:
    """Layer names the file declares, layer 0 first, then the ones in use."""
    used = {"0", "ANNOTATION"}
    for view in sketch.views:
        used.update(line.layer for line in view.lines)
        used.update(circle.layer for circle in view.circles)
    ordered = ["0", *sorted(name for name in used if name != "0")]
    return tuple(ordered)


def _sheet_extents(sketch: AxleSketch) -> tuple[float, float, float, float]:
    """Sheet bounds covering geometry and the title block above it."""
    boxes = [view.sheet_bbox() for view in sketch.views]
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    # View titles sit 16 mm above each box and are 10 mm tall. The title block
    # is a further stack above the global top.
    title_top = max_y + 16.0 + 10.0
    header_top = title_top + 20.0 + 14.0 * len(sketch.notes)
    text_width = max((len(note) * 8.0 * 0.6 for note in sketch.notes), default=0.0)
    return (min_x, min_y, max(max_x, min_x + text_width), header_top)


def _slug(name: str) -> str:
    """A filename stem from a design name."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "design"


def _ascii(text: str) -> str:
    """DXF text is 7-bit. Newlines would split a group-code pair."""
    flat = text.replace("\n", " ").replace("\r", " ")
    return flat.encode("ascii", errors="replace").decode("ascii")


class _Dxf:
    """An R12 group-code stream. Codes are right-justified in three columns."""

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str]] = []

    def add(self, code: int, value: str) -> None:
        """Append one group-code pair."""
        self._pairs.append((f"{code:3d}", value))

    def add_float(self, code: int, value: float) -> None:
        """Append a coordinate or scalar, in millimetres, to 0.001 µm."""
        self.add(code, f"{value:.6f}")

    def bytes(self) -> bytes:
        """Encode the stream. No trailing newline, so the line count stays even."""
        lines = [line for pair in self._pairs for line in pair]
        return "\n".join(lines).encode("ascii")


def _emit_line(
    dxf: _Dxf, layer: str, start: tuple[float, float], end: tuple[float, float]
) -> None:
    """Write one LINE entity."""
    dxf.add(0, "LINE")
    dxf.add(8, layer)
    dxf.add_float(10, start[0])
    dxf.add_float(20, start[1])
    dxf.add_float(30, 0.0)
    dxf.add_float(11, end[0])
    dxf.add_float(21, end[1])
    dxf.add_float(31, 0.0)


def _emit_circle(
    dxf: _Dxf, layer: str, center: tuple[float, float], radius: float
) -> None:
    """Write one CIRCLE entity."""
    dxf.add(0, "CIRCLE")
    dxf.add(8, layer)
    dxf.add_float(10, center[0])
    dxf.add_float(20, center[1])
    dxf.add_float(30, 0.0)
    dxf.add_float(40, radius)


def _emit_text(dxf: _Dxf, x: float, y: float, height: float, text: str) -> None:
    """Write one TEXT entity. R12 group 1 is capped at 255 characters."""
    dxf.add(0, "TEXT")
    dxf.add(8, "ANNOTATION")
    dxf.add_float(10, x)
    dxf.add_float(20, y)
    dxf.add_float(30, 0.0)
    dxf.add_float(40, height)
    dxf.add(1, _ascii(text)[:240])

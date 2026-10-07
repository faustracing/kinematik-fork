"""Per-axle DXF sketches, including a round trip of the golden hardpoint CSV.

The CSV is loaded through the same importer the rest of the suite uses, drawn,
and read back out of the DXF. Front and rear are separate drawings: shifting
both axles onto one plan-view origin makes their linkages overlap, which is
the collision a single whole-car top view would be.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from workbench.export.dxf import (
    View,
    axle_sketch,
    sketch_to_dxf,
    write_axle_dxfs,
)
from workbench.io import load_design

_GAP_MM = 80.0


def _pairs(data: bytes) -> list[tuple[str, str]]:
    """Split an R12 DXF into group-code pairs."""
    text = data.decode("ascii")
    lines = text.splitlines()
    assert len(lines) % 2 == 0, "a DXF is a stream of pairs"
    assert text.endswith("EOF")
    return [
        (lines[index].strip(), lines[index + 1].strip())
        for index in range(0, len(lines), 2)
    ]


def _entities(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Entities in the ENTITIES section, one dict of group code to value."""
    start = end = None
    for index, (code, value) in enumerate(pairs):
        if code == "2" and value == "ENTITIES":
            start = index + 1
        elif start is not None and code == "0" and value == "ENDSEC":
            end = index
            break
    assert start is not None and end is not None
    entities: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for code, value in pairs[start:end]:
        if code == "0":
            if current is not None:
                entities.append(current)
            current = {"type": value}
        elif current is not None:
            current[code] = value
    if current is not None:
        entities.append(current)
    return entities


def _segments(
    data: bytes,
) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    """LINE entities as ``(layer, start, end)`` in sheet millimetres."""
    segments = []
    for entity in _entities(_pairs(data)):
        if entity.get("type") != "LINE":
            continue
        segments.append(
            (
                entity["8"],
                (float(entity["10"]), float(entity["20"])),
                (float(entity["11"]), float(entity["21"])),
            )
        )
    return segments


def _has_segment(
    data: bytes, layer: str, start: tuple[float, float], end: tuple[float, float]
) -> bool:
    """True when the DXF has that line in either direction."""
    for found_layer, first, second in _segments(data):
        if found_layer != layer:
            continue
        forward = first == pytest.approx(start) and second == pytest.approx(end)
        reverse = first == pytest.approx(end) and second == pytest.approx(start)
        if forward or reverse:
            return True
    return False


def _circles(data: bytes) -> list[tuple[str, tuple[float, float], float]]:
    """CIRCLE entities as ``(layer, center, radius)``."""
    circles = []
    for entity in _entities(_pairs(data)):
        if entity.get("type") != "CIRCLE":
            continue
        circles.append(
            (
                entity["8"],
                (float(entity["10"]), float(entity["20"])),
                float(entity["40"]),
            )
        )
    return circles


def _separated(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    gap: float,
) -> bool:
    """True when two boxes are at least ``gap`` apart on one axis."""
    apart_x = first[2] + gap <= second[0] or second[2] + gap <= first[0]
    apart_y = first[3] + gap <= second[1] or second[3] + gap <= first[1]
    return apart_x or apart_y


def _csv_point(golden_csv: Path, name: str) -> tuple[float, float, float]:
    """One point straight from the golden CSV, in the file's own millimetres."""
    with golden_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["Point Name"] == name:
                return (
                    float(row["X (mm)"]),
                    float(row["Y (mm)"]),
                    float(row["Z (mm)"]),
                )
    raise AssertionError(f"{name!r} is not in {golden_csv}")


class TestGoldenRoundTrip:
    def test_a_csv_hardpoint_round_trips_through_the_front_view(self, golden_csv: Path):
        """Y is unchanged by the datum shift, so the file's own Y must come back.

        Z is shifted onto the ground plane on the way in, so the DXF is checked
        against the loaded design for Z and against the CSV bytes for Y.
        """
        file_x, file_y, _file_z = _csv_point(golden_csv, "LCA Outboard LF")
        design = load_design(golden_csv, name="golden-car")
        position = design.corner("lf").position("lca_outboard")
        assert position[1] == pytest.approx(file_y)
        assert position[0] != pytest.approx(file_x)

        sketch = axle_sketch(design, "front")
        view = sketch.view(View.FRONT)
        projected = (position[1], position[2])
        assert any(
            line.start == pytest.approx(projected)
            or line.end == pytest.approx(projected)
            for line in view.lines
            if line.layer == "LOWER_WISHBONE"
        )

        data = sketch_to_dxf(sketch)
        wishbone = [
            line
            for line in view.lines
            if line.layer == "LOWER_WISHBONE"
            and (
                line.start == pytest.approx(projected)
                or line.end == pytest.approx(projected)
            )
        ]
        assert wishbone
        assert any(
            _has_segment(data, line.layer, view.sheet(line.start), view.sheet(line.end))
            for line in wishbone
        )

    def test_every_sketch_line_is_in_the_dxf(self, golden_csv: Path):
        design = load_design(golden_csv, name="golden-car")
        sketch = axle_sketch(design, "front")
        data = sketch_to_dxf(sketch)
        for view in sketch.views:
            for line in view.lines:
                assert _has_segment(
                    data, line.layer, view.sheet(line.start), view.sheet(line.end)
                ), line

    def test_the_wheel_centre_projects_on_the_named_axes(self, golden_csv: Path):
        design = load_design(golden_csv, name="golden-car")
        sketch = axle_sketch(design, "rear")
        position = design.corner("lr").position("wheel_center")
        for view in sketch.views:
            projected = (
                position["xyz".index(view.horizontal)],
                position["xyz".index(view.vertical)],
            )
            assert any(
                circle.center == pytest.approx(projected) and circle.layer == "NODES"
                for circle in view.circles
            )

    def test_front_keeps_the_tie_rod_and_rear_keeps_the_toe_link(self, golden_design):
        front_layers = {
            line.layer
            for view in axle_sketch(golden_design, "front").views
            for line in view.lines
        }
        rear_layers = {
            line.layer
            for view in axle_sketch(golden_design, "rear").views
            for line in view.lines
        }
        assert "TIE_ROD" in front_layers
        assert "TOE_LINK" not in front_layers
        assert "TOE_LINK" in rear_layers
        assert "TIE_ROD" not in rear_layers
        assert {
            "UPPER_WISHBONE",
            "LOWER_WISHBONE",
            "ACTUATION",
            "WHEEL",
        } <= front_layers
        assert {"UPPER_WISHBONE", "LOWER_WISHBONE", "ACTUATION", "WHEEL"} <= rear_layers


class TestPerAxle:
    def test_the_two_axles_are_a_wheelbase_apart_in_plan(self, golden_design):
        """Collapsing each axle onto x = 0 would drop this difference to zero."""
        front = axle_sketch(golden_design, "front").view(View.TOP)
        rear = axle_sketch(golden_design, "rear").view(View.TOP)
        front_x = golden_design.corner("lf").position("wheel_center")[0]
        rear_x = golden_design.corner("lr").position("wheel_center")[0]
        assert any(
            circle.center[0] == pytest.approx(front_x) for circle in front.circles
        )
        assert any(circle.center[0] == pytest.approx(rear_x) for circle in rear.circles)
        assert front_x - rear_x == pytest.approx(golden_design.vehicle.wheelbase_mm)

    def test_normalising_both_axles_onto_one_origin_makes_them_overlap(
        self, golden_design
    ):
        """The plan-view collision the exporter refuses to draw."""

        def local_span(axle_id: str) -> tuple[float, float]:
            corner = "lf" if axle_id == "front" else "lr"
            origin = golden_design.corner(corner).position("wheel_center")[0]
            view = axle_sketch(golden_design, axle_id).view(View.TOP)
            xs = [
                point[0] - origin
                for line in view.lines
                if line.layer not in {"CENTRELINE", "GROUND"}
                for point in (line.start, line.end)
            ]
            return min(xs), max(xs)

        front = local_span("front")
        rear = local_span("rear")
        assert front[0] < rear[1] and rear[0] < front[1]

    def test_the_front_drawing_does_not_contain_the_rear_wheel(self, golden_design):
        sketch = axle_sketch(golden_design, "front")
        rear_x = golden_design.corner("lr").position("wheel_center")[0]
        side = sketch.view(View.SIDE)
        xs = [point[0] for line in side.lines for point in (line.start, line.end)]
        assert rear_x < min(xs)

    def test_each_axle_is_its_own_file(self, golden_design, tmp_path: Path):
        paths = write_axle_dxfs(golden_design, tmp_path)
        assert set(paths) == {"front", "rear"}
        front = paths["front"].read_bytes()
        rear = paths["rear"].read_bytes()
        assert b"front axle only" in front
        assert b"rear axle only" not in front
        assert b"rear axle only" in rear
        assert b"front axle only" not in rear
        assert paths["front"].suffix == ".dxf"
        assert paths["front"] != paths["rear"]

    def test_the_three_views_do_not_land_on_each_other(self, golden_design):
        sketch = axle_sketch(golden_design, "front")
        boxes = [view.sheet_bbox() for view in sketch.views]
        assert len(boxes) == 3
        for index, box in enumerate(boxes):
            for other in boxes[index + 1 :]:
                assert _separated(box, other, _GAP_MM)

    def test_an_axle_with_no_right_corner_does_not_invent_one(self, golden_design):
        right_y = golden_design.corner("rf").position("wheel_center")[1]
        front = golden_design.axles["front"].model_copy(update={"right": None})
        design = golden_design.model_copy(
            update={"axles": {"front": front, "rear": golden_design.axles["rear"]}}
        )
        view = axle_sketch(design, "front").view(View.FRONT)
        horizontals = [
            point[0] for line in view.lines for point in (line.start, line.end)
        ]
        assert right_y < 0.0
        assert not any(value == pytest.approx(right_y) for value in horizontals)

    def test_an_unknown_axle_names_the_ones_that_exist(self, golden_design):
        with pytest.raises(ValueError, match="no 'middle' axle"):
            axle_sketch(golden_design, "middle")


class TestDxfFile:
    def test_the_file_is_ascii_r12_millimetres_and_balanced(self, golden_design):
        data = sketch_to_dxf(axle_sketch(golden_design, "front"))
        data.decode("ascii")
        pairs = _pairs(data)
        assert pairs[-1] == ("0", "EOF")
        assert sum(value == "SECTION" for code, value in pairs if code == "0") == 3
        assert sum(value == "ENDSEC" for code, value in pairs if code == "0") == 3
        units = next(
            pairs[index + 1]
            for index, (code, value) in enumerate(pairs)
            if code == "9" and value == "$INSUNITS"
        )
        assert units == ("70", "4")
        assert any(code == "1" and value == "AC1009" for code, value in pairs)

    def test_every_entity_layer_is_declared(self, golden_design):
        data = sketch_to_dxf(axle_sketch(golden_design, "rear"))
        pairs = _pairs(data)
        declared = {
            value
            for index, (code, value) in enumerate(pairs)
            if code == "2" and index > 0 and pairs[index - 1] == ("0", "LAYER")
        }
        for entity in _entities(pairs):
            if "8" in entity:
                assert entity["8"] in declared

    def test_the_front_view_tire_is_a_circle_and_the_plan_view_is_a_line(
        self, golden_design
    ):
        sketch = axle_sketch(golden_design, "front")
        data = sketch_to_dxf(sketch)
        radius = golden_design.tire.kinematic_radius_mm
        front = sketch.view(View.FRONT)
        wheel = golden_design.corner("lf").position("wheel_center")
        center = front.sheet((wheel[1], wheel[2]))
        assert any(
            layer == "TIRE"
            and found == pytest.approx(center)
            and found_radius == pytest.approx(radius)
            for layer, found, found_radius in _circles(data)
        )
        top = sketch.view(View.TOP)
        assert any(line.layer == "TIRE" for line in top.lines)
        assert not any(
            circle.layer == "TIRE" and circle.radius == pytest.approx(radius)
            for circle in top.circles
        )

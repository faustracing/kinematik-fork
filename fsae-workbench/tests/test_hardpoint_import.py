"""The general hardpoint importer: OptimumK, Excel, and loose CSV layouts."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
import pytest
from workbench.io import load_design as load_canonical_csv
from workbench.io.hardpoint_csv import HardpointCsvError
from workbench.io.hardpoint_import import (
    HardpointImportError,
    ImportReport,
    RawPoint,
    import_design,
    import_points,
    infer_unit,
    parse_rows,
    read_table,
    resolve_corner,
    resolve_node_id,
)


def _golden_rows(golden_csv: Path) -> list[dict[str, str]]:
    with golden_csv.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    *,
    header: tuple[str, str, str, str] = ("Point Name", "X (mm)", "Y (mm)", "Z (mm)"),
    delimiter: str = ",",
    preamble: list[str] | None = None,
    scale: float = 1.0,
    flip_xy: bool = False,
) -> Path:
    """Re-emit the golden rows in some other file's house style."""
    lines = list(preamble or [])
    lines.append(delimiter.join(header))
    for row in rows:
        x = float(row["X (mm)"]) * scale * (-1.0 if flip_xy else 1.0)
        y = float(row["Y (mm)"]) * scale * (-1.0 if flip_xy else 1.0)
        z = float(row["Z (mm)"]) * scale
        lines.append(
            delimiter.join([row["Point Name"], f"{x:.6f}", f"{y:.6f}", f"{z:.6f}"])
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _positions(design) -> dict[str, tuple[float, float, float]]:
    return {
        f"{corner.id}.{node_id}": node.position
        for axle in design.axles.values()
        for corner in axle.corners
        for node_id, node in corner.nodes.items()
    }


class TestCornerResolution:
    @pytest.mark.parametrize(
        ("label", "corner"),
        [
            ("LF", "lf"),
            ("FL", "lf"),
            ("Front Left", "lf"),
            ("left front", "lf"),
            ("RF", "rf"),
            ("FR", "rf"),
            ("LR", "lr"),
            ("RL", "lr"),
            ("RR", "rr"),
            ("rear right", "rr"),
        ],
    )
    def test_both_orderings_of_every_corner_label_resolve(self, label, corner):
        assert resolve_corner(f"Wheel Center {label}")[0] == corner

    def test_the_corner_label_is_stripped_from_the_point_name(self):
        assert resolve_corner("Front Left UCA Fore Inboard")[1] == "UCA Fore Inboard"

    def test_an_unlabelled_point_resolves_to_no_corner(self):
        corner, remainder, matched = resolve_corner("Wheel Center")
        assert corner is None
        assert matched == ()
        assert remainder == "Wheel Center"

    def test_a_name_claiming_two_corners_is_refused(self):
        corner, _, matched = resolve_corner("LF RR Wheel Center")
        assert corner is None
        assert set(matched) == {"lf", "rr"}

    def test_fore_and_aft_words_are_not_mistaken_for_corner_labels(self):
        """'Rear' alone describes a pickup; 'rear left' describes a corner."""
        corner, remainder, _ = resolve_corner("UCA Rear Inboard LR")
        assert corner == "lr"
        assert remainder == "UCA Rear Inboard"


class TestNodeResolution:
    @pytest.mark.parametrize(
        ("name", "node_id"),
        [
            ("LCA Aft Inboard", "lca_aft_inboard"),
            ("Upper Front Inner", "uca_fore_inboard"),
            ("UCA Rear Inboard", "uca_aft_inboard"),
            ("Lower Ball Joint", "lca_outboard"),
            ("Upper Outer", "uca_outboard"),
            ("Tie Rod Outer", "tie_rod_outboard"),
            ("Track Rod Inner", "tie_rod_inboard"),
            ("Steering Rack Inner", "tie_rod_inboard"),
            ("Toe Link Inboard", "toe_link_inboard"),
            ("Wheel Center", "wheel_center"),
            ("WC", "wheel_center"),
            ("Contact Patch", "contact_patch"),
            ("Pullrod Outboard", "pushrod_outboard"),
            ("Rocker Pullrod", "rocker_pushrod"),
            ("Bellcrank Pivot", "rocker_pivot"),
            ("Rocker Damper", "rocker_damper"),
            ("Spring Inboard", "damper_inboard"),
        ],
    )
    def test_names_no_file_in_this_project_uses_still_resolve(self, name, node_id):
        assert resolve_node_id(name)[0] == node_id

    def test_a_tie_rod_is_not_confused_with_a_toe_link(self):
        """Both carry 'rod'/'toe' vocabulary; the two are different members."""
        assert resolve_node_id("Tie Rod Inner")[0] == "tie_rod_inboard"
        assert resolve_node_id("Toe Link Inner")[0] == "toe_link_inboard"

    def test_an_underspecified_wishbone_pickup_is_ambiguous(self):
        """'UCA Inboard' does not say fore or aft, and guessing mirrors an arm."""
        node_id, candidates = resolve_node_id("UCA Inboard")
        assert node_id is None
        assert set(candidates) == {"uca_fore_inboard", "uca_aft_inboard"}

    def test_a_body_name_is_not_a_hardpoint(self):
        assert resolve_node_id("Upright")[0] is None

    def test_an_architecture_the_bridge_cannot_solve_is_not_recognised(self):
        """MacPherson and multi-link points would load into an unsolvable design."""
        assert resolve_node_id("Strut Top")[0] is None
        assert resolve_node_id("Link 3 Inner")[0] is None


class TestUnitInference:
    def test_a_declared_unit_wins(self):
        points = [RawPoint("p", (1.0, 2.0, 3.0))]
        unit, basis = infer_unit(points, "in")
        assert unit == "in"
        assert "column headers" in basis

    @pytest.mark.parametrize(
        ("scale", "unit"),
        [(1.0, "mm"), (1.0 / 25.4, "in"), (1.0 / 1000.0, "m")],
    )
    def test_a_car_sized_span_identifies_the_unit(self, golden_csv, scale, unit):
        rows = _golden_rows(golden_csv)
        points = [
            RawPoint(
                row["Point Name"],
                (
                    float(row["X (mm)"]) * scale,
                    float(row["Y (mm)"]) * scale,
                    float(row["Z (mm)"]) * scale,
                ),
            )
            for row in rows
        ]
        assert infer_unit(points)[0] == unit

    def test_the_inference_does_not_depend_on_where_the_origin_is(self, golden_csv):
        """A magnitude heuristic reads a far-off CAD origin as a unit change."""
        rows = _golden_rows(golden_csv)
        shifted = [
            RawPoint(
                row["Point Name"],
                (
                    float(row["X (mm)"]) / 1000.0 + 50.0,
                    float(row["Y (mm)"]) / 1000.0,
                    float(row["Z (mm)"]) / 1000.0,
                ),
            )
            for row in rows
        ]
        assert infer_unit(shifted)[0] == "m"

    def test_an_unknown_unit_override_is_rejected(self, golden_csv):
        with pytest.raises(HardpointImportError, match="Unknown unit"):
            import_points(golden_csv, unit="furlongs")


class TestLayoutTolerance:
    def test_the_canonical_csv_imports_through_the_general_path(self, golden_csv):
        report = import_points(golden_csv)
        assert len(report.points) == 60
        assert report.corners == ("lf", "rf", "lr", "rr")
        assert report.issues == ()
        assert report.unit == "mm"

    def test_a_title_block_above_the_table_is_skipped(self, golden_csv, tmp_path):
        path = _write_csv(
            tmp_path / "titled.csv",
            _golden_rows(golden_csv),
            preamble=["Team Car 2026 hardpoint export", "generated 2026-10-07", ""],
        )
        assert len(import_points(path).points) == 60

    def test_a_semicolon_delimited_export_is_read(self, golden_csv, tmp_path):
        path = _write_csv(
            tmp_path / "euro.csv", _golden_rows(golden_csv), delimiter=";"
        )
        assert len(import_points(path).points) == 60

    def test_columns_in_another_order_are_read_by_header(self, golden_csv, tmp_path):
        rows = _golden_rows(golden_csv)
        lines = ["Z [mm],Y [mm],Name,X [mm]"]
        lines += [
            f"{row['Z (mm)']},{row['Y (mm)']},{row['Point Name']},{row['X (mm)']}"
            for row in rows
        ]
        path = tmp_path / "reordered.csv"
        path.write_text("\n".join(lines) + "\n")
        report = import_points(path)
        assert len(report.points) == 60
        assert report.unit_basis == "declared in the file's column headers"

    def test_a_headerless_table_is_read_positionally(self, golden_csv, tmp_path):
        rows = _golden_rows(golden_csv)
        lines = [
            f"{row['Point Name']},{row['X (mm)']},{row['Y (mm)']},{row['Z (mm)']}"
            for row in rows
        ]
        path = tmp_path / "headerless.csv"
        path.write_text("\n".join(lines) + "\n")
        assert len(import_points(path).points) == 60

    def test_a_file_with_no_point_table_is_rejected(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("just some prose\nand more prose\n")
        with pytest.raises(HardpointImportError, match="No point table"):
            import_points(path)

    def test_a_missing_file_is_named_in_the_error(self, tmp_path):
        with pytest.raises(HardpointImportError, match="No such hardpoint file"):
            import_points(tmp_path / "absent.csv")

    def test_blank_rows_end_a_table_so_a_second_one_is_found(self, tmp_path):
        text = "\n".join(
            [
                "Point Name,X (mm),Y (mm),Z (mm)",
                "Wheel Center LF,774.7,584.2,223.52",
                "",
                "Point Name,X (mm),Y (mm),Z (mm)",
                "Wheel Center RF,774.7,-584.2,223.52",
            ]
        )
        path = tmp_path / "two-tables.csv"
        path.write_text(text + "\n")
        report = import_points(path)
        assert set(report.points) == {"lf.wheel_center", "rf.wheel_center"}


class TestExcel:
    def test_a_workbook_imports_the_same_points_as_the_csv(self, golden_csv, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Hardpoints"
        sheet.append(["Point Name", "X (mm)", "Y (mm)", "Z (mm)"])
        for row in _golden_rows(golden_csv):
            sheet.append(
                [
                    row["Point Name"],
                    float(row["X (mm)"]),
                    float(row["Y (mm)"]),
                    float(row["Z (mm)"]),
                ]
            )
        path = tmp_path / "car.xlsx"
        workbook.save(path)

        report = import_points(path)
        assert len(report.points) == 60
        assert report.sheets == ("Hardpoints",)
        csv_report = import_points(golden_csv)
        for key, value in csv_report.points.items():
            assert report.points[key] == pytest.approx(value)

    def test_a_workbook_is_detected_from_its_bytes_without_a_name(
        self, golden_csv, tmp_path
    ):
        pytest.importorskip("openpyxl")
        openpyxl = pytest.importorskip("openpyxl")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Point Name", "X (mm)", "Y (mm)", "Z (mm)"])
        sheet.append(["Wheel Center LF", 774.7, 584.2, 223.52])
        buffer = io.BytesIO()
        workbook.save(buffer)
        assert set(import_points(buffer.getvalue()).points) == {"lf.wheel_center"}


class TestRefusals:
    def test_an_ambiguous_name_is_reported_and_left_unmapped(
        self, golden_csv, tmp_path
    ):
        rows = _golden_rows(golden_csv)
        for row in rows:
            if row["Point Name"] == "UCA Fore Inboard LF":
                row["Point Name"] = "UCA Inboard LF"
        path = _write_csv(tmp_path / "ambiguous.csv", rows)
        report = import_points(path)
        assert "lf.uca_fore_inboard" not in report.points
        ambiguous = [i for i in report.issues if i.kind == "ambiguous"]
        assert len(ambiguous) == 1
        assert set(ambiguous[0].candidates) == {
            "uca_fore_inboard",
            "uca_aft_inboard",
        }
        assert "guessed at" in ambiguous[0].message

    def test_two_rows_claiming_one_hardpoint_are_both_refused(
        self, golden_csv, tmp_path
    ):
        rows = _golden_rows(golden_csv)
        duplicate = dict(rows[0])
        duplicate["Point Name"] = "Lower Aft Inboard LF"
        rows.append(duplicate)
        path = _write_csv(tmp_path / "duplicate.csv", rows)
        report = import_points(path)
        assert "lf.lca_aft_inboard" not in report.points
        duplicates = [i for i in report.issues if i.kind == "duplicate"]
        assert len(duplicates) == 2
        assert "rows claim lf.lca_aft_inboard" in duplicates[0].message

    def test_an_unrecognised_name_is_reported_with_its_location(self, tmp_path):
        path = tmp_path / "odd.csv"
        path.write_text("Point Name,X (mm),Y (mm),Z (mm)\nGearbox Mount LF,10,20,30\n")
        report = import_points(path)
        issue = report.issues[0]
        assert issue.kind == "unrecognised"
        assert "row 2" in issue.message

    def test_a_point_with_no_corner_label_is_reported_not_guessed(self, tmp_path):
        path = tmp_path / "unlabelled.csv"
        path.write_text("Point Name,X (mm),Y (mm),Z (mm)\nWheel Center,10,20,30\n")
        issue = import_points(path).issues[0]
        assert issue.candidates == ("wheel_center",)
        assert "names no corner" in issue.message

    def test_a_single_corner_file_is_not_mirrored_into_a_car(self, tmp_path):
        """KinematiK reflected a left corner to its one-corner editor."""
        path = tmp_path / "one-corner.csv"
        path.write_text(
            "Point Name,X (mm),Y (mm),Z (mm)\nWheel Center LF,774.7,584.2,223.52\n"
        )
        with pytest.raises(HardpointImportError, match="all four"):
            import_design(path)

    def test_a_contradictory_frame_is_rejected(self, golden_csv, tmp_path):
        """Reuses `verify_frame`, so a half-converted file cannot slip through."""
        rows = _golden_rows(golden_csv)
        for row in rows:  # negate X only: front/rear flips, left/right does not
            row["X (mm)"] = str(-float(row["X (mm)"]))
        path = _write_csv(tmp_path / "half-flipped.csv", rows)
        with pytest.raises(HardpointCsvError, match="self-contradictory"):
            import_design(path)


class TestDesignEquivalence:
    def test_the_golden_csv_round_trips_to_the_same_design(self, golden_csv):
        """The general path and the canonical path must not drift apart."""
        general, report = import_design(golden_csv, name="golden-car")
        canonical = load_canonical_csv(golden_csv, name="golden-car")
        assert general.fingerprint() == canonical.fingerprint()
        assert report.issues == ()

    def test_the_round_trip_preserves_the_measured_vehicle_dimensions(self, golden_csv):
        design, _ = import_design(golden_csv)
        assert design.vehicle.wheelbase_mm == pytest.approx(1549.4)
        assert design.vehicle.front_track_mm == pytest.approx(1168.4)
        assert design.vehicle.rear_track_mm == pytest.approx(1143.0)
        assert design.tire.loaded_radius_mm == pytest.approx(223.52)

    def test_a_file_in_sae_axes_converts_to_the_same_design(self, golden_csv, tmp_path):
        """No new sign-flipping logic: `frames.sae_to_iso` does it, as detected."""
        path = _write_csv(
            tmp_path / "sae.csv",
            _golden_rows(golden_csv),
            flip_xy=True,
        )
        design, _ = import_design(path, name="golden-car")
        canonical = load_canonical_csv(golden_csv, name="golden-car")
        assert design.fingerprint() == canonical.fingerprint()
        assert design.provenance["source_frame"] == "sae"

    def test_an_imperial_file_lands_on_the_same_geometry(self, golden_csv, tmp_path):
        path = _write_csv(
            tmp_path / "inches.csv",
            _golden_rows(golden_csv),
            header=("Point Name", "X", "Y", "Z"),
            scale=1.0 / 25.4,
        )
        design, report = import_design(path, name="golden-car")
        assert report.unit == "in"
        canonical = load_canonical_csv(golden_csv, name="golden-car")
        imported = _positions(design)
        for key, expected in _positions(canonical).items():
            assert imported[key] == pytest.approx(expected, abs=1e-3), key

    def test_the_provenance_records_how_the_units_were_decided(
        self, golden_csv, tmp_path
    ):
        path = _write_csv(
            tmp_path / "inches.csv",
            _golden_rows(golden_csv),
            header=("Point Name", "X", "Y", "Z"),
            scale=1.0 / 25.4,
        )
        design, _ = import_design(path)
        assert design.provenance["source_unit"] == "in"
        assert "inches" in design.provenance["source_unit_basis"]
        assert design.provenance["import_issues"] == []

    def test_an_imported_design_solves(self, golden_csv, solver):
        from workbench.solve import solve

        design, _ = import_design(golden_csv, name="golden-car")
        result = solve(design, "front", "bump", steps=11)
        assert result.converged

    def test_a_design_imported_from_bytes_names_its_source(self, golden_csv):
        design, _ = import_design(
            golden_csv.read_bytes(), filename="car.csv", name="from-bytes"
        )
        assert design.provenance["source_file"] == "car.csv"


class TestReportSummary:
    def test_the_summary_names_the_corners_and_the_unit_basis(self, golden_csv):
        summary = import_points(golden_csv).summary()
        assert "60 points mapped" in summary
        assert "corners: lf, rf, lr, rr" in summary
        assert "units: mm" in summary

    def test_the_summary_counts_every_kind_of_refusal(self, tmp_path):
        path = tmp_path / "messy.csv"
        path.write_text(
            "Point Name,X (mm),Y (mm),Z (mm)\n"
            "Gearbox Mount LF,10,20,30\n"
            "UCA Inboard LF,10,20,30\n"
        )
        summary = import_points(path).summary()
        assert "1 unrecognised" in summary
        assert "1 ambiguous" in summary

    def test_rows_read_counts_data_rows_not_mapped_points(self, tmp_path):
        path = tmp_path / "messy.csv"
        path.write_text(
            "Point Name,X (mm),Y (mm),Z (mm)\n"
            "Gearbox Mount LF,10,20,30\n"
            "Wheel Center LF,10,20,30\n"
        )
        report = import_points(path)
        assert report.rows_read == 2
        assert len(report.points) == 1


class TestLowLevelHelpers:
    def test_read_table_keeps_row_numbers_for_error_messages(self, golden_csv):
        rows = read_table(golden_csv)
        assert rows[0][1] == 1
        assert rows[0][2][0] == "Point Name"

    def test_parse_rows_reports_a_declared_unit(self, golden_csv):
        points, unit = parse_rows(read_table(golden_csv))
        assert unit == "mm"
        assert len(points) == 60

    def test_an_import_report_is_a_plain_data_object(self):
        report = ImportReport(
            points={"lf.wheel_center": np.zeros(3)}, unit="mm", unit_basis="test"
        )
        assert report.corners == ("lf",)

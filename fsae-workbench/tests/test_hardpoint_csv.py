"""Hardpoint CSV import, and the empirical coordinate-frame check."""

from __future__ import annotations

from pathlib import Path

import pytest
from workbench.core.frames import Frame, iso_to_sae
from workbench.io.hardpoint_csv import (
    HardpointCsvError,
    load_design,
    read_points,
    verify_frame,
)

HEADER = "Point Name,X (mm),Y (mm),Z (mm)"


def _rewrite(source: Path, destination: Path, transform) -> Path:
    lines = source.read_text().strip().splitlines()
    out = [lines[0]]
    for line in lines[1:]:
        name, x, y, z = line.rsplit(",", 3)
        new = transform(name, float(x), float(y), float(z))
        if new is not None:
            out.append(f"{new[0]},{new[1]},{new[2]},{new[3]}")
    destination.write_text("\n".join(out) + "\n")
    return destination


class TestReadPoints:
    def test_reads_every_point_of_the_reference_car(self, golden_csv):
        points = read_points(golden_csv)
        assert len(points) == 60, "15 points on each of four corners"
        assert points["lf.wheel_center"] == pytest.approx([774.7, 584.2, 223.52])

    def test_normalises_point_names_to_canonical_node_ids(self, golden_csv):
        points = read_points(golden_csv)
        assert "lf.lca_aft_inboard" in points
        assert "rr.toe_link_outboard" in points

    def test_pull_rod_and_push_rod_share_one_node_id(self, golden_csv):
        """The two are one link to the kinematics; `actuation` carries the rest."""
        points = read_points(golden_csv)
        assert "lf.pushrod_outboard" in points
        assert "lr.pushrod_outboard" in points

    def test_a_missing_corner_token_is_a_readable_error(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(f"{HEADER}\nLCA Outboard,1,2,3\n")
        with pytest.raises(HardpointCsvError, match="does not end in a corner token"):
            read_points(path)

    def test_an_unknown_point_name_names_the_map_to_extend(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(f"{HEADER}\nMystery Bracket LF,1,2,3\n")
        with pytest.raises(HardpointCsvError, match="POINT_NAME_TO_NODE_ID"):
            read_points(path)

    def test_an_unparseable_coordinate_names_the_line(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(f"{HEADER}\nLCA Outboard LF,1,two,3\n")
        with pytest.raises(HardpointCsvError, match="Line 2"):
            read_points(path)

    def test_a_duplicate_point_is_rejected(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(f"{HEADER}\nLCA Outboard LF,1,2,3\nLCA Outboard LF,4,5,6\n")
        with pytest.raises(HardpointCsvError, match="duplicate point"):
            read_points(path)

    def test_a_missing_column_is_rejected(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("Point Name,X (mm),Y (mm)\nLCA Outboard LF,1,2\n")
        with pytest.raises(HardpointCsvError, match="missing the 'z \\(mm\\)' column"):
            read_points(path)


class TestFrameVerification:
    def test_the_reference_car_is_iso_8855(self, golden_csv):
        """The headline frame question, answered from the geometry.

        Four independent checks agree: the front corners are at +X, the left
        corners at +Y, the pickups the file *names* "Fore" are at +X, and the
        contact patches are below their wheel centres.
        """
        report = verify_frame(read_points(golden_csv))
        assert report.frame is Frame.ISO8855
        assert len(report.evidence) == 5

    def test_measures_the_car_from_the_file(self, golden_csv):
        report = verify_frame(read_points(golden_csv))
        assert report.front_axle_x == pytest.approx(774.7)
        assert report.ground_z == pytest.approx(0.0)
        assert report.wheelbase_mm == pytest.approx(1549.4)
        assert report.front_track_mm == pytest.approx(1168.4)
        assert report.rear_track_mm == pytest.approx(1143.0)

    def test_the_loaded_radius_confirms_the_z_datum_is_the_ground_plane(
        self, golden_csv
    ):
        """An 18 inch tire deflecting 5.08 mm is a loaded FSAE slick.

        Wheel centres sit 223.52 mm above the file's contact-patch plane
        against a 228.60 mm unloaded radius: 5.08 mm, exactly 0.200 in. A
        chassis-datum Z origin would show no such agreement.
        """
        from workbench.core.defaults import HOOSIER_18X6_R25B

        report = verify_frame(read_points(golden_csv))
        assert report.loaded_radius_mm == pytest.approx(223.52)
        deflection = HOOSIER_18X6_R25B.unloaded_radius_mm - report.loaded_radius_mm
        assert HOOSIER_18X6_R25B.unloaded_radius_mm == pytest.approx(228.6)
        assert deflection == pytest.approx(5.08, abs=1e-9)
        assert deflection == pytest.approx(0.2 * 25.4, abs=1e-9)

    def test_an_sae_file_is_detected(self, golden_csv, tmp_path):
        sae = _rewrite(
            golden_csv,
            tmp_path / "sae.csv",
            lambda name, x, y, z: (name, *iso_to_sae([x, y, z])),
        )
        assert verify_frame(read_points(sae)).frame is Frame.SAE

    def test_a_contradictory_frame_is_rejected_rather_than_guessed(
        self, golden_csv, tmp_path
    ):
        """Flipping X alone leaves the axes mutually inconsistent."""
        flipped = _rewrite(
            golden_csv,
            tmp_path / "half.csv",
            lambda name, x, y, z: (name, -x, y, z),
        )
        with pytest.raises(HardpointCsvError, match="self-contradictory"):
            verify_frame(read_points(flipped))

    def test_an_inverted_z_is_rejected(self, golden_csv, tmp_path):
        inverted = _rewrite(
            golden_csv,
            tmp_path / "zdown.csv",
            lambda name, x, y, z: (name, x, y, -z),
        )
        with pytest.raises(HardpointCsvError, match="\\+Z is not up"):
            verify_frame(read_points(inverted))

    def test_a_car_without_four_wheel_centres_cannot_be_verified(
        self, golden_csv, tmp_path
    ):
        trimmed = _rewrite(
            golden_csv,
            tmp_path / "partial.csv",
            lambda name, x, y, z: (
                None if name.startswith("Wheel Center R") else (name, x, y, z)
            ),
        )
        with pytest.raises(HardpointCsvError, match="all four wheel centres"):
            verify_frame(read_points(trimmed))


class TestLoadDesign:
    def test_builds_a_front_and_a_rear_axle(self, golden_design):
        assert sorted(golden_design.axles) == ["front", "rear"]
        for axle in golden_design.axles.values():
            assert axle.right is not None, "explicit right corner, not a Y=0 mirror"
            assert axle.architecture == "double_wishbone"

    def test_detects_steering_from_the_links_present(self, golden_design):
        assert golden_design.axles["front"].steering == "rack"
        assert golden_design.axles["rear"].steering == "none"
        assert "tie_rod_inboard" in golden_design.corner("lf").nodes
        assert "toe_link_inboard" in golden_design.corner("lr").nodes

    def test_detects_pullrod_at_the_front_and_pushrod_at_the_rear(self, golden_design):
        """Read from the geometry: a pullrod runs downhill to its rocker."""
        assert golden_design.corner("lf").actuation == "pullrod_rocker"
        assert golden_design.corner("rf").actuation == "pullrod_rocker"
        assert golden_design.corner("lr").actuation == "pushrod_rocker"
        assert golden_design.corner("rr").actuation == "pushrod_rocker"

    def test_infers_the_nearest_wishbone_as_the_pushrod_mount(self, golden_design):
        assert golden_design.corner("lf").pushrod_mount == "upper_wishbone"
        assert golden_design.corner("lr").pushrod_mount == "lower_wishbone"

    def test_marks_chassis_pickups_fixed_and_outboard_nodes_free(self, golden_design):
        corner = golden_design.corner("lf")
        assert corner.nodes["lca_fore_inboard"].fixed
        assert corner.nodes["rocker_pivot"].fixed
        assert not corner.nodes["lca_outboard"].fixed
        assert not corner.nodes["wheel_center"].fixed

    def test_shifts_the_datum_onto_the_front_axle_and_the_ground(self, golden_design):
        front = golden_design.corner("lf").position("wheel_center")
        rear = golden_design.corner("lr").position("wheel_center")
        assert front[0] == pytest.approx(0.0)
        assert front[2] == pytest.approx(223.52)
        assert rear[0] == pytest.approx(-1549.4)
        assert golden_design.corner("lf").position("contact_patch")[2] == pytest.approx(
            0.0
        )

    def test_the_datum_shift_is_a_pure_translation(self, golden_csv, golden_design):
        """Lengths must be identical with and without normalisation."""
        import numpy as np

        raw = load_design(golden_csv, normalise_datum=False)
        for corner_id in ("lf", "lr"):
            shifted = golden_design.corner(corner_id)
            original = raw.corner(corner_id)
            for node_id in shifted.nodes:
                a = np.asarray(shifted.position(node_id))
                b = np.asarray(original.position(node_id))
                reference_a = np.asarray(shifted.position("wheel_center"))
                reference_b = np.asarray(original.position("wheel_center"))
                assert np.linalg.norm(a - reference_a) == pytest.approx(
                    np.linalg.norm(b - reference_b)
                )

    def test_measures_the_loaded_radius_rather_than_assuming_it(self, golden_design):
        assert golden_design.tire.loaded_radius_mm == pytest.approx(223.52)
        assert golden_design.tire.kinematic_radius_mm == pytest.approx(223.52)
        assert golden_design.tire.unloaded_radius_mm == pytest.approx(228.6)

    def test_carries_the_real_tire_through_to_the_design(self, golden_design):
        tire = golden_design.tire
        assert tire.name == "Hoosier 18x6.0-10"
        assert tire.compound == "R25B"
        assert (tire.overall_diameter_in, tire.rim_diameter_in) == (18.0, 10.0)

    def test_records_what_was_defaulted_rather_than_measured(self, golden_design):
        provenance = golden_design.provenance
        assert provenance["source_frame"] == "iso8855"
        assert provenance["static_deflection_mm"] == pytest.approx(5.08)
        assert "spring rates" in provenance["defaulted"]
        assert "static camber and toe (wheel spin axis)" in provenance["defaulted"]

    def test_an_sae_file_loads_to_the_same_design(self, golden_csv, tmp_path):
        """Round tripping through SAE must not move the car."""
        sae = _rewrite(
            golden_csv,
            tmp_path / "sae.csv",
            lambda name, x, y, z: (name, *iso_to_sae([x, y, z])),
        )
        from_sae = load_design(sae, name="golden-car")
        from_iso = load_design(golden_csv, name="golden-car")
        assert from_sae.fingerprint() == from_iso.fingerprint()

    def test_a_corner_missing_a_wishbone_is_a_readable_error(
        self, golden_csv, tmp_path
    ):
        trimmed = _rewrite(
            golden_csv,
            tmp_path / "trimmed.csv",
            lambda name, x, y, z: (
                None if name.startswith("UCA Outboard LF") else (name, x, y, z)
            ),
        )
        with pytest.raises(HardpointCsvError, match="missing required nodes"):
            load_design(trimmed)

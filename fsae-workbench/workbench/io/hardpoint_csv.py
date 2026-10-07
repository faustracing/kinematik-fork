"""Load a four-corner hardpoint CSV into a `Design`.

The expected shape is one row per point:

    Point Name,X (mm),Y (mm),Z (mm)
    LCA Aft Inboard LF,631.469,251.028,120.599

The trailing token is the corner (`LF`, `RF`, `LR`, `RR`) and the rest is the
point name, which is normalised to the canonical snake_case node ids in
`workbench.core.design.NODE_LABELS`.

Coordinate frame
----------------
The file is read as ISO 8855 (`+X` forward, `+Y` left, `+Z` up) and verified
rather than trusted: `verify_frame` checks that the `F` corners sit forward of
the `R` corners, that the `L` corners sit on the same side as `+Y`, that the
points named "Fore" sit forward of the points named "Aft", and that the contact
patches sit below their wheel centres. A file in SAE axes fails the first three
checks, and `load_design` can convert it on request.

The file's own origin is preserved only in provenance: coordinates are shifted
onto the design datum, front axle centreline at `X = 0` and ground plane at
`Z = 0`. The shift is a pure translation, so every angle and length is
unchanged.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from workbench.core import defaults as wb_defaults
from workbench.core.design import (
    SCHEMA_VERSION,
    Axle,
    Corner,
    Design,
    Node,
    TireSpec,
    VehicleSpec,
)
from workbench.core.frames import Frame, normalise_origin, sae_to_iso

__all__ = [
    "CORNER_TOKENS",
    "POINT_NAME_TO_NODE_ID",
    "FrameReport",
    "HardpointCsvError",
    "design_from_points",
    "load_design",
    "read_points",
    "verify_frame",
]


class HardpointCsvError(ValueError):
    """Raised when a hardpoint CSV cannot be read as a four-corner car."""


CORNER_TOKENS: Final[dict[str, str]] = {
    "LF": "lf",
    "RF": "rf",
    "LR": "lr",
    "RR": "rr",
}

POINT_NAME_TO_NODE_ID: Final[dict[str, str]] = {
    "lca aft inboard": "lca_aft_inboard",
    "lca fore inboard": "lca_fore_inboard",
    "lca outboard": "lca_outboard",
    "lower aft inboard": "lca_aft_inboard",
    "lower fore inboard": "lca_fore_inboard",
    "lower outboard": "lca_outboard",
    "uca aft inboard": "uca_aft_inboard",
    "uca fore inboard": "uca_fore_inboard",
    "uca outboard": "uca_outboard",
    "upper aft inboard": "uca_aft_inboard",
    "upper fore inboard": "uca_fore_inboard",
    "upper outboard": "uca_outboard",
    "tie rod inboard": "tie_rod_inboard",
    "tie rod outboard": "tie_rod_outboard",
    "track rod inboard": "tie_rod_inboard",
    "track rod outboard": "tie_rod_outboard",
    "toe link inboard": "toe_link_inboard",
    "toe link outboard": "toe_link_outboard",
    "wheel center": "wheel_center",
    "wheel centre": "wheel_center",
    "contact patch": "contact_patch",
    "pull rod outboard": "pushrod_outboard",
    "pullrod outboard": "pushrod_outboard",
    "push rod outboard": "pushrod_outboard",
    "pushrod outboard": "pushrod_outboard",
    "rocker pull rod": "rocker_pushrod",
    "rocker pullrod": "rocker_pushrod",
    "rocker push rod": "rocker_pushrod",
    "rocker pushrod": "rocker_pushrod",
    "rocker pivot": "rocker_pivot",
    "rocker damper": "rocker_damper",
    "damper inboard": "damper_inboard",
}
"""Normalised source point names to canonical node ids.

Both "Pull Rod" and "Push Rod" land on `pushrod_*`: the two are the same link
kinematically, and the corner's `actuation` field carries the difference.
"""

_CHASSIS_NODES: Final[frozenset[str]] = frozenset(
    {
        "lca_fore_inboard",
        "lca_aft_inboard",
        "uca_fore_inboard",
        "uca_aft_inboard",
        "tie_rod_inboard",
        "toe_link_inboard",
        "rocker_pivot",
        "damper_inboard",
    }
)

_REQUIRED_NODES: Final[frozenset[str]] = frozenset(
    {
        "lca_fore_inboard",
        "lca_aft_inboard",
        "lca_outboard",
        "uca_fore_inboard",
        "uca_aft_inboard",
        "uca_outboard",
        "wheel_center",
        "contact_patch",
    }
)

_WISHBONE_BODIES: Final[dict[str, tuple[str, str, str]]] = {
    "upper_wishbone": ("uca_fore_inboard", "uca_aft_inboard", "uca_outboard"),
    "lower_wishbone": ("lca_fore_inboard", "lca_aft_inboard", "lca_outboard"),
}


@dataclass(frozen=True, slots=True)
class FrameReport:
    """Result of empirically checking a hardpoint file's coordinate frame.

    Attributes:
        frame: The frame the coordinates are consistent with.
        front_axle_x: X of the front axle centreline in the file's own datum.
        ground_z: Z of the static ground plane in the file's own datum.
        wheelbase_mm: Front to rear wheel-centre distance.
        front_track_mm: Front wheel-centre separation.
        rear_track_mm: Rear wheel-centre separation.
        loaded_radius_mm: Wheel-centre height above the contact-patch plane.
        evidence: Human-readable checks, each with its measured value.
    """

    frame: Frame
    front_axle_x: float
    ground_z: float
    wheelbase_mm: float
    front_track_mm: float
    rear_track_mm: float
    loaded_radius_mm: float
    evidence: tuple[str, ...]


def read_points(source: Path | str | Iterable[str]) -> dict[str, np.ndarray]:
    """Read a hardpoint CSV into `{"<corner>.<node_id>": xyz}`.

    Args:
        source: Path to the CSV, or any iterable of its lines.

    Returns:
        Mapping of `"lf.lca_outboard"`-style keys to `(3,)` float arrays, in
        the file's own frame and datum.

    Raises:
        HardpointCsvError: On a missing header, an unparseable coordinate, an
            unrecognised point name, or a duplicate point.
    """
    handle = (
        source.open(newline="", encoding="utf-8-sig")
        if isinstance(source, Path)
        else Path(source).open(newline="", encoding="utf-8-sig")
        if isinstance(source, str)
        else None
    )
    lines: Iterable[str] = handle if handle is not None else source  # type: ignore[assignment]
    try:
        reader = csv.DictReader(lines)
        if reader.fieldnames is None:
            raise HardpointCsvError("Hardpoint CSV is empty")
        columns = {name.strip().lower(): name for name in reader.fieldnames}
        name_column = _require_column(columns, "point name")
        axis_columns = [
            _require_column(columns, f"{axis} (mm)") for axis in ("x", "y", "z")
        ]
        points: dict[str, np.ndarray] = {}
        for line_number, row in enumerate(reader, start=2):
            raw_name = (row.get(name_column) or "").strip()
            if not raw_name:
                continue
            key = _parse_point_name(raw_name, line_number)
            if key in points:
                raise HardpointCsvError(
                    f"Line {line_number}: duplicate point {raw_name!r}"
                )
            points[key] = _parse_coordinates(row, axis_columns, raw_name, line_number)
    finally:
        if handle is not None:
            handle.close()
    if not points:
        raise HardpointCsvError("Hardpoint CSV contains no points")
    return points


def _require_column(columns: Mapping[str, str], wanted: str) -> str:
    try:
        return columns[wanted]
    except KeyError:
        raise HardpointCsvError(
            f"Hardpoint CSV is missing the {wanted!r} column; found {sorted(columns)}"
        ) from None


def _parse_point_name(raw_name: str, line_number: int) -> str:
    head, _, token = raw_name.rpartition(" ")
    corner = CORNER_TOKENS.get(token.upper())
    if corner is None:
        raise HardpointCsvError(
            f"Line {line_number}: point {raw_name!r} does not end in a corner "
            f"token; expected one of {sorted(CORNER_TOKENS)}"
        )
    normalised = " ".join(head.lower().split())
    node_id = POINT_NAME_TO_NODE_ID.get(normalised)
    if node_id is None:
        raise HardpointCsvError(
            f"Line {line_number}: unrecognised point name {head!r}. Add it to "
            "workbench.io.hardpoint_csv.POINT_NAME_TO_NODE_ID if it is real."
        )
    return f"{corner}.{node_id}"


def _parse_coordinates(
    row: Mapping[str, str | None],
    axis_columns: list[str],
    raw_name: str,
    line_number: int,
) -> np.ndarray:
    try:
        return np.array(
            [float((row[column] or "").strip()) for column in axis_columns],
            dtype=np.float64,
        )
    except (TypeError, ValueError) as error:
        raise HardpointCsvError(
            f"Line {line_number}: point {raw_name!r} has an unparseable "
            f"coordinate ({error})"
        ) from error


def verify_frame(points: Mapping[str, np.ndarray]) -> FrameReport:
    """Determine a hardpoint file's coordinate frame from the geometry itself.

    Args:
        points: Output of `read_points`, in the file's own frame.

    Returns:
        A `FrameReport` naming the frame and the measurements behind it.

    Raises:
        HardpointCsvError: When the file has no complete set of four wheel
            centres, or when the axis signs are mutually contradictory and so
            match neither ISO 8855 nor SAE.
    """
    centres = {
        corner: points.get(f"{corner}.wheel_center")
        for corner in CORNER_TOKENS.values()
    }
    missing = [corner for corner, value in centres.items() if value is None]
    if missing:
        raise HardpointCsvError(
            f"Cannot verify the frame without all four wheel centres; "
            f"missing {sorted(missing)}"
        )
    lf, rf = centres["lf"], centres["rf"]
    lr = centres["lr"]
    assert lf is not None and rf is not None and lr is not None

    front_is_positive_x = float(lf[0]) > float(lr[0])
    left_is_positive_y = float(lf[1]) > float(rf[1])
    fore_is_positive_x = _fore_is_positive_x(points)
    patch_below_centre = _patch_below_centre(points)

    iso_votes = (front_is_positive_x, left_is_positive_y, fore_is_positive_x)
    if all(iso_votes):
        frame = Frame.ISO8855
    elif not any(iso_votes):
        frame = Frame.SAE
    else:
        raise HardpointCsvError(
            "Hardpoint frame is self-contradictory: front axle at "
            f"{'+' if front_is_positive_x else '-'}X, left corners at "
            f"{'+' if left_is_positive_y else '-'}Y, 'Fore' pickups at "
            f"{'+' if fore_is_positive_x else '-'}X. Neither ISO 8855 nor SAE."
        )
    if not patch_below_centre:
        raise HardpointCsvError(
            "Contact patches are not below their wheel centres, so +Z is not up"
        )

    loaded_radius = float(
        np.mean(
            [
                points[f"{corner}.wheel_center"][2]
                - points[f"{corner}.contact_patch"][2]
                for corner in CORNER_TOKENS.values()
                if f"{corner}.contact_patch" in points
            ]
        )
    )
    sign = 1.0 if frame is Frame.ISO8855 else -1.0
    return FrameReport(
        frame=frame,
        front_axle_x=float(lf[0]),
        ground_z=float(points["lf.contact_patch"][2]),
        wheelbase_mm=abs(float(lf[0]) - float(lr[0])),
        front_track_mm=abs(float(lf[1]) - float(rf[1])),
        rear_track_mm=abs(float(lr[1]) - float(centres["rr"][1])),  # type: ignore[index]
        loaded_radius_mm=loaded_radius,
        evidence=(
            f"front axle is at {'+' if front_is_positive_x else '-'}X "
            f"(front {float(lf[0]):.1f} vs rear {float(lr[0]):.1f})",
            f"left corners are at {'+' if left_is_positive_y else '-'}Y "
            f"(LF {float(lf[1]):.1f} vs RF {float(rf[1]):.1f})",
            f"'Fore' pickups are at {'+' if fore_is_positive_x else '-'}X, "
            "agreeing with the axle check",
            f"contact patches lie {loaded_radius:.2f} mm below their wheel "
            "centres, so +Z is up",
            f"axis sign convention: {'+' if sign > 0 else '-'}X forward, "
            f"{'+' if sign > 0 else '-'}Y left",
        ),
    )


def _fore_is_positive_x(points: Mapping[str, np.ndarray]) -> bool:
    """Whether points named "Fore" sit at greater X than their "Aft" partners.

    An independent check on the longitudinal axis: it reads the file's own
    naming rather than the corner tokens, so it catches a file whose corner
    labels and coordinates disagree.
    """
    deltas = [
        float(points[f"{corner}.{arm}_fore_inboard"][0])
        - float(points[f"{corner}.{arm}_aft_inboard"][0])
        for corner in CORNER_TOKENS.values()
        for arm in ("lca", "uca")
        if f"{corner}.{arm}_fore_inboard" in points
        and f"{corner}.{arm}_aft_inboard" in points
    ]
    if not deltas:
        raise HardpointCsvError(
            "No Fore/Aft pickup pairs found, so the longitudinal axis "
            "direction cannot be confirmed independently"
        )
    if not (all(d > 0 for d in deltas) or all(d < 0 for d in deltas)):
        raise HardpointCsvError(
            f"Fore/Aft pickup pairs disagree on the longitudinal axis: {deltas}"
        )
    return deltas[0] > 0


def _patch_below_centre(points: Mapping[str, np.ndarray]) -> bool:
    deltas = [
        float(points[f"{corner}.wheel_center"][2])
        - float(points[f"{corner}.contact_patch"][2])
        for corner in CORNER_TOKENS.values()
        if f"{corner}.contact_patch" in points
    ]
    return bool(deltas) and all(delta > 0 for delta in deltas)


def load_design(
    source: Path | str,
    *,
    name: str = "",
    car_defaults: wb_defaults.CarDefaults = wb_defaults.GOLDEN_CAR,
    frame: Frame | None = None,
    normalise_datum: bool = True,
) -> Design:
    """Load a four-corner hardpoint CSV into a `Design`.

    Args:
        source: Path to the CSV.
        name: Design name; defaults to the file stem.
        car_defaults: Tire, spring, mass, and synthesis-policy data for the
            values a hardpoint file cannot carry.
        frame: Force a source frame instead of detecting one. Detection is the
            default and is strongly preferred.
        normalise_datum: Shift coordinates so the front axle centreline is at
            `X = 0` and the ground plane at `Z = 0`.

    Returns:
        A `Design` with a front and a rear axle, both with explicit left and
        right corners.

    Raises:
        HardpointCsvError: On a malformed file, a contradictory frame, or a
            corner missing a required node.
    """
    path = Path(source)
    return design_from_points(
        read_points(path),
        name=name or path.stem,
        car_defaults=car_defaults,
        frame=frame,
        normalise_datum=normalise_datum,
        provenance={"source_file": path.name},
    )


def design_from_points(
    points: Mapping[str, np.ndarray],
    *,
    name: str,
    car_defaults: wb_defaults.CarDefaults = wb_defaults.GOLDEN_CAR,
    frame: Frame | None = None,
    normalise_datum: bool = True,
    provenance: Mapping[str, object] | None = None,
) -> Design:
    """Assemble a `Design` from already-parsed hardpoints.

    This is the half of `load_design` that is independent of the file format:
    verify the frame, convert it if it is SAE, shift onto the design datum,
    build both axles, and record what was measured against what was defaulted.
    `workbench.io.hardpoint_import` reuses it so a spreadsheet import and a
    CSV import cannot drift apart on frames, datums, or defaults.

    Args:
        points: `{"<corner>.<node_id>": xyz}` in the source's own frame and
            datum, as produced by `read_points`.
        name: Design name.
        car_defaults: Tire, spring, mass, and synthesis-policy data for the
            values a hardpoint file cannot carry.
        frame: Force a source frame instead of detecting one. Detection is the
            default and is strongly preferred.
        normalise_datum: Shift coordinates so the front axle centreline is at
            `X = 0` and the ground plane at `Z = 0`.
        provenance: Extra provenance to merge in, e.g. where the points came
            from. Format-independent provenance is added here.

    Returns:
        A `Design` with a front and a rear axle, both with explicit left and
        right corners.

    Raises:
        HardpointCsvError: On a contradictory frame or a corner missing a
            required node.
    """
    report = verify_frame(points)
    source_frame = frame or report.frame
    if source_frame is Frame.SAE:
        points = {key: sae_to_iso(value) for key, value in points.items()}
        report = verify_frame(points)
    if normalise_datum:
        points = {
            key: normalise_origin(
                value, front_axle_x=report.front_axle_x, ground_z=report.ground_z
            )
            for key, value in points.items()
        }

    axles = {
        axle_id: _build_axle(axle_id, points, car_defaults)
        for axle_id in ("front", "rear")
    }
    front_tire = car_defaults.front.tire
    loaded_radius = round(report.loaded_radius_mm, 6)
    tire = TireSpec(
        name=front_tire.name,
        compound=front_tire.compound,
        overall_diameter_in=front_tire.overall_diameter_in,
        section_width_in=front_tire.section_width_in,
        rim_diameter_in=front_tire.rim_diameter_in,
        # Measured from the file, not assumed: the wheel-centre height above
        # the contact-patch plane *is* the static loaded radius.
        loaded_radius_mm=loaded_radius,
        wheel_offset_mm=car_defaults.front.wheel_offset_mm,
    )
    vehicle = VehicleSpec(
        wheelbase_mm=round(report.wheelbase_mm, 6),
        front_track_mm=round(report.front_track_mm, 6),
        rear_track_mm=round(report.rear_track_mm, 6),
        mass_kg=car_defaults.mass.mass_kg,
        front_mass_fraction=car_defaults.mass.front_mass_fraction,
        cg_height_mm=car_defaults.mass.cg_height_mm,
        front_brake_bias=car_defaults.mass.front_brake_bias,
        driven_axle=car_defaults.mass.driven_axle,
    )
    return Design(
        schema_version=SCHEMA_VERSION,
        name=name,
        tire=tire,
        vehicle=vehicle,
        axles=axles,
        provenance={
            **(provenance or {}),
            "source_frame": source_frame.value,
            "frame_evidence": list(report.evidence),
            "datum_shift_mm": (
                [-report.front_axle_x, 0.0, -report.ground_z]
                if normalise_datum
                else [0.0, 0.0, 0.0]
            ),
            "measured_loaded_radius_mm": loaded_radius,
            "unloaded_radius_mm": front_tire.unloaded_radius_mm,
            "static_deflection_mm": round(
                front_tire.unloaded_radius_mm - loaded_radius, 6
            ),
            "defaulted": [
                "tire size and compound",
                "spring rates",
                "mass properties",
                "rack travel",
                "static camber and toe (wheel spin axis)",
                "rocker pivot axis direction",
                "pushrod mount body",
            ],
        },
    )


def _build_axle(
    axle_id: str,
    points: Mapping[str, np.ndarray],
    car_defaults: wb_defaults.CarDefaults,
) -> Axle:
    suffix = "f" if axle_id == "front" else "r"
    corners = {
        side: _build_corner(f"{side}{suffix}", points, axle_id) for side in ("l", "r")
    }
    steered = "tie_rod_inboard" in corners["l"].nodes
    del car_defaults  # Axle-level defaults are applied by the solver bridge.
    return Axle(
        id=axle_id,  # type: ignore[arg-type]
        architecture="double_wishbone",
        steering="rack" if steered else "none",
        left=corners["l"],
        right=corners["r"],
    )


def _build_corner(
    corner_id: str, points: Mapping[str, np.ndarray], axle_id: str
) -> Corner:
    prefix = f"{corner_id}."
    nodes = {
        key[len(prefix) :]: value
        for key, value in points.items()
        if key.startswith(prefix)
    }
    if not nodes:
        raise HardpointCsvError(f"No points found for corner {corner_id!r}")
    absent = _REQUIRED_NODES - set(nodes)
    if absent:
        raise HardpointCsvError(
            f"Corner {corner_id!r} is missing required nodes: {sorted(absent)}"
        )
    has_rocker = {"pushrod_outboard", "rocker_pushrod", "rocker_pivot"} <= set(nodes)
    # Front corners pull, rear corners push, on this car and on most FSAE cars
    # with the rocker low at the front and high at the rear. Decide it from the
    # geometry instead of the axle: a pullrod runs downhill from the upright to
    # the rocker, a pushrod runs uphill.
    actuation = "direct"
    if has_rocker:
        downhill = float(nodes["rocker_pushrod"][2]) < float(
            nodes["pushrod_outboard"][2]
        )
        actuation = "pullrod_rocker" if downhill else "pushrod_rocker"
    return Corner(
        id=corner_id,  # type: ignore[arg-type]
        nodes={
            node_id: Node(
                id=node_id,
                position=(float(xyz[0]), float(xyz[1]), float(xyz[2])),
                fixed=node_id in _CHASSIS_NODES,
            )
            for node_id, xyz in sorted(nodes.items())
        },
        actuation=actuation,  # type: ignore[arg-type]
        spring="coilover" if "damper_inboard" in nodes else "none",
        pushrod_mount=_nearest_wishbone_body(nodes) if has_rocker else "upright",
    )


def _nearest_wishbone_body(nodes: Mapping[str, np.ndarray]) -> str:
    """Pick the moving body that most plausibly carries the pushrod pickup.

    A hardpoint file does not say which body a pushrod bolts to, and the choice
    changes the motion ratio substantially. Scoring by distance to the wishbone
    outboard joint picks the arm the pickup actually sits on for a conventional
    layout: a pullrod tab near the upper ball joint scores the upper wishbone,
    a pushrod tab near the lower ball joint scores the lower.

    Returns `"upright"` when neither wishbone is clearly nearer, since the
    upright is the body that carries any pickup rigidly regardless of plane.
    """
    pickup = nodes["pushrod_outboard"]
    scores = {
        body: float(np.linalg.norm(pickup - nodes[anchors[2]]))
        for body, anchors in _WISHBONE_BODIES.items()
        if all(anchor in nodes for anchor in anchors)
    }
    if len(scores) < 2:
        return "upright"
    best, second = sorted(scores.items(), key=lambda item: item[1])[:2]
    if second[1] - best[1] < 10.0:
        return "upright"
    return best[0]

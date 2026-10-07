"""Coordinate frame adapter.

ISO 8855 is canonical everywhere in the workbench: ``+X`` forward, ``+Y`` left,
``+Z`` up, millimetres. The Suspension Explorer solver uses the same frame, so
the bridge needs no conversion. KinematiK uses SAE vehicle axes (``+X`` rear,
``+Y`` right, ``+Z`` up), so anything imported from or exported to KinematiK
passes through :func:`sae_to_iso` / :func:`iso_to_sae`.

Both conversions are the same involution — negate X and Y, leave Z — so one
array operation serves both directions. They are kept as two named functions
because call sites read very differently and silently using the wrong one
mirrors a car front-to-back.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "AXIS_FLIP_ISO_SAE",
    "Frame",
    "iso_to_sae",
    "normalise_origin",
    "sae_to_iso",
]


class Frame(StrEnum):
    """Supported authored coordinate frames."""

    ISO8855 = "iso8855"
    """+X forward, +Y left, +Z up. Canonical for the workbench and the solver."""

    SAE = "sae"
    """+X rear, +Y right, +Z up. KinematiK's native frame."""


AXIS_FLIP_ISO_SAE: Final[NDArray[np.float64]] = np.array([-1.0, -1.0, 1.0])
"""Per-axis sign flip between ISO 8855 and SAE vehicle axes."""


def _flip(points: NDArray[np.float64] | list) -> NDArray[np.float64]:
    data = np.asarray(points, dtype=np.float64)
    if data.shape[-1] != 3:
        raise ValueError(f"Expected trailing axis of length 3, got shape {data.shape}")
    return data * AXIS_FLIP_ISO_SAE


def sae_to_iso(points: NDArray[np.float64] | list) -> NDArray[np.float64]:
    """Convert SAE vehicle axes to ISO 8855.

    Args:
        points: ``(3,)`` or ``(..., 3)`` coordinates in millimetres, SAE axes.

    Returns:
        The same coordinates expressed in ISO 8855 axes.
    """
    return _flip(points)


def iso_to_sae(points: NDArray[np.float64] | list) -> NDArray[np.float64]:
    """Convert ISO 8855 axes to SAE vehicle axes.

    Args:
        points: ``(3,)`` or ``(..., 3)`` coordinates in millimetres, ISO 8855.

    Returns:
        The same coordinates expressed in SAE axes.
    """
    return _flip(points)


def normalise_origin(
    points: NDArray[np.float64] | list,
    *,
    front_axle_x: float,
    ground_z: float = 0.0,
) -> NDArray[np.float64]:
    """Shift ISO 8855 coordinates onto the workbench design datum.

    The design datum places the front axle centreline at ``X = 0`` and the
    static ground plane at ``Z = 0``, which is also the Suspension Explorer
    design condition. Authored files commonly use a mid-car or chassis-datum
    origin instead.

    Args:
        points: ``(3,)`` or ``(..., 3)`` ISO 8855 coordinates in millimetres.
        front_axle_x: X of the front axle centreline in the source datum.
        ground_z: Z of the static ground plane in the source datum.

    Returns:
        Coordinates translated onto the design datum. Orientation is unchanged,
        so every angle and every relative length is invariant.
    """
    data = np.asarray(points, dtype=np.float64)
    if data.shape[-1] != 3:
        raise ValueError(f"Expected trailing axis of length 3, got shape {data.shape}")
    return data - np.array([front_axle_x, 0.0, ground_z])

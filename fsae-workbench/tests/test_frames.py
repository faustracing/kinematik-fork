"""Coordinate frame adapter."""

from __future__ import annotations

import numpy as np
import pytest
from workbench.core.frames import (
    Frame,
    iso_to_sae,
    normalise_origin,
    sae_to_iso,
)


def test_sae_to_iso_flips_x_and_y_only():
    assert sae_to_iso([100.0, 200.0, 300.0]) == pytest.approx([-100.0, -200.0, 300.0])


def test_conversion_is_an_involution():
    points = np.array([[631.5, 251.0, 120.6], [-804.1, -266.2, 138.6]])
    assert iso_to_sae(sae_to_iso(points)) == pytest.approx(points)


def test_a_left_front_corner_maps_between_the_two_conventions():
    """ISO left-front is +X +Y; the same corner in SAE is -X -Y."""
    iso_left_front = np.array([774.7, 584.2, 223.52])
    sae = iso_to_sae(iso_left_front)
    assert sae[0] < 0.0, "SAE puts the front axle at negative X"
    assert sae[1] < 0.0, "SAE puts the left side at negative Y"
    assert sae[2] == pytest.approx(223.52), "both frames agree +Z is up"


def test_conversion_is_vectorised_over_many_points():
    points = np.random.default_rng(0).normal(size=(7, 3)) * 500.0
    assert sae_to_iso(points).shape == (7, 3)


def test_wrong_trailing_axis_is_rejected():
    with pytest.raises(ValueError, match="trailing axis of length 3"):
        sae_to_iso([[1.0, 2.0]])


def test_normalise_origin_moves_the_front_axle_to_zero():
    shifted = normalise_origin([774.7, 584.2, 223.52], front_axle_x=774.7, ground_z=0.0)
    assert shifted == pytest.approx([0.0, 584.2, 223.52])


def test_normalise_origin_preserves_every_relative_length():
    points = np.array([[774.7, 584.2, 223.52], [631.5, 251.0, 120.6]])
    before = np.linalg.norm(points[0] - points[1])
    shifted = normalise_origin(points, front_axle_x=774.7, ground_z=12.0)
    assert np.linalg.norm(shifted[0] - shifted[1]) == pytest.approx(before)


def test_frame_values_are_the_wire_names():
    assert Frame.ISO8855 == "iso8855"
    assert Frame.SAE == "sae"

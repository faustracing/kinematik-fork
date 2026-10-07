"""Does ``clamp`` actually return the *nearest* allowable point?

Correctness of containment is easy to assert; nearness is not, so these tests
compare against a brute-force search over a fine grid. The grid resolution
bounds how good an answer it can find, which is why the tolerances below are
in grid steps rather than in floating-point epsilons.
"""

from __future__ import annotations

import numpy as np
import pytest

from workbench.regions import (
    Box,
    Difference,
    Intersection,
    OrientedBox,
    Sphere,
    Union,
    combine,
)


def brute_force_nearest(region, pts: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Nearest allowable grid point for each row of ``pts``."""
    allowed = grid[np.asarray(region.permits(grid))]
    assert len(allowed), "the test grid found no allowable points at all"
    d = np.linalg.norm(allowed[None, :, :] - pts[:, None, :], axis=2)
    return allowed[np.argmin(d, axis=1)]


def make_grid(lo, hi, n: int) -> np.ndarray:
    axes = [np.linspace(a, b, n) for a, b in zip(lo, hi)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


STEP = 20.0 / 40  # grid spacing used by the fixtures below


@pytest.fixture
def grid() -> np.ndarray:
    return make_grid((-10, -10, -10), (10, 10, 10), 41)


@pytest.fixture
def probes(rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(-10, 10, size=(60, 3))


def assert_near_optimal(region, pts: np.ndarray, grid: np.ndarray) -> None:
    got = region.clamp(pts)
    assert np.asarray(region.permits(got)).all()
    best = brute_force_nearest(region, pts, grid)
    got_d = np.linalg.norm(got - pts, axis=1)
    best_d = np.linalg.norm(best - pts, axis=1)
    # The grid can only beat us by a sampling artefact of up to one step.
    assert np.all(got_d <= best_d + STEP * np.sqrt(3) + 1e-6)


def test_box_minus_sphere(probes: np.ndarray, grid: np.ndarray) -> None:
    region = Difference(
        id="d",
        children=[
            Box(id="o", min=(-8, -8, -8), max=(8, 8, 8)),
            Sphere(id="h", center=(0, 0, 0), radius=4.0),
        ],
    )
    assert_near_optimal(region, probes, grid)


def test_intersection_with_a_blocking_keep_out(
    probes: np.ndarray, grid: np.ndarray
) -> None:
    # The keep-out's nearest face points straight out of the allowed slab, so
    # a naive "escape through the closest face" clamp gets this wrong.
    region = Intersection(
        id="i",
        children=[
            Box(id="slab", min=(-9, -9, 0), max=(9, 9, 3)),
            Box(id="keepout", min=(-9, -9, -1), max=(9, 9, 2), allow=False),
        ],
    )
    assert_near_optimal(region, probes, grid)


def test_union_of_disjoint_boxes(probes: np.ndarray, grid: np.ndarray) -> None:
    region = Union(
        id="u",
        children=[
            Box(id="a", min=(-9, -9, -9), max=(-3, 9, 9)),
            Box(id="b", min=(3, -9, -9), max=(9, 9, 9)),
        ],
    )
    assert_near_optimal(region, probes, grid)


def test_deny_union_of_overlapping_boxes(
    probes: np.ndarray, grid: np.ndarray
) -> None:
    region = Union(
        id="u",
        allow=False,
        children=[
            Box(id="a", min=(-8, -4, -4), max=(2, 4, 4)),
            Box(id="b", min=(0, -4, -4), max=(8, 4, 4)),
        ],
    )
    assert_near_optimal(region, probes, grid)


def test_deny_sphere_inside_an_allowed_oriented_box(
    probes: np.ndarray, grid: np.ndarray
) -> None:
    c, s = np.cos(np.radians(25)), np.sin(np.radians(25))
    region = combine(
        [
            OrientedBox(
                id="o",
                center=(0, 0, 0),
                half_extents=(9, 5, 5),
                rotation=(c, -s, 0, s, c, 0, 0, 0, 1),
            ),
            Sphere(id="k", center=(1, 1, 0), radius=3.0, allow=False),
        ]
    )
    assert_near_optimal(region, probes, grid)


def test_clamp_is_idempotent(rng: np.random.Generator) -> None:
    region = Intersection(
        id="i",
        children=[
            Box(id="a", min=(0, 0, 0), max=(100, 100, 100)),
            Sphere(id="k", center=(50, 50, 50), radius=20.0, allow=False),
        ],
    )
    pts = rng.uniform(-50, 150, size=(500, 3))
    once = region.clamp(pts)
    twice = region.clamp(once)
    assert np.asarray(region.permits(once)).all()
    np.testing.assert_allclose(twice, once, atol=1e-6)


def test_clamped_samples_stay_allowable(rng: np.random.Generator) -> None:
    region = Difference(
        id="d",
        children=[
            Box(id="o", min=(-100, -100, 0), max=(100, 100, 400)),
            Box(id="h1", min=(-20, -20, 100), max=(20, 20, 200)),
            Sphere(id="h2", center=(60, 0, 300), radius=40.0),
        ],
    )
    pts = region.sample(2000, rng)
    assert np.asarray(region.permits(pts)).all()
    np.testing.assert_allclose(region.clamp(pts), pts)

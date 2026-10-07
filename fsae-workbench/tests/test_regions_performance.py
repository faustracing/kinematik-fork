"""The optimizer calls these on thousands of points per iteration.

The budgets below are deliberately loose -- roughly an order of magnitude above
what a developer machine measures -- because the point is to catch a
regression into a Python-level loop, not to benchmark CI hardware.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from workbench.regions import Box, Intersection, OrientedBox, Polytope, Sphere, Union

N = 10_000


def elapsed(fn, *args) -> tuple[float, object]:
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


@pytest.fixture
def cloud(rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(-400, 400, size=(N, 3))


@pytest.fixture
def realistic() -> Intersection:
    """A pickup's allowable volume as the app would actually build it."""
    c, s = np.cos(np.radians(15)), np.sin(np.radians(15))
    return Intersection(
        id="pickup",
        children=[
            Box(id="envelope", min=(-300, -250, 60), max=(300, 250, 380)),
            OrientedBox(
                id="frame_rail",
                center=(0, 0, 200),
                half_extents=(280, 200, 150),
                rotation=(c, -s, 0, s, c, 0, 0, 0, 1),
            ),
            Sphere(id="driver_foot", center=(150, 120, 150), radius=90.0, allow=False),
            Box(id="rule_ground", min=(-400, -400, -400), max=(400, 400, 0), allow=False),
        ],
    )


def test_contains_is_vectorised(realistic: Intersection, cloud: np.ndarray) -> None:
    dt, inside = elapsed(realistic.contains, cloud)
    assert inside.shape == (N,)
    assert 0 < inside.sum() < N
    assert dt < 0.25, f"contains on {N} points took {dt * 1e3:.0f} ms"


def test_clamp_is_vectorised(realistic: Intersection, cloud: np.ndarray) -> None:
    dt, out = elapsed(realistic.clamp, cloud)
    assert out.shape == (N, 3)
    assert np.asarray(realistic.permits(out)).mean() > 0.99
    assert dt < 2.0, f"clamp on {N} points took {dt * 1e3:.0f} ms"


def test_clamp_scales_sublinearly_in_python_overhead(
    realistic: Intersection, rng: np.random.Generator
) -> None:
    small = rng.uniform(-400, 400, size=(100, 3))
    large = rng.uniform(-400, 400, size=(10_000, 3))
    dt_small, _ = elapsed(realistic.clamp, small)
    dt_large, _ = elapsed(realistic.clamp, large)
    # A hidden per-point Python loop would make this ratio about 100.
    assert dt_large / max(dt_small, 1e-6) < 30


def test_polytope_contains_is_a_single_matmul(cloud: np.ndarray) -> None:
    p = Polytope(
        id="p",
        a=[(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
           (1, 1, 1), (-1, -1, -1)],
        b=[200.0] * 6 + [300.0, 300.0],
    )
    dt, inside = elapsed(p.contains, cloud)
    assert inside.shape == (N,)
    assert dt < 0.1, f"polytope contains on {N} points took {dt * 1e3:.0f} ms"


def test_union_clamp_stays_within_budget(cloud: np.ndarray) -> None:
    u = Union(
        id="u",
        children=[
            Box(id="a", min=(-300, -300, 0), max=(-50, 300, 300)),
            Box(id="b", min=(50, -300, 0), max=(300, 300, 300)),
        ],
    )
    dt, out = elapsed(u.clamp, cloud)
    assert u.contains(out).all()
    assert dt < 2.0, f"union clamp on {N} points took {dt * 1e3:.0f} ms"


def test_sampling_throughput(rng: np.random.Generator) -> None:
    region = Intersection(
        id="i",
        children=[
            Box(id="a", min=(-100, -100, 0), max=(100, 100, 200)),
            Sphere(id="k", center=(0, 0, 100), radius=50.0, allow=False),
        ],
    )
    dt, pts = elapsed(region.sample, 20_000, rng)
    assert pts.shape == (20_000, 3)
    assert region.contains(pts).all()
    assert dt < 2.0, f"sampling 20k points took {dt * 1e3:.0f} ms"

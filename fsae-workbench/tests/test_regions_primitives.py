from __future__ import annotations

import numpy as np
import pytest

from workbench.regions import (
    Box,
    EmptyRegionError,
    OrientedBox,
    Polytope,
    Sphere,
    UnboundedRegionError,
    parse_region,
)

UNIT_CUBE_HALFSPACES = dict(
    a=[(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
    b=[1.0] * 6,
)


def rot_z(deg: float) -> tuple[float, ...]:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return (c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0)


@pytest.fixture
def box() -> Box:
    return Box(id="b", min=(-10, -20, 0), max=(10, 20, 30))


# -- shape handling -----------------------------------------------------------


def test_single_point_returns_scalars(box: Box) -> None:
    assert box.contains([0, 0, 15]) is True
    assert box.contains((0, 0, 100)) is False
    assert box.clamp([0, 0, 100]).shape == (3,)


def test_array_input_returns_arrays(box: Box) -> None:
    pts = np.array([[0, 0, 15], [0, 0, 100]], dtype=float)
    inside = box.contains(pts)
    assert isinstance(inside, np.ndarray)
    assert inside.tolist() == [True, False]
    assert box.clamp(pts).shape == (2, 3)


@pytest.mark.parametrize("bad", [np.zeros(2), np.zeros((4, 2)), np.zeros((2, 2, 3))])
def test_malformed_input_rejected(box: Box, bad: np.ndarray) -> None:
    with pytest.raises(ValueError):
        box.contains(bad)


def test_empty_input_is_fine(box: Box) -> None:
    pts = np.empty((0, 3))
    assert box.contains(pts).shape == (0,)
    assert box.clamp(pts).shape == (0, 3)


# -- box ----------------------------------------------------------------------


def test_box_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="exceeds max"):
        Box(id="bad", min=(1, 0, 0), max=(0, 0, 0))


def test_box_faces_count_as_inside(box: Box) -> None:
    corners = np.array([[-10, -20, 0], [10, 20, 30], [10, 0, 0]], dtype=float)
    assert box.contains(corners).all()


def test_box_clamp_in_matches_clip(box: Box, rng: np.random.Generator) -> None:
    pts = rng.uniform(-60, 60, size=(500, 3))
    np.testing.assert_allclose(box.clamp(pts), np.clip(pts, box._lo, box._hi))
    assert box.contains(box.clamp(pts)).all()


def test_box_clamp_leaves_interior_points_alone(
    box: Box, rng: np.random.Generator
) -> None:
    pts = rng.uniform(box._lo, box._hi, size=(200, 3))
    np.testing.assert_allclose(box.clamp(pts), pts)


def test_deny_box_pushes_out_through_the_nearest_face() -> None:
    deny = Box(id="d", min=(0, 0, 0), max=(10, 10, 100), allow=False)
    # Nearest escape from (1, 5, 50) is the x = 0 face, 1 mm away.
    out = deny.clamp([1, 5, 50])
    assert out[0] < 0.0
    np.testing.assert_allclose(out[1:], [5, 50])
    assert np.linalg.norm(out - np.array([1, 5, 50])) == pytest.approx(1.0, abs=1e-5)
    assert deny.permits(out)


def test_deny_box_leaves_exterior_points_alone() -> None:
    deny = Box(id="d", min=(0, 0, 0), max=(10, 10, 10), allow=False)
    p = np.array([[50.0, 0.0, 0.0], [-1.0, -1.0, -1.0]])
    np.testing.assert_allclose(deny.clamp(p), p)


def test_deny_box_escape_is_the_true_nearest_exterior_point() -> None:
    deny = Box(id="d", min=(0, 0, 0), max=(4, 6, 8), allow=False)
    rng = np.random.default_rng(7)
    pts = rng.uniform([0, 0, 0], [4, 6, 8], size=(300, 3))
    out = deny.clamp(pts)
    moved = np.linalg.norm(out - pts, axis=1)
    expected = np.minimum(
        np.min(pts - np.array([0, 0, 0]), axis=1),
        np.min(np.array([4, 6, 8]) - pts, axis=1),
    )
    np.testing.assert_allclose(moved, expected, atol=1e-5)
    assert np.asarray(deny.permits(out)).all()


def test_degenerate_flat_box_behaves_like_its_plane() -> None:
    flat = Box(id="f", min=(0, 0, 5), max=(10, 10, 5))
    assert flat.contains([5, 5, 5])
    assert not flat.contains([5, 5, 5.1])
    np.testing.assert_allclose(flat.clamp([5, 5, 50]), [5, 5, 5])
    lo, hi = flat.bounds()
    np.testing.assert_allclose(hi - lo, [10, 10, 0])


def test_degenerate_box_cannot_be_sampled(rng: np.random.Generator) -> None:
    # A flat box has a well-defined uniform distribution in 2D but the generic
    # rejection path would spin forever, so the allow=False variant must fail
    # loudly rather than hang.
    flat = Box(id="f", min=(0, 0, 5), max=(10, 10, 5), allow=False)
    with pytest.raises(UnboundedRegionError):
        flat.sample(5, rng)


def test_box_sample_is_uniform_and_inside(rng: np.random.Generator) -> None:
    b = Box(id="b", min=(-1, 2, 0), max=(3, 4, 1))
    pts = b.sample(20000, rng)
    assert pts.shape == (20000, 3)
    assert b.contains(pts).all()
    np.testing.assert_allclose(pts.mean(axis=0), [1.0, 3.0, 0.5], atol=0.03)


def test_box_mesh_payload() -> None:
    b = Box(id="b", label="cell", min=(0, 1, 2), max=(3, 4, 5))
    assert b.to_mesh() == {"type": "box", "min": [0, 1, 2], "max": [3, 4, 5]}
    view = b.to_viewport()
    assert view["id"] == "b" and view["kind"] == "box" and view["allow"] is True
    assert view["label"] == "cell"


# -- sphere -------------------------------------------------------------------


def test_sphere_requires_positive_radius() -> None:
    with pytest.raises(ValueError):
        Sphere(id="s", center=(0, 0, 0), radius=0.0)


def test_sphere_clamp_projects_radially() -> None:
    s = Sphere(id="s", center=(1, 2, 3), radius=5.0)
    out = s.clamp([1, 2, 30])
    np.testing.assert_allclose(out, [1, 2, 8])
    np.testing.assert_allclose(s.clamp([1, 2, 4]), [1, 2, 4])


def test_deny_sphere_pushes_out(rng: np.random.Generator) -> None:
    s = Sphere(id="s", center=(0, 0, 0), radius=5.0, allow=False)
    pts = s.model_copy(update={"allow": True}).sample(500, rng)
    out = s.clamp(pts)
    r = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(r, 5.0, atol=1e-5)
    assert np.asarray(s.permits(out)).all()


def test_deny_sphere_handles_the_centre() -> None:
    s = Sphere(id="s", center=(4, 4, 4), radius=2.0, allow=False)
    out = s.clamp([4, 4, 4])
    assert s.permits(out)
    np.testing.assert_allclose(out[1:], [4, 4])


def test_sphere_sample_is_uniform_in_volume(rng: np.random.Generator) -> None:
    s = Sphere(id="s", center=(0, 0, 0), radius=2.0)
    pts = s.sample(30000, rng)
    assert s.contains(pts).all()
    r = np.linalg.norm(pts, axis=1)
    # Uniform in a ball means r^3 is uniform on [0, R^3].
    assert np.mean((r / 2.0) ** 3) == pytest.approx(0.5, abs=0.02)
    np.testing.assert_allclose(pts.mean(axis=0), [0, 0, 0], atol=0.05)


def test_sphere_bounds_and_mesh() -> None:
    s = Sphere(id="s", center=(1, 0, 0), radius=2.0)
    lo, hi = s.bounds()
    np.testing.assert_allclose(lo, [-1, -2, -2])
    np.testing.assert_allclose(hi, [3, 2, 2])
    assert s.to_mesh() == {"type": "sphere", "center": [1, 0, 0], "radius": 2.0}


# -- oriented box -------------------------------------------------------------


def test_oriented_box_rejects_non_orthonormal_rotation() -> None:
    with pytest.raises(ValueError, match="orthonormal"):
        OrientedBox(
            id="o",
            center=(0, 0, 0),
            half_extents=(1, 1, 1),
            rotation=(2, 0, 0, 0, 1, 0, 0, 0, 1),
        )


def test_identity_oriented_box_matches_aabb(rng: np.random.Generator) -> None:
    o = OrientedBox(id="o", center=(1, 2, 3), half_extents=(4, 5, 6))
    b = Box(id="b", min=(-3, -3, -3), max=(5, 7, 9))
    pts = rng.uniform(-15, 15, size=(400, 3))
    np.testing.assert_array_equal(o.contains(pts), b.contains(pts))
    np.testing.assert_allclose(o.clamp(pts), b.clamp(pts), atol=1e-9)


def test_rotated_box_containment() -> None:
    o = OrientedBox(
        id="o", center=(0, 0, 0), half_extents=(10, 1, 1), rotation=rot_z(45)
    )
    # The long axis now points along the x = y diagonal.
    assert o.contains([5 / np.sqrt(2) * 1.0, 5 / np.sqrt(2) * 1.0, 0])
    assert not o.contains([5, -5, 0])


def test_rotated_box_clamp_lands_on_the_surface(rng: np.random.Generator) -> None:
    o = OrientedBox(
        id="o", center=(3, 0, 0), half_extents=(10, 2, 2), rotation=rot_z(30)
    )
    pts = rng.uniform(-40, 40, size=(300, 3))
    out = o.clamp(pts)
    assert o.contains(out).all()
    # Clamping is a projection: doing it twice changes nothing.
    np.testing.assert_allclose(o.clamp(out), out, atol=1e-9)


def test_deny_oriented_box_pushes_out(rng: np.random.Generator) -> None:
    o = OrientedBox(
        id="o",
        center=(0, 0, 0),
        half_extents=(5, 5, 5),
        rotation=rot_z(20),
        allow=False,
    )
    pts = rng.uniform(-4, 4, size=(200, 3))
    assert np.asarray(o.permits(o.clamp(pts))).all()


def test_oriented_box_bounds_envelope_the_corners() -> None:
    o = OrientedBox(
        id="o", center=(0, 0, 0), half_extents=(10, 1, 1), rotation=rot_z(45)
    )
    lo, hi = o.bounds()
    expected = 11 / np.sqrt(2)
    np.testing.assert_allclose(hi[:2], [expected, expected], atol=1e-9)
    np.testing.assert_allclose(lo[:2], [-expected, -expected], atol=1e-9)


def test_oriented_box_mesh_is_a_closed_hull() -> None:
    o = OrientedBox(
        id="o", center=(0, 0, 0), half_extents=(1, 2, 3), rotation=rot_z(15)
    )
    mesh = o.to_mesh()
    assert len(mesh["vertices"]) == 8
    assert len(mesh["indices"]) == 12
    # Every edge of a closed triangle mesh is shared by exactly two faces.
    edges: dict[frozenset[int], int] = {}
    for tri in mesh["indices"]:
        for a, b in zip(tri, tri[1:] + tri[:1]):
            edges[frozenset((a, b))] = edges.get(frozenset((a, b)), 0) + 1
    assert set(edges.values()) == {2}


def test_oriented_box_sample_stays_inside(rng: np.random.Generator) -> None:
    o = OrientedBox(
        id="o", center=(1, 1, 1), half_extents=(3, 1, 2), rotation=rot_z(37)
    )
    pts = o.sample(5000, rng)
    assert o.contains(pts).all()
    np.testing.assert_allclose(pts.mean(axis=0), [1, 1, 1], atol=0.15)


# -- polytope -----------------------------------------------------------------


def test_polytope_validates_its_inputs() -> None:
    with pytest.raises(ValueError, match="offsets"):
        Polytope(id="p", a=[(1, 0, 0)], b=[1.0, 2.0])
    with pytest.raises(ValueError, match="at least one half-space"):
        Polytope(id="p", a=[], b=[])
    with pytest.raises(ValueError, match="cannot be zero"):
        Polytope(id="p", a=[(0, 0, 0)], b=[1.0])


def test_cube_polytope_matches_the_equivalent_box(rng: np.random.Generator) -> None:
    p = Polytope(id="p", **UNIT_CUBE_HALFSPACES)
    b = Box(id="b", min=(-1, -1, -1), max=(1, 1, 1))
    pts = rng.uniform(-3, 3, size=(500, 3))
    np.testing.assert_array_equal(p.contains(pts), b.contains(pts))
    np.testing.assert_allclose(p.clamp(pts), b.clamp(pts), atol=1e-6)
    lo, hi = p.bounds()
    np.testing.assert_allclose(lo, [-1, -1, -1], atol=1e-9)
    np.testing.assert_allclose(hi, [1, 1, 1], atol=1e-9)


def test_polytope_clamp_handles_an_oblique_face(rng: np.random.Generator) -> None:
    # A corner cut off the unit cube by x + y + z <= 1.
    p = Polytope(
        id="p",
        a=UNIT_CUBE_HALFSPACES["a"] + [(1, 1, 1)],
        b=UNIT_CUBE_HALFSPACES["b"] + [1.0],
    )
    assert not p.contains([0.9, 0.9, 0.9])
    out = p.clamp([0.9, 0.9, 0.9])
    assert p.contains(out)
    np.testing.assert_allclose(out.sum(), 1.0, atol=1e-6)


def test_deny_polytope_pushes_out(rng: np.random.Generator) -> None:
    p = Polytope(id="p", allow=False, **UNIT_CUBE_HALFSPACES)
    pts = rng.uniform(-0.9, 0.9, size=(300, 3))
    out = p.clamp(pts)
    assert np.asarray(p.permits(out)).all()
    # Nearest escape from inside a unit cube is the nearest face.
    moved = np.linalg.norm(out - pts, axis=1)
    expected = 1.0 - np.abs(pts).max(axis=1)
    np.testing.assert_allclose(moved, expected, atol=1e-5)


def test_polytope_mesh_is_a_closed_oriented_hull() -> None:
    p = Polytope(id="p", **UNIT_CUBE_HALFSPACES)
    mesh = p.to_mesh()
    verts = np.asarray(mesh["vertices"])
    tris = np.asarray(mesh["indices"])
    assert mesh["type"] == "mesh"
    assert len(tris) == 12
    centroid = verts.mean(axis=0)
    for i, j, k in tris:
        normal = np.cross(verts[j] - verts[i], verts[k] - verts[i])
        assert float(normal @ (verts[i] - centroid)) > 0.0
    # Signed volume of a closed outward-oriented hull is the real volume.
    vol = sum(
        float(np.dot(verts[i] - centroid, np.cross(verts[j] - centroid, verts[k] - centroid)))
        for i, j, k in tris
    ) / 6.0
    assert vol == pytest.approx(8.0, rel=1e-6)


def test_infeasible_polytope_reports_empty() -> None:
    p = Polytope(id="p", a=[(1, 0, 0), (-1, 0, 0)], b=[-1.0, -1.0])
    assert not p.contains([0, 0, 0])
    with pytest.raises(EmptyRegionError):
        p.bounds()


def test_unbounded_polytope_refuses_to_invent_a_box() -> None:
    half_space = Polytope(id="p", a=[(0, 0, -1)], b=[0.0])  # z >= 0
    assert half_space.contains([100, -50, 3])
    assert not half_space.contains([0, 0, -1])
    with pytest.raises((UnboundedRegionError, EmptyRegionError)):
        half_space.bounds()


def test_polytope_sample_stays_inside(rng: np.random.Generator) -> None:
    p = Polytope(
        id="p",
        a=UNIT_CUBE_HALFSPACES["a"] + [(1, 1, 1)],
        b=UNIT_CUBE_HALFSPACES["b"] + [1.0],
    )
    pts = p.sample(2000, rng)
    assert p.contains(pts).all()


def test_zero_thickness_polytope_reports_empty(rng: np.random.Generator) -> None:
    flat = Polytope(
        id="flat",
        a=[(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
        b=[0.0, 0.0, 1.0, 1.0, 1.0, 1.0],
    )
    assert flat.contains([0, 0.5, 0.5])
    with pytest.raises(EmptyRegionError, match="no interior"):
        flat.sample(10, rng)


def test_sample_rejects_a_negative_count(rng: np.random.Generator) -> None:
    with pytest.raises(ValueError):
        Box(id="b", min=(0, 0, 0), max=(1, 1, 1)).sample(-1, rng)


# -- serialisation ------------------------------------------------------------


@pytest.mark.parametrize(
    "region",
    [
        Box(id="b", min=(0, 0, 0), max=(1, 1, 1)),
        Sphere(id="s", center=(0, 0, 0), radius=1.0, allow=False),
        OrientedBox(
            id="o", center=(0, 0, 0), half_extents=(1, 2, 3), rotation=rot_z(10)
        ),
        Polytope(id="p", **UNIT_CUBE_HALFSPACES),
    ],
)
def test_regions_round_trip_through_json(region) -> None:
    clone = parse_region(region.model_dump())
    assert type(clone) is type(region)
    assert clone == region

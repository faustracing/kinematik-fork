"""Composite semantics: unions, intersections, differences and deny children.

The rule these tests pin down is the one stated in
``workbench/regions/composite.py``: a child with ``allow=False`` is subtractive
whatever composite it sits in, and ``clamp`` must therefore push points *out*
of those children while pulling them into the positive ones.
"""

from __future__ import annotations

import numpy as np
import pytest

from workbench.regions import (
    Box,
    ClampError,
    Difference,
    EmptyRegionError,
    Intersection,
    Polytope,
    SamplingError,
    Sphere,
    UnboundedRegionError,
    Union,
    combine,
    feasible,
    parse_region,
    regions_for_node,
)


def box(id: str, lo, hi, *, allow: bool = True) -> Box:
    return Box(id=id, min=lo, max=hi, allow=allow)


# -- construction -------------------------------------------------------------


def test_composites_need_children() -> None:
    with pytest.raises(ValueError, match="at least one child"):
        Union(id="u", children=[])
    with pytest.raises(ValueError, match="minuend"):
        Difference(id="d", children=[box("a", (0, 0, 0), (1, 1, 1))])


# -- union --------------------------------------------------------------------


@pytest.fixture
def two_boxes() -> Union:
    return Union(
        id="u",
        children=[box("a", (0, 0, 0), (10, 10, 10)), box("b", (50, 0, 0), (60, 10, 10))],
    )


def test_union_contains_either_branch(two_boxes: Union) -> None:
    pts = np.array([[5, 5, 5], [55, 5, 5], [30, 5, 5]], dtype=float)
    assert two_boxes.contains(pts).tolist() == [True, True, False]


def test_union_clamp_picks_the_nearer_branch(two_boxes: Union) -> None:
    np.testing.assert_allclose(two_boxes.clamp([20, 5, 5]), [10, 5, 5])
    np.testing.assert_allclose(two_boxes.clamp([45, 5, 5]), [50, 5, 5])
    # Exactly halfway: either answer is correct, but it must be one of them.
    mid = two_boxes.clamp([30, 5, 5])
    assert two_boxes.contains(mid)


def test_union_clamp_leaves_contained_points_alone(two_boxes: Union) -> None:
    pts = np.array([[1, 1, 1], [59, 9, 9]], dtype=float)
    np.testing.assert_allclose(two_boxes.clamp(pts), pts)


def test_union_bounds_envelope_every_branch(two_boxes: Union) -> None:
    lo, hi = two_boxes.bounds()
    np.testing.assert_allclose(lo, [0, 0, 0])
    np.testing.assert_allclose(hi, [60, 10, 10])


def test_union_sample_hits_both_branches(rng: np.random.Generator) -> None:
    u = Union(
        id="u",
        children=[box("a", (0, 0, 0), (1, 1, 1)), box("b", (9, 0, 0), (10, 1, 1))],
    )
    pts = u.sample(4000, rng)
    assert u.contains(pts).all()
    assert (pts[:, 0] < 5).sum() > 1500
    assert (pts[:, 0] > 5).sum() > 1500


def test_union_with_a_deny_child_has_a_hole() -> None:
    u = Union(
        id="u",
        children=[
            box("outer", (0, 0, 0), (10, 10, 10)),
            box("hole", (4, 4, 4), (6, 6, 6), allow=False),
        ],
    )
    assert u.contains([1, 1, 1])
    assert not u.contains([5, 5, 5])
    out = u.clamp([5, 5, 5.5])
    assert u.contains(out)
    # Nearest way out of the hole from (5, 5, 5.5) is the z = 6 face.
    np.testing.assert_allclose(out[:2], [5, 5])
    assert out[2] == pytest.approx(6.0, abs=1e-5)


# -- intersection -------------------------------------------------------------


def test_intersection_requires_every_positive_child() -> None:
    i = Intersection(
        id="i",
        children=[box("a", (0, 0, 0), (10, 10, 10)), box("b", (5, 5, 5), (20, 20, 20))],
    )
    assert i.contains([7, 7, 7])
    assert not i.contains([1, 1, 1])
    np.testing.assert_allclose(i.bounds()[0], [5, 5, 5])
    np.testing.assert_allclose(i.bounds()[1], [10, 10, 10])


def test_intersection_clamp_satisfies_every_child(rng: np.random.Generator) -> None:
    i = Intersection(
        id="i",
        children=[
            box("a", (0, 0, 0), (10, 10, 10)),
            Sphere(id="s", center=(10, 10, 10), radius=9.0),
        ],
    )
    pts = rng.uniform(-20, 30, size=(400, 3))
    out = i.clamp(pts)
    assert i.contains(out).all()
    np.testing.assert_allclose(i.clamp(out), out, atol=1e-6)


def test_intersection_clamp_pushes_out_of_deny_children() -> None:
    i = Intersection(
        id="i",
        children=[
            box("allow", (0, 0, 0), (100, 100, 100)),
            Sphere(id="keepout", center=(50, 50, 50), radius=10.0, allow=False),
        ],
    )
    assert not i.contains([50, 50, 55])
    out = i.clamp([50, 50, 55])
    assert i.contains(out)
    assert np.linalg.norm(out - np.array([50, 50, 50])) == pytest.approx(10.0, abs=1e-4)


def test_deny_child_wins_over_an_allow_child_that_overlaps_it() -> None:
    i = Intersection(
        id="i",
        children=[
            box("allow", (0, 0, 0), (10, 10, 10)),
            box("deny", (0, 0, 0), (10, 10, 4), allow=False),
        ],
    )
    assert not i.contains([5, 5, 2])
    out = i.clamp([5, 5, 2])
    assert out[2] > 4.0
    assert i.contains(out)


def test_disjoint_intersection_is_empty() -> None:
    i = Intersection(
        id="i",
        children=[box("a", (0, 0, 0), (1, 1, 1)), box("b", (10, 10, 10), (11, 11, 11))],
    )
    assert not i.contains(np.array([[0.5, 0.5, 0.5], [10.5, 10.5, 10.5]])).any()
    with pytest.raises(EmptyRegionError):
        i.bounds()
    with pytest.raises(ClampError, match="no allowable point"):
        i.clamp([5, 5, 5], strict=True)
    # Non-strict is best effort, and must still not pretend to have succeeded.
    assert not i.contains(i.clamp([5, 5, 5]))


def test_intersection_of_only_deny_children_is_unbounded() -> None:
    i = Intersection(id="i", children=[box("d", (0, 0, 0), (1, 1, 1), allow=False)])
    assert i.contains([100, 100, 100])
    assert not i.contains([0.5, 0.5, 0.5])
    with pytest.raises(UnboundedRegionError):
        i.bounds()
    with pytest.raises(UnboundedRegionError):
        i.sample(5, np.random.default_rng(0))


def test_sampling_a_nearly_empty_intersection_fails_loudly(
    rng: np.random.Generator,
) -> None:
    # The AABB is the full outer box but almost all of it is carved away, so
    # rejection sampling must give up instead of spinning.
    i = Intersection(
        id="i",
        children=[
            box("outer", (0, 0, 0), (100, 100, 100)),
            box("carve", (0, 0, 0), (100, 100, 99.999), allow=False),
            box("carve2", (0.001, 0, 0), (100, 100, 100), allow=False),
        ],
    )
    with pytest.raises(SamplingError, match="acceptance"):
        i.sample(100, rng, attempt_factor=50)


# -- difference ---------------------------------------------------------------


def test_difference_subtracts_the_later_children() -> None:
    d = Difference(
        id="d",
        children=[
            box("outer", (0, 0, 0), (10, 10, 10)),
            Sphere(id="hole", center=(5, 5, 5), radius=3.0),
        ],
    )
    assert d.contains([1, 1, 1])
    assert not d.contains([5, 5, 5])
    out = d.clamp([5, 5, 6])
    assert d.contains(out)
    assert np.linalg.norm(out - np.array([5, 5, 5])) == pytest.approx(3.0, abs=1e-4)


def test_difference_ignores_the_allow_flag_of_its_subtrahends() -> None:
    subtrahend_allow = Difference(
        id="d1",
        children=[box("o", (0, 0, 0), (10, 10, 10)), box("h", (4, 4, 4), (6, 6, 6))],
    )
    subtrahend_deny = Difference(
        id="d2",
        children=[
            box("o", (0, 0, 0), (10, 10, 10)),
            box("h", (4, 4, 4), (6, 6, 6), allow=False),
        ],
    )
    pts = np.array([[5, 5, 5], [1, 1, 1]], dtype=float)
    np.testing.assert_array_equal(
        subtrahend_allow.contains(pts), subtrahend_deny.contains(pts)
    )


def test_difference_bounds_follow_the_minuend() -> None:
    d = Difference(
        id="d",
        children=[box("o", (0, 0, 0), (10, 10, 10)), box("h", (0, 0, 0), (5, 10, 10))],
    )
    lo, hi = d.bounds()
    np.testing.assert_allclose(lo, [0, 0, 0])
    np.testing.assert_allclose(hi, [10, 10, 10])


def test_difference_sample_avoids_the_hole(rng: np.random.Generator) -> None:
    d = Difference(
        id="d",
        children=[box("o", (0, 0, 0), (10, 10, 10)), box("h", (0, 0, 0), (5, 10, 10))],
    )
    pts = d.sample(3000, rng)
    assert d.contains(pts).all()
    assert (pts[:, 0] >= 5).all()


# -- deny composites ----------------------------------------------------------


def test_deny_composite_clamp_leaves_the_whole_volume() -> None:
    forbidden = Union(
        id="u",
        allow=False,
        children=[
            box("a", (0, 0, 0), (10, 10, 10)),
            box("b", (8, 0, 0), (20, 10, 10)),
        ],
    )
    # (9, 5, 5) sits in the overlap, so escaping one branch is not enough.
    out = forbidden.clamp([9, 5, 5])
    assert forbidden.permits(out)
    assert not forbidden.contains(out)


def test_deny_intersection_escapes_through_the_nearest_constraint() -> None:
    forbidden = Intersection(
        id="i",
        allow=False,
        children=[
            box("a", (0, 0, 0), (100, 100, 100)),
            box("b", (0, 0, 0), (3, 100, 100)),
        ],
    )
    # The volume is the 3 mm sliver; the nearest way out of (1, 50, 50) is x < 0.
    out = forbidden.clamp([1, 50, 50])
    assert forbidden.permits(out)
    assert out[0] < 0.0


def test_deny_difference_clamp() -> None:
    forbidden = Difference(
        id="d",
        allow=False,
        children=[box("o", (0, 0, 0), (10, 10, 10)), box("h", (4, 4, 4), (6, 6, 6))],
    )
    assert forbidden.permits([5, 5, 5])  # inside the hole, so outside the volume
    out = forbidden.clamp([1, 1, 1])
    assert forbidden.permits(out)


# -- nesting and the optimizer-facing helpers ---------------------------------


def test_nested_composites_clamp_consistently(rng: np.random.Generator) -> None:
    inner = Union(
        id="inner",
        children=[box("a", (0, 0, 0), (10, 10, 10)), box("b", (12, 0, 0), (20, 10, 10))],
    )
    nested = Intersection(
        id="outer",
        children=[
            inner,
            box("slab", (0, 0, 3), (20, 10, 7)),
            Sphere(id="keepout", center=(6, 5, 5), radius=2.0, allow=False),
        ],
    )
    pts = rng.uniform(-10, 30, size=(300, 3))
    out = nested.clamp(pts)
    good = nested.contains(out)
    assert good.mean() > 0.95
    assert nested.contains(nested.clamp(out[good])).all()


def test_walk_yields_the_whole_tree() -> None:
    nested = Intersection(
        id="outer",
        children=[
            Union(
                id="inner",
                children=[box("a", (0, 0, 0), (1, 1, 1))],
            ),
            box("b", (0, 0, 0), (1, 1, 1)),
        ],
    )
    assert [r.id for r in nested.walk()] == ["outer", "inner", "a", "b"]


def test_combine_folds_allow_and_deny_regions_together() -> None:
    user_space = box("user", (0, 0, 0), (100, 100, 100))
    illegal = box("rule", (40, 40, 40), (60, 60, 60), allow=False)
    both = combine([user_space, illegal], id="feasible")
    assert both.contains([10, 10, 10])
    assert not both.contains([50, 50, 50])
    assert both.contains(both.clamp([50, 50, 50]))


def test_combine_rejects_an_empty_list() -> None:
    with pytest.raises(ValueError):
        combine([])


def test_feasible_is_the_conjunction_of_permits() -> None:
    regions = [
        box("user", (0, 0, 0), (100, 100, 100)),
        box("rule", (40, 40, 40), (60, 60, 60), allow=False),
    ]
    pts = np.array([[10, 10, 10], [50, 50, 50], [-1, 0, 0]], dtype=float)
    assert feasible(regions, pts).tolist() == [True, False, False]
    assert feasible(regions, [10, 10, 10]) is True


def test_applies_to_scopes_a_region_to_node_ids() -> None:
    everything = box("all", (0, 0, 0), (1, 1, 1))
    rear_only = Box(
        id="rear",
        min=(0, 0, 0),
        max=(1, 1, 1),
        applies_to=["lr.*", "rr.*"],
    )
    except_patches = Box(
        id="nopatch",
        min=(0, 0, 0),
        max=(1, 1, 1),
        applies_to=["!*contact_patch"],
    )
    assert everything.applies_to_node("lf.lca_outboard")
    assert rear_only.applies_to_node("lr.wheel_center")
    assert not rear_only.applies_to_node("lf.wheel_center")
    assert except_patches.applies_to_node("lf.wheel_center")
    assert not except_patches.applies_to_node("lf.contact_patch")
    picked = regions_for_node([everything, rear_only, except_patches], "lf.contact_patch")
    assert [r.id for r in picked] == ["all"]


# -- payload and serialisation ------------------------------------------------


def test_composite_mesh_nests_its_children() -> None:
    u = Union(
        id="u",
        label="cell",
        children=[
            box("a", (0, 0, 0), (1, 1, 1)),
            Sphere(id="s", center=(5, 5, 5), radius=1.0, allow=False),
        ],
    )
    view = u.to_viewport()
    assert view["kind"] == "union"
    mesh = view["mesh"]
    assert mesh["type"] == "group" and mesh["op"] == "union"
    assert [c["id"] for c in mesh["children"]] == ["a", "s"]
    assert mesh["children"][0]["mesh"]["type"] == "box"
    assert mesh["children"][1]["allow"] is False


def test_composite_round_trips_through_json() -> None:
    original = Intersection(
        id="i",
        children=[
            Union(
                id="u",
                children=[
                    box("a", (0, 0, 0), (1, 1, 1)),
                    Polytope(
                        id="p",
                        a=[(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
                        b=[1.0] * 6,
                    ),
                ],
            ),
            Sphere(id="s", center=(0, 0, 0), radius=5.0, allow=False),
        ],
    )
    clone = parse_region(original.model_dump())
    assert clone == original
    assert isinstance(clone, Intersection)
    assert isinstance(clone.children[0], Union)
    assert isinstance(clone.children[0].children[1], Polytope)

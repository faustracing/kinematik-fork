# ============================================================================
#  KinematiK — Formula SAE suspension & vehicle dynamics toolkit
#  Created by Frederik Thio. Copyright (c) 2026 Frederik Thio.
#  Open source. Original author: Frederik Thio, creator of KinematiK.
# ============================================================================
"""External benchmark: Arévalo, Medina and Valladolid (2018), Ingenius 20, 95-106.

Their Table 3 hardpoints, solved in Lotus Suspension Analysis, give camber and
toe change over ±30 mm of wheel-centre travel. Paper axes are x forward, z up
from a datum with the wheel centre at 310 mm; KinematiK's are x rearward from
the axle and z up from the ground, with a 247.65 mm (19.5 in) tire radius.
"""
import numpy as np
import pytest

from suspension.kinematics import Hardpoints, SuspensionKinematics

R = 247.65
REAR = {"lower_front_inner": (335, 250, 203.59), "lower_rear_inner": (15, 250, 203.59), "upper_front_inner": (335, 290, 347.59),
        "upper_rear_inner": (15, 290, 347.59), "lower_outer": (148.83, 555, 219), "upper_outer": (171.17, 529, 401),
        "tie_rod_outer": (220, 549.14, 259.83), "tie_rod_inner": (220, 258.5, 234.2), "wheel_center": (160, 600, 310)}
FRONT = {"lower_front_inner": (1732, 212, 227.59), "lower_rear_inner": (1443.9, 212, 227.59), "upper_front_inner": (1732, 256, 377.59),
         "upper_rear_inner": (1446.6, 256, 377.59), "lower_outer": (1730, 520, 218.83), "upper_outer": (1760, 520, 400.83),
         "tie_rod_outer": (1790, 520, 218.83), "tie_rod_inner": (1750, 190, 227.59), "wheel_center": (1760, 590, 310)}


def _corner(pts, x_axle):
    hp = Hardpoints.default()
    for k, p in pts.items():
        setattr(hp, k, np.array([-(p[0] - x_axle), p[1], p[2] - (310.0 - R)]))
    hp.contact_patch = np.array([0.0, hp.wheel_center[1], 0.0])
    return hp


def _change_at_wheel_travel(hp, dz):
    k = SuspensionKinematics(hp); s0 = k.solve_at_travel(0.0); lo, hi = dz - 15, dz + 15
    for _ in range(50):
        mid = 0.5 * (lo + hi); w = k.solve_at_travel(mid).wheel_center[2] - s0.wheel_center[2]
        lo, hi = (mid, hi) if w < dz else (lo, mid)
    s = k.solve_at_travel(0.5 * (lo + hi)); return s.camber - s0.camber, s.toe - s0.toe


def test_rear_camber_matches_lotus():
    hp = _corner(REAR, 160.0)
    assert _change_at_wheel_travel(hp, 30.0)[0] == pytest.approx(-1.63, abs=0.015)
    assert _change_at_wheel_travel(hp, -30.0)[0] == pytest.approx(1.41, abs=0.015)


def test_front_camber_and_toe_match_lotus():
    hp = _corner(FRONT, 1760.0)
    cb, tb = _change_at_wheel_travel(hp, 30.0); cr, tr = _change_at_wheel_travel(hp, -30.0)
    assert cb == pytest.approx(-1.13, abs=0.015)
    assert tb == pytest.approx(0.0328, abs=0.001) and tr == pytest.approx(0.1393, abs=0.001)
    assert 0.9 <= cr < 1.0                                      # published as 0.9, one decimal

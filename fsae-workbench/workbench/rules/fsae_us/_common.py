"""Suspension- and chassis-geometry rules shared by the Formula SAE US years.

Every rule below quotes a clause that was read directly out of the published
rulebook; the limits are transcribed, not inferred. The two documents used are

* *Formula SAE Rules 2026*, Version 1.0, 10 Sept 2025
* *Formula SAE Rules 2027*, Version 1.0, 1 September 2026

and their V.1--V.4 sections are substantively identical, which is why the
encoded clauses live here rather than in either year module. See
``workbench/rules/GAPS.md`` for the clauses that were deliberately *not*
encoded.

One rule, :class:`RolloverTiltStability`, is a derived criterion rather than a
transcribed limit: V.1.3.1 states a requirement without a number and defers to
the IN.11.2.2 tilt test, so the 60 degree tilt angle is converted into a
track-to-CG-height ratio by elementary statics. That derivation is called out
in the rule's own description so an auditor knows which part came from the
document and which part is trigonometry.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from ...regions import Box, Region
from .. import _design_access as da
from ..base import Finding, MissingData, Rule, Severity

if TYPE_CHECKING:  # pragma: no cover
    from ...core.design import Design

#: Margin by which rule-derived exclusion volumes stop short of the legal
#: boundary, so a design sitting exactly on a limit is not clamped off it.
BOUNDARY_MARGIN_MM = 1e-6


class WheelbaseMinimum(Rule):
    """V.1.2: "The vehicle must have a minimum wheelbase of 1525 mm"."""

    id = "wheelbase_min"
    citation = "V.1.2"
    description = "Minimum wheelbase of 1525 mm"
    severity = Severity.BLOCKER
    limit_mm = 1525.0

    def _check(self, design: "Design") -> Finding | None:
        wb = da.wheelbase_mm(design)
        if wb >= self.limit_mm:
            return None
        return self.finding(
            f"wheelbase {wb:.1f} mm is below the {self.limit_mm:.0f} mm minimum",
            measured=wb,
            limit=self.limit_mm,
        )

    def _regions(self, design: "Design") -> list[Region]:
        lo, hi = da.design_bounds(design)
        out: list[Region] = []
        # ISO 8855 has +X forward, so the rear axle must sit at least
        # 1525 mm *behind* the front one and vice versa. Each exclusion is
        # anchored on the opposite axle as the design currently stands and is
        # regenerated whenever the ruleset is re-evaluated.
        for moving, anchor, sign in (("rear", "front", -1.0), ("front", "rear", +1.0)):
            try:
                anchor_x = float(
                    np.mean(
                        [p[0] for p in da.wheel_center_nodes(design, anchor).values()]
                    )
                )
                scoped = sorted(da.wheel_center_nodes(design, moving))
            except MissingData:
                continue
            if not scoped:
                continue
            limit_x = anchor_x + sign * self.limit_mm
            if sign < 0:
                box_min = (limit_x + BOUNDARY_MARGIN_MM, lo[1], lo[2])
                box_max = (max(hi[0], limit_x + 1.0), hi[1], hi[2])
            else:
                box_min = (min(lo[0], limit_x - 1.0), lo[1], lo[2])
                box_max = (limit_x - BOUNDARY_MARGIN_MM, hi[1], hi[2])
            out.append(
                Box(
                    id=f"rule.{self.id}.{moving}",
                    label=f"{self.citation} wheelbase minimum ({moving} axle)",
                    allow=False,
                    source=self.region_source,
                    applies_to=scoped,
                    min=box_min,
                    max=box_max,
                )
            )
        return out


class TrackRatioMinimum(Rule):
    """V.1.3.2: smaller track "no less than 75% of the larger track"."""

    id = "track_ratio_min"
    citation = "V.1.3.2"
    description = "Smaller track must be at least 75% of the larger track"
    severity = Severity.BLOCKER
    min_ratio = 0.75

    def _measure(self, design: "Design") -> tuple[float, float, str]:
        front = da.track_mm(design, "front")
        rear = da.track_mm(design, "rear")
        smaller_axle = "front" if front <= rear else "rear"
        return min(front, rear), max(front, rear), smaller_axle

    def _check(self, design: "Design") -> Finding | None:
        smaller, larger, axle = self._measure(design)
        if larger <= 0.0:
            raise MissingData("vehicle track is zero")
        ratio = smaller / larger
        if ratio >= self.min_ratio:
            return None
        return self.finding(
            f"{axle} track {smaller:.1f} mm is {ratio * 100:.1f}% of the "
            f"{larger:.1f} mm larger track, below the "
            f"{self.min_ratio * 100:.0f}% minimum",
            measured=ratio,
            limit=self.min_ratio,
        )

    def _regions(self, design: "Design") -> list[Region]:
        smaller, larger, axle = self._measure(design)
        half = self.min_ratio * larger / 2.0 - BOUNDARY_MARGIN_MM
        if half <= 0.0:
            return []
        scoped = sorted(da.wheel_center_nodes(design, axle))
        if not scoped:
            return []
        lo, hi = da.design_bounds(design)
        # A wheel centre closer to the centreline than half the minimum track
        # puts the narrow axle below 75% of the wide one.
        return [
            Box(
                id=f"rule.{self.id}",
                label=f"{self.citation} minimum {axle} half-track",
                allow=False,
                source=self.region_source,
                applies_to=scoped,
                min=(lo[0], -half, lo[2]),
                max=(hi[0], half, hi[2]),
            )
        ]


class RolloverTiltStability(Rule):
    """V.1.3.1 with IN.11.2.2: track and CG must survive a 60 degree tilt.

    V.1.3.1 requires that "the track and center of gravity must combine to
    provide sufficient rollover stability" and points at IN.11.2, where
    IN.11.2.2 requires the vehicle not to roll when tilted 60 degrees. The
    static tip condition for that test is ``(track / 2) / cg_height >= tan
    60``; the trigonometry is ours, the 60 degrees is the rulebook's.

    Reported as a warning rather than a blocker because the tilt test is run
    with the tallest driver aboard and fluids filled, neither of which the
    design model carries.
    """

    id = "rollover_tilt_stability"
    citation = "V.1.3.1 / IN.11.2.2"
    description = "Track and CG height must pass the 60 degree tilt test"
    severity = Severity.WARNING
    tilt_angle_deg = 60.0

    def _check(self, design: "Design") -> Finding | None:
        track = min(da.track_mm(design, "front"), da.track_mm(design, "rear"))
        cg = da.cg_height_mm(design)
        if cg <= 0.0:
            raise MissingData("CG height is zero or negative")
        required = math.tan(math.radians(self.tilt_angle_deg))
        ratio = (track / 2.0) / cg
        if ratio >= required:
            return None
        return self.finding(
            f"half-track to CG-height ratio {ratio:.2f} is below the {required:.2f} "
            f"needed to stay upright at {self.tilt_angle_deg:.0f} degrees "
            f"(track {track:.0f} mm, CG {cg:.0f} mm, bare vehicle, no driver)",
            measured=ratio,
            limit=required,
        )


class SuspensionTravelMinimum(Rule):
    """V.3.1.1: "usable minimum wheel travel of 50 mm, with a driver seated"."""

    id = "suspension_travel_min"
    citation = "V.3.1.1"
    description = "Usable wheel travel of at least 50 mm with a driver seated"
    severity = Severity.BLOCKER
    limit_mm = 50.0

    def _check(self, design: "Design") -> Finding | None:
        travel = da.suspension_travel_mm(design)
        if travel >= self.limit_mm:
            return None
        return self.finding(
            f"usable wheel travel {travel:.1f} mm is below the "
            f"{self.limit_mm:.0f} mm minimum",
            measured=travel,
            limit=self.limit_mm,
        )


class ShockAbsorbersPresent(Rule):
    """V.3.1.1: a fully operational suspension "with shock absorbers, front and rear"."""

    id = "shock_absorbers_present"
    citation = "V.3.1.1"
    description = "Every corner must carry a spring/damper unit"
    severity = Severity.BLOCKER

    def _check(self, design: "Design") -> Finding | None:
        bare: list[str] = []
        for corner_id, corner, _ in da.iter_corners(design):
            spring = getattr(corner, "spring", None)
            if spring is None:
                raise MissingData("Corner.spring")
            if str(spring) == "none":
                bare.append(corner_id)
        if not bare:
            return None
        return self.finding(
            "no spring/damper unit modelled at " + ", ".join(sorted(bare)),
            nodes=sorted(bare),
        )


class FrontSteeringMechanical(Rule):
    """V.3.2.1/V.3.2.2: the steering wheel must be mechanically linked to the
    front wheels, and electrically operated front steering is prohibited."""

    id = "front_steering_mechanical"
    citation = "V.3.2.1"
    description = "Front wheels must be mechanically steered"
    severity = Severity.BLOCKER

    def _check(self, design: "Design") -> Finding | None:
        front = da.axle(design, "front")
        steering = getattr(front, "steering", None)
        if steering is None:
            raise MissingData("Axle.steering on the front axle")
        if str(steering) == "none":
            return self.finding(
                "the front axle has no steering mechanism; V.3.2.1 requires the "
                "steering wheel to be mechanically connected to the front wheels"
            )
        return None


class SteeringFreePlayMax(Rule):
    """V.3.2.5: "Steering system free play must be less than seven degrees (7 deg)
    total measured at the steering wheel"."""

    id = "steering_free_play_max"
    citation = "V.3.2.5"
    description = "Steering free play below 7 degrees at the steering wheel"
    severity = Severity.BLOCKER
    limit_deg = 7.0

    def _check(self, design: "Design") -> Finding | None:
        play = da.angle_deg(
            da.vehicle(design),
            ("steering_free_play_deg", "steering_free_play"),
            "steering free play",
        )
        if play < self.limit_deg:
            return None
        return self.finding(
            f"steering free play {play:.1f} deg is not below the "
            f"{self.limit_deg:.0f} deg limit",
            measured=play,
            limit=self.limit_deg,
        )


class SteeringStopsPresent(Rule):
    """V.3.2.4: positive steering stops must prevent the linkage locking up and
    must keep the wheels and tires clear of suspension, bodywork and chassis.

    Always advisory: the clause is about hardware and about clearances to
    bodywork, and the design model carries neither. It is encoded so the
    requirement appears in the report with its citation rather than being
    silently dropped.
    """

    id = "steering_stops_present"
    citation = "V.3.2.4"
    description = "Positive steering stops limiting rack and wheel travel"
    severity = Severity.INFO
    advisory = True

    def _check(self, design: "Design") -> Finding | None:
        return self.finding(
            "verify by hand: positive steering stops must prevent four-bar "
            "lock-up and keep the wheels and tires clear of suspension, "
            "bodywork and chassis at full lock",
            severity=Severity.INFO,
        )


class RearSteerAngleMax(Rule):
    """V.3.2.10.a: rear wheel steering must be mechanically limited to a
    maximum of six degrees (6 deg) of angular movement."""

    id = "rear_steer_angle_max"
    citation = "V.3.2.10"
    description = "Rear wheel steering limited to 6 degrees"
    severity = Severity.BLOCKER
    limit_deg = 6.0

    def _check(self, design: "Design") -> Finding | None:
        rear = da.axle(design, "rear")
        steering = getattr(rear, "steering", None)
        if steering is None or str(steering) == "none":
            return None
        angle = da.angle_deg(
            da.vehicle(design),
            ("rear_steer_max_deg", "rear_steer_angle_deg"),
            "maximum rear steer angle",
        )
        if angle <= self.limit_deg:
            return None
        return self.finding(
            f"rear steer range {angle:.1f} deg exceeds the "
            f"{self.limit_deg:.0f} deg maximum",
            measured=angle,
            limit=self.limit_deg,
        )


class WheelDiameterMinimum(Rule):
    """V.4.1: "Wheels must be 203.2 mm (8.0 inches) or more in diameter"."""

    id = "wheel_diameter_min"
    citation = "V.4.1"
    description = "Wheel (rim) diameter of at least 203.2 mm"
    severity = Severity.BLOCKER
    limit_mm = 203.2

    def _check(self, design: "Design") -> Finding | None:
        d = da.rim_diameter_mm(design)
        if d >= self.limit_mm:
            return None
        return self.finding(
            f"wheel diameter {d:.1f} mm is below the {self.limit_mm:.1f} mm minimum",
            measured=d,
            limit=self.limit_mm,
        )


class GroundContactClearance(Rule):
    """V.1.4.1: ground clearance must prevent any part of the vehicle other
    than the tires from touching the ground during dynamic events.

    The clause carries no number, so the encoded constraint is the one thing it
    unambiguously implies: no hardpoint may sit at or below the ground plane.
    The separate 90 mm figure in V.1.4.2 applies to the Lower Side Impact
    Structure, which the design model does not represent -- see ``GAPS.md``.
    """

    id = "ground_contact_clearance"
    citation = "V.1.4.1"
    description = "No part of the vehicle except the tires may reach the ground"
    severity = Severity.WARNING
    #: Contact-patch nodes legitimately sit on the ground plane.
    exempt = ["!*contact_patch*", "!*.tire*"]

    def _check(self, design: "Design") -> Finding | None:
        offenders = [
            node_id
            for node_id, pos, _ in da.iter_nodes(design)
            if pos[2] <= 0.0 and not any(tag in node_id for tag in ("contact_patch",))
        ]
        if not offenders:
            return None
        return self.finding(
            f"{len(offenders)} hardpoint(s) are at or below the ground plane",
            nodes=sorted(offenders),
        )

    def _regions(self, design: "Design") -> list[Region]:
        lo, hi = da.design_bounds(design)
        return [
            Box(
                id=f"rule.{self.id}",
                label=f"{self.citation} below the ground plane",
                allow=False,
                source=self.region_source,
                applies_to=list(self.exempt),
                min=(lo[0], lo[1], min(lo[2], -1.0)),
                max=(hi[0], hi[1], 0.0),
            )
        ]


class OpenWheelKeepOut(Rule):
    """V.1.1.c: the open-wheel keep-out zone.

    "No part of the vehicle may enter a keep out zone defined by two lines
    extending vertically from positions 75 mm in front of and 75 mm aft of, the
    outer diameter of the front and rear tires in the side view elevation of
    the vehicle, with tires steered straight ahead. This keep out zone will
    extend laterally from the outside plane of the wheel/tire to the inboard
    plane of the wheel/tire."

    The clause governs bodywork and aerodynamic devices, not the suspension
    members that necessarily live inside the wheel's lateral band, so the
    emitted regions are scoped to bodywork and aero node ids. On a pure
    hardpoint design they bind nothing and exist for the viewport and for
    packaging work; they become live as soon as bodywork nodes are modelled.
    """

    id = "open_wheel_keep_out"
    citation = "V.1.1"
    description = "Keep-out zone 75 mm fore and aft of each tire"
    severity = Severity.WARNING
    margin_mm = 75.0
    #: Node-id globs the zone binds. Hardpoints are deliberately not included.
    scope = ["*bodywork*", "*aero*", "*wing*", "*nose*", "*sidepod*", "*undertray*"]

    def _check(self, design: "Design") -> Finding | None:
        return None

    def _regions(self, design: "Design") -> list[Region]:
        radius = da.tire_outer_diameter_mm(design) / 2.0
        width = da.tire_width_mm(design)
        lo, hi = da.design_bounds(design)
        out: list[Region] = []
        for corner_id, corner, mirrored in da.iter_corners(design):
            nodes = getattr(corner, "nodes", {})
            key = next(
                (
                    k
                    for k in (*da.WHEEL_CENTER_KEYS, *da.CONTACT_PATCH_KEYS)
                    if k in nodes
                ),
                None,
            )
            if key is None:
                continue
            pos = nodes[key].position
            if mirrored:
                pos = da._mirror_position(pos)
            x, y, _ = (float(c) for c in pos)
            inner, outer = sorted((abs(y) - width / 2.0, abs(y) + width / 2.0))
            y_lo, y_hi = (inner, outer) if y >= 0 else (-outer, -inner)
            out.append(
                Box(
                    id=f"rule.{self.id}.{corner_id}",
                    label=f"{self.citation} open-wheel keep-out ({corner_id})",
                    allow=False,
                    source=self.region_source,
                    applies_to=list(self.scope),
                    min=(x - radius - self.margin_mm, y_lo, lo[2]),
                    max=(x + radius + self.margin_mm, y_hi, hi[2]),
                )
            )
        return out


def common_rules() -> list[Rule]:
    """The clauses encoded identically for every Formula SAE US year shipped."""
    return [
        OpenWheelKeepOut(),
        WheelbaseMinimum(),
        TrackRatioMinimum(),
        RolloverTiltStability(),
        GroundContactClearance(),
        SuspensionTravelMinimum(),
        ShockAbsorbersPresent(),
        FrontSteeringMechanical(),
        SteeringStopsPresent(),
        SteeringFreePlayMax(),
        RearSteerAngleMax(),
        WheelDiameterMinimum(),
    ]

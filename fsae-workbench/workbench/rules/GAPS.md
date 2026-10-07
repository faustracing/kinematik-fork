# Encoded rules, and what was deliberately left out

Primary sources, both read in full for the sections listed:

| Document | Version | Date | Sections read |
| --- | --- | --- | --- |
| Formula SAE Rules 2026 | 1.0 | 10 Sept 2025 | V.1, V.2, V.3, V.4, F.5–F.8 (scan), IN.11 |
| Formula SAE Rules 2027 | 1.0 | 1 September 2026 | same, diffed line by line against 2026 |

Both are published on fsaeonline.com under Series Resources. The 2027 rulebook
is the official Version 1.0, **not** the 21 July 2026 public-comment draft
(GR.4.4 says draft rules "are not valid for competition").

## Encoded, with the limit transcribed from the document

| Rule id | Citation | Limit | Emits regions |
| --- | --- | --- | --- |
| `open_wheel_keep_out` | V.1.1 | 75 mm fore/aft of tire OD | yes (bodywork-scoped) |
| `wheelbase_min` | V.1.2 | 1525 mm | yes |
| `track_ratio_min` | V.1.3.2 | smaller track ≥ 75% of larger | yes |
| `ground_contact_clearance` | V.1.4.1 | no number; ground plane only | yes |
| `suspension_travel_min` | V.3.1.1 | 50 mm usable wheel travel | no |
| `shock_absorbers_present` | V.3.1.1 | shocks front and rear | no |
| `front_steering_mechanical` | V.3.2.1 | mechanical link required | no |
| `steering_free_play_max` | V.3.2.5 | < 7° at the steering wheel | no |
| `rear_steer_angle_max` | V.3.2.10 | 6° maximum | no |
| `wheel_diameter_min` | V.4.1 | 203.2 mm | no |

## Encoded, but derived rather than transcribed

| Rule id | Citation | Why it is derived |
| --- | --- | --- |
| `rollover_tilt_stability` | V.1.3.1 / IN.11.2.2 | V.1.3.1 states the requirement without a number and defers to IN.11.2, where IN.11.2.2 gives a 60° tilt. Converting that to `(track/2) / cg_height ≥ tan 60°` is elementary statics, not rulebook text. Reported as a WARNING, and it ignores driver mass and fluids, which the real tilt test includes. |

## Advisory only — cited but never decidable from the model

| Rule id | Citation | Why |
| --- | --- | --- |
| `steering_stops_present` | V.3.2.4 | The clause is about hardware existence and about clearance to bodywork and chassis at full lock. Neither the stops nor the bodywork are in the `Design` model, so the rule always returns an INFO finding telling the user to verify it by hand. |

`open_wheel_keep_out` is a half-case: the zone itself is fully specified by
V.1.1.c and is emitted as real geometry, but it governs bodywork and aero
devices rather than suspension members, which necessarily occupy the wheel's
lateral band. Its regions are therefore scoped to bodywork/aero node ids and
bind nothing on a pure-hardpoint design. They are correct geometry waiting for
a model that carries bodywork.

## Not encoded

Every entry here is a rule whose limit *is* printed in the document but which
cannot be evaluated against the `Design` contract as it stands. None of them
were guessed at.

| Citation | Rule | Why omitted |
| --- | --- | --- |
| V.1.1.a, V.1.1.b | Top 180° of the wheels unobstructed from above; wheels unobstructed in side view | Requires a bodywork and aero surface model. |
| V.1.4.2 | Distance to ground below the Lower Side Impact Structure must be ≤ 90 mm (should be ≤ 75 mm) | The LSIS (F.6.4.5, F.7.5.1) is a chassis member; `Design` has no chassis structure nodes. Becomes checkable the moment a frame model exists. |
| V.2.1.1, V.2.2 | 5th percentile female through 95th percentile male accommodation; 100° field of vision | Needs the driver package and the anthropometric templates from the Event Website. |
| V.3.1.3 | All suspension mounting points visible at Technical Inspection | Not a geometric predicate over hardpoints. |
| V.3.1.4, V.3.2.8 | Suspension and steering fasteners are Critical Fasteners (T.8.2) | Fastener-level detail outside the kinematic model. |
| V.3.1.5, V.3.2.9 | Spherical rod ends in double shear or captured by an oversize head/washer | Joint construction detail; no component model. |
| V.3.2.3, V.3.2.6, V.3.2.7 | Rigid mechanical linkage; rack mechanically attached to chassis; mechanical, visible column joints | Construction requirements, not geometry. |
| V.3.3.1–V.3.3.4 | Steering wheel clearance, quick disconnect, continuous near-circular perimeter | Steering wheel is not modelled. |
| V.4.2.1–V.4.2.3 | Wheel nut retention, lug bolt justification, anodized aluminium nuts | Hardware. |
| V.4.3.2 | Wet tire minimum tread depth 2.4 mm | Tire construction, not geometry; could be encoded if `TireSpec` ever carries a wet-tire tread depth. |
| V.4.3.3–V.4.3.5 | Tire sets, tire pressure, no hand cutting or warmers | Operational, not design-time. |
| F.5.6.5, F.5.6.6, T.1.1 | Driver Template and Cockpit Opening template | These are genuine geometric exclusion volumes and the best remaining candidates for a region contribution, but they are defined by a 2D template of circles (300 mm head, 200 mm and 200 mm body circles on a 280 mm spine) positioned against the Main Hoop and the pedal face. Encoding them needs cockpit and roll hoop geometry that `Design` does not yet carry. Flagged as the highest-value gap to close once a chassis model lands. |
| F.6.4.4, F.6.4.5, F.7.5.1 | Upper and Lower Side Impact Structure height bands (e.g. 345 mm above the lowest point of the Lower Side Impact Member) | Chassis structure, not suspension hardpoints. |
| IN.11.2.1 | No fluid leakage at 45° tilt | Not geometric. |

## Design-model fields the rules would need

These are the inputs the accessors in `_design_access.py` look for. Where they
are absent the rule degrades to an `INFO: not verifiable from the model`
finding rather than passing silently.

- `vehicle.wheelbase_mm`, `vehicle.track_front_mm`, `vehicle.track_rear_mm`,
  `vehicle.cg_height_mm`
- `vehicle.wheel_travel_mm` — usable wheel travel with a driver seated (V.3.1.1)
- `vehicle.steering_free_play_deg` (V.3.2.5)
- `vehicle.rear_steer_max_deg` (V.3.2.10.a, only when the rear axle steers)
- `tire.rim_diameter_mm` (V.4.1), `tire.outer_diameter_mm` and `tire.width_mm`
  (V.1.1.c keep-out zone)
- a `wheel_center` or `contact_patch` node in every corner

# FSAE Kinematics Workbench

A tire-first suspension design tool for Formula SAE. Design geometry inside
allowable regions you draw, check it against a selectable FSAE ruleset by
series and year, and optimise it against performance targets — on top of the
[Suspension Explorer](https://github.com/faustracing/suspension-explorer-core)
constraint solver.

This is Phase 0: the package scaffold, the `Design` model, the coordinate frame
adapter, the hardpoint importer, and the solver bridge. The Streamlit app, the
3D viewport, the region algebra, the rules modules, and the optimizer land on
top of this.

## Status

| Package | What it does | State |
| --- | --- | --- |
| `workbench.core` | `Design` model, coordinate frames, documented defaults | Phase 0, landed |
| `workbench.io` | Hardpoint CSV import with empirical frame verification | Phase 0, landed |
| `workbench.solve` | `Design` to solver geometry, sweep templates, `SolveResult` | Phase 0, landed |
| `workbench.regions` | Region algebra: box, sphere, polytope, boolean composites | Phase 3 |
| `workbench.rules` | FSAE rulesets keyed by `(series, year)` | Phase 3 |
| `workbench.objectives` | Target bands and scoring | Phase 4 |
| `workbench.optimize` | DOE seeding, NSGA-II, CMA-ES | Phase 4 |
| `workbench.app` | Streamlit pages | Phase 1 |
| `components/kinematics_viewport` | React/Three.js Streamlit component | Phase 2 |

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ../se-fork          # the solver; see below
pytest
```

### Solver dependency

`workbench.solve` imports `kinematics` (the installable package name of
suspension-explorer-core) in process. It is a hard runtime dependency, but it
is declared as the optional `solver` extra rather than in
`[project.dependencies]`, because it is not published to PyPI and has no stable
public git ref to pin yet. Until it has one, install it from a local checkout:

```bash
pip install -e /path/to/suspension-explorer-core    # /agent/repos/se-fork here
```

`uv` users get this automatically from `[tool.uv.sources]`.

**TODO(solver-pin):** once the repository is reachable, move it into
`[project.dependencies]` as
`kinematics @ git+https://github.com/faustracing/suspension-explorer-core@v0.10.0`,
delete the `solver` extra, and drop the `pytest.importorskip` guards in
`tests/conftest.py`. CI already installs from `vars.SOLVER_SPEC` when that
repository variable is set, and skips the solver tests with a notice when it is
not, so pinning is a one-line change in two places.

## Coordinates

**ISO 8855 millimetres everywhere: `+X` forward, `+Y` left, `+Z` up.** This is
also the solver's frame, so the bridge converts nothing. The design datum puts
the front axle centreline at `X = 0` and the static ground plane at `Z = 0`.

KinematiK uses SAE vehicle axes (`+X` rear, `+Y` right, `+Z` up). Anything
crossing that boundary goes through `workbench.core.frames.sae_to_iso` or
`iso_to_sae`.

Angles are degrees at every boundary — JSON, UI, CSV. Radians stay inside the
solver.

The importer does not take a file's frame on trust. `verify_frame` checks four
independent properties of the geometry and reports what it found:

1. The front corners sit forward of the rear corners.
2. The left corners sit on the `+Y` side of the right corners.
3. Pickups the file *names* "Fore" sit forward of their "Aft" partners — a
   naming-based check, so it catches a file whose corner labels and coordinates
   disagree.
4. Contact patches sit below their wheel centres.

A file in SAE axes fails the first three together and is converted. A file that
fails only some of them is contradictory and is rejected rather than guessed at.

## The reference car

`tests/fixtures/golden-car-hardpoints.csv` is the primary regression fixture: a
complete four-corner double wishbone car with explicit left *and* right
corners, so it exercises the solver's axle composition rather than its `Y = 0`
mirror shortcut.

Verified from the file itself: **ISO 8855**, wheelbase 1549.4 mm, front track
1168.4 mm, rear track 1143.0 mm, wheel centres 223.52 mm above the
contact-patch plane. Front corners are pullrod to rocker with tie rods, rear
are pushrod to rocker with toe links — detected from the geometry (a pullrod
runs downhill from the upright to the rocker, a pushrod runs uphill) rather
than assumed from the axle.

### The tire confirms the Z datum

The car runs Hoosier 18x6.0-10 R25B slicks: 228.60 mm unloaded radius. The
file's wheel centres sit 223.52 mm above its contact-patch plane, implying
**5.08 mm — exactly 0.200 in — of static deflection**, which is right for a
loaded FSAE slick. That is independent confirmation that the file's `Z = 0`
really is the ground plane and not a chassis datum.

It also settles which radius the kinematics must use. The solver resolves
contact patches, scrub radius, steering-axis ground offset, and roll centre
height against a ground plane one tire radius below the wheel plane, so the
*loaded* radius is the physically correct input. The loader measures it from
the file (`wheel centre Z − contact patch Z`) rather than assuming the unloaded
value. Using 228.60 mm instead would put the solved contact patches 5.08 mm
below the authored ones and shift the front roll centre by 2.74 mm and the
front scrub radius by 0.18 mm.

### What the file does not carry

A hardpoint export is only the linkage. Everything else lives in
`workbench.core.defaults` as structured data, with units and measurement
locations named, so a record is replaced rather than a constant hunted:

| Data | Value | Source |
| --- | --- | --- |
| Tire | Hoosier 18x6.0-10 R25B, loaded radius 223.52 mm | measured |
| Front spring | 43.78 N/mm **at the damper** | measured |
| Rear spring | 39.40 N/mm **at the damper** | measured |
| Mass properties | 290 kg, 48% front, 300 mm CG | placeholder |
| Rack | ±50 mm, 180° lock to lock | placeholder |
| Static camber / toe | 0.0° / 0.0° | policy, see below |
| Rocker pivot axis | normal of the rocker plane | reconstruction |
| Pushrod mount body | nearest wishbone | inference |

Spring rates are quoted **at the damper**, which is what a supplier quotes and
what these numbers are. Referring them to the wheel needs the motion ratio:
`rate_wheel = rate_damper * motion_ratio ** 2`. `SpringDefaults.measured_at`
records which end a rate belongs to so the squared conversion cannot be
silently skipped — use `workbench.solve.wheel_rate_n_per_mm`.

Two solver inputs are *reconstructed* rather than defaulted:

- **The wheel spin axis.** The solver locates the wheel from two hub points. A
  file with one wheel-centre row fixes the axis position but not its
  orientation, so static camber and toe have to come from somewhere. They
  default to zero, which keeps the loaded design a faithful reading of the
  file: the solved contact patch then lands exactly on the file's own
  contact-patch row, and any non-zero static camber or toe reported afterwards
  is real linkage behaviour rather than an assumption. **This is why the pinned
  static camber and toe are zero** — they are inputs this file does not have,
  not outputs. Camber *gain* is real geometry and unaffected.
- **The rocker pivot axis.** The solver needs two points on the rocker's
  rotation axis; the file gives one pivot point. A rocker is a planar body, so
  the normal of the plane through the pivot and its two pickups recovers the
  pin direction. Both axles converge at every step of every template with this
  reconstruction, and the resulting motion ratios (0.684 front, 0.761 rear) sit
  squarely in the normal FSAE range.

The pushrod **mount body** is an inference worth knowing about, because it is
the one assumption that materially moves a number. A hardpoint file does not
say which moving body a pushrod bolts to, and the locating linkage does not
care — but the motion ratio does:

| Front corner mount | Motion ratio |
| --- | --- |
| upper wishbone (chosen) | 0.684 |
| upright | 0.737 |
| lower wishbone | 0.317 |

| Rear corner mount | Motion ratio |
| --- | --- |
| lower wishbone (chosen) | 0.761 |
| upright | 0.836 |
| upper wishbone | 0.413 |

The loader picks the nearer wishbone outboard joint, which gives the upper
wishbone at the front (the pullrod tab sits 56 mm from the upper ball joint and
24 mm off the upper wishbone plane) and the lower wishbone at the rear (56 mm
from the lower ball joint, 20 mm off the plane). Neither pickup is exactly
coplanar with its arm, which is normal for a welded tab. Override it with
`Corner.pushrod_mount` if the car says otherwise; camber gain, bump steer,
caster, KPI, and scrub are all unchanged by the choice.

## Cross-check against KinematiK

KinematiK has its own double-wishbone solver. Running the same geometry through
both — the hardpoints converted to SAE axes, the same reconstructed rocker
axis, static camber and toe zeroed in both — agrees to five decimal places on
caster, KPI, and motion ratio. Two differences are *definitional*, not
numerical, and both matter when reading KinematiK output:

**1. "Scrub radius" means two different things.** KinematiK reports the signed
lateral offset from the wheel centre plane to the steering axis at the ground.
The solver reports the ISO 8855 §7.2.10 quantity: the unsigned distance in the
road plane from the contact centre to the steering-axis intersection, which
includes the longitudinal (trail) component. On the front corner those are
25.39 mm and 35.92 mm — the same geometry, two definitions. The solver metric
that corresponds to KinematiK's number is `steering_axis_offset_ground`, and it
matches to four decimal places.

**2. KinematiK's "wheel travel" is lower-ball-joint travel.** Its solver drives
the lower ball joint's Z to set travel, while `CornerState.travel` and the UI
label that axis as wheel-centre travel. The wheel centre moves less than the
ball joint, so every per-millimetre gradient KinematiK reports is scaled by
`1 / (d z_lbj / d z_hub)`:

| | solver, per hub mm | solver, per LBJ mm | KinematiK |
| --- | --- | --- | --- |
| Front camber gain, °/mm | −0.044843 | **−0.046102** | **−0.046102** |
| Rear camber gain, °/mm | −0.055070 | **−0.057451** | **−0.057452** |
| Front bump steer, °/mm | +0.0000927 | +0.0000953 | −0.0000920 ¹ |
| Rear bump steer, °/mm | −0.0017468 | −0.0018221 | +0.0018210 ¹ |

¹ KinematiK reports toe positive as toe-*out*, the solver positive as toe-*in*,
so these are the same number with opposite signs.

Re-expressed per lower-ball-joint millimetre the two solvers are identical to
five decimals, so **the solvers agree and only the travel datum differs**. The
ratio is 0.9728 at the front and 0.9587 at the rear, meaning KinematiK's
camber-gain and bump-steer figures are high by 2.8% and 4.3% respectively when
read as "per mm of wheel travel". Its motion ratio is *not* affected: that
calculation normalises by actual wheel-centre travel, which is why it agrees
with the solver to four decimals.

The workbench reports gradients per **wheel-centre** millimetre, which is the
conventional definition and the one the solver uses.

## Using it

```python
from workbench.io import load_design
from workbench.solve import motion_ratio, solve, wheel_rate_n_per_mm
from workbench.core.defaults import GOLDEN_CAR

design = load_design("tests/fixtures/golden-car-hardpoints.csv")
result = solve(design, "front", "bump", travel_mm=25.0, steps=21)

assert result.converged
static = result.static()
print(static["camber_left"], static["caster_left"], static["roll_center_z"])

ratio = motion_ratio(result)
rate = GOLDEN_CAR.front.spring.rate_n_per_mm
print(f"MR {ratio:.3f}, wheel rate {wheel_rate_n_per_mm(result, rate):.1f} N/mm")
```

Sweep templates are `bump`, `droop`, `roll`, `steer`, and `combined`. All five
hold the rack; on an unsteered axle the solver drops that hold, so `bump`,
`droop`, and `roll` work unchanged on both axles. `steer` and `combined` drive
the rack and are rejected early on an axle without one.

Non-convergence does **not** raise. `solve` catches the solver's `RuntimeError`
at the bridge boundary and returns `converged=False` with the failure as a
finding, so an optimizer can penalise a design instead of crashing on it.
Modelling errors — a missing node, a collinear rocker, an unsupported
architecture — do raise `WorkbenchSolveError`, because those are bugs in the
caller rather than properties of the design.

Inside any loop use `solve`, which calls `solve_evaluated_sweep` once.
`analyze_sweep` solves twice and must not appear in loop-shaped code.

## Repository layout

This directory is staged inside `kinematik-fork` until the standalone
`faustracing/fsae-workbench` repository exists, then extracted with
`git subtree split` with history intact. It is already self-contained — its own
`pyproject.toml`, licence, CI workflow, and fixtures — so the split needs no
rewriting. The CI workflow under `.github/workflows/` is inert where it sits,
since GitHub only runs workflows from a repository root.

## Licence

AGPL-3.0-only, matching both upstream projects. The AGPL's obligations attach
on distribution or on serving the software to others over a network, not to
private use — so a private repository is fine, but hosting this for other teams
owes them source.

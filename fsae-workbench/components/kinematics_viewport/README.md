# `kinematics_viewport`

Interactive 3D suspension viewport for the FSAE Kinematics Workbench, packaged
as a custom Streamlit component: a TypeScript + React + Three.js frontend plus a
thin Python wrapper.

Coordinates are **ISO 8855 millimetres — +X forward, +Y left, +Z up**, used
verbatim all the way into Three.js (the library's default up vector is flipped
to +Z rather than wrapping the scene in a rotated group, so gizmo axes and
camera presets agree with the vehicle frame).

## Layout

```
kinematics_viewport/
  __init__.py          # declare_component + kinematics_viewport(...) -> dict | None
  sample_payload.py    # demo-only four-corner payload
  demo_app.py          # minimal Streamlit demo
  frontend/
    index.html         # Streamlit entry
    dev.html           # standalone dev harness, no Python needed
    src/
      types.ts             # payload / event contract
      geometry.ts          # region containment, clamping, colours
      positionStore.ts     # mutable position source of truth for the scene
      useViewportEvents.ts # monotonic seq + debounced emits
      KinematicsViewport.tsx
      StreamlitApp.tsx     # Streamlit bridge
      DevHarness.tsx       # standalone harness with an event log
      sampleDesign.ts      # hardcoded harness payload
      scene/               # camera rig, grid/axes, nodes, links, regions, gizmos
```

## Build

```bash
cd frontend
npm install
npm run build      # tsc --noEmit && vite build -> frontend/build/
```

`frontend/build/` is gitignored; `__init__.py` raises a clear error if the
bundle is missing.

## Develop

Standalone frontend, no Python:

```bash
cd frontend && npm run dev     # http://localhost:3001/dev.html
```

Against a live Streamlit app:

```bash
cd frontend && npm run dev
KINEMATICS_VIEWPORT_DEV=1 streamlit run ../demo_app.py
```

Demo with the built bundle:

```bash
streamlit run fsae-workbench/components/kinematics_viewport/demo_app.py
```

## Python API

```python
from components.kinematics_viewport import kinematics_viewport, is_stale

event = kinematics_viewport(payload, height=680, key="viewport")
if not is_stale(event, st.session_state.last_seq):
    st.session_state.last_seq = event["seq"]
    ...
```

Streamlit replays the last component value on every script re-run, so callers
must track the highest `seq` they have processed and drop anything at or below
it. `is_stale` does that check.

## Why there is no value on every mouse move

`Streamlit.setComponentValue` re-runs the entire Python script. Emitting during
a drag is what makes custom components feel terrible, so the frontend never
emits from a pointer-move or animation-frame handler:

| Interaction | Emits | When |
| --- | --- | --- |
| Orbit / zoom / pan | never | — |
| Sweep play or scrub | never | frames are pushed once per solve |
| Node drag | `node_moved` | on pointer release, debounced 220 ms |
| Region move / resize / create | `region_changed` | on pointer release, debounced 220 ms |
| Click selection | `selection_changed` | debounced 280 ms |
| Commit button | `commit` | immediately, `committed: true` |

Node positions and sweep frames are written into a mutable `PositionStore` that
the scene reads inside `useFrame`, so dragging and playback never go through
React state either.

## Interactions

- **View presets** — `iso`, `front`, `side`, `top`. `top` uses +X as screen-up so
  the nose points up the page.
- **Select** a node to get a translate gizmo. The drag is clamped client-side
  against the node's bound `allow=true` region and pushed out of every
  `allow=false` region; a refused boundary flashes yellow. The server
  re-validates — the clamp is a UX affordance, not the source of truth.
- **Draw box** places a new allowable box wherever you click the ground plane,
  or around the selected node with *Box on node*. The new box is selected in
  resize mode so you can drag the handles immediately.
- **Move / Resize** switch the region gizmo between translate and scale.
- `allow=false` regions render as translucent red volumes; nodes carrying
  findings are tinted and haloed by severity, and the findings list selects the
  implicated node on click.
- **Commit to solver** flushes all uncommitted node moves and region edits in
  one event; **Discard** throws them away locally.

## Payload and event shapes

See `src/types.ts`. Node ids are `"{corner}.{node}"` or
`"{axle}.center.{node}"`. Regions carry a `mesh` the client can render:
`{min, max}` for boxes, `{center, radius}` for spheres. Region kinds without a
client mesh (polytopes, composites) are skipped client-side and left entirely
to server validation.

"""Interactive 3D suspension viewport as a custom Streamlit component.

The frontend is a TypeScript/React/Three.js bundle under ``frontend/``. Python's
only job here is to declare the component, hand it a JSON payload, and hand back
whatever event the frontend last emitted.

Payload and event shapes are defined by the workbench shared contracts; see
``PAYLOAD_SCHEMA_VERSION`` and the ``ViewportEvent`` keys below. Coordinates are
ISO 8855 millimetres: +X forward, +Y left, +Z up.

Set ``KINEMATICS_VIEWPORT_DEV=1`` to point the component at the Vite dev server
on ``http://localhost:3001`` instead of the built bundle.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, TypedDict

import streamlit.components.v1 as components

__all__ = [
    "PAYLOAD_SCHEMA_VERSION",
    "ViewportEvent",
    "kinematics_viewport",
    "is_stale",
]

PAYLOAD_SCHEMA_VERSION = 1

_DEV = os.environ.get("KINEMATICS_VIEWPORT_DEV", "").lower() in {"1", "true", "yes"}
_DEV_URL = os.environ.get("KINEMATICS_VIEWPORT_DEV_URL", "http://localhost:3001")
_BUILD_DIR = Path(__file__).parent / "frontend" / "build"

EventName = Literal[
    "node_moved", "region_changed", "selection_changed", "commit", "noop"
]


class ViewportEvent(TypedDict):
    """What the frontend sends back via ``Streamlit.setComponentValue``."""

    event: EventName
    seq: int
    nodeMoves: dict[str, list[float]]
    regions: list[dict[str, Any]]
    selection: list[str]
    committed: bool


if _DEV:
    _component_func = components.declare_component(
        "kinematics_viewport", url=_DEV_URL
    )
else:
    if not (_BUILD_DIR / "index.html").exists():
        raise RuntimeError(
            f"kinematics_viewport frontend bundle is missing at {_BUILD_DIR}. "
            "Run `npm install && npm run build` in "
            "components/kinematics_viewport/frontend, or set "
            "KINEMATICS_VIEWPORT_DEV=1 to use the Vite dev server."
        )
    _component_func = components.declare_component(
        "kinematics_viewport", path=str(_BUILD_DIR)
    )


def kinematics_viewport(
    payload: dict[str, Any],
    *,
    height: int = 620,
    key: str | None = None,
    default: ViewportEvent | None = None,
) -> ViewportEvent | None:
    """Render the viewport and return the most recent event, if any.

    Args:
        payload: Viewport payload. Must at minimum carry ``nodes``; ``links``,
            ``regions``, ``findings``, ``frames``, ``selection`` and ``view``
            are optional and default to empty on the frontend.
        height: Component height in CSS pixels.
        key: Streamlit widget key. Supply one if more than one viewport is on
            the page.
        default: Value returned before the frontend has emitted anything.

    Returns:
        The last :class:`ViewportEvent`, or ``default`` (``None``) if the
        component has not emitted yet.

    The frontend deliberately does not emit on pointer move. Values arrive on
    drag end, on region edit end, on debounced selection changes, and on an
    explicit commit, each carrying a monotonically increasing ``seq`` so stale
    events can be discarded with :func:`is_stale`.
    """
    payload = {"schemaVersion": PAYLOAD_SCHEMA_VERSION, **payload}
    return _component_func(
        payload=payload, height=height, key=key, default=default
    )


def is_stale(event: ViewportEvent | None, last_seq: int) -> bool:
    """True when ``event`` is missing or older than ``last_seq``.

    Streamlit replays the last component value on every script re-run, so an
    app that acts on events must keep the highest ``seq`` it has processed in
    session state and drop anything at or below it.
    """
    return event is None or int(event.get("seq", 0)) <= last_seq

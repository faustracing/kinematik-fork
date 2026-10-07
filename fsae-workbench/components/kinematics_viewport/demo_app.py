"""Minimal Streamlit demo for the kinematics viewport component.

Run from the repository root::

    streamlit run fsae-workbench/components/kinematics_viewport/demo_app.py

It stands in for the real workbench app: it holds a payload in session state,
applies events the viewport sends back, and shows how ``seq`` is used to drop
the stale value Streamlit replays on every script re-run.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from components.kinematics_viewport import (  # noqa: E402
    ViewportEvent,
    is_stale,
    kinematics_viewport,
)
from components.kinematics_viewport.sample_payload import sample_payload  # noqa: E402

st.set_page_config(page_title="Kinematics viewport demo", layout="wide")

if "payload" not in st.session_state:
    st.session_state.payload = sample_payload()
if "last_seq" not in st.session_state:
    st.session_state.last_seq = 0
if "history" not in st.session_state:
    st.session_state.history = []
if "solves" not in st.session_state:
    st.session_state.solves = 0


def apply_event(event: ViewportEvent) -> None:
    """Server-side handling. The server is authoritative, the client is not."""
    payload: dict[str, Any] = st.session_state.payload

    if event["nodeMoves"]:
        by_id = {n["id"]: n for n in payload["nodes"]}
        for node_id, position in event["nodeMoves"].items():
            node = by_id.get(node_id)
            if node is None:
                continue
            # Re-validate here against the real region algebra; the client
            # clamp is only a responsiveness affordance.
            node["p"] = [float(v) for v in position]

    if event["regions"]:
        regions = {r["id"]: r for r in payload["regions"]}
        for region in event["regions"]:
            regions[region["id"]] = region
        payload["regions"] = list(regions.values())

    if event["selection"]:
        payload["selection"] = event["selection"]

    if event["committed"]:
        # Where the workbench would call solve() and refresh frames/findings.
        st.session_state.solves += 1


left, right = st.columns([3, 1], gap="medium")

with right:
    st.subheader("Round trip")
    st.caption(
        "Drag a node, draw a box, scrub the sweep. Only discrete events reach "
        "Python; scrubbing never does."
    )
    if st.button("Reset design", use_container_width=True):
        st.session_state.payload = sample_payload()
        st.session_state.history = []
        st.session_state.solves = 0
        st.rerun()
    st.metric("Solver commits", st.session_state.solves)
    st.metric("Events applied", len(st.session_state.history))

with left:
    event = kinematics_viewport(
        copy.deepcopy(st.session_state.payload), height=680, key="viewport"
    )

if not is_stale(event, st.session_state.last_seq):
    assert event is not None
    st.session_state.last_seq = int(event["seq"])
    apply_event(event)
    st.session_state.history.insert(
        0, {"seq": event["seq"], "event": event["event"], "committed": event["committed"]}
    )
    del st.session_state.history[20:]
    if event["committed"]:
        st.rerun()

with right:
    st.subheader("Event log")
    if st.session_state.history:
        st.dataframe(st.session_state.history, use_container_width=True, hide_index=True)
    else:
        st.caption("No events yet.")

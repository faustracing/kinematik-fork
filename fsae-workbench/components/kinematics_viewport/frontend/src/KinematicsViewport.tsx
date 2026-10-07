import { Canvas } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  boxFromCenterSize,
  round3,
  SEVERITY_COLOR,
  SEVERITY_ORDER,
} from "./geometry";
import { PositionStore } from "./positionStore";
import { boundsOf, Scene, type GizmoMode, type Tool } from "./scene/Scene";
import "./scene/zUp";
import type {
  RegionPayload,
  Severity,
  Vec3,
  ViewPreset,
  ViewportEvent,
  ViewportPayload,
} from "./types";
import { useViewportEvents } from "./useViewportEvents";
import "./viewport.css";

const VIEW_PRESETS: ViewPreset[] = ["iso", "front", "side", "top"];
const DEFAULT_BOX_HALF: Vec3 = [60, 50, 45];
const REFUSAL_HOLD_MS = 650;
const NODE_MOVE_DEBOUNCE_MS = 220;
const REGION_DEBOUNCE_MS = 220;
const SELECTION_DEBOUNCE_MS = 280;
const PLAYBACK_INTERVAL_MS = 33;

export interface KinematicsViewportProps {
  payload: ViewportPayload;
  height: number;
  onEvent: (event: ViewportEvent) => void;
}

export function KinematicsViewport({ payload, height, onEvent }: KinematicsViewportProps) {
  const { emit } = useViewportEvents(onEvent);
  const storeRef = useRef<PositionStore>(null);
  if (storeRef.current === null) storeRef.current = new PositionStore();
  const store = storeRef.current;

  const [localMoves, setLocalMoves] = useState<Record<string, Vec3>>({});
  const [localRegions, setLocalRegions] = useState<Record<string, RegionPayload>>({});
  const [selection, setSelection] = useState<string[]>(payload.selection);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [gizmoMode, setGizmoMode] = useState<GizmoMode>("translate");
  const [preset, setPreset] = useState<ViewPreset>(payload.view?.preset ?? "iso");
  const [presetNonce, setPresetNonce] = useState(0);
  const [frameIndex, setFrameIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [refusedRegions, setRefusedRegions] = useState<Set<string>>(new Set());
  const [showAllowable, setShowAllowable] = useState(true);
  const [showIllegal, setShowIllegal] = useState(false);
  const [dragReadout, setDragReadout] = useState<Vec3 | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Mirrors of the edit state, so pointer-release handlers can build the next
  // value without a state-updater callback (which React may invoke twice).
  const localMovesRef = useRef(localMoves);
  const localRegionsRef = useRef(localRegions);
  const selectionRef = useRef(selection);
  localMovesRef.current = localMoves;
  localRegionsRef.current = localRegions;
  selectionRef.current = selection;

  // Python is the source of truth: a fresh payload supersedes local edits.
  const payloadKey = useMemo(() => JSON.stringify(payload.nodes.map((n) => [n.id, n.p])), [payload]);
  useEffect(() => {
    setLocalMoves({});
    setLocalRegions({});
    setFrameIndex(null);
    setPlaying(false);
    store.clearOverrides();
  }, [payloadKey, store]);

  useEffect(() => {
    setSelection(payload.selection);
  }, [payload.selection]);

  useEffect(() => {
    if (payload.view?.preset) setPreset(payload.view.preset);
  }, [payload.view?.preset]);

  store.setBaseFromPayload(payload, localMoves);

  const regions = useMemo(() => {
    const merged = payload.regions.map((r) => localRegions[r.id] ?? r);
    const known = new Set(merged.map((r) => r.id));
    for (const r of Object.values(localRegions)) {
      if (!known.has(r.id)) merged.push(r);
    }
    return merged;
  }, [payload.regions, localRegions]);

  const severityByNode = useMemo(() => {
    const map = new Map<string, Severity>();
    for (const finding of payload.findings) {
      for (const id of finding.nodes) {
        const current = map.get(id);
        if (!current || SEVERITY_ORDER[finding.severity] > SEVERITY_ORDER[current]) {
          map.set(id, finding.severity);
        }
      }
    }
    return map;
  }, [payload.findings]);

  const bounds = useMemo(
    () => boundsOf(payload.nodes.map((n) => n.p)),
    [payload.nodes],
  );

  const nodeById = useMemo(
    () => new Map(payload.nodes.map((n) => [n.id, n])),
    [payload.nodes],
  );

  const frames = payload.frames;
  const animating = frameIndex !== null;

  // Sweep playback writes straight into the position store; the scene reads it
  // in `useFrame`, so scrubbing never touches Python.
  useEffect(() => {
    if (frameIndex === null || !frames[frameIndex]) {
      store.clearOverrides();
      return;
    }
    store.setOverrides(frames[frameIndex].p);
  }, [frameIndex, frames, store]);

  useEffect(() => {
    if (!playing || frames.length === 0) return;
    const id = setInterval(() => {
      setFrameIndex((i) => ((i ?? 0) + 1) % frames.length);
    }, PLAYBACK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [playing, frames.length]);

  // A gizmo handle release lands as a canvas "pointer missed", which would
  // otherwise clear the selection the user is in the middle of editing.
  const gizmoDragging = useRef(false);
  const handleGizmoDragStateChange = useCallback((dragging: boolean) => {
    if (dragging) {
      gizmoDragging.current = true;
      return;
    }
    setTimeout(() => {
      gizmoDragging.current = false;
    }, 150);
  }, []);

  const refusalTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastRefusalKey = useRef("");
  const lastReadoutAt = useRef(0);

  // Stay yellow for the whole time a drag is pressed against a wall. The
  // previous timer started on the first refused sample and expired mid-drag,
  // so a slow pull to the face flashed and then went quiet.
  const showRefusal = useCallback((ids: string[]) => {
    if (ids.length > 0) {
      const key = ids.join("|");
      if (refusalTimer.current) {
        clearTimeout(refusalTimer.current);
        refusalTimer.current = null;
      }
      if (key === lastRefusalKey.current) return;
      lastRefusalKey.current = key;
      setRefusedRegions(new Set(ids));
      return;
    }
    if (lastRefusalKey.current === "" || refusalTimer.current) return;
    lastRefusalKey.current = "";
    refusalTimer.current = setTimeout(() => {
      refusalTimer.current = null;
      setRefusedRegions(new Set());
    }, REFUSAL_HOLD_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (refusalTimer.current) clearTimeout(refusalTimer.current);
    };
  }, []);

  const handleNodeDragMove = useCallback(
    (position: Vec3, refusedBy: string[]) => {
      showRefusal(refusedBy);
      // Throttled purely so the numeric readout stays legible; no event here.
      const now = performance.now();
      if (now - lastReadoutAt.current > 60) {
        lastReadoutAt.current = now;
        setDragReadout(position);
      }
    },
    [showRefusal],
  );

  const handleNodeDragEnd = useCallback(
    (nodeId: string, position: Vec3) => {
      setDragReadout(null);
      showRefusal([]);
      const next = { ...localMovesRef.current, [nodeId]: round3(position) };
      localMovesRef.current = next;
      setLocalMoves(next);
      emit("node_moved", {
        nodeMoves: next,
        selection: [nodeId],
        debounceMs: NODE_MOVE_DEBOUNCE_MS,
      });
    },
    [emit, showRefusal],
  );

  const handleRegionEditEnd = useCallback(
    (region: RegionPayload) => {
      const next = { ...localRegionsRef.current, [region.id]: region };
      localRegionsRef.current = next;
      setLocalRegions(next);
      emit("region_changed", {
        regions: Object.values(next),
        selection: selectionRef.current,
        debounceMs: REGION_DEBOUNCE_MS,
      });
    },
    [emit],
  );

  const changeSelection = useCallback(
    (ids: string[]) => {
      setSelection(ids);
      setSelectedRegionId(null);
      emit("selection_changed", { selection: ids, debounceMs: SELECTION_DEBOUNCE_MS });
    },
    [emit],
  );

  const createBoxAt = useCallback(
    (center: Vec3, bindNodeId?: string) => {
      const id = `user_box_${Date.now().toString(36)}`;
      const region: RegionPayload = {
        id,
        kind: "box",
        allow: true,
        label: bindNodeId
          ? `Envelope for ${nodeById.get(bindNodeId)?.label ?? bindNodeId}`
          : "New allowable box",
        source: "user",
        mesh: boxFromCenterSize(round3(center), [
          DEFAULT_BOX_HALF[0] * 2,
          DEFAULT_BOX_HALF[1] * 2,
          DEFAULT_BOX_HALF[2] * 2,
        ]),
      };
      const next = { ...localRegionsRef.current, [id]: region };
      localRegionsRef.current = next;
      setLocalRegions(next);
      emit("region_changed", {
        regions: Object.values(next),
        selection: bindNodeId ? [bindNodeId] : selectionRef.current,
        debounceMs: REGION_DEBOUNCE_MS,
      });
      setSelectedRegionId(id);
      setGizmoMode("scale");
      setTool("select");
      setToast("Box created — drag the handles to resize");
    },
    [emit, nodeById],
  );

  const handlePickNode = useCallback(
    (id: string, additive: boolean) => {
      if (tool === "draw_box") {
        createBoxAt(store.get(id), id);
        return;
      }
      const current = selectionRef.current;
      changeSelection(
        additive
          ? current.includes(id)
            ? current.filter((s) => s !== id)
            : [...current, id]
          : [id],
      );
    },
    [tool, changeSelection, createBoxAt, store],
  );

  const toggleRegionAllow = useCallback(
    (region: RegionPayload) => {
      handleRegionEditEnd({ ...region, allow: !region.allow });
    },
    [handleRegionEditEnd],
  );

  const dirty = Object.keys(localMoves).length > 0 || Object.keys(localRegions).length > 0;

  const commit = useCallback(() => {
    emit("commit", {
      nodeMoves: localMoves,
      regions: Object.values(localRegions),
      selection,
      committed: true,
    });
    setToast("Committed to Python");
  }, [emit, localMoves, localRegions, selection]);

  const reset = useCallback(() => {
    setLocalMoves({});
    setLocalRegions({});
    store.clearOverrides();
    setFrameIndex(null);
    setPlaying(false);
    setToast("Local edits discarded");
  }, [store]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 1800);
    return () => clearTimeout(id);
  }, [toast]);

  const selectedNode = selection.length === 1 ? nodeById.get(selection[0]) : undefined;
  const selectedRegion = selectedRegionId
    ? regions.find((r) => r.id === selectedRegionId)
    : undefined;
  const selectedPosition = selectedNode
    ? (dragReadout ?? localMoves[selectedNode.id] ?? store.get(selectedNode.id))
    : null;

  const currentFrame = frameIndex !== null ? frames[frameIndex] : undefined;

  return (
    <div className="kv-root" style={{ height }}>
      <div className="kv-canvas">
        <Canvas
          dpr={[1, 2]}
          gl={{ antialias: true, preserveDrawingBuffer: true }}
          camera={{ fov: 42, near: 8, far: 80000, position: [1400, 1200, 880] }}
          onPointerMissed={() => {
            if (gizmoDragging.current) return;
            if (selectedRegionId) setSelectedRegionId(null);
            else if (selectionRef.current.length) changeSelection([]);
          }}
        >
          <Scene
            nodes={payload.nodes}
            links={payload.links}
            regions={regions}
            store={store}
            bounds={bounds}
            preset={preset}
            presetNonce={presetNonce}
            selection={selection}
            selectedRegionId={selectedRegionId}
            severityByNode={severityByNode}
            refusedRegions={refusedRegions}
            showAllowable={showAllowable}
            showIllegal={showIllegal}
            tool={tool}
            gizmoMode={gizmoMode}
            editingLocked={animating}
            onPickNode={handlePickNode}
            onPickRegion={(id) => {
              setSelectedRegionId(id);
              setTool("select");
            }}
            onGizmoDragStateChange={handleGizmoDragStateChange}
            onDrawBoxAt={(p) => createBoxAt(p)}
            onNodeDragMove={handleNodeDragMove}
            onNodeDragEnd={handleNodeDragEnd}
            onRegionEditEnd={handleRegionEditEnd}
          />
        </Canvas>
      </div>

      <div className="kv-overlay">
        <div className="kv-topbar">
          <div className="kv-group">
            <span className="kv-group-label">View</span>
            {VIEW_PRESETS.map((p) => (
              <button
                key={p}
                className={`kv-btn ${preset === p ? "is-active" : ""}`}
                onClick={() => {
                  setPreset(p);
                  setPresetNonce((n) => n + 1);
                }}
              >
                {p}
              </button>
            ))}
          </div>

          <div className="kv-group">
            <span className="kv-group-label">Tool</span>
            <button
              className={`kv-btn ${tool === "select" ? "is-active" : ""}`}
              onClick={() => setTool("select")}
            >
              Select
            </button>
            <button
              className={`kv-btn ${tool === "draw_box" ? "is-active" : ""}`}
              onClick={() => setTool("draw_box")}
            >
              Draw box
            </button>
            <button
              className="kv-btn"
              disabled={!selectedNode}
              onClick={() => selectedNode && createBoxAt(store.get(selectedNode.id), selectedNode.id)}
            >
              Box on node
            </button>
          </div>

          <div className="kv-group">
            <span className="kv-group-label">Region</span>
            <button
              className={`kv-btn ${gizmoMode === "translate" ? "is-active" : ""}`}
              disabled={!selectedRegion}
              onClick={() => setGizmoMode("translate")}
            >
              Move
            </button>
            <button
              className={`kv-btn ${gizmoMode === "scale" ? "is-active" : ""}`}
              disabled={!selectedRegion}
              onClick={() => setGizmoMode("scale")}
            >
              Resize
            </button>
          </div>

          <span className="kv-spacer" />
          {dirty && <span className="kv-dirty">● uncommitted</span>}
          <div className="kv-group">
            <button className="kv-btn kv-danger" disabled={!dirty} onClick={reset}>
              Discard
            </button>
            <button className="kv-btn kv-primary" disabled={!dirty} onClick={commit}>
              Commit to solver
            </button>
          </div>
        </div>

        <div className="kv-bottombar">
          <div className="kv-timeline">
            <span className="kv-group-label">Sweep</span>
            <button
              className={`kv-btn ${playing ? "is-active" : ""}`}
              disabled={frames.length === 0}
              onClick={() => {
                if (frames.length === 0) return;
                setFrameIndex((i) => (i === null ? 0 : i));
                setPlaying((p) => !p);
              }}
            >
              {playing ? "Pause" : "Play"}
            </button>
            <button
              className="kv-btn"
              disabled={frames.length === 0 || frameIndex === null}
              onClick={() => {
                setPlaying(false);
                setFrameIndex(null);
              }}
            >
              Static
            </button>
            <input
              type="range"
              min={0}
              max={Math.max(0, frames.length - 1)}
              step={1}
              value={frameIndex ?? 0}
              disabled={frames.length === 0}
              onChange={(e) => {
                setPlaying(false);
                setFrameIndex(Number(e.target.value));
              }}
            />
            <span className="kv-readout">
              {frames.length === 0
                ? "no frames"
                : currentFrame
                  ? `${currentFrame.t.toFixed(1)} ${payload.frameUnit ?? ""}`.trim()
                  : "static"}
            </span>
          </div>

          <div className="kv-legend">
            <span className="kv-group-label">Volumes</span>
            <button
              type="button"
              className={`kv-swatch kv-toggle ${showAllowable ? "is-on" : "is-off"}`}
              aria-pressed={showAllowable}
              title="Show or hide allowable regions"
              onClick={() => setShowAllowable((v) => !v)}
            >
              <i style={{ background: "#22d3ee" }} /> allowable
            </button>
            <button
              type="button"
              className={`kv-swatch kv-toggle ${showIllegal ? "is-on" : "is-off"}`}
              aria-pressed={showIllegal}
              title="Show or hide illegal exclusion volumes"
              onClick={() => setShowIllegal((v) => !v)}
            >
              <i style={{ background: "#ef4444" }} /> illegal
            </button>
            <span className="kv-swatch">
              <i style={{ background: "#7dd3fc" }} /> chassis pickup
            </span>
            <span className="kv-swatch">
              <i style={{ background: "#facc15" }} /> selected
            </span>
          </div>
        </div>
      </div>

      <div className="kv-side">
        {selectedNode && (
          <div className="kv-card">
            <h4>Node</h4>
            <dl className="kv-kv">
              <dt>Label</dt>
              <dd>{selectedNode.label ?? selectedNode.id}</dd>
              <dt>Id</dt>
              <dd>{selectedNode.id}</dd>
              <dt>Kind</dt>
              <dd>{selectedNode.fixed ? "chassis pickup" : "solved / free"}</dd>
              <dt>Region</dt>
              <dd>{selectedNode.regionId ?? "unbounded"}</dd>
            </dl>
            {selectedPosition && (
              <div className="kv-coords">
                <div className="kv-coord">
                  <span>X fwd</span>
                  {selectedPosition[0].toFixed(1)}
                </div>
                <div className="kv-coord">
                  <span>Y left</span>
                  {selectedPosition[1].toFixed(1)}
                </div>
                <div className="kv-coord">
                  <span>Z up</span>
                  {selectedPosition[2].toFixed(1)}
                </div>
              </div>
            )}
            {animating && <p className="kv-hint">Return to static to edit nodes.</p>}
          </div>
        )}

        {selectedRegion && (
          <div className="kv-card">
            <h4>Region</h4>
            <dl className="kv-kv">
              <dt>Label</dt>
              <dd>{selectedRegion.label ?? selectedRegion.id}</dd>
              <dt>Kind</dt>
              <dd>{selectedRegion.kind}</dd>
              <dt>Source</dt>
              <dd>{selectedRegion.source ?? "user"}</dd>
              <dt>Mode</dt>
              <dd>{selectedRegion.allow ? "allowable" : "illegal"}</dd>
            </dl>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <button className="kv-btn" onClick={() => toggleRegionAllow(selectedRegion)}>
                Make {selectedRegion.allow ? "illegal" : "allowable"}
              </button>
              <button className="kv-btn" onClick={() => setSelectedRegionId(null)}>
                Done
              </button>
            </div>
          </div>
        )}

        {payload.findings.length > 0 && (
          <div className="kv-card">
            <h4>Findings</h4>
            {payload.findings.map((f, i) => (
              <div
                key={`${f.ruleId ?? "finding"}-${i}`}
                className="kv-finding"
                onClick={() => f.nodes.length && changeSelection([f.nodes[0]])}
              >
                <span
                  className="kv-chip"
                  style={{ background: SEVERITY_COLOR[f.severity] }}
                >
                  {f.severity}
                </span>
                <span>{f.message}</span>
              </div>
            ))}
          </div>
        )}

        <div className="kv-card">
          <h4>Frame</h4>
          <p className="kv-hint">
            ISO 8855, millimetres. +X forward, +Y left, +Z up. Drags are clamped to the
            node&apos;s allowable region client-side; the solver re-validates on commit.
          </p>
        </div>
      </div>

      {toast && <div className="kv-toast">{toast}</div>}
    </div>
  );
}

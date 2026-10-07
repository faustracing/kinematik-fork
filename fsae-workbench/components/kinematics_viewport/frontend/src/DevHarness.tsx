import { useCallback, useState } from "react";
import { KinematicsViewport } from "./KinematicsViewport";
import { normalizePayload } from "./payload";
import { SAMPLE_PAYLOAD } from "./sampleDesign";
import type { ViewportEvent, ViewportPayload } from "./types";
import "./dev.css";

const MAX_LOG = 40;

/**
 * Standalone harness: the component with a hardcoded payload and no Streamlit,
 * so the frontend can be developed and demonstrated without a Python app.
 *
 * It also plays the part of the server, applying committed node moves back
 * into the payload the way `workbench` will once the solver has re-run.
 */
export function DevHarness() {
  // Through the same normaliser the Streamlit path uses, so the harness
  // exercises the real payload handling rather than a privileged shortcut.
  const [payload, setPayload] = useState<ViewportPayload>(() =>
    normalizePayload(SAMPLE_PAYLOAD),
  );
  const [log, setLog] = useState<ViewportEvent[]>([]);
  const [applied, setApplied] = useState(0);

  const handleEvent = useCallback((event: ViewportEvent) => {
    setLog((prev) => [event, ...prev].slice(0, MAX_LOG));
    if (event.event !== "commit") return;
    setApplied((n) => n + 1);
    setPayload((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) =>
        event.nodeMoves[n.id] ? { ...n, p: event.nodeMoves[n.id] } : n,
      ),
      regions: mergeRegions(prev, event),
      selection: event.selection.length ? event.selection : prev.selection,
    }));
  }, []);

  return (
    <div className="dev-root">
      <header className="dev-header">
        <strong>FSAE Kinematics Workbench</strong>
        <span>viewport dev harness — hardcoded four-corner payload, no Python</span>
        <span className="dev-spacer" />
        <span className="dev-stat">server applies: {applied}</span>
        <span className="dev-stat">events: {log.length ? log[0].seq : 0}</span>
      </header>

      <div className="dev-body">
        <KinematicsViewport payload={payload} height={700} onEvent={handleEvent} />

        <aside className="dev-log">
          <h3>Component values sent to Python</h3>
          <p>
            Nothing is emitted while the pointer moves. Values appear only on drag end,
            region edit end, debounced selection changes, and explicit commit.
          </p>
          {log.length === 0 && <div className="dev-empty">No events yet.</div>}
          {log.map((event) => (
            <pre key={event.seq} className={`dev-event dev-${event.event}`}>
              {formatEvent(event)}
            </pre>
          ))}
        </aside>
      </div>
    </div>
  );
}

function mergeRegions(prev: ViewportPayload, event: ViewportEvent) {
  if (event.regions.length === 0) return prev.regions;
  const byId = new Map(prev.regions.map((r) => [r.id, r]));
  for (const r of event.regions) byId.set(r.id, r);
  return [...byId.values()];
}

function formatEvent(event: ViewportEvent): string {
  const moves = Object.entries(event.nodeMoves)
    .map(([id, p]) => `    ${id}: [${p.map((v) => v.toFixed(1)).join(", ")}]`)
    .join("\n");
  const regions = event.regions.map((r) => `    ${r.id} (${r.kind}, allow=${r.allow})`).join("\n");
  const lines = [`seq ${event.seq}  ${event.event}${event.committed ? "  [committed]" : ""}`];
  if (event.selection.length) lines.push(`  selection: ${event.selection.join(", ")}`);
  if (moves) lines.push(`  nodeMoves:\n${moves}`);
  if (regions) lines.push(`  regions:\n${regions}`);
  return lines.join("\n");
}

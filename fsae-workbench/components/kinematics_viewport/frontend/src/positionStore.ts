import type { Vec3, ViewportPayload } from "./types";

/**
 * Mutable position source of truth for the scene.
 *
 * Node positions change at pointer rate while dragging and at frame rate while
 * the sweep plays. Routing those through React state would re-render the whole
 * graph tens of times a second, so the scene reads positions from this store
 * inside `useFrame` instead and React state is reserved for discrete UI
 * changes (selection, tool, play/pause).
 */
export class PositionStore {
  /** Positions as last known from Python, plus uncommitted local node moves. */
  private base = new Map<string, Vec3>();
  /** Transient overrides: active drag target, or the current sweep frame. */
  private override = new Map<string, Vec3>();

  setBaseFromPayload(payload: ViewportPayload, localMoves: Record<string, Vec3>) {
    this.base.clear();
    for (const n of payload.nodes) this.base.set(n.id, n.p);
    for (const [id, p] of Object.entries(localMoves)) {
      if (this.base.has(id)) this.base.set(id, p);
    }
  }

  setBase(id: string, p: Vec3) {
    this.base.set(id, p);
  }

  getBase(id: string): Vec3 | undefined {
    return this.base.get(id);
  }

  setOverride(id: string, p: Vec3) {
    this.override.set(id, p);
  }

  setOverrides(entries: Record<string, Vec3>) {
    this.override.clear();
    for (const [id, p] of Object.entries(entries)) this.override.set(id, p);
  }

  clearOverrides() {
    this.override.clear();
  }

  clearOverride(id: string) {
    this.override.delete(id);
  }

  get(id: string): Vec3 {
    return this.override.get(id) ?? this.base.get(id) ?? ORIGIN;
  }

  has(id: string): boolean {
    return this.base.has(id);
  }
}

const ORIGIN: Vec3 = [0, 0, 0];

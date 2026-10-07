import { useCallback, useEffect, useRef } from "react";
import type { RegionPayload, Vec3, ViewportEvent, ViewportEventName } from "./types";

export interface EmitOptions {
  nodeMoves?: Record<string, Vec3>;
  regions?: RegionPayload[];
  selection?: string[];
  committed?: boolean;
  /** Milliseconds to coalesce successive emits of the same event name. */
  debounceMs?: number;
}

export type Emit = (event: ViewportEventName, options?: EmitOptions) => void;

/**
 * Emits component values back to Python with a monotonic `seq`.
 *
 * The hard rule here is that nothing in the scene may call `emit` from a
 * pointer-move or animation frame handler. Streamlit re-runs the whole script
 * on every component value, so values are produced only at discrete moments:
 * drag end, region edit end, debounced selection changes, and explicit commit.
 */
export function useViewportEvents(onEvent: (event: ViewportEvent) => void) {
  const seq = useRef(0);
  const onEventRef = useRef(onEvent);
  const timers = useRef(new Map<ViewportEventName, ReturnType<typeof setTimeout>>());
  const pending = useRef(new Map<ViewportEventName, ViewportEvent>());

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const active = timers.current;
    return () => {
      for (const t of active.values()) clearTimeout(t);
      active.clear();
    };
  }, []);

  const emit = useCallback<Emit>((event, options = {}) => {
    const { debounceMs = 0, ...rest } = options;
    seq.current += 1;
    const payload: ViewportEvent = {
      event,
      seq: seq.current,
      nodeMoves: rest.nodeMoves ?? {},
      regions: rest.regions ?? [],
      selection: rest.selection ?? [],
      committed: rest.committed ?? false,
    };

    if (debounceMs <= 0) {
      const existing = timers.current.get(event);
      if (existing) {
        clearTimeout(existing);
        timers.current.delete(event);
        pending.current.delete(event);
      }
      onEventRef.current(payload);
      return;
    }

    pending.current.set(event, payload);
    const existing = timers.current.get(event);
    if (existing) clearTimeout(existing);
    timers.current.set(
      event,
      setTimeout(() => {
        const queued = pending.current.get(event);
        timers.current.delete(event);
        pending.current.delete(event);
        if (queued) onEventRef.current(queued);
      }, debounceMs),
    );
  }, []);

  return { emit, currentSeq: seq };
}

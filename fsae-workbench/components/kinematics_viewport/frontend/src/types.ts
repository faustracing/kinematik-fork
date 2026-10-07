/**
 * Payload types for the kinematics viewport.
 *
 * These mirror the "Viewport component props and events" section of the
 * workbench shared contracts. All positions are ISO 8855 millimetres:
 * +X forward, +Y left, +Z up.
 */

export type Vec3 = [number, number, number];

export type Severity = "BLOCKER" | "WARNING" | "INFO";

export type ViewPreset = "iso" | "front" | "side" | "top";

export interface NodePayload {
  /** `"{corner}.{node}"` or `"{axle}.center.{node}"`. */
  id: string;
  p: Vec3;
  fixed?: boolean;
  regionId?: string | null;
  corner?: string | null;
  label?: string;
}

export type LinkKind =
  | "wishbone"
  | "tie_rod"
  | "toe_link"
  | "pushrod"
  | "pullrod"
  | "rocker"
  | "damper"
  | "upright"
  | "chassis"
  | string;

export interface LinkPayload {
  a: string;
  b: string;
  kind?: LinkKind;
}

export interface BoxMesh {
  min: Vec3;
  max: Vec3;
}

export interface SphereMesh {
  center: Vec3;
  radius: number;
}

export type RegionMesh = BoxMesh | SphereMesh;

export interface RegionPayload {
  id: string;
  kind: "box" | "sphere" | "polytope" | "union" | "intersection" | "difference";
  /** True = allowable volume, false = illegal/excluded. */
  allow: boolean;
  label?: string;
  /** `"user"` or `"rule:T.2.4"`. */
  source?: string;
  mesh?: RegionMesh;
}

export interface FindingPayload {
  nodes: string[];
  severity: Severity;
  message: string;
  ruleId?: string;
  citation?: string;
}

export interface FramePayload {
  /** Sweep abscissa, e.g. bump travel in mm or steer angle in degrees. */
  t: number;
  p: Record<string, Vec3>;
}

export interface ViewPayload {
  preset?: ViewPreset;
}

export interface ViewportPayload {
  schemaVersion: number;
  nodes: NodePayload[];
  links: LinkPayload[];
  regions: RegionPayload[];
  findings: FindingPayload[];
  frames: FramePayload[];
  selection: string[];
  view?: ViewPayload;
  /** Optional unit label for the sweep abscissa, used by the scrubber. */
  frameUnit?: string;
}

export type ViewportEventName =
  | "node_moved"
  | "region_changed"
  | "selection_changed"
  | "commit"
  | "noop";

export interface ViewportEvent {
  event: ViewportEventName;
  seq: number;
  nodeMoves: Record<string, Vec3>;
  regions: RegionPayload[];
  selection: string[];
  committed: boolean;
}

export const EMPTY_PAYLOAD: ViewportPayload = {
  schemaVersion: 1,
  nodes: [],
  links: [],
  regions: [],
  findings: [],
  frames: [],
  selection: [],
};

export function isBoxMesh(m: RegionMesh | undefined): m is BoxMesh {
  return !!m && Array.isArray((m as BoxMesh).min) && Array.isArray((m as BoxMesh).max);
}

export function isSphereMesh(m: RegionMesh | undefined): m is SphereMesh {
  return !!m && typeof (m as SphereMesh).radius === "number";
}

/** Fill in optional fields so the rest of the app can treat the payload as total. */
export function normalizePayload(raw: Partial<ViewportPayload> | null | undefined): ViewportPayload {
  if (!raw) return EMPTY_PAYLOAD;
  return {
    schemaVersion: raw.schemaVersion ?? 1,
    nodes: raw.nodes ?? [],
    links: raw.links ?? [],
    regions: raw.regions ?? [],
    findings: raw.findings ?? [],
    frames: raw.frames ?? [],
    selection: raw.selection ?? [],
    view: raw.view,
    frameUnit: raw.frameUnit,
  };
}

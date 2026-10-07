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

/** `[x, y, z, w]`. */
export type Quat = [number, number, number, number];

/** Triangle as indices into a polytope's `vertices`. */
export type Tri = [number, number, number];

export type RegionKind =
  | "box"
  | "obox"
  | "sphere"
  | "polytope"
  | "union"
  | "intersection"
  | "difference";

export interface BoxMesh {
  type: "box";
  min: Vec3;
  max: Vec3;
}

/** Oriented box: half extents in its own frame, rotated by `quaternion`. */
export interface OboxMesh {
  type: "obox";
  center: Vec3;
  halfExtents: Vec3;
  quaternion: Quat;
}

export interface SphereMesh {
  type: "sphere";
  center: Vec3;
  radius: number;
}

/** Closed triangulated surface. Faces index into `vertices`. */
export interface PolytopeMesh {
  type: "polytope";
  vertices: Vec3[];
  faces: Tri[];
}

export interface CompositeMesh {
  type: "union" | "intersection" | "difference";
  /** For `difference`, `children[0]` minus the rest. */
  children: RegionMesh[];
}

export type RegionMesh =
  | BoxMesh
  | OboxMesh
  | SphereMesh
  | PolytopeMesh
  | CompositeMesh;

export interface RegionPayload {
  id: string;
  kind: RegionKind;
  /** True = allowable volume, false = illegal/excluded. */
  allow: boolean;
  label?: string;
  /** `"user"` or `"rule:T.2.4"`. */
  source?: string;
  mesh?: RegionMesh;
  /**
   * Node-id globs naming the nodes this region binds, in `fnmatch` style
   * (`*` and `?` match across `.`). Empty or absent means the region is not
   * scoped by glob: an `allow=false` region then applies everywhere, and an
   * `allow=true` region binds only through `Node.regionId`.
   */
  appliesTo?: string[];
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
  return m?.type === "box";
}

export function isOboxMesh(m: RegionMesh | undefined): m is OboxMesh {
  return m?.type === "obox";
}

export function isSphereMesh(m: RegionMesh | undefined): m is SphereMesh {
  return m?.type === "sphere";
}

export function isPolytopeMesh(m: RegionMesh | undefined): m is PolytopeMesh {
  return m?.type === "polytope";
}

export function isCompositeMesh(m: RegionMesh | undefined): m is CompositeMesh {
  return m?.type === "union" || m?.type === "intersection" || m?.type === "difference";
}

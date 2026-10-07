/**
 * A hardcoded four-corner double-wishbone payload for the standalone dev
 * harness, so the frontend can be developed and demonstrated with no running
 * Python app.
 *
 * Numbers are loosely based on the workbench golden car: wheelbase 1549.4 mm,
 * front track 1168.4 mm, rear track 1143.0 mm, static wheel centre 223.52 mm.
 * ISO 8855 millimetres, +X forward / +Y left / +Z up.
 */

import type {
  FindingPayload,
  FramePayload,
  LinkPayload,
  NodePayload,
  RegionPayload,
  Vec3,
  ViewportPayload,
} from "./types";

const WHEELBASE = 1549.4;
const TRACK_FRONT = 1168.4;
const TRACK_REAR = 1143.0;
const WHEEL_CENTRE_Z = 223.52;

interface CornerSpec {
  id: string;
  axleX: number;
  halfTrack: number;
  /** +1 for a left corner, -1 for a right corner. */
  side: 1 | -1;
  steered: boolean;
  actuation: "pullrod" | "pushrod";
}

const CORNERS: CornerSpec[] = [
  { id: "lf", axleX: WHEELBASE / 2, halfTrack: TRACK_FRONT / 2, side: 1, steered: true, actuation: "pullrod" },
  { id: "rf", axleX: WHEELBASE / 2, halfTrack: TRACK_FRONT / 2, side: -1, steered: true, actuation: "pullrod" },
  { id: "lr", axleX: -WHEELBASE / 2, halfTrack: TRACK_REAR / 2, side: 1, steered: false, actuation: "pushrod" },
  { id: "rr", axleX: -WHEELBASE / 2, halfTrack: TRACK_REAR / 2, side: -1, steered: false, actuation: "pushrod" },
];

/** Corner-local layout: [dx from axle line, |y|, z]. */
const LAYOUT: Record<string, [number, number, number]> = {
  lca_fore_inboard: [125, 180, 110],
  lca_aft_inboard: [-145, 180, 118],
  lca_outboard: [4, 0 /* filled from halfTrack */, 112],
  uca_fore_inboard: [105, 212, 268],
  uca_aft_inboard: [-125, 212, 272],
  uca_outboard: [-6, 0, 306],
  steer_inboard: [92, 168, 136],
  steer_outboard: [74, 0, 152],
  rod_outboard: [-10, 0, 296],
  rocker_pivot: [-62, 196, 352],
  damper_inboard: [-168, 58, 338],
  wheel_center: [0, 0, WHEEL_CENTRE_Z],
  contact_patch: [0, 0, 0],
};

/** Outboard nodes sit inboard of the wheel centre by these amounts. */
const OUTBOARD_INSET: Record<string, number> = {
  lca_outboard: 62,
  uca_outboard: 88,
  steer_outboard: 72,
  rod_outboard: 96,
  wheel_center: 0,
  contact_patch: 0,
};

const LABELS: Record<string, string> = {
  lca_fore_inboard: "LCA Fore Inboard",
  lca_aft_inboard: "LCA Aft Inboard",
  lca_outboard: "LCA Outboard",
  uca_fore_inboard: "UCA Fore Inboard",
  uca_aft_inboard: "UCA Aft Inboard",
  uca_outboard: "UCA Outboard",
  steer_inboard: "Tie Rod Inboard",
  steer_outboard: "Tie Rod Outboard",
  rod_outboard: "Pushrod Outboard",
  rocker_pivot: "Rocker Pivot",
  damper_inboard: "Damper Inboard",
  wheel_center: "Wheel Centre",
  contact_patch: "Contact Patch",
};

/** Inboard chassis pickups are fixed; the rest are solved or driven. */
const FIXED = new Set([
  "lca_fore_inboard",
  "lca_aft_inboard",
  "uca_fore_inboard",
  "uca_aft_inboard",
  "steer_inboard",
  "rocker_pivot",
  "damper_inboard",
]);

/** Outboard nodes that swing with wheel travel in the synthetic sweep. */
const MOVING = ["lca_outboard", "uca_outboard", "steer_outboard", "rod_outboard", "wheel_center", "contact_patch"];

function cornerNodePosition(corner: CornerSpec, key: string): Vec3 {
  const [dx, absY, z] = LAYOUT[key];
  const inset = OUTBOARD_INSET[key];
  const y = inset === undefined ? absY : corner.halfTrack - inset;
  return [corner.axleX + dx, corner.side * y, z];
}

function cornerLabel(corner: CornerSpec, key: string): string {
  if (key === "steer_inboard") return corner.steered ? "Tie Rod Inboard" : "Toe Link Inboard";
  if (key === "steer_outboard") return corner.steered ? "Tie Rod Outboard" : "Toe Link Outboard";
  if (key === "rod_outboard") return corner.actuation === "pullrod" ? "Pullrod Outboard" : "Pushrod Outboard";
  return LABELS[key] ?? key;
}

function buildNodes(): NodePayload[] {
  const nodes: NodePayload[] = [];
  for (const corner of CORNERS) {
    for (const key of Object.keys(LAYOUT)) {
      nodes.push({
        id: `${corner.id}.${key}`,
        p: cornerNodePosition(corner, key),
        fixed: FIXED.has(key),
        corner: corner.id,
        label: cornerLabel(corner, key),
        regionId: regionForNode(corner.id, key),
      });
    }
  }
  nodes.push({
    id: "front.center.rack_center",
    p: [WHEELBASE / 2 + 92, 0, 136],
    fixed: true,
    corner: null,
    label: "Rack Centre",
    regionId: null,
  });
  return nodes;
}

function regionForNode(cornerId: string, key: string): string | null {
  if (cornerId === "lf" && key === "lca_fore_inboard") return "r_lf_lca_fore";
  if (cornerId === "lf" && key === "uca_fore_inboard") return "r_lf_uca_fore";
  if (cornerId === "lf" && key === "lca_outboard") return "r_lf_lca_outboard";
  return null;
}

const CORNER_LINKS: Array<[string, string, string]> = [
  ["lca_fore_inboard", "lca_outboard", "wishbone"],
  ["lca_aft_inboard", "lca_outboard", "wishbone"],
  ["uca_fore_inboard", "uca_outboard", "wishbone"],
  ["uca_aft_inboard", "uca_outboard", "wishbone"],
  ["steer_inboard", "steer_outboard", "tie_rod"],
  ["rod_outboard", "rocker_pivot", "pullrod"],
  ["rocker_pivot", "damper_inboard", "damper"],
  ["lca_outboard", "uca_outboard", "upright"],
  ["uca_outboard", "wheel_center", "upright"],
  ["lca_outboard", "wheel_center", "upright"],
  ["steer_outboard", "wheel_center", "upright"],
  ["wheel_center", "contact_patch", "upright"],
];

function buildLinks(): LinkPayload[] {
  const links: LinkPayload[] = [];
  for (const corner of CORNERS) {
    for (const [a, b, kind] of CORNER_LINKS) {
      const resolved = kind === "tie_rod" && !corner.steered ? "toe_link" : kind;
      const actuated = resolved === "pullrod" && corner.actuation === "pushrod" ? "pushrod" : resolved;
      links.push({ a: `${corner.id}.${a}`, b: `${corner.id}.${b}`, kind: actuated });
    }
  }
  // Chassis outline, so the car reads as a car in the viewport.
  const chassis: Array<[string, string]> = [
    ["lf.lca_fore_inboard", "rf.lca_fore_inboard"],
    ["lr.lca_fore_inboard", "rr.lca_fore_inboard"],
    ["lf.lca_fore_inboard", "lr.lca_aft_inboard"],
    ["rf.lca_fore_inboard", "rr.lca_aft_inboard"],
    ["lf.uca_fore_inboard", "rf.uca_fore_inboard"],
    ["lr.uca_fore_inboard", "rr.uca_fore_inboard"],
    ["lf.uca_fore_inboard", "lr.uca_aft_inboard"],
    ["rf.uca_fore_inboard", "rr.uca_aft_inboard"],
  ];
  for (const [a, b] of chassis) links.push({ a, b, kind: "chassis" });
  links.push({ a: "lf.steer_inboard", b: "front.center.rack_center", kind: "chassis" });
  links.push({ a: "rf.steer_inboard", b: "front.center.rack_center", kind: "chassis" });
  return links;
}

function boxAround(p: Vec3, half: Vec3): { min: Vec3; max: Vec3 } {
  return {
    min: [p[0] - half[0], p[1] - half[1], p[2] - half[2]],
    max: [p[0] + half[0], p[1] + half[1], p[2] + half[2]],
  };
}

function buildRegions(): RegionPayload[] {
  const lf = CORNERS[0];
  return [
    {
      id: "r_lf_lca_fore",
      kind: "box",
      allow: true,
      label: "LF LCA fore pickup envelope",
      source: "user",
      mesh: boxAround(cornerNodePosition(lf, "lca_fore_inboard"), [70, 55, 45]),
    },
    {
      id: "r_lf_uca_fore",
      kind: "box",
      allow: true,
      label: "LF UCA fore pickup envelope",
      source: "user",
      mesh: boxAround(cornerNodePosition(lf, "uca_fore_inboard"), [60, 50, 60]),
    },
    {
      id: "r_lf_lca_outboard",
      kind: "sphere",
      allow: true,
      label: "LF LCA outboard upright envelope",
      source: "user",
      mesh: { center: cornerNodePosition(lf, "lca_outboard"), radius: 55 },
    },
    {
      id: "r_cockpit",
      kind: "box",
      allow: false,
      label: "Cockpit template exclusion",
      source: "rule:T.2.4",
      mesh: { min: [-260, -175, 60], max: [320, 175, 520] },
    },
    {
      id: "r_ground",
      kind: "box",
      allow: false,
      label: "Minimum ground clearance",
      source: "rule:T.2.5",
      mesh: { min: [-900, -620, -40], max: [900, 620, 28] },
    },
  ];
}

function buildFindings(): FindingPayload[] {
  return [
    {
      nodes: ["lf.uca_outboard", "rf.uca_outboard"],
      severity: "WARNING",
      message: "Front camber gain is below the target band at 25 mm bump.",
      ruleId: "obj.camber_gain",
      citation: "objective",
    },
    {
      nodes: ["lf.steer_inboard"],
      severity: "BLOCKER",
      message: "Tie rod inboard pickup intrudes into the cockpit template exclusion.",
      ruleId: "fsae_us.T.2.4",
      citation: "T.2.4",
    },
    {
      nodes: ["lr.rocker_pivot"],
      severity: "INFO",
      message: "Rear motion ratio 1.08; consider lowering the rocker pivot for linearity.",
      ruleId: "obj.motion_ratio",
      citation: "objective",
    },
  ];
}

/**
 * Synthetic bump sweep: swing the outboard cluster about the lower inboard
 * axis so the scrubber has something physically plausible to animate.
 */
function buildFrames(nodes: NodePayload[]): FramePayload[] {
  const byId = new Map(nodes.map((n) => [n.id, n.p]));
  const frames: FramePayload[] = [];
  const steps = 41;
  for (let i = 0; i < steps; i++) {
    const t = -25 + (50 * i) / (steps - 1);
    const p: Record<string, Vec3> = {};
    for (const corner of CORNERS) {
      const pivot = byId.get(`${corner.id}.lca_fore_inboard`)!;
      // Arc radius from the lower inboard pivot out to the lower ball joint.
      const lower = byId.get(`${corner.id}.lca_outboard`)!;
      const arm = Math.hypot(lower[1] - pivot[1], lower[2] - pivot[2]);
      const theta = Math.asin(Math.max(-0.95, Math.min(0.95, t / arm)));
      for (const key of MOVING) {
        const base = byId.get(`${corner.id}.${key}`)!;
        const dy = base[1] - pivot[1];
        const dz = base[2] - pivot[2];
        const c = Math.cos(theta);
        const s = Math.sin(theta) * corner.side;
        p[`${corner.id}.${key}`] = [
          base[0],
          pivot[1] + dy * c - dz * s,
          pivot[2] + dy * s + dz * c,
        ];
      }
    }
    frames.push({ t: Math.round(t * 100) / 100, p });
  }
  return frames;
}

export function buildSamplePayload(): ViewportPayload {
  const nodes = buildNodes();
  return {
    schemaVersion: 1,
    nodes,
    links: buildLinks(),
    regions: buildRegions(),
    findings: buildFindings(),
    frames: buildFrames(nodes),
    selection: ["lf.lca_fore_inboard"],
    view: { preset: "iso" },
    frameUnit: "mm bump",
  };
}

export const SAMPLE_PAYLOAD = buildSamplePayload();

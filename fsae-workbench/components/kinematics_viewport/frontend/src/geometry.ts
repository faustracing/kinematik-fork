import type { BoxMesh, Severity, Vec3 } from "./types";

export const EPS = 1e-6;

export function add(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function length(a: Vec3): number {
  return Math.hypot(a[0], a[1], a[2]);
}

export function distance(a: Vec3, b: Vec3): number {
  return length(sub(a, b));
}

export function boxCenter(m: BoxMesh): Vec3 {
  return [
    (m.min[0] + m.max[0]) / 2,
    (m.min[1] + m.max[1]) / 2,
    (m.min[2] + m.max[2]) / 2,
  ];
}

export function boxSize(m: BoxMesh): Vec3 {
  return [
    Math.abs(m.max[0] - m.min[0]),
    Math.abs(m.max[1] - m.min[1]),
    Math.abs(m.max[2] - m.min[2]),
  ];
}

export function boxFromCenterSize(center: Vec3, size: Vec3): BoxMesh {
  const h: Vec3 = [Math.abs(size[0]) / 2, Math.abs(size[1]) / 2, Math.abs(size[2]) / 2];
  return {
    type: "box",
    min: [center[0] - h[0], center[1] - h[1], center[2] - h[2]],
    max: [center[0] + h[0], center[1] + h[1], center[2] + h[2]],
  };
}

/** Repair a box whose min/max got swapped by a negative-scale drag. */
export function normalizeBox(m: BoxMesh): BoxMesh {
  return {
    type: "box",
    min: [
      Math.min(m.min[0], m.max[0]),
      Math.min(m.min[1], m.max[1]),
      Math.min(m.min[2], m.max[2]),
    ],
    max: [
      Math.max(m.min[0], m.max[0]),
      Math.max(m.min[1], m.max[1]),
      Math.max(m.min[2], m.max[2]),
    ],
  };
}

export const SEVERITY_ORDER: Record<Severity, number> = {
  INFO: 1,
  WARNING: 2,
  BLOCKER: 3,
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  INFO: "#38bdf8",
  WARNING: "#fbbf24",
  BLOCKER: "#ef4444",
};

export const LINK_COLOR: Record<string, string> = {
  wishbone: "#e2e8f0",
  tie_rod: "#f472b6",
  toe_link: "#f472b6",
  pushrod: "#34d399",
  pullrod: "#34d399",
  rocker: "#a78bfa",
  damper: "#fb923c",
  upright: "#94a3b8",
  chassis: "#64748b",
};

export function linkColor(kind: string | undefined): string {
  return (kind && LINK_COLOR[kind]) || "#cbd5e1";
}

export function round3(v: Vec3, digits = 2): Vec3 {
  const f = 10 ** digits;
  return [
    Math.round(v[0] * f) / f,
    Math.round(v[1] * f) / f,
    Math.round(v[2] * f) / f,
  ];
}

import type { BoxMesh, RegionPayload, Severity, Vec3 } from "./types";
import { isBoxMesh, isSphereMesh } from "./types";

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
    min: [center[0] - h[0], center[1] - h[1], center[2] - h[2]],
    max: [center[0] + h[0], center[1] + h[1], center[2] + h[2]],
  };
}

/** Repair a box whose min/max got swapped by a negative-scale drag. */
export function normalizeBox(m: BoxMesh): BoxMesh {
  return {
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

export function containsPoint(region: RegionPayload, p: Vec3): boolean {
  const m = region.mesh;
  if (isBoxMesh(m)) {
    const b = normalizeBox(m);
    return (
      p[0] >= b.min[0] - EPS &&
      p[0] <= b.max[0] + EPS &&
      p[1] >= b.min[1] - EPS &&
      p[1] <= b.max[1] + EPS &&
      p[2] >= b.min[2] - EPS &&
      p[2] <= b.max[2] + EPS
    );
  }
  if (isSphereMesh(m)) {
    return distance(p, m.center) <= m.radius + EPS;
  }
  // Region kinds without a client-renderable mesh (polytope, composites) are
  // not clamped here; the server re-validates and is authoritative.
  return true;
}

/** Nearest point inside an `allow=true` region, or on/just outside an `allow=false` one. */
export function clampToRegion(region: RegionPayload, p: Vec3): Vec3 {
  const m = region.mesh;
  if (isBoxMesh(m)) {
    const b = normalizeBox(m);
    if (region.allow) {
      return [
        Math.min(Math.max(p[0], b.min[0]), b.max[0]),
        Math.min(Math.max(p[1], b.min[1]), b.max[1]),
        Math.min(Math.max(p[2], b.min[2]), b.max[2]),
      ];
    }
    return pushOutOfBox(b, p);
  }
  if (isSphereMesh(m)) {
    const d = sub(p, m.center);
    const len = length(d);
    if (region.allow) {
      if (len <= m.radius || len < EPS) return p;
      const k = m.radius / len;
      return [m.center[0] + d[0] * k, m.center[1] + d[1] * k, m.center[2] + d[2] * k];
    }
    if (len >= m.radius) return p;
    const dir: Vec3 = len < EPS ? [0, 0, 1] : [d[0] / len, d[1] / len, d[2] / len];
    return [
      m.center[0] + dir[0] * m.radius,
      m.center[1] + dir[1] * m.radius,
      m.center[2] + dir[2] * m.radius,
    ];
  }
  return p;
}

/** Move `p` to the nearest face of `b` if it is inside. */
function pushOutOfBox(b: BoxMesh, p: Vec3): Vec3 {
  const inside =
    p[0] > b.min[0] && p[0] < b.max[0] &&
    p[1] > b.min[1] && p[1] < b.max[1] &&
    p[2] > b.min[2] && p[2] < b.max[2];
  if (!inside) return p;
  let bestAxis = 0;
  let bestDist = Infinity;
  let bestValue = p[0];
  for (let axis = 0; axis < 3; axis++) {
    const toMin = p[axis] - b.min[axis];
    const toMax = b.max[axis] - p[axis];
    if (toMin < bestDist) {
      bestDist = toMin;
      bestAxis = axis;
      bestValue = b.min[axis];
    }
    if (toMax < bestDist) {
      bestDist = toMax;
      bestAxis = axis;
      bestValue = b.max[axis];
    }
  }
  const out: Vec3 = [p[0], p[1], p[2]];
  out[bestAxis] = bestValue;
  return out;
}

export interface ClampResult {
  position: Vec3;
  /** Region ids whose boundary refused the requested position. */
  refusedBy: string[];
}

/**
 * Clamp a requested drag position against the node's own allowable region and
 * every `allow=false` region in the scene.
 *
 * Purely a UX affordance: the server re-validates and is the source of truth.
 */
export function clampDrag(
  requested: Vec3,
  allowRegion: RegionPayload | undefined,
  denyRegions: RegionPayload[],
): ClampResult {
  let p = requested;
  const refusedBy: string[] = [];

  if (allowRegion && allowRegion.allow && !containsPoint(allowRegion, p)) {
    p = clampToRegion(allowRegion, p);
    refusedBy.push(allowRegion.id);
  }

  // A push-out can land the point back inside another deny volume, so iterate a
  // few times before giving up and taking the best effort.
  for (let pass = 0; pass < 4; pass++) {
    let moved = false;
    for (const region of denyRegions) {
      if (containsPoint(region, p)) {
        const next = clampToRegion(region, p);
        if (distance(next, p) > EPS) {
          p = next;
          moved = true;
          if (!refusedBy.includes(region.id)) refusedBy.push(region.id);
        }
      }
    }
    if (allowRegion && allowRegion.allow && !containsPoint(allowRegion, p)) {
      p = clampToRegion(allowRegion, p);
      if (!refusedBy.includes(allowRegion.id)) refusedBy.push(allowRegion.id);
      moved = true;
    }
    if (!moved) break;
  }

  return { position: p, refusedBy };
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

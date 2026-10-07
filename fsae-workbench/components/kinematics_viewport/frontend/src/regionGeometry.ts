/**
 * Client-side region containment and clamping.
 *
 * This exists purely so a drag feels responsive: the point is kept inside its
 * allowable volume and out of illegal ones at pointer rate, without a round
 * trip. The server re-validates with the real region algebra and is the only
 * source of truth, so the approximations noted below (surface projection for
 * polytopes, iterative projection for composites) are acceptable.
 */

import { distance, length, sub } from "./geometry";
import type {
  CompositeMesh,
  OboxMesh,
  PolytopeMesh,
  Quat,
  RegionMesh,
  RegionPayload,
  Vec3,
} from "./types";

const EPS = 1e-6;
/** Nudge used to land just outside a surface rather than exactly on it. */
const OUTSET = 1e-3;

// ---------------------------------------------------------------- quaternions

function rotate(q: Quat, v: Vec3): Vec3 {
  const [x, y, z, w] = q;
  const tx = 2 * (y * v[2] - z * v[1]);
  const ty = 2 * (z * v[0] - x * v[2]);
  const tz = 2 * (x * v[1] - y * v[0]);
  return [
    v[0] + w * tx + (y * tz - z * ty),
    v[1] + w * ty + (z * tx - x * tz),
    v[2] + w * tz + (x * ty - y * tx),
  ];
}

function conjugate(q: Quat): Quat {
  return [-q[0], -q[1], -q[2], q[3]];
}

function toLocal(mesh: OboxMesh, p: Vec3): Vec3 {
  return rotate(conjugate(mesh.quaternion), sub(p, mesh.center));
}

function toWorld(mesh: OboxMesh, p: Vec3): Vec3 {
  const r = rotate(mesh.quaternion, p);
  return [r[0] + mesh.center[0], r[1] + mesh.center[1], r[2] + mesh.center[2]];
}

// ----------------------------------------------------------------- axis boxes

function aabbContains(min: Vec3, max: Vec3, p: Vec3): boolean {
  for (let i = 0; i < 3; i++) {
    if (p[i] < min[i] - EPS || p[i] > max[i] + EPS) return false;
  }
  return true;
}

function aabbClampInside(min: Vec3, max: Vec3, p: Vec3): Vec3 {
  return [
    Math.min(Math.max(p[0], min[0]), max[0]),
    Math.min(Math.max(p[1], min[1]), max[1]),
    Math.min(Math.max(p[2], min[2]), max[2]),
  ];
}

/** Move `p` out through its nearest face if it is inside. */
function aabbPushOut(min: Vec3, max: Vec3, p: Vec3): Vec3 {
  if (!aabbContains(min, max, p)) return p;
  let bestAxis = 0;
  let bestDist = Infinity;
  let bestValue = p[0];
  for (let axis = 0; axis < 3; axis++) {
    const toMin = p[axis] - min[axis];
    const toMax = max[axis] - p[axis];
    if (toMin < bestDist) {
      bestDist = toMin;
      bestAxis = axis;
      bestValue = min[axis] - OUTSET;
    }
    if (toMax < bestDist) {
      bestDist = toMax;
      bestAxis = axis;
      bestValue = max[axis] + OUTSET;
    }
  }
  const out: Vec3 = [p[0], p[1], p[2]];
  out[bestAxis] = bestValue;
  return out;
}

// ----------------------------------------------------------------- polytopes

function triNormal(a: Vec3, b: Vec3, c: Vec3): Vec3 {
  const u = sub(b, a);
  const v = sub(c, a);
  return [
    u[1] * v[2] - u[2] * v[1],
    u[2] * v[0] - u[0] * v[2],
    u[0] * v[1] - u[1] * v[0],
  ];
}

/** Möller–Trumbore, used for parity counting rather than shading. */
function rayHitsTriangle(origin: Vec3, dir: Vec3, a: Vec3, b: Vec3, c: Vec3): boolean {
  const e1 = sub(b, a);
  const e2 = sub(c, a);
  const pv: Vec3 = [
    dir[1] * e2[2] - dir[2] * e2[1],
    dir[2] * e2[0] - dir[0] * e2[2],
    dir[0] * e2[1] - dir[1] * e2[0],
  ];
  const det = e1[0] * pv[0] + e1[1] * pv[1] + e1[2] * pv[2];
  if (Math.abs(det) < 1e-9) return false;
  const inv = 1 / det;
  const tv = sub(origin, a);
  const u = (tv[0] * pv[0] + tv[1] * pv[1] + tv[2] * pv[2]) * inv;
  if (u < 0 || u > 1) return false;
  const qv: Vec3 = [
    tv[1] * e1[2] - tv[2] * e1[1],
    tv[2] * e1[0] - tv[0] * e1[2],
    tv[0] * e1[1] - tv[1] * e1[0],
  ];
  const v = (dir[0] * qv[0] + dir[1] * qv[1] + dir[2] * qv[2]) * inv;
  if (v < 0 || u + v > 1) return false;
  const t = (e2[0] * qv[0] + e2[1] * qv[1] + e2[2] * qv[2]) * inv;
  return t > EPS;
}

/**
 * Ray-parity containment, so concave polytopes work too (the Python side may
 * send a difference of convex pieces already triangulated).
 */
function polytopeContains(mesh: PolytopeMesh, p: Vec3): boolean {
  const dir: Vec3 = [0.5773502691896258, 0.5773502691896258, 0.5773502691896258];
  let crossings = 0;
  for (const [i, j, k] of mesh.faces) {
    if (rayHitsTriangle(p, dir, mesh.vertices[i], mesh.vertices[j], mesh.vertices[k])) {
      crossings++;
    }
  }
  return crossings % 2 === 1;
}

function closestPointOnTriangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3): Vec3 {
  const ab = sub(b, a);
  const ac = sub(c, a);
  const ap = sub(p, a);
  const d1 = ab[0] * ap[0] + ab[1] * ap[1] + ab[2] * ap[2];
  const d2 = ac[0] * ap[0] + ac[1] * ap[1] + ac[2] * ap[2];
  if (d1 <= 0 && d2 <= 0) return a;

  const bp = sub(p, b);
  const d3 = ab[0] * bp[0] + ab[1] * bp[1] + ab[2] * bp[2];
  const d4 = ac[0] * bp[0] + ac[1] * bp[1] + ac[2] * bp[2];
  if (d3 >= 0 && d4 <= d3) return b;

  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const v = d1 / (d1 - d3);
    return [a[0] + ab[0] * v, a[1] + ab[1] * v, a[2] + ab[2] * v];
  }

  const cp = sub(p, c);
  const d5 = ab[0] * cp[0] + ab[1] * cp[1] + ab[2] * cp[2];
  const d6 = ac[0] * cp[0] + ac[1] * cp[1] + ac[2] * cp[2];
  if (d6 >= 0 && d5 <= d6) return c;

  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const w = d2 / (d2 - d6);
    return [a[0] + ac[0] * w, a[1] + ac[1] * w, a[2] + ac[2] * w];
  }

  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
    const w = (d4 - d3) / (d4 - d3 + (d5 - d6));
    return [b[0] + (c[0] - b[0]) * w, b[1] + (c[1] - b[1]) * w, b[2] + (c[2] - b[2]) * w];
  }

  const denom = 1 / (va + vb + vc);
  const v = vb * denom;
  const w = vc * denom;
  return [
    a[0] + ab[0] * v + ac[0] * w,
    a[1] + ab[1] * v + ac[1] * w,
    a[2] + ab[2] * v + ac[2] * w,
  ];
}

interface SurfaceHit {
  point: Vec3;
  normal: Vec3;
  distance: number;
}

function closestSurfacePoint(mesh: PolytopeMesh, p: Vec3): SurfaceHit | null {
  let best: SurfaceHit | null = null;
  for (const [i, j, k] of mesh.faces) {
    const a = mesh.vertices[i];
    const b = mesh.vertices[j];
    const c = mesh.vertices[k];
    const q = closestPointOnTriangle(p, a, b, c);
    const d = distance(p, q);
    if (!best || d < best.distance) {
      best = { point: q, normal: triNormal(a, b, c), distance: d };
    }
  }
  return best;
}

// ------------------------------------------------------------------- generic

export function meshContains(mesh: RegionMesh | undefined, p: Vec3): boolean {
  if (!mesh) return true;
  switch (mesh.type) {
    case "box":
      return aabbContains(mesh.min, mesh.max, p);
    case "obox": {
      const h = mesh.halfExtents;
      return aabbContains([-h[0], -h[1], -h[2]], h, toLocal(mesh, p));
    }
    case "sphere":
      return distance(p, mesh.center) <= mesh.radius + EPS;
    case "polytope":
      return polytopeContains(mesh, p);
    case "union":
      return mesh.children.some((c) => meshContains(c, p));
    case "intersection":
      return mesh.children.every((c) => meshContains(c, p));
    case "difference":
      return (
        meshContains(mesh.children[0], p) &&
        !mesh.children.slice(1).some((c) => meshContains(c, p))
      );
  }
}

/** Nearest point inside `mesh`. Returns `p` unchanged when already inside. */
export function meshClampInside(mesh: RegionMesh | undefined, p: Vec3): Vec3 {
  if (!mesh || meshContains(mesh, p)) return p;
  switch (mesh.type) {
    case "box":
      return aabbClampInside(mesh.min, mesh.max, p);
    case "obox": {
      const h = mesh.halfExtents;
      const local = aabbClampInside([-h[0], -h[1], -h[2]], h, toLocal(mesh, p));
      return toWorld(mesh, local);
    }
    case "sphere": {
      const d = sub(p, mesh.center);
      const len = length(d);
      if (len < EPS) return p;
      const k = mesh.radius / len;
      return [
        mesh.center[0] + d[0] * k,
        mesh.center[1] + d[1] * k,
        mesh.center[2] + d[2] * k,
      ];
    }
    case "polytope": {
      const hit = closestSurfacePoint(mesh, p);
      return hit ? hit.point : p;
    }
    case "union": {
      let best = p;
      let bestDist = Infinity;
      for (const child of mesh.children) {
        const q = meshClampInside(child, p);
        const d = distance(p, q);
        if (d < bestDist) {
          bestDist = d;
          best = q;
        }
      }
      return best;
    }
    case "intersection":
      return settle(p, (q) => {
        let out = q;
        for (const child of mesh.children) out = meshClampInside(child, out);
        return out;
      });
    case "difference":
      return settle(p, (q) => {
        let out = meshClampInside(mesh.children[0], q);
        for (const child of mesh.children.slice(1)) out = meshPushOut(child, out);
        return out;
      });
  }
}

/** Nearest point outside `mesh`. Returns `p` unchanged when already outside. */
export function meshPushOut(mesh: RegionMesh | undefined, p: Vec3): Vec3 {
  if (!mesh || !meshContains(mesh, p)) return p;
  switch (mesh.type) {
    case "box":
      return aabbPushOut(mesh.min, mesh.max, p);
    case "obox": {
      const h = mesh.halfExtents;
      const local = aabbPushOut([-h[0], -h[1], -h[2]], h, toLocal(mesh, p));
      return toWorld(mesh, local);
    }
    case "sphere": {
      const d = sub(p, mesh.center);
      const len = length(d);
      const dir: Vec3 = len < EPS ? [0, 0, 1] : [d[0] / len, d[1] / len, d[2] / len];
      const r = mesh.radius + OUTSET;
      return [
        mesh.center[0] + dir[0] * r,
        mesh.center[1] + dir[1] * r,
        mesh.center[2] + dir[2] * r,
      ];
    }
    case "polytope": {
      const hit = closestSurfacePoint(mesh, p);
      if (!hit) return p;
      const n = hit.normal;
      const len = length(n);
      if (len < EPS) return hit.point;
      // Nudge along the face normal, whichever side takes us out.
      const step: Vec3 = [(n[0] / len) * OUTSET, (n[1] / len) * OUTSET, (n[2] / len) * OUTSET];
      const forward: Vec3 = [
        hit.point[0] + step[0],
        hit.point[1] + step[1],
        hit.point[2] + step[2],
      ];
      if (!meshContains(mesh, forward)) return forward;
      return [hit.point[0] - step[0], hit.point[1] - step[1], hit.point[2] - step[2]];
    }
    case "union":
      return settle(p, (q) => {
        let out = q;
        for (const child of mesh.children) out = meshPushOut(child, out);
        return out;
      });
    case "intersection": {
      // Leaving any one child leaves the intersection; take the cheapest exit.
      let best = p;
      let bestDist = Infinity;
      for (const child of mesh.children) {
        const q = meshPushOut(child, p);
        const d = distance(p, q);
        if (d > EPS && d < bestDist) {
          bestDist = d;
          best = q;
        }
      }
      return best;
    }
    case "difference": {
      const out = meshPushOut(mesh.children[0], p);
      let best = out;
      let bestDist = distance(p, out);
      for (const child of mesh.children.slice(1)) {
        const q = meshClampInside(child, p);
        const d = distance(p, q);
        if (d < bestDist) {
          bestDist = d;
          best = q;
        }
      }
      return best;
    }
  }
}

/** Repeat a projection until it stops moving, or we run out of patience. */
function settle(p: Vec3, step: (q: Vec3) => Vec3, passes = 6): Vec3 {
  let current = p;
  for (let i = 0; i < passes; i++) {
    const next = step(current);
    if (distance(next, current) < EPS) return next;
    current = next;
  }
  return current;
}

// ------------------------------------------------------------------- editing

/** Axis-aligned bounds of any mesh, used to seat an edit proxy. */
export function meshBounds(mesh: RegionMesh): { min: Vec3; max: Vec3 } {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  const grow = (p: Vec3) => {
    for (let i = 0; i < 3; i++) {
      if (p[i] < min[i]) min[i] = p[i];
      if (p[i] > max[i]) max[i] = p[i];
    }
  };
  switch (mesh.type) {
    case "box":
      grow(mesh.min);
      grow(mesh.max);
      break;
    case "obox": {
      const h = mesh.halfExtents;
      for (const sx of [-1, 1]) {
        for (const sy of [-1, 1]) {
          for (const sz of [-1, 1]) {
            grow(toWorld(mesh, [sx * h[0], sy * h[1], sz * h[2]]));
          }
        }
      }
      break;
    }
    case "sphere": {
      const r = mesh.radius;
      grow([mesh.center[0] - r, mesh.center[1] - r, mesh.center[2] - r]);
      grow([mesh.center[0] + r, mesh.center[1] + r, mesh.center[2] + r]);
      break;
    }
    case "polytope":
      for (const v of mesh.vertices) grow(v);
      break;
    default:
      for (const child of mesh.children) {
        const b = meshBounds(child);
        grow(b.min);
        grow(b.max);
      }
  }
  return { min, max };
}

/** Rigid translation of any mesh, so composites can be dragged as a unit. */
export function translateMesh(mesh: RegionMesh, d: Vec3): RegionMesh {
  const shift = (p: Vec3): Vec3 => [p[0] + d[0], p[1] + d[1], p[2] + d[2]];
  switch (mesh.type) {
    case "box":
      return { ...mesh, min: shift(mesh.min), max: shift(mesh.max) };
    case "obox":
      return { ...mesh, center: shift(mesh.center) };
    case "sphere":
      return { ...mesh, center: shift(mesh.center) };
    case "polytope":
      return { ...mesh, vertices: mesh.vertices.map(shift) };
    default:
      return {
        ...mesh,
        children: mesh.children.map((c) => translateMesh(c, d)),
      } satisfies CompositeMesh;
  }
}

/** Only primitives with an obvious single extent can be resized in the scene. */
export function isResizable(mesh: RegionMesh | undefined): boolean {
  return mesh?.type === "box" || mesh?.type === "obox" || mesh?.type === "sphere";
}

// --------------------------------------------------------------- applicability

const globCache = new Map<string, RegExp>();

/**
 * `fnmatch` semantics, matching the Python side: `*` and `?` match across the
 * `.` separator, and `[...]` classes pass through.
 */
export function matchesGlob(pattern: string, value: string): boolean {
  let re = globCache.get(pattern);
  if (!re) {
    let source = "";
    for (let i = 0; i < pattern.length; i++) {
      const ch = pattern[i];
      if (ch === "*") {
        // Collapse `**` so callers used to recursive globs get the same result.
        while (pattern[i + 1] === "*") i++;
        source += ".*";
      } else if (ch === "?") {
        source += ".";
      } else if (ch === "[") {
        const close = pattern.indexOf("]", i + 1);
        if (close === -1) {
          source += "\\[";
        } else {
          const body = pattern.slice(i + 1, close).replace(/^!/, "^");
          source += `[${body}]`;
          i = close;
        }
      } else {
        source += ch.replace(/[.+^${}()|\\]/g, "\\$&");
      }
    }
    re = new RegExp(`^${source}$`);
    globCache.set(pattern, re);
  }
  return re.test(value);
}

/**
 * Whether `region` constrains `nodeId`.
 *
 * `appliesTo` is authoritative when present. When it is absent the region is
 * unscoped: an illegal volume applies to every node, while an allowable volume
 * binds only through the node's own `regionId`.
 */
export function regionApplies(
  region: RegionPayload,
  nodeId: string,
  nodeRegionId: string | null | undefined,
): boolean {
  if (region.appliesTo && region.appliesTo.length > 0) {
    return region.appliesTo.some((pattern) => matchesGlob(pattern, nodeId));
  }
  return region.allow ? region.id === nodeRegionId : true;
}

export interface ClampResult {
  position: Vec3;
  /** Region ids whose boundary refused the requested position. */
  refusedBy: string[];
}

/**
 * Clamp a requested drag position against every region that binds this node.
 *
 * A UX affordance, not the source of truth: the server re-validates with the
 * real region algebra on the next event.
 */
export function clampDrag(
  requested: Vec3,
  nodeId: string,
  nodeRegionId: string | null | undefined,
  regions: RegionPayload[],
): ClampResult {
  const binding = regions.filter(
    (r) => r.mesh && regionApplies(r, nodeId, nodeRegionId),
  );
  if (binding.length === 0) return { position: requested, refusedBy: [] };

  const allow = binding.filter((r) => r.allow);
  const deny = binding.filter((r) => !r.allow);

  let p = requested;
  const refusedBy: string[] = [];
  const note = (id: string) => {
    if (!refusedBy.includes(id)) refusedBy.push(id);
  };

  // Pushing out of one volume can land inside another, so iterate to a fixed
  // point rather than trusting a single pass.
  for (let pass = 0; pass < 6; pass++) {
    let moved = false;
    for (const region of allow) {
      if (!meshContains(region.mesh, p)) {
        const next = meshClampInside(region.mesh, p);
        if (distance(next, p) > EPS) {
          p = next;
          moved = true;
          note(region.id);
        }
      }
    }
    for (const region of deny) {
      if (meshContains(region.mesh, p)) {
        const next = meshPushOut(region.mesh, p);
        if (distance(next, p) > EPS) {
          p = next;
          moved = true;
          note(region.id);
        }
      }
    }
    if (!moved) break;
  }

  return { position: p, refusedBy };
}

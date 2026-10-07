/**
 * Tolerant normalisation of the payload Python sends.
 *
 * Region meshes carry a `type` discriminator inside `mesh`. The Python side is
 * snake_case and the rest of this payload is camelCase, so both spellings are
 * accepted for multi-word fields (`applies_to`/`appliesTo`,
 * `half_extents`/`halfExtents`) and the normalised result is always camelCase.
 * Anything we cannot make sense of is dropped to `undefined` rather than
 * throwing: an unrenderable region is still validated server-side.
 */

import {
  EMPTY_PAYLOAD,
  type BoxMesh,
  type CompositeMesh,
  type OboxMesh,
  type PolytopeMesh,
  type Quat,
  type RegionKind,
  type RegionMesh,
  type RegionPayload,
  type SphereMesh,
  type Tri,
  type Vec3,
  type ViewportPayload,
} from "./types";

type Raw = Record<string, unknown>;

function pick(raw: Raw, ...names: string[]): unknown {
  for (const name of names) {
    if (raw[name] !== undefined && raw[name] !== null) return raw[name];
  }
  return undefined;
}

function asVec3(value: unknown): Vec3 | undefined {
  if (!Array.isArray(value) || value.length < 3) return undefined;
  const [x, y, z] = value;
  if (typeof x !== "number" || typeof y !== "number" || typeof z !== "number") {
    return undefined;
  }
  return [x, y, z];
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const out = value.filter((v): v is string => typeof v === "string");
  return out.length ? out : undefined;
}

const IDENTITY: Quat = [0, 0, 0, 1];

/** Degrees, XYZ intrinsic order — the convention the contracts use for angles. */
function eulerDegToQuat([rx, ry, rz]: Vec3): Quat {
  const h = Math.PI / 360;
  const [cx, sx] = [Math.cos(rx * h), Math.sin(rx * h)];
  const [cy, sy] = [Math.cos(ry * h), Math.sin(ry * h)];
  const [cz, sz] = [Math.cos(rz * h), Math.sin(rz * h)];
  return [
    sx * cy * cz + cx * sy * sz,
    cx * sy * cz - sx * cy * sz,
    cx * cy * sz + sx * sy * cz,
    cx * cy * cz - sx * sy * sz,
  ];
}

/** Column-major-agnostic: expects three row vectors forming an orthonormal basis. */
function basisToQuat(rows: Vec3[]): Quat {
  const [r0, r1, r2] = rows;
  const m00 = r0[0], m01 = r0[1], m02 = r0[2];
  const m10 = r1[0], m11 = r1[1], m12 = r1[2];
  const m20 = r2[0], m21 = r2[1], m22 = r2[2];
  const trace = m00 + m11 + m22;
  if (trace > 0) {
    const s = 0.5 / Math.sqrt(trace + 1);
    return [(m21 - m12) * s, (m02 - m20) * s, (m10 - m01) * s, 0.25 / s];
  }
  if (m00 > m11 && m00 > m22) {
    const s = 2 * Math.sqrt(1 + m00 - m11 - m22);
    return [0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s];
  }
  if (m11 > m22) {
    const s = 2 * Math.sqrt(1 + m11 - m00 - m22);
    return [(m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s];
  }
  const s = 2 * Math.sqrt(1 + m22 - m00 - m11);
  return [(m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s];
}

function readRotation(raw: Raw): Quat {
  const quat = pick(raw, "quaternion", "quat", "q");
  if (Array.isArray(quat) && quat.length === 4 && quat.every((v) => typeof v === "number")) {
    return quat as Quat;
  }
  const axes = pick(raw, "axes", "basis", "R");
  if (Array.isArray(axes) && axes.length === 3) {
    const rows = axes.map(asVec3);
    if (rows.every((r): r is Vec3 => r !== undefined)) return basisToQuat(rows);
  }
  const euler = asVec3(pick(raw, "rotation", "euler", "rpy"));
  if (euler) return eulerDegToQuat(euler);
  return IDENTITY;
}

function normalizeMesh(value: unknown): RegionMesh | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Raw;
  const declared = pick(raw, "type", "kind");
  const type = typeof declared === "string" ? declared.toLowerCase() : inferType(raw);

  switch (type) {
    case "box":
    case "aabb": {
      const min = asVec3(pick(raw, "min", "lo", "lower"));
      const max = asVec3(pick(raw, "max", "hi", "upper"));
      if (!min || !max) return undefined;
      return { type: "box", min, max } satisfies BoxMesh;
    }
    case "obox":
    case "oriented_box":
    case "orientedbox": {
      const center = asVec3(pick(raw, "center", "centre", "origin"));
      let halfExtents = asVec3(pick(raw, "halfExtents", "half_extents", "halfSize", "half_size"));
      if (!halfExtents) {
        const size = asVec3(pick(raw, "size", "extents"));
        if (size) halfExtents = [size[0] / 2, size[1] / 2, size[2] / 2];
      }
      if (!center || !halfExtents) return undefined;
      return {
        type: "obox",
        center,
        halfExtents,
        quaternion: readRotation(raw),
      } satisfies OboxMesh;
    }
    case "sphere":
    case "ball": {
      const center = asVec3(pick(raw, "center", "centre", "origin"));
      const radius = asNumber(pick(raw, "radius", "r"));
      if (!center || radius === undefined) return undefined;
      return { type: "sphere", center, radius } satisfies SphereMesh;
    }
    case "polytope":
    case "mesh":
    case "hull": {
      const rawVertices = pick(raw, "vertices", "points", "verts");
      const rawFaces = pick(raw, "faces", "triangles", "tris", "indices");
      if (!Array.isArray(rawVertices) || !Array.isArray(rawFaces)) return undefined;
      const vertices = rawVertices.map(asVec3).filter((v): v is Vec3 => v !== undefined);
      const faces: Tri[] = [];
      for (const face of rawFaces) {
        if (!Array.isArray(face) || face.length < 3) continue;
        // Triangulate as a fan, so quads and n-gons survive too.
        for (let i = 1; i + 1 < face.length; i++) {
          const tri = [face[0], face[i], face[i + 1]];
          if (tri.every((n) => typeof n === "number" && n >= 0 && n < vertices.length)) {
            faces.push(tri as Tri);
          }
        }
      }
      if (vertices.length < 4 || faces.length < 4) return undefined;
      return { type: "polytope", vertices, faces } satisfies PolytopeMesh;
    }
    case "union":
    case "intersection":
    case "difference": {
      const rawChildren = pick(raw, "children", "operands", "meshes");
      if (!Array.isArray(rawChildren)) return undefined;
      const children = rawChildren
        .map(normalizeMesh)
        .filter((m): m is RegionMesh => m !== undefined);
      if (children.length === 0) return undefined;
      return { type, children } satisfies CompositeMesh;
    }
    default:
      return undefined;
  }
}

/** Pre-discriminator payloads, and anything that forgot its `type`. */
function inferType(raw: Raw): string {
  if (raw.min !== undefined && raw.max !== undefined) return "box";
  if (raw.radius !== undefined) return "sphere";
  if (raw.halfExtents !== undefined || raw.half_extents !== undefined) return "obox";
  if (raw.vertices !== undefined || raw.points !== undefined) return "polytope";
  if (raw.children !== undefined) return "union";
  return "";
}

const REGION_KINDS: RegionKind[] = [
  "box",
  "obox",
  "sphere",
  "polytope",
  "union",
  "intersection",
  "difference",
];

export function normalizeRegion(value: unknown): RegionPayload | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Raw;
  const id = raw.id;
  if (typeof id !== "string") return undefined;
  const mesh = normalizeMesh(pick(raw, "mesh", "geometry"));
  const declaredKind = typeof raw.kind === "string" ? raw.kind.toLowerCase() : undefined;
  const kind = (REGION_KINDS as string[]).includes(declaredKind ?? "")
    ? (declaredKind as RegionKind)
    : ((mesh?.type ?? "box") as RegionKind);
  return {
    id,
    kind,
    allow: raw.allow !== false,
    label: typeof raw.label === "string" ? raw.label : undefined,
    source: typeof raw.source === "string" ? raw.source : undefined,
    mesh,
    appliesTo: asStringArray(pick(raw, "appliesTo", "applies_to")),
  };
}

/** Fill in optional fields so the rest of the app can treat the payload as total. */
export function normalizePayload(
  raw: Partial<ViewportPayload> | null | undefined,
): ViewportPayload {
  if (!raw) return EMPTY_PAYLOAD;
  return {
    schemaVersion: raw.schemaVersion ?? 1,
    nodes: raw.nodes ?? [],
    links: raw.links ?? [],
    regions: (raw.regions ?? [])
      .map(normalizeRegion)
      .filter((r): r is RegionPayload => r !== undefined),
    findings: raw.findings ?? [],
    frames: raw.frames ?? [],
    selection: raw.selection ?? [],
    view: raw.view,
    frameUnit: raw.frameUnit,
  };
}

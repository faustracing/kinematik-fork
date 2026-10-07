import { describe, expect, it } from "vitest";
import { normalizePayload, normalizeRegion } from "./payload";
import {
  clampDrag,
  matchesGlob,
  meshContains,
  meshPushOut,
  regionApplies,
} from "./regionGeometry";
import type { RegionPayload, Vec3 } from "./types";

function region(partial: Partial<RegionPayload> & Pick<RegionPayload, "id">): RegionPayload {
  return { kind: "box", allow: true, ...partial } as RegionPayload;
}

describe("mesh normalisation", () => {
  it("reads the type discriminator inside mesh", () => {
    const r = normalizeRegion({
      id: "r1",
      kind: "box",
      allow: true,
      mesh: { type: "box", min: [0, 0, 0], max: [10, 10, 10] },
    });
    expect(r?.mesh).toEqual({ type: "box", min: [0, 0, 0], max: [10, 10, 10] });
  });

  it("accepts snake_case applies_to and half_extents", () => {
    const r = normalizeRegion({
      id: "r2",
      kind: "obox",
      allow: true,
      applies_to: ["lf.*"],
      mesh: {
        type: "obox",
        center: [0, 0, 0],
        half_extents: [10, 20, 30],
        rotation: [0, 0, 90],
      },
    });
    expect(r?.appliesTo).toEqual(["lf.*"]);
    expect(r?.mesh?.type).toBe("obox");
    expect(r?.mesh && "halfExtents" in r.mesh && r.mesh.halfExtents).toEqual([10, 20, 30]);
  });

  it("infers the type for pre-discriminator payloads", () => {
    const r = normalizeRegion({
      id: "r3",
      kind: "sphere",
      allow: true,
      mesh: { center: [1, 2, 3], radius: 4 },
    });
    expect(r?.mesh).toEqual({ type: "sphere", center: [1, 2, 3], radius: 4 });
  });

  it("drops a region whose mesh cannot be understood rather than throwing", () => {
    const p = normalizePayload({
      regions: [
        { id: "ok", kind: "box", allow: true, mesh: { type: "box", min: [0, 0, 0], max: [1, 1, 1] } },
        { id: "bad", kind: "box", allow: true, mesh: { type: "wat" } },
      ] as never,
    });
    expect(p.regions.map((r) => r.id)).toEqual(["ok", "bad"]);
    expect(p.regions[1].mesh).toBeUndefined();
  });

  it("triangulates n-gon faces into a polytope", () => {
    const r = normalizeRegion({
      id: "r4",
      kind: "polytope",
      allow: false,
      mesh: {
        type: "polytope",
        vertices: [
          [0, 0, 0],
          [1, 0, 0],
          [1, 1, 0],
          [0, 1, 0],
          [0.5, 0.5, 1],
        ],
        faces: [[0, 3, 2, 1], [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
      },
    });
    expect(r?.mesh?.type).toBe("polytope");
    expect(r?.mesh && "faces" in r.mesh && r.mesh.faces.length).toBe(6);
  });
});

describe("containment", () => {
  const cube = { type: "polytope" as const, ...unitCube() };

  it("handles a rotated oriented box", () => {
    const mesh = {
      type: "obox" as const,
      center: [0, 0, 0] as Vec3,
      halfExtents: [100, 10, 10] as Vec3,
      // 90 degrees about Z: the long axis now runs along +Y.
      quaternion: [0, 0, Math.SQRT1_2, Math.SQRT1_2] as [number, number, number, number],
    };
    expect(meshContains(mesh, [0, 80, 0])).toBe(true);
    expect(meshContains(mesh, [80, 0, 0])).toBe(false);
  });

  it("uses ray parity for polytopes", () => {
    expect(meshContains(cube, [0.5, 0.5, 0.5])).toBe(true);
    expect(meshContains(cube, [1.5, 0.5, 0.5])).toBe(false);
  });

  it("subtracts the trailing children of a difference", () => {
    const mesh = {
      type: "difference" as const,
      children: [
        { type: "box" as const, min: [-10, -10, -10] as Vec3, max: [10, 10, 10] as Vec3 },
        { type: "sphere" as const, center: [0, 0, 0] as Vec3, radius: 5 },
      ],
    };
    expect(meshContains(mesh, [8, 0, 0])).toBe(true);
    expect(meshContains(mesh, [0, 0, 0])).toBe(false);
  });

  it("pushes a point out of a box through its nearest face", () => {
    const mesh = { type: "box" as const, min: [0, 0, 0] as Vec3, max: [10, 10, 100] as Vec3 };
    const out = meshPushOut(mesh, [1, 5, 50]);
    expect(out[0]).toBeLessThan(0);
    expect(meshContains(mesh, out)).toBe(false);
  });
});

describe("applies_to scoping", () => {
  it("matches fnmatch-style globs across the dot separator", () => {
    expect(matchesGlob("lf.*", "lf.lca_outboard")).toBe(true);
    expect(matchesGlob("*_inboard", "lf.lca_fore_inboard")).toBe(true);
    expect(matchesGlob("*.rocker_pivot", "lr.rocker_pivot")).toBe(true);
    expect(matchesGlob("lf.*", "rf.lca_outboard")).toBe(false);
    expect(matchesGlob("front.center.rack_?", "front.center.rack_c")).toBe(true);
  });

  it("prefers applies_to over the node's regionId binding", () => {
    const r = region({ id: "r", allow: true, appliesTo: ["lf.*"] });
    expect(regionApplies(r, "lf.lca_outboard", null)).toBe(true);
    expect(regionApplies(r, "rr.lca_outboard", "r")).toBe(false);
  });

  it("falls back to regionId for unscoped allowable regions", () => {
    const r = region({ id: "r", allow: true });
    expect(regionApplies(r, "lf.lca_outboard", "r")).toBe(true);
    expect(regionApplies(r, "lf.lca_outboard", null)).toBe(false);
  });

  it("applies unscoped illegal regions to every node", () => {
    const r = region({ id: "r", allow: false });
    expect(regionApplies(r, "anything", null)).toBe(true);
  });
});

describe("clampDrag", () => {
  const allow = region({
    id: "envelope",
    allow: true,
    appliesTo: ["lf.lca_fore_inboard"],
    mesh: { type: "box", min: [0, 0, 0], max: [100, 100, 100] },
  });
  const deny = region({
    id: "illegal",
    allow: false,
    appliesTo: ["lf.*"],
    mesh: { type: "box", min: [40, 40, -1000], max: [60, 60, 1000] },
  });

  it("clamps to the allowable box and names the refusing region", () => {
    const { position, refusedBy } = clampDrag(
      [250, 50, 50],
      "lf.lca_fore_inboard",
      "envelope",
      [allow, deny],
    );
    expect(position[0]).toBeCloseTo(100);
    expect(refusedBy).toEqual(["envelope"]);
  });

  it("leaves a legal move untouched", () => {
    const { position, refusedBy } = clampDrag(
      [10, 10, 10],
      "lf.lca_fore_inboard",
      "envelope",
      [allow, deny],
    );
    expect(position).toEqual([10, 10, 10]);
    expect(refusedBy).toEqual([]);
  });

  it("does not refuse a node the regions do not bind", () => {
    const { position, refusedBy } = clampDrag(
      [9999, 9999, 9999],
      "rr.uca_outboard",
      null,
      [allow, deny],
    );
    expect(position).toEqual([9999, 9999, 9999]);
    expect(refusedBy).toEqual([]);
  });

  it("pushes out of an illegal volume it does bind", () => {
    const { position, refusedBy } = clampDrag(
      [50, 50, 50],
      "lf.lca_fore_inboard",
      "envelope",
      [allow, deny],
    );
    expect(refusedBy).toContain("illegal");
    expect(meshContains(deny.mesh, position)).toBe(false);
    expect(meshContains(allow.mesh, position)).toBe(true);
  });
});

function unitCube() {
  const vertices: Vec3[] = [
    [0, 0, 0],
    [1, 0, 0],
    [1, 1, 0],
    [0, 1, 0],
    [0, 0, 1],
    [1, 0, 1],
    [1, 1, 1],
    [0, 1, 1],
  ];
  const faces: [number, number, number][] = [
    [0, 2, 1], [0, 3, 2],
    [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5],
    [2, 3, 7], [2, 7, 6],
    [3, 0, 4], [3, 4, 7],
  ];
  return { vertices, faces };
}

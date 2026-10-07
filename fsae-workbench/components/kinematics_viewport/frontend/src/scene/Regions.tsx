import { Edges } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useMemo } from "react";
import * as THREE from "three";
import { boxCenter, boxSize, normalizeBox } from "../geometry";
import type { PolytopeMesh, RegionMesh, RegionPayload } from "../types";

const ALLOW_COLOR = "#22d3ee";
const DENY_COLOR = "#ef4444";
const REFUSED_COLOR = "#fde047";

export interface RegionsProps {
  regions: RegionPayload[];
  selectedRegionId: string | null;
  /** Regions whose boundary just refused a drag; drawn hot. */
  refused: Set<string>;
  onPick: (id: string) => void;
}

export function Regions({ regions, selectedRegionId, refused, onPick }: RegionsProps) {
  return (
    <group>
      {regions.map((region) => (
        <RegionVolume
          key={region.id}
          region={region}
          selected={region.id === selectedRegionId}
          refused={refused.has(region.id)}
          onPick={onPick}
        />
      ))}
    </group>
  );
}

function RegionVolume({
  region,
  selected,
  refused,
  onPick,
}: {
  region: RegionPayload;
  selected: boolean;
  refused: boolean;
  onPick: (id: string) => void;
}) {
  if (!region.mesh) return null;

  const base = region.allow ? ALLOW_COLOR : DENY_COLOR;
  const color = refused ? REFUSED_COLOR : base;
  const fillOpacity = refused ? 0.3 : region.allow ? 0.07 : 0.16;
  const edgeOpacity = refused ? 1 : selected ? 0.95 : 0.55;

  // Region faces sit between the camera and the nodes they enclose, so a click
  // that also touched a node belongs to the node, not the region.
  const handlePick = (e: ThreeEvent<MouseEvent>) => {
    if (e.intersections.some((hit) => hit.object.userData.nodeId)) return;
    e.stopPropagation();
    onPick(region.id);
  };

  return (
    <MeshVolume
      mesh={region.mesh}
      color={color}
      fillOpacity={fillOpacity}
      edgeOpacity={edgeOpacity}
      edgeWidth={selected || refused ? 2.5 : 1.2}
      onPick={handlePick}
    />
  );
}

interface VolumeProps {
  mesh: RegionMesh;
  color: string;
  fillOpacity: number;
  edgeOpacity: number;
  edgeWidth: number;
  onPick: (e: ThreeEvent<MouseEvent>) => void;
  /** Subtracted operands of a `difference` are drawn as hollow cut-outs. */
  subtracted?: boolean;
}

/**
 * Renders one region mesh.
 *
 * Composites are drawn by recursing into their children rather than by running
 * real CSG: union and intersection look the same as overlaid volumes, and the
 * subtracted operands of a difference are drawn wireframe so it is readable
 * which part is being removed. Containment and clamping use the exact algebra
 * in `regionGeometry`, so only the picture is an approximation.
 */
function MeshVolume({
  mesh,
  color,
  fillOpacity,
  edgeOpacity,
  edgeWidth,
  onPick,
  subtracted = false,
}: VolumeProps) {
  const opacity = subtracted ? 0 : fillOpacity;

  switch (mesh.type) {
    case "box": {
      const box = normalizeBox(mesh);
      const c = boxCenter(box);
      const s = boxSize(box);
      return (
        <mesh position={c} onClick={onPick} renderOrder={2}>
          <boxGeometry args={[s[0], s[1], s[2]]} />
          <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
          <Edges linewidth={edgeWidth} color={color} transparent opacity={edgeOpacity} />
        </mesh>
      );
    }
    case "obox": {
      const h = mesh.halfExtents;
      const q = new THREE.Quaternion(...mesh.quaternion);
      return (
        <mesh position={mesh.center} quaternion={q} onClick={onPick} renderOrder={2}>
          <boxGeometry args={[h[0] * 2, h[1] * 2, h[2] * 2]} />
          <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
          <Edges linewidth={edgeWidth} color={color} transparent opacity={edgeOpacity} />
        </mesh>
      );
    }
    case "sphere":
      return (
        <mesh position={mesh.center} onClick={onPick} renderOrder={2}>
          <sphereGeometry args={[mesh.radius, 28, 20]} />
          <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
          <Edges linewidth={edgeWidth * 0.8} color={color} transparent opacity={edgeOpacity * 0.6} />
        </mesh>
      );
    case "polytope":
      return (
        <PolytopeVolume
          mesh={mesh}
          color={color}
          opacity={opacity}
          edgeOpacity={edgeOpacity}
          edgeWidth={edgeWidth}
          onPick={onPick}
        />
      );
    case "union":
    case "intersection":
    case "difference":
      return (
        <group>
          {mesh.children.map((child, i) => (
            <MeshVolume
              key={i}
              mesh={child}
              color={color}
              fillOpacity={fillOpacity}
              edgeOpacity={edgeOpacity}
              edgeWidth={edgeWidth}
              onPick={onPick}
              subtracted={mesh.type === "difference" && i > 0}
            />
          ))}
        </group>
      );
  }
}

function PolytopeVolume({
  mesh,
  color,
  opacity,
  edgeOpacity,
  edgeWidth,
  onPick,
}: {
  mesh: PolytopeMesh;
  color: string;
  opacity: number;
  edgeOpacity: number;
  edgeWidth: number;
  onPick: (e: ThreeEvent<MouseEvent>) => void;
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const positions = new Float32Array(mesh.vertices.length * 3);
    mesh.vertices.forEach((v, i) => {
      positions[i * 3] = v[0];
      positions[i * 3 + 1] = v[1];
      positions[i * 3 + 2] = v[2];
    });
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setIndex(mesh.faces.flat());
    g.computeVertexNormals();
    return g;
  }, [mesh]);

  return (
    <mesh geometry={geometry} onClick={onPick} renderOrder={2}>
      <meshBasicMaterial
        color={color}
        transparent
        opacity={opacity}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
      <Edges linewidth={edgeWidth} color={color} transparent opacity={edgeOpacity} />
    </mesh>
  );
}

import { Edges, TransformControls } from "@react-three/drei";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { boxCenter, boxFromCenterSize, boxSize, normalizeBox } from "../geometry";
import type { RegionPayload, Vec3 } from "../types";
import { isBoxMesh, isSphereMesh } from "../types";

const MIN_EXTENT = 10; // mm

export interface RegionGizmoProps {
  region: RegionPayload;
  mode: "translate" | "scale";
  size: number;
  onEditEnd: (region: RegionPayload) => void;
}

/**
 * Move or resize an allowable region directly in the scene.
 *
 * The live proxy is what the user drags; the real region volume is hidden by
 * the caller while editing, so no React state churns at pointer rate. The
 * region payload is rebuilt and emitted once, on release.
 */
export function RegionGizmo({ region, mode, size, onEditEnd }: RegionGizmoProps) {
  const proxy = useRef<THREE.Mesh>(null);
  const [attached, setAttached] = useState<THREE.Object3D | null>(null);
  const dragging = useRef(false);

  const box = isBoxMesh(region.mesh) ? normalizeBox(region.mesh) : null;
  const sphere = isSphereMesh(region.mesh) ? region.mesh : null;
  const center: Vec3 = box ? boxCenter(box) : sphere ? sphere.center : [0, 0, 0];
  const extents: Vec3 = box ? boxSize(box) : [1, 1, 1];
  const radius = sphere ? sphere.radius : 1;

  useEffect(() => {
    const obj = proxy.current;
    if (!obj) return;
    obj.position.set(center[0], center[1], center[2]);
    obj.scale.set(1, 1, 1);
    setAttached(obj);
    // Re-seed whenever the edited region changes identity or geometry.
  }, [region.id, center[0], center[1], center[2], extents[0], extents[1], extents[2], radius]);

  const commit = () => {
    const obj = proxy.current;
    if (!obj) return;
    const nextCenter: Vec3 = [obj.position.x, obj.position.y, obj.position.z];
    if (box) {
      const nextSize: Vec3 = [
        Math.max(MIN_EXTENT, extents[0] * Math.abs(obj.scale.x)),
        Math.max(MIN_EXTENT, extents[1] * Math.abs(obj.scale.y)),
        Math.max(MIN_EXTENT, extents[2] * Math.abs(obj.scale.z)),
      ];
      onEditEnd({ ...region, mesh: boxFromCenterSize(nextCenter, nextSize) });
      return;
    }
    if (sphere) {
      const factor = Math.max(
        Math.abs(obj.scale.x),
        Math.abs(obj.scale.y),
        Math.abs(obj.scale.z),
      );
      onEditEnd({
        ...region,
        mesh: { center: nextCenter, radius: Math.max(MIN_EXTENT, radius * factor) },
      });
    }
  };

  if (!box && !sphere) return null;

  const color = region.allow ? "#22d3ee" : "#ef4444";

  return (
    <>
      <mesh ref={proxy} position={center} renderOrder={3}>
        {box ? (
          <boxGeometry args={[extents[0], extents[1], extents[2]]} />
        ) : (
          <sphereGeometry args={[radius, 28, 20]} />
        )}
        <meshBasicMaterial color={color} transparent opacity={0.16} depthWrite={false} />
        <Edges linewidth={2.5} color={color} />
      </mesh>
      {attached && (
        <TransformControls
          object={attached}
          mode={mode}
          size={size}
          space={mode === "scale" ? "local" : "world"}
          onMouseDown={() => {
            dragging.current = true;
          }}
          onMouseUp={() => {
            if (!dragging.current) return;
            dragging.current = false;
            commit();
          }}
        />
      )}
    </>
  );
}

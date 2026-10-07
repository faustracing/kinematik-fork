import { Edges, TransformControls } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { boxFromCenterSize, sub } from "../geometry";
import { isResizable, meshBounds, translateMesh } from "../regionGeometry";
import type { RegionMesh, RegionPayload, Vec3 } from "../types";

const MIN_EXTENT = 10; // mm

export interface RegionGizmoProps {
  region: RegionPayload;
  mode: "translate" | "scale";
  size: number;
  /** Lets the host suppress click-to-deselect while a handle is held. */
  onDragStateChange: (dragging: boolean) => void;
  onEditEnd: (region: RegionPayload) => void;
}

interface ProxyShape {
  center: Vec3;
  /** Full extents of the proxy box, or `null` when the proxy is a sphere. */
  extents: Vec3 | null;
  radius: number;
  quaternion: THREE.Quaternion;
}

function proxyFor(mesh: RegionMesh): ProxyShape {
  if (mesh.type === "sphere") {
    return {
      center: mesh.center,
      extents: null,
      radius: mesh.radius,
      quaternion: new THREE.Quaternion(),
    };
  }
  if (mesh.type === "obox") {
    const h = mesh.halfExtents;
    return {
      center: mesh.center,
      extents: [h[0] * 2, h[1] * 2, h[2] * 2],
      radius: 1,
      quaternion: new THREE.Quaternion(...mesh.quaternion),
    };
  }
  // Boxes use their own extents; polytopes and composites get an AABB proxy
  // they can only be translated by.
  const b = meshBounds(mesh);
  return {
    center: [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2],
    extents: [b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]],
    radius: 1,
    quaternion: new THREE.Quaternion(),
  };
}

/**
 * Move or resize a region directly in the scene.
 *
 * The live proxy is what the user drags; the caller hides the real volume
 * while editing, so no React state churns at pointer rate. The region payload
 * is rebuilt and emitted once, on release.
 *
 * Boxes, oriented boxes and spheres can be resized. Polytopes and composites
 * are dragged rigidly by an axis-aligned proxy — rescaling a triangulated hull
 * or a boolean tree is the server's job, not a gizmo's.
 */
export function RegionGizmo({
  region,
  mode,
  size,
  onDragStateChange,
  onEditEnd,
}: RegionGizmoProps) {
  const proxyRef = useRef<THREE.Mesh>(null);
  const [attached, setAttached] = useState<THREE.Object3D | null>(null);
  const dragging = useRef(false);

  const mesh = region.mesh;
  const shape = useMemo(() => (mesh ? proxyFor(mesh) : null), [mesh]);
  const resizable = isResizable(mesh);
  const effectiveMode = resizable ? mode : "translate";

  const key = shape ? shape.center.join(",") + "|" + (shape.extents ?? []).join(",") : "";
  useEffect(() => {
    const obj = proxyRef.current;
    if (!obj || !shape) return;
    obj.position.set(shape.center[0], shape.center[1], shape.center[2]);
    obj.scale.set(1, 1, 1);
    setAttached(obj);
  }, [region.id, key, shape]);

  if (!mesh || !shape) return null;

  const commit = () => {
    const obj = proxyRef.current;
    if (!obj) return;
    const nextCenter: Vec3 = [obj.position.x, obj.position.y, obj.position.z];
    const scale: Vec3 = [
      Math.abs(obj.scale.x),
      Math.abs(obj.scale.y),
      Math.abs(obj.scale.z),
    ];

    if (mesh.type === "box" && shape.extents) {
      const s = shape.extents;
      onEditEnd({
        ...region,
        mesh: boxFromCenterSize(nextCenter, [
          Math.max(MIN_EXTENT, s[0] * scale[0]),
          Math.max(MIN_EXTENT, s[1] * scale[1]),
          Math.max(MIN_EXTENT, s[2] * scale[2]),
        ]),
      });
      return;
    }

    if (mesh.type === "obox") {
      const h = mesh.halfExtents;
      onEditEnd({
        ...region,
        mesh: {
          ...mesh,
          center: nextCenter,
          halfExtents: [
            Math.max(MIN_EXTENT / 2, h[0] * scale[0]),
            Math.max(MIN_EXTENT / 2, h[1] * scale[1]),
            Math.max(MIN_EXTENT / 2, h[2] * scale[2]),
          ],
        },
      });
      return;
    }

    if (mesh.type === "sphere") {
      const factor = Math.max(scale[0], scale[1], scale[2]);
      onEditEnd({
        ...region,
        mesh: { ...mesh, center: nextCenter, radius: Math.max(MIN_EXTENT, mesh.radius * factor) },
      });
      return;
    }

    onEditEnd({ ...region, mesh: translateMesh(mesh, sub(nextCenter, shape.center)) });
  };

  const color = region.allow ? "#22d3ee" : "#ef4444";

  return (
    <>
      <mesh
        ref={proxyRef}
        position={shape.center}
        quaternion={shape.quaternion}
        renderOrder={3}
      >
        {shape.extents ? (
          <boxGeometry args={[shape.extents[0], shape.extents[1], shape.extents[2]]} />
        ) : (
          <sphereGeometry args={[shape.radius, 28, 20]} />
        )}
        <meshBasicMaterial color={color} transparent opacity={0.16} depthWrite={false} />
        <Edges linewidth={2.5} color={color} />
      </mesh>
      {attached && (
        <TransformControls
          object={attached}
          mode={effectiveMode}
          size={size}
          space={effectiveMode === "scale" ? "local" : "world"}
          onMouseDown={() => {
            dragging.current = true;
            onDragStateChange(true);
          }}
          onMouseUp={() => {
            onDragStateChange(false);
            if (!dragging.current) return;
            dragging.current = false;
            commit();
          }}
        />
      )}
    </>
  );
}

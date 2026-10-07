import { TransformControls } from "@react-three/drei";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { clampDrag } from "../geometry";
import type { PositionStore } from "../positionStore";
import type { RegionPayload, Vec3 } from "../types";

export interface NodeGizmoProps {
  nodeId: string;
  store: PositionStore;
  /** The node's own allowable region, if it has one bound. */
  allowRegion: RegionPayload | undefined;
  /** Every `allow=false` region in the scene. */
  denyRegions: RegionPayload[];
  size: number;
  /** Called at pointer rate with the clamped position and refusing region ids. */
  onDragMove: (position: Vec3, refusedBy: string[]) => void;
  /** Called once, on pointer release. This is what produces a Streamlit event. */
  onDragEnd: (nodeId: string, position: Vec3) => void;
}

export function NodeGizmo({
  nodeId,
  store,
  allowRegion,
  denyRegions,
  size,
  onDragMove,
  onDragEnd,
}: NodeGizmoProps) {
  const target = useRef<THREE.Group>(null);
  const [attached, setAttached] = useState<THREE.Object3D | null>(null);
  const dragging = useRef(false);

  useEffect(() => {
    const obj = target.current;
    if (!obj) return;
    const p = store.get(nodeId);
    obj.position.set(p[0], p[1], p[2]);
    setAttached(obj);
  }, [nodeId, store]);

  const handleObjectChange = () => {
    const obj = target.current;
    if (!obj) return;
    const requested: Vec3 = [obj.position.x, obj.position.y, obj.position.z];
    const { position, refusedBy } = clampDrag(requested, allowRegion, denyRegions);
    obj.position.set(position[0], position[1], position[2]);
    store.setOverride(nodeId, position);
    onDragMove(position, refusedBy);
  };

  return (
    <>
      <group ref={target} />
      {attached && (
        <TransformControls
          object={attached}
          mode="translate"
          size={size}
          space="world"
          onObjectChange={handleObjectChange}
          onMouseDown={() => {
            dragging.current = true;
          }}
          onMouseUp={() => {
            if (!dragging.current) return;
            dragging.current = false;
            const obj = target.current;
            if (!obj) return;
            const p: Vec3 = [obj.position.x, obj.position.y, obj.position.z];
            store.clearOverride(nodeId);
            store.setBase(nodeId, p);
            onDragEnd(nodeId, p);
          }}
        />
      )}
    </>
  );
}

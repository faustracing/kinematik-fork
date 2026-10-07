import { TransformControls } from "@react-three/drei";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { clampDrag } from "../regionGeometry";
import type { PositionStore } from "../positionStore";
import type { RegionPayload, Vec3 } from "../types";

export interface NodeGizmoProps {
  nodeId: string;
  store: PositionStore;
  /** The node's `regionId` binding, used when a region carries no `appliesTo`. */
  nodeRegionId: string | null | undefined;
  /** Every region in the scene; `clampDrag` picks the ones that bind this node. */
  regions: RegionPayload[];
  size: number;
  /** Lets the host suppress click-to-deselect while a handle is held. */
  onDragStateChange: (dragging: boolean) => void;
  /** Called at pointer rate with the clamped position and refusing region ids. */
  onDragMove: (position: Vec3, refusedBy: string[]) => void;
  /** Called once, on pointer release. This is what produces a Streamlit event. */
  onDragEnd: (nodeId: string, position: Vec3) => void;
}

export function NodeGizmo({
  nodeId,
  store,
  nodeRegionId,
  regions,
  size,
  onDragStateChange,
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
    const { position, refusedBy } = clampDrag(requested, nodeId, nodeRegionId, regions);
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
            onDragStateChange(true);
          }}
          onMouseUp={() => {
            onDragStateChange(false);
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

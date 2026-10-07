import { Billboard, Text } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { SEVERITY_COLOR } from "../geometry";
import type { PositionStore } from "../positionStore";
import type { NodePayload, Severity } from "../types";

const FREE_COLOR = "#e2e8f0";
const FIXED_COLOR = "#7dd3fc";
const SELECTED_COLOR = "#facc15";

export interface NodesProps {
  nodes: NodePayload[];
  store: PositionStore;
  selection: string[];
  severityByNode: Map<string, Severity>;
  nodeRadius: number;
  onPick: (id: string, additive: boolean) => void;
}

export function Nodes({
  nodes,
  store,
  selection,
  severityByNode,
  nodeRadius,
  onPick,
}: NodesProps) {
  const selected = useMemo(() => new Set(selection), [selection]);
  const [hovered, setHovered] = useState<string | null>(null);
  const group = useRef<THREE.Group>(null);

  useFrame(() => {
    const g = group.current;
    if (!g) return;
    for (const child of g.children) {
      const id = child.userData.nodeId as string | undefined;
      if (!id) continue;
      const p = store.get(id);
      child.position.set(p[0], p[1], p[2]);
    }
  });

  return (
    <group ref={group}>
      {nodes.map((node) => {
        const isSelected = selected.has(node.id);
        const severity = severityByNode.get(node.id);
        const color = isSelected
          ? SELECTED_COLOR
          : severity
            ? SEVERITY_COLOR[severity]
            : node.fixed
              ? FIXED_COLOR
              : FREE_COLOR;
        const r = nodeRadius * (isSelected ? 1.45 : hovered === node.id ? 1.25 : 1);
        return (
          <group key={node.id} userData={{ nodeId: node.id }}>
            {/* Generous invisible hit sphere: the visible markers are only a
                few millimetres across at vehicle scale. */}
            <mesh
              userData={{ nodeId: node.id }}
              onPointerOver={(e: ThreeEvent<PointerEvent>) => {
                e.stopPropagation();
                setHovered(node.id);
              }}
              onPointerOut={() => setHovered((h) => (h === node.id ? null : h))}
              onClick={(e: ThreeEvent<MouseEvent>) => {
                e.stopPropagation();
                onPick(node.id, e.shiftKey);
              }}
            >
              <sphereGeometry args={[nodeRadius * 2.8, 12, 8]} />
              <meshBasicMaterial visible={false} depthWrite={false} />
            </mesh>
            <mesh raycast={() => null}>
              {node.fixed ? (
                <boxGeometry args={[r * 1.7, r * 1.7, r * 1.7]} />
              ) : (
                <sphereGeometry args={[r, 20, 14]} />
              )}
              <meshStandardMaterial
                color={color}
                emissive={color}
                emissiveIntensity={isSelected ? 0.65 : 0.18}
                roughness={0.45}
                metalness={0.1}
              />
            </mesh>
            {severity && !isSelected && (
              <mesh raycast={() => null}>
                <sphereGeometry args={[r * 1.9, 16, 12]} />
                <meshBasicMaterial
                  color={SEVERITY_COLOR[severity]}
                  transparent
                  opacity={0.18}
                  depthWrite={false}
                />
              </mesh>
            )}
            {(isSelected || hovered === node.id) && (
              <Billboard position={[0, 0, nodeRadius * 3]}>
                <Text
                  fontSize={nodeRadius * 2.4}
                  color="#f8fafc"
                  outlineWidth={nodeRadius * 0.25}
                  outlineColor="#0b1220"
                  anchorX="center"
                  anchorY="bottom"
                >
                  {node.label ?? node.id}
                </Text>
              </Billboard>
            )}
          </group>
        );
      })}
    </group>
  );
}

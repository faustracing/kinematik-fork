import { Billboard, Line, Text } from "@react-three/drei";
import { useMemo } from "react";
import type { Vec3 } from "../types";
import type { SceneBounds } from "./CameraRig";

/** Ground plane grid in the ISO 8855 XY plane, plus the origin triad. */
export function GroundAndAxes({ bounds }: { bounds: SceneBounds }) {
  const extent = useMemo(() => {
    const step = 100;
    const half = Math.ceil((bounds.radius * 1.6) / step) * step;
    return { step, half };
  }, [bounds.radius]);

  const gridPoints = useMemo(() => {
    const pts: number[] = [];
    const { step, half } = extent;
    for (let v = -half; v <= half; v += step) {
      pts.push(-half, v, 0, half, v, 0);
      pts.push(v, -half, 0, v, half, 0);
    }
    return new Float32Array(pts);
  }, [extent]);

  const axisLength = bounds.radius * 0.55;
  const labelSize = Math.max(28, bounds.radius * 0.05);

  return (
    <group>
      <lineSegments renderOrder={-1}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[gridPoints, 3]}
            count={gridPoints.length / 3}
            itemSize={3}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#1f2937" transparent opacity={0.9} />
      </lineSegments>

      <Axis to={[axisLength, 0, 0]} color="#f87171" label="+X fwd" size={labelSize} />
      <Axis to={[0, axisLength, 0]} color="#4ade80" label="+Y left" size={labelSize} />
      <Axis to={[0, 0, axisLength]} color="#60a5fa" label="+Z up" size={labelSize} />
    </group>
  );
}

function Axis({
  to,
  color,
  label,
  size,
}: {
  to: Vec3;
  color: string;
  label: string;
  size: number;
}) {
  return (
    <group>
      <Line points={[[0, 0, 0], to]} color={color} lineWidth={2} />
      <Billboard position={[to[0] * 1.08, to[1] * 1.08, to[2] * 1.08 + size * 0.4]}>
        <Text fontSize={size} color={color} anchorX="center" anchorY="middle">
          {label}
        </Text>
      </Billboard>
    </group>
  );
}

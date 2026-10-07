import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { linkColor } from "../geometry";
import type { PositionStore } from "../positionStore";
import type { LinkPayload } from "../types";

/**
 * All links in one `LineSegments` with vertex colours, positions refreshed
 * imperatively each frame so drags and sweep playback stay smooth.
 */
export function Links({
  links,
  store,
  nodeIds,
}: {
  links: LinkPayload[];
  store: PositionStore;
  nodeIds: Set<string>;
}) {
  const visible = useMemo(
    () => links.filter((l) => nodeIds.has(l.a) && nodeIds.has(l.b)),
    [links, nodeIds],
  );

  const geometry = useRef<THREE.BufferGeometry>(null);

  const { positions, colors } = useMemo(() => {
    const pos = new Float32Array(visible.length * 6);
    const col = new Float32Array(visible.length * 6);
    const c = new THREE.Color();
    visible.forEach((link, i) => {
      c.set(linkColor(link.kind));
      for (const vertex of [0, 1]) {
        col[i * 6 + vertex * 3 + 0] = c.r;
        col[i * 6 + vertex * 3 + 1] = c.g;
        col[i * 6 + vertex * 3 + 2] = c.b;
      }
    });
    return { positions: pos, colors: col };
  }, [visible]);

  const writePositions = () => {
    visible.forEach((link, i) => {
      const a = store.get(link.a);
      const b = store.get(link.b);
      positions[i * 6 + 0] = a[0];
      positions[i * 6 + 1] = a[1];
      positions[i * 6 + 2] = a[2];
      positions[i * 6 + 3] = b[0];
      positions[i * 6 + 4] = b[1];
      positions[i * 6 + 5] = b[2];
    });
    const attr = geometry.current?.getAttribute("position");
    if (attr) attr.needsUpdate = true;
    geometry.current?.computeBoundingSphere();
  };

  useLayoutEffect(writePositions);
  useFrame(writePositions);

  if (visible.length === 0) return null;

  return (
    <lineSegments frustumCulled={false}>
      <bufferGeometry ref={geometry}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={visible.length * 2}
          itemSize={3}
          usage={THREE.DynamicDrawUsage}
        />
        <bufferAttribute
          attach="attributes-color"
          args={[colors, 3]}
          count={visible.length * 2}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial vertexColors linewidth={2} />
    </lineSegments>
  );
}

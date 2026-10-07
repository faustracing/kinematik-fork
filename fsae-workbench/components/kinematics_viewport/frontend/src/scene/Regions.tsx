import { Edges } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { boxCenter, boxSize, normalizeBox } from "../geometry";
import type { RegionPayload } from "../types";
import { isBoxMesh, isSphereMesh } from "../types";

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
  const base = region.allow ? ALLOW_COLOR : DENY_COLOR;
  const color = refused ? REFUSED_COLOR : base;
  const fillOpacity = refused ? 0.3 : region.allow ? 0.07 : 0.16;
  const edgeOpacity = refused ? 1 : selected ? 0.95 : 0.55;

  const handlePick = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    onPick(region.id);
  };

  if (isBoxMesh(region.mesh)) {
    const box = normalizeBox(region.mesh);
    const c = boxCenter(box);
    const s = boxSize(box);
    return (
      <mesh position={c} onPointerDown={handlePick} renderOrder={2}>
        <boxGeometry args={[s[0], s[1], s[2]]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={fillOpacity}
          depthWrite={false}
        />
        <Edges
          linewidth={selected || refused ? 2.5 : 1.2}
          color={color}
          transparent
          opacity={edgeOpacity}
        />
      </mesh>
    );
  }

  if (isSphereMesh(region.mesh)) {
    return (
      <mesh position={region.mesh.center} onPointerDown={handlePick} renderOrder={2}>
        <sphereGeometry args={[region.mesh.radius, 28, 20]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={fillOpacity}
          depthWrite={false}
          wireframe={false}
        />
        <Edges
          linewidth={selected || refused ? 2 : 1}
          color={color}
          transparent
          opacity={edgeOpacity * 0.6}
        />
      </mesh>
    );
  }

  // Polytopes and composites carry no client mesh; they are server-side only.
  return null;
}

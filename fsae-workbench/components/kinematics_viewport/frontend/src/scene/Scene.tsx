import type { ThreeEvent } from "@react-three/fiber";
import type { PositionStore } from "../positionStore";
import type { NodePayload, RegionPayload, Severity, Vec3, ViewPreset } from "../types";
import { boundsOf, CameraRig, type SceneBounds } from "./CameraRig";
import { GroundAndAxes } from "./GroundAndAxes";
import { Links } from "./Links";
import { NodeGizmo } from "./NodeGizmo";
import { Nodes } from "./Nodes";
import { RegionGizmo } from "./RegionGizmo";
import { Regions } from "./Regions";
import type { LinkPayload } from "../types";

export type Tool = "select" | "draw_box";
export type GizmoMode = "translate" | "scale";

export interface SceneProps {
  nodes: NodePayload[];
  links: LinkPayload[];
  regions: RegionPayload[];
  store: PositionStore;
  bounds: SceneBounds;
  preset: ViewPreset;
  presetNonce: number;
  selection: string[];
  selectedRegionId: string | null;
  severityByNode: Map<string, Severity>;
  refusedRegions: Set<string>;
  tool: Tool;
  gizmoMode: GizmoMode;
  /** Node editing is suppressed while the sweep is scrubbed off its static pose. */
  editingLocked: boolean;
  onPickNode: (id: string, additive: boolean) => void;
  onPickRegion: (id: string) => void;
  onPickEmpty: () => void;
  onDrawBoxAt: (point: Vec3) => void;
  onNodeDragMove: (position: Vec3, refusedBy: string[]) => void;
  onNodeDragEnd: (nodeId: string, position: Vec3) => void;
  onRegionEditEnd: (region: RegionPayload) => void;
}

export function Scene(props: SceneProps) {
  const {
    nodes,
    links,
    regions,
    store,
    bounds,
    preset,
    presetNonce,
    selection,
    selectedRegionId,
    severityByNode,
    refusedRegions,
    tool,
    gizmoMode,
    editingLocked,
    onPickNode,
    onPickRegion,
    onPickEmpty,
    onDrawBoxAt,
    onNodeDragMove,
    onNodeDragEnd,
    onRegionEditEnd,
  } = props;

  const nodeIds = new Set(nodes.map((n) => n.id));
  const nodeRadius = Math.max(6, bounds.radius * 0.011);
  const gizmoSize = 0.9;

  const gizmoNodeId =
    !editingLocked && tool === "select" && selection.length === 1 && !selectedRegionId
      ? selection[0]
      : null;
  const gizmoNode = gizmoNodeId ? nodes.find((n) => n.id === gizmoNodeId) : undefined;
  const allowRegion = gizmoNode?.regionId
    ? regions.find((r) => r.id === gizmoNode.regionId && r.allow)
    : undefined;
  const denyRegions = regions.filter((r) => !r.allow);

  const editedRegion = selectedRegionId
    ? regions.find((r) => r.id === selectedRegionId)
    : undefined;
  const visibleRegions = editedRegion
    ? regions.filter((r) => r.id !== editedRegion.id)
    : regions;

  return (
    <>
      <color attach="background" args={["#0b1220"]} />
      <hemisphereLight args={["#dbeafe", "#0f172a", 1.1]} />
      <directionalLight position={[2000, 1500, 2500]} intensity={1.5} />
      <directionalLight position={[-1800, -1200, 900]} intensity={0.5} />

      <CameraRig
        bounds={bounds}
        preset={preset}
        presetNonce={presetNonce}
        enabled
      />

      <GroundAndAxes bounds={bounds} />

      {/* Click-through backdrop: clears selection, or places a new box in draw mode. */}
      <mesh
        position={[bounds.center[0], bounds.center[1], 0]}
        visible={false}
        onPointerDown={(e: ThreeEvent<PointerEvent>) => {
          if (tool === "draw_box") {
            e.stopPropagation();
            onDrawBoxAt([e.point.x, e.point.y, e.point.z]);
          } else {
            onPickEmpty();
          }
        }}
      >
        <planeGeometry args={[bounds.radius * 8, bounds.radius * 8]} />
        <meshBasicMaterial />
      </mesh>

      <Regions
        regions={visibleRegions}
        selectedRegionId={selectedRegionId}
        refused={refusedRegions}
        onPick={onPickRegion}
      />

      <Links links={links} store={store} nodeIds={nodeIds} />

      <Nodes
        nodes={nodes}
        store={store}
        selection={selection}
        severityByNode={severityByNode}
        nodeRadius={nodeRadius}
        onPick={onPickNode}
      />

      {gizmoNodeId && (
        <NodeGizmo
          key={gizmoNodeId}
          nodeId={gizmoNodeId}
          store={store}
          allowRegion={allowRegion}
          denyRegions={denyRegions}
          size={gizmoSize}
          onDragMove={onNodeDragMove}
          onDragEnd={onNodeDragEnd}
        />
      )}

      {editedRegion && (
        <RegionGizmo
          key={editedRegion.id}
          region={editedRegion}
          mode={gizmoMode}
          size={gizmoSize}
          onEditEnd={onRegionEditEnd}
        />
      )}
    </>
  );
}

export { boundsOf };
export type { SceneBounds };

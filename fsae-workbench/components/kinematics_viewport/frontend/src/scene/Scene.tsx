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
  /** Allowable volumes. On by default; they are the clamp envelopes. */
  showAllowable: boolean;
  /** Illegal exclusion volumes. Off by default — they swamp the car. */
  showIllegal: boolean;
  tool: Tool;
  gizmoMode: GizmoMode;
  /** Node editing is suppressed while the sweep is scrubbed off its static pose. */
  editingLocked: boolean;
  onPickNode: (id: string, additive: boolean) => void;
  onPickRegion: (id: string) => void;
  onGizmoDragStateChange: (dragging: boolean) => void;
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
    showAllowable,
    showIllegal,
    tool,
    gizmoMode,
    editingLocked,
    onPickNode,
    onPickRegion,
    onGizmoDragStateChange,
    onDrawBoxAt,
    onNodeDragMove,
    onNodeDragEnd,
    onRegionEditEnd,
  } = props;

  const nodeIds = new Set(nodes.map((n) => n.id));
  const nodeRadius = Math.max(8, bounds.radius * 0.0135);
  const gizmoSize = 0.9;

  const gizmoNodeId =
    !editingLocked && tool === "select" && selection.length === 1 && !selectedRegionId
      ? selection[0]
      : null;
  const gizmoNode = gizmoNodeId ? nodes.find((n) => n.id === gizmoNodeId) : undefined;

  const editedRegion = selectedRegionId
    ? regions.find((r) => r.id === selectedRegionId)
    : undefined;
  // The region under the gizmo is drawn by RegionGizmo, not here. A volume
  // that just refused a drag is drawn even when its layer is hidden, so the
  // yellow flash still explains the clamp.
  const visibleRegions = regions.filter((region) => {
    if (editedRegion && region.id === editedRegion.id) return false;
    if (refusedRegions.has(region.id)) return true;
    return region.allow ? showAllowable : showIllegal;
  });

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

      {/* Ground pick target, only live in draw mode. It must not exist
          otherwise: a full-scene backdrop swallows the pointer-down that
          starts a transform-gizmo drag. */}
      {tool === "draw_box" && (
        <mesh
          position={[bounds.center[0], bounds.center[1], 0]}
          visible={false}
          onClick={(e: ThreeEvent<MouseEvent>) => {
            e.stopPropagation();
            onDrawBoxAt([e.point.x, e.point.y, e.point.z]);
          }}
        >
          <planeGeometry args={[bounds.radius * 8, bounds.radius * 8]} />
          <meshBasicMaterial />
        </mesh>
      )}

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
          nodeRegionId={gizmoNode?.regionId}
          regions={regions}
          size={gizmoSize}
          onDragStateChange={onGizmoDragStateChange}
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
          onDragStateChange={onGizmoDragStateChange}
          onEditEnd={onRegionEditEnd}
        />
      )}
    </>
  );
}

export { boundsOf };
export type { SceneBounds };

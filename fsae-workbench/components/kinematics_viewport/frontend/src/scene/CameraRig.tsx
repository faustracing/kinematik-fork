import { OrbitControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { ViewPreset, Vec3 } from "../types";
import { UP_X, UP_Z } from "./zUp";

export interface SceneBounds {
  center: Vec3;
  /** Half the bounding-box diagonal, for grid and marker scale. */
  radius: number;
  min: Vec3;
  max: Vec3;
}

export function boundsOf(points: Vec3[]): SceneBounds {
  if (points.length === 0) {
    return { center: [0, 0, 0], radius: 1000, min: [-1000, -1000, 0], max: [1000, 1000, 400] };
  }
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of points) {
    for (let i = 0; i < 3; i++) {
      if (p[i] < min[i]) min[i] = p[i];
      if (p[i] > max[i]) max[i] = p[i];
    }
  }
  const center: Vec3 = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const radius = Math.max(
    200,
    0.5 * Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]),
  );
  return { center, radius, min, max };
}

/**
 * Distance that frames the vehicle AABB in the viewport.
 *
 * A bounding-sphere fit leaves a long, low car sitting in the middle of a
 * large empty frame — the sphere's empty corners are what the old
 * `radius * 2.6` distance was framing. Project the box into the view and
 * sit the camera so the car fills the frame. `margin` scales that distance:
 * above 1 leaves air for gizmos, below 1 crops the box corners slightly.
 */
export function framingDistance(
  min: Vec3,
  max: Vec3,
  direction: Vec3,
  up: Vec3,
  fovDeg: number,
  aspect: number,
  margin: number,
): number {
  const center = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  const norm = (v: number[]) => {
    const len = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / len, v[1] / len, v[2] / len];
  };
  const cross = (a: number[], b: number[]) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  // Match Object3D.lookAt: camera +Z points from the target toward the eye.
  const viewZ = norm(direction);
  let camUp = norm(up);
  if (Math.abs(dot(viewZ, camUp)) > 0.98) camUp = [0, 1, 0];
  const right = norm(cross(camUp, viewZ));
  const trueUp = norm(cross(viewZ, right));

  let halfW = 1;
  let halfH = 1;
  for (const x of [min[0], max[0]]) {
    for (const y of [min[1], max[1]]) {
      for (const z of [min[2], max[2]]) {
        const p = [x - center[0], y - center[1], z - center[2]];
        halfW = Math.max(halfW, Math.abs(dot(p, right)));
        halfH = Math.max(halfH, Math.abs(dot(p, trueUp)));
      }
    }
  }
  const vFov = (fovDeg * Math.PI) / 180;
  const safeAspect = Number.isFinite(aspect) && aspect > 0.25 ? aspect : 1.4;
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * safeAspect);
  const distV = halfH / Math.tan(vFov / 2);
  const distH = halfW / Math.tan(hFov / 2);
  return Math.max(distV, distH, 200) * margin;
}

/**
 * Preset eye directions, expressed in ISO 8855 so they read the way a vehicle
 * engineer expects: "front" looks rearward from ahead of the car, "side" looks
 * at the left flank, "top" is a plan view with the nose pointing up-screen.
 *
 * `margin` is the air around the vehicle AABB. Iso sits a touch inside a
 * strict fit so the wishbones read large; the orthographic presets keep a
 * slim border so the nose, tail and contact patches stay on screen.
 */
const PRESETS: Record<ViewPreset, { dir: Vec3; up: THREE.Vector3; margin: number }> = {
  iso: { dir: [1.0, 0.85, 0.62], up: UP_Z, margin: 0.92 },
  front: { dir: [1, 0, 0.05], up: UP_Z, margin: 1.16 },
  side: { dir: [0.02, 1, 0.06], up: UP_Z, margin: 1.12 },
  top: { dir: [0, 0, 1], up: UP_X, margin: 1.08 },
};

export interface CameraRigProps {
  bounds: SceneBounds;
  preset: ViewPreset;
  /** Bumped by the toolbar to re-apply the same preset. */
  presetNonce: number;
  enabled: boolean;
}

export function CameraRig({ bounds, preset, presetNonce, enabled }: CameraRigProps) {
  const controls = useRef<OrbitControlsImpl>(null);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);

  useEffect(() => {
    if (size.height < 2) return;
    const spec = PRESETS[preset] ?? PRESETS.iso;
    const dir = new THREE.Vector3(...spec.dir).normalize();
    const target = new THREE.Vector3(...bounds.center);
    const fov = camera.fov || 42;
    const distance = framingDistance(
      bounds.min,
      bounds.max,
      spec.dir,
      [spec.up.x, spec.up.y, spec.up.z],
      fov,
      size.width / size.height,
      spec.margin,
    );
    const eye = target.clone().addScaledVector(dir, distance);
    camera.up.copy(spec.up);
    camera.position.copy(eye);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.copy(target);
      controls.current.update();
    }
  }, [camera, preset, presetNonce, bounds, size.width, size.height]);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enabled={enabled}
      enableDamping
      dampingFactor={0.12}
      minDistance={Math.max(80, bounds.radius * 0.12)}
      maxDistance={bounds.radius * 8}
    />
  );
}

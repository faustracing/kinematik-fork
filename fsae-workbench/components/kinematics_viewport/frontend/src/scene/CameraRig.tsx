import { OrbitControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { ViewPreset, Vec3 } from "../types";
import { UP_X, UP_Z } from "./zUp";

export interface SceneBounds {
  center: Vec3;
  radius: number;
}

export function boundsOf(points: Vec3[]): SceneBounds {
  if (points.length === 0) return { center: [0, 0, 0], radius: 1000 };
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
  return { center, radius };
}

/**
 * Preset eye directions, expressed in ISO 8855 so they read the way a vehicle
 * engineer expects: "front" looks rearward from ahead of the car, "side" looks
 * at the left flank, "top" is a plan view with the nose pointing up-screen.
 */
const PRESETS: Record<ViewPreset, { dir: Vec3; up: THREE.Vector3; distance: number }> = {
  iso: { dir: [1.0, 0.85, 0.6], up: UP_Z, distance: 2.6 },
  front: { dir: [1, 0, 0.08], up: UP_Z, distance: 2.9 },
  side: { dir: [0, 1, 0.08], up: UP_Z, distance: 2.9 },
  top: { dir: [0, 0, 1], up: UP_X, distance: 2.7 },
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
  const camera = useThree((s) => s.camera);

  useEffect(() => {
    const spec = PRESETS[preset] ?? PRESETS.iso;
    const dir = new THREE.Vector3(...spec.dir).normalize();
    const target = new THREE.Vector3(...bounds.center);
    const eye = target.clone().addScaledVector(dir, bounds.radius * spec.distance);
    camera.up.copy(spec.up);
    camera.position.copy(eye);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.copy(target);
      controls.current.update();
    }
  }, [camera, preset, presetNonce, bounds.center, bounds.radius]);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enabled={enabled}
      enableDamping
      dampingFactor={0.12}
      minDistance={bounds.radius * 0.25}
      maxDistance={bounds.radius * 12}
    />
  );
}

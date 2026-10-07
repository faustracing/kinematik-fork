import * as THREE from "three";

/**
 * ISO 8855 is +Z up, three.js defaults to +Y up. Rather than wrapping the whole
 * scene in a rotated group (which would make every drag axis and gizmo handle
 * lie about which way is forward), flip the library default so cameras,
 * controls and the transform gizmo all agree that Z is up and payload
 * coordinates can be used verbatim.
 */
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

export const UP_Z = new THREE.Vector3(0, 0, 1);
export const UP_X = new THREE.Vector3(1, 0, 0);

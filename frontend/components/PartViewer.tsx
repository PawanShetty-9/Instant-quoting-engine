"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

// Technical-illustration look: flat light body + ink feature edges, like an isometric view
// on a drawing sheet. Tint hints at the material family.
const TINT: Record<string, number> = {
  Aluminium: 0xdfe4e8,
  "Stahl / Steel": 0xc9ced3,
  "Edelstahl / Stainless": 0xd6dadd,
  "Buntmetall / Non-ferrous": 0xe8d9a8,
  "Titan / Titanium": 0xc8c6cf,
  "Kunststoff / Plastic": 0xf1efe6,
};

export default function PartViewer({ url, category }: { url: string; category?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "3D-Ansicht des Bauteils – ziehen zum Drehen");
    renderer.domElement.setAttribute("role", "img");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = !reduced;
    controls.autoRotate = !reduced;
    controls.autoRotateSpeed = 0.6;

    scene.add(new THREE.HemisphereLight(0xffffff, 0xb9c3c1, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 1.4, 1.2);
    scene.add(key);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    let frame = 0;
    let disposed = false;
    const loop = () => {
      if (disposed) return;
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };

    const loader = new STLLoader();
    loader.load(
      url,
      (geometry) => {
        if (disposed) return;
        geometry.computeBoundingBox();
        const box = geometry.boundingBox!;
        const center = box.getCenter(new THREE.Vector3());
        geometry.translate(-center.x, -center.y, -center.z);
        geometry.computeVertexNormals();

        const body = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: TINT[category ?? ""] ?? 0xd9dee2,
            roughness: 0.62,
            metalness: 0.15,
            polygonOffset: true,
            polygonOffsetFactor: 1,
            polygonOffsetUnits: 1,
          }),
        );
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 28),
          new THREE.LineBasicMaterial({ color: 0x16212b }),
        );
        // CAD is Z-up, three.js is Y-up.
        const part = new THREE.Group();
        part.add(body, edges);
        part.rotation.x = -Math.PI / 2;
        scene.add(part);

        const size = box.getSize(new THREE.Vector3()).length();
        camera.position.set(size * 1.3, size * 1.0, size * 1.55);
        camera.near = size / 100;
        camera.far = size * 20;
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
        loop();
      },
      undefined,
      () => setFailed(true),
    );

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const mat = mesh.material as THREE.Material | undefined;
        mat?.dispose?.();
      });
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [url, category]);

  if (failed) {
    return (
      <div className="empty">
        <strong>Vorschau nicht verfügbar</strong>
        <span className="en">Preview unavailable – the quote below is unaffected.</span>
      </div>
    );
  }
  return <div ref={host} style={{ position: "absolute", inset: 0 }} />;
}

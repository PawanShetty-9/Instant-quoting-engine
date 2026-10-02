"use client";

// Interactive 3D hero for the landing page: a machined flange plate built procedurally
// (no file download), drawn in the same technical-illustration style as the quote viewer.
// Drag to rotate, pick a material, toggle "feature detection" to see what the engine finds.

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const MATERIALS = [
  { key: "alu", de: "Aluminium", color: 0xdfe4e8, metalness: 0.25, roughness: 0.5 },
  { key: "steel", de: "Stahl C45", color: 0xbfc5cb, metalness: 0.35, roughness: 0.55 },
  { key: "brass", de: "Messing", color: 0xe3cf8f, metalness: 0.4, roughness: 0.45 },
  { key: "ti", de: "Titan", color: 0xbdb9c7, metalness: 0.35, roughness: 0.5 },
  { key: "pom", de: "POM-C", color: 0xf1efe6, metalness: 0.0, roughness: 0.8 },
] as const;
type MaterialKey = (typeof MATERIALS)[number]["key"];

// Part geometry in millimetres.
const PLATE = { w: 120, h: 80, t: 14, r: 8 };
const BOLT_HOLES: [number, number][] = [
  [-45, -28],
  [45, -28],
  [-45, 28],
  [45, 28],
];
const BOLT_R = 5;
const BORE_R = 14;
const BOSS = { r: 24, h: 20 };

function buildPart(): { body: THREE.BufferGeometry[]; features: THREE.Vector3[] } {
  const { w, h, t, r } = PLATE;
  const outline = new THREE.Shape();
  outline.moveTo(-w / 2 + r, -h / 2);
  outline.lineTo(w / 2 - r, -h / 2);
  outline.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  outline.lineTo(w / 2, h / 2 - r);
  outline.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
  outline.lineTo(-w / 2 + r, h / 2);
  outline.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
  outline.lineTo(-w / 2, -h / 2 + r);
  outline.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);

  const hole = (x: number, y: number, radius: number) => {
    const p = new THREE.Path();
    p.absarc(x, y, radius, 0, Math.PI * 2, true);
    return p;
  };
  outline.holes.push(...BOLT_HOLES.map(([x, y]) => hole(x, y, BOLT_R)), hole(0, 0, BORE_R));

  const plate = new THREE.ExtrudeGeometry(outline, { depth: t, bevelEnabled: false, curveSegments: 40 });
  // Extrusion runs along +Z; lay the plate flat (Y-up) with its top face at y = 0.
  plate.rotateX(-Math.PI / 2);
  plate.translate(0, -t, 0);

  // Boss: a ring revolved around the bore axis, sitting on the plate.
  const boss = new THREE.LatheGeometry(
    [
      new THREE.Vector2(BORE_R, 0),
      new THREE.Vector2(BOSS.r, 0),
      new THREE.Vector2(BOSS.r, BOSS.h - 2),
      new THREE.Vector2(BOSS.r - 2, BOSS.h),
      new THREE.Vector2(BORE_R, BOSS.h),
      new THREE.Vector2(BORE_R, 0),
    ],
    64,
  );

  const features = [
    ...BOLT_HOLES.map(([x, y]) => new THREE.Vector3(x, 0.2, -y)),
    new THREE.Vector3(0, BOSS.h + 0.2, 0),
  ];
  return { body: [plate, boss], features };
}

export default function HeroPart() {
  const host = useRef<HTMLDivElement>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const markersRef = useRef<THREE.Group | null>(null);
  const [material, setMaterial] = useState<MaterialKey>("alu");
  const [showFeatures, setShowFeatures] = useState(true);
  const [webgl, setWebgl] = useState(true);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebgl(false);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("role", "img");
    renderer.domElement.setAttribute("aria-label", "3D-Modell eines Flanschteils – ziehen zum Drehen");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(28, 1, 1, 5000);
    camera.position.set(150, 135, 180);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableZoom = false; // keep page scrolling intact
    controls.enablePan = false;
    controls.enableDamping = !reduced;
    controls.autoRotate = !reduced;
    controls.autoRotateSpeed = 0.9;
    controls.target.set(0, 2, 0);

    scene.add(new THREE.HemisphereLight(0xffffff, 0xb9c3c1, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.7);
    key.position.set(1, 1.6, 1.1);
    scene.add(key);

    const mat = new THREE.MeshStandardMaterial({
      color: MATERIALS[0].color,
      metalness: MATERIALS[0].metalness,
      roughness: MATERIALS[0].roughness,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
      side: THREE.DoubleSide,
    });
    materialRef.current = mat;
    const ink = new THREE.LineBasicMaterial({ color: 0x16212b });

    const { body, features } = buildPart();
    const part = new THREE.Group();
    for (const g of body) {
      g.computeVertexNormals();
      part.add(new THREE.Mesh(g, mat), new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), ink));
    }

    // Feature markers: marking-blue rings on every detected hole, like a measuring report.
    const markers = new THREE.Group();
    const ringMat = new THREE.MeshBasicMaterial({ color: 0x2445a8, transparent: true, opacity: 0.9 });
    features.forEach((p, i) => {
      const radius = i < BOLT_HOLES.length ? BOLT_R + 2.5 : BORE_R + 2.5;
      const ring = new THREE.Mesh(new THREE.RingGeometry(radius, radius + 1.6, 48), ringMat);
      ring.rotation.x = -Math.PI / 2;
      ring.position.copy(p);
      markers.add(ring);
    });
    markersRef.current = markers;
    part.add(markers);
    scene.add(part);

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // Pause rendering while the hero is off-screen.
    let visible = true;
    const io = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting));
    io.observe(el);

    let frame = 0;
    const clock = new THREE.Clock();
    const loop = () => {
      frame = requestAnimationFrame(loop);
      if (!visible) return;
      const t = clock.getElapsedTime();
      ringMat.opacity = reduced ? 0.9 : 0.55 + 0.35 * Math.sin(t * 2.4) ** 2;
      controls.update();
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      io.disconnect();
      controls.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose?.();
      });
      mat.dispose();
      ink.dispose();
      ringMat.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  useEffect(() => {
    const m = MATERIALS.find((x) => x.key === material)!;
    const mat = materialRef.current;
    if (!mat) return;
    mat.color.setHex(m.color);
    mat.metalness = m.metalness;
    mat.roughness = m.roughness;
  }, [material]);

  useEffect(() => {
    if (markersRef.current) markersRef.current.visible = showFeatures;
  }, [showFeatures]);

  return (
    <div className="hero-3d">
      <div className="hero-canvas" ref={host}>
        {!webgl && (
          <div className="empty">
            <strong>3D-Ansicht nicht verfügbar</strong>
            <span className="en">WebGL is disabled in this browser.</span>
          </div>
        )}
      </div>
      <div className="hero-controls">
        <div className="swatches" role="radiogroup" aria-label="Werkstoff">
          {MATERIALS.map((m) => (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={material === m.key}
              onClick={() => setMaterial(m.key)}
            >
              <span className="swatch" style={{ background: `#${m.color.toString(16).padStart(6, "0")}` }} />
              {m.de}
            </button>
          ))}
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showFeatures} onChange={(e) => setShowFeatures(e.target.checked)} />
          Merkmalserkennung
        </label>
      </div>
      <div className="hero-readout" aria-live="polite">
        {showFeatures ? (
          <>
            <span>
              <b className="figure">4×</b> Bohrung Ø10
            </span>
            <span>
              <b className="figure">1×</b> Bohrung Ø28
            </span>
            <span>
              <b className="figure">1×</b> Bund
            </span>
            <span>→ 3-Achs-Fräsen</span>
          </>
        ) : (
          <span className="en">Ziehen zum Drehen · drag to rotate</span>
        )}
      </div>
    </div>
  );
}

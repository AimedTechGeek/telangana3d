// 3D works layer: dams, barrages, reservoirs, pump houses, conduits and the proposal's works drawn with three.js inside one Mapbox
// custom layer (spec docs/ui-redesign-spec.md section 8.7). Loaded as an ES module after app.js; app.js talks to it through
// window.Atlas3D and waits for the 'atlas3d:ready' event, so a CDN failure only costs the 3D bodies.
// SPIKE: one box at Saraswati Barrage to verify terrain placement, exaggeration, occlusion, slot and style switches.
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.min.js';

const LAYER_ID = 'atlas3d';

let map = null, options = null, renderer = null, layerAdded = false, slotAccepted = null;
const scene = new THREE.Scene();
const camera = new THREE.Camera();
camera.matrixAutoUpdate = false;
const lights = { ambient: new THREE.AmbientLight(0xffffff, 0.6), sun: new THREE.DirectionalLight(0xffffff, 1.4) };
// Azimuth 315°, altitude 45° (the hillshade's light): x east, y north, z up in the local frame.
lights.sun.position.set(-Math.SQRT1_2 * Math.cos(Math.PI / 4), Math.SQRT1_2 * Math.cos(Math.PI / 4), Math.sin(Math.PI / 4));
scene.add(lights.ambient, lights.sun, lights.sun.target);

const uniforms = { uExag: { value: 1 }, uWidthScale: { value: 1 }, uYear: { value: 0 } };
const batches = [];
let lastCalls = 0, revision = 0;

/** Vertex placement shared by every material: z_world = (ground + height) × exaggeration, cross-sections widened when zoomed out. */
function placeOnTerrain(material) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aGround;\nattribute vec2 aAcross;\nattribute float aYear;\nuniform float uExag;\nuniform float uWidthScale;\nuniform float uYear;')
      .replace('#include <begin_vertex>', 'vec3 transformed = vec3(position.xy + aAcross * uWidthScale, (aGround + position.z) * uExag);\n'
        + 'if (uYear > 0.5 && aYear > -0.5 && (aYear < 0.5 || aYear > uYear + 0.5)) transformed = vec3(0.0);');
  };
  material.customProgramCacheKey = () => 'atlas3d';
  return material;
}

function localFrame(lon, lat) {
  const origin = mapboxgl.MercatorCoordinate.fromLngLat([lon, lat], 0);
  const s = origin.meterInMercatorCoordinateUnits();
  const placement = new THREE.Matrix4().makeTranslation(origin.x, origin.y, 0).multiply(new THREE.Matrix4().makeScale(s, -s, s));
  const toLocal = (lng, lt) => { const m = mapboxgl.MercatorCoordinate.fromLngLat([lng, lt], 0); return [(m.x - origin.x) / s, -(m.y - origin.y) / s]; };
  return { origin, s, placement, toLocal };
}

function groundAt(lon, lat) {
  const z = map.queryTerrainElevation([lon, lat], { exaggerated: false });
  return z === null || z === undefined || Number.isNaN(z) ? null : z;
}

// GL JS 3.33 does not render a zoom-dependent exaggeration at its expression value: Terrain.calculateExaggeration lerps the rendered
// value towards it by at most 10–20 % per frame, and only while the camera altitude moves by 2 m or more (measured: 5.4× still rendered
// at z13.5 right after a jump from z7.3). The bodies therefore follow the exaggeration the terrain is drawn with, read back through
// the public API as exaggerated / unexaggerated elevation at the centre; options.exaggeration() (slider × zoom factor × rise) is the
// target and the fallback until a DEM tile is loaded there.
let renderedExag = null;
function exaggerationNow() {
  const target = options.exaggeration();
  const centre = map.getCenter();
  const plain = map.queryTerrainElevation(centre, { exaggerated: false }), raised = map.queryTerrainElevation(centre, { exaggerated: true });
  if (plain !== null && plain !== undefined && raised !== null && raised !== undefined && plain > 5) renderedExag = raised / plain;
  return renderedExag === null ? target : renderedExag;
}

/** The spike box: 40 × 40 m footprint, 30 m tall, standing on the sampled ground at (lon, lat). */
function spikeBox(lon, lat, fallback) {
  const frame = localFrame(lon, lat);
  const geometry = new THREE.BoxGeometry(1, 1, 30);
  geometry.translate(0, 0, 15);
  const n = geometry.attributes.position.count;
  const across = new Float32Array(n * 2);
  const position = geometry.attributes.position;
  for (let i = 0; i < n; i++) { across[i * 2] = position.getX(i) * 40; across[i * 2 + 1] = position.getY(i) * 40; position.setX(i, 0); position.setY(i, 0); }
  geometry.setAttribute('aAcross', new THREE.BufferAttribute(across, 2));
  const ground = groundAt(lon, lat);
  geometry.setAttribute('aGround', new THREE.BufferAttribute(new Float32Array(n).fill(ground === null ? fallback : ground), 1));
  geometry.setAttribute('aYear', new THREE.BufferAttribute(new Float32Array(n).fill(-1), 1));
  const mesh = new THREE.Mesh(geometry, placeOnTerrain(new THREE.MeshLambertMaterial({ color: '#ff00ff' })));
  mesh.frustumCulled = false;
  const root = new THREE.Group(); root.add(mesh);
  return { group: 'dams', status: 'operational', root, frame, lon, lat, fallback, geometry, visible: true, objects: 1 };
}

function resample() {
  let changed = false;
  for (const batch of batches) {
    const ground = groundAt(batch.lon, batch.lat);
    if (ground === null) continue;
    const attr = batch.geometry.attributes.aGround;
    if (Math.abs(attr.getX(0) - ground) < 0.01) continue;
    for (let i = 0; i < attr.count; i++) attr.setX(i, ground);
    attr.needsUpdate = true; changed = true;
  }
  if (changed) map.triggerRepaint();
}

const layer = {
  id: LAYER_ID, type: 'custom', renderingMode: '3d', slot: 'middle',
  onAdd(m, gl) {
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true });
      renderer.autoClear = false;
      renderer.info.autoReset = false;
    }
    layerAdded = true;
  },
  onRemove() { layerAdded = false; },
  render(gl, matrix) {
    if (!renderer) return;
    const canvas = map.getCanvas();
    renderer.resetState();
    renderer.setViewport(0, 0, canvas.width, canvas.height);
    renderer.info.reset();
    uniforms.uExag.value = exaggerationNow();
    uniforms.uWidthScale.value = Math.min(8, Math.max(1, 2 ** (11 - map.getZoom())));
    const mapMatrix = new THREE.Matrix4().fromArray(matrix);
    for (const batch of batches) {
      if (!batch.visible) continue;
      camera.projectionMatrix.copy(mapMatrix).multiply(batch.frame.placement);
      camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
      scene.add(batch.root);
      renderer.render(scene, camera);
      scene.remove(batch.root);
    }
    lastCalls = renderer.info.render.calls;
  },
};

function addLayer() {
  if (map.getLayer(LAYER_ID)) return;
  try { map.addLayer(layer); slotAccepted = slotAccepted === null ? true : slotAccepted; } catch (error) {
    const { slot, ...withoutSlot } = layer;
    map.addLayer(withoutSlot); slotAccepted = false;
    console.warn(`3D: custom layer added without slot (${error.message})`);
  }
}

const api = {
  async init(m, opts) {
    map = m; options = opts;
    const [dams, lines] = await Promise.all([fetch('data/dams.json').then((r) => r.json()), fetch('data/dam_lines.geojson').then((r) => r.json())]);
    const line = lines.features.find((f) => f.properties.i === 24);
    const coords = line.geometry.coordinates, mid = coords[Math.floor(coords.length / 2)];
    batches.push(spikeBox(mid[0], mid[1], dams[24].elev_m));
    addLayer();
    map.on('style.load', addLayer);
    // The flow animation repaints every frame, so 'idle' rarely fires: moves and DEM tile loads trigger the re-sampling too.
    map.on('idle', resample);
    map.on('moveend', resample);
    map.on('sourcedata', (event) => { if (event.sourceId === 'mapbox-dem' && event.tile) resample(); });
    revision++;
    map.triggerRepaint();
  },
  setTheme() {}, setVisible() {}, setYear() {}, setStatus() {}, setData() {},
  setExaggeration() { if (map) map.triggerRepaint(); },
  _spikeAt(lon, lat, fallback) { batches.length = 0; batches.push(spikeBox(lon, lat, fallback)); map.triggerRepaint(); },
  probe([lon, lat]) {
    const groundM = groundAt(lon, lat), exaggeration = exaggerationNow();
    return { groundM, exaggeration, target: options.exaggeration(), z: groundM === null ? null : groundM * exaggeration };
  },
  stats() {
    const styleLayer = map && map.getLayer(LAYER_ID);
    return { layer: Boolean(styleLayer), slot: styleLayer ? (styleLayer.slot ?? null) : null, slotAccepted, revision,
             groups: { dams: { objects: batches.length, visible: true, batches: batches.length } }, calls: lastCalls };
  },
};

window.Atlas3D = api;
window.dispatchEvent(new Event('atlas3d:ready'));

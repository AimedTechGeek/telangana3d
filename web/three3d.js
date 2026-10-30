// 3D works layer: dams, barrages, reservoirs, pump houses, conduits and the proposal's works drawn with three.js inside one Mapbox
// custom layer (spec docs/ui-redesign-spec.md section 8.7). Loaded as an ES module after app.js; app.js talks to it through
// window.Atlas3D and waits for the 'atlas3d:ready' event, so a CDN failure only costs the 3D bodies.
// Every shape is a generic stand-in sized from the listed numbers, not an as-built drawing (the About sheet says so).
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.min.js';

const LAYER_ID = 'atlas3d';
const CELL_DEG = 0.5;                    // batches are built per group, status and 0.5° cell so float32 stays sharp at z16
const FADE_ZOOM = 0.5;                   // each group fades in over this much zoom above its band
const RESAMPLE_MS = 500;
const STEP_M = 100;                      // lines are densified to this spacing and the ground sampled per vertex
const BOUNDS_PAD = 0.2;
const BANDS = { reservoirs: 8, dams: 9, pumps: 10, conduits: 10.5, pool: 8, proposal: 9 };
const DAM_UNKNOWN_M = 15, DAM_CREST_W = 8, DAM_BELOW_M = 5;
const BARRAGE_MIN_M = 12, DECK_W = 10, DECK_T = 2, PIER_ALONG = 3, PIER_ACROSS = 12, PIER_STEP = 20, GATE_FRACTION = 0.7;
const PIPE_R = 1.6, PIPE_PX = 1.5, PIPE_GAP = 2.4, TUNNEL_R = 5, WIDTH_CAP = 8;
const PORTAL_W = 12, PORTAL_H = 10, PORTAL_D = 4;
const PUMP_WALL_M = 18, PUMP_ROOF_M = 4;
const WATER_LIFT = 0.3;
const LEVEL_MIN_SAMPLES = 16;
const FILES = { dams: 'data/dams.json', pumps: 'data/pumphouses.json', links: 'data/links.geojson', damLines: 'data/dam_lines.geojson',
                reservoirs: 'data/reservoirs.geojson', conduits: 'data/conduits.geojson' };
const GROUPS = ['dams', 'reservoirs', 'pumps', 'conduits', 'proposal'];

// Spec 8.7.6.
const COLOURS = {
  light: { dam: '#b8805a', damUnknown: '#dfb39d', barragePier: '#8a8f94', barrageDeck: '#5f6b73', gate: '#0f7f78', pumpWall: '#e7e1d6',
           pumpRoof: '#c2410c', pipe: '#d4895a', tunnel: '#c2410c', lining: '#cfc8bb', water: '#5aa6e0', proposal: '#14b8a6', proposalWater: '#5eead4' },
  dark: { dam: '#c9946e', damUnknown: '#9c6650', barragePier: '#9aa3aa', barrageDeck: '#7b8790', gate: '#4fd1c5', pumpWall: '#b8b2a7',
          pumpRoof: '#fb923c', pipe: '#fdba74', tunnel: '#fb923c', lining: '#8f8a82', water: '#3f8fd0', proposal: '#2dd4bf', proposalWater: '#5eead4' },
};
const TOKEN_OPACITY = { water: 0.82, proposalWater: 0.82, tunnel: 0.45 };
const BUILDING_TINT = '#f59e0b';
const TOKENS = { dam: 'dam', damUnknown: 'damUnknown', deck: 'barrageDeck', pier: 'barragePier', gate: 'gate', pipe: 'pipe', tunnel: 'tunnel',
                 lining: 'lining', water: 'water', wall: 'pumpWall', roof: 'pumpRoof', portal: 'tunnel' };
const PROPOSAL_TOKENS = Object.fromEntries(Object.keys(TOKENS).map((k) => [k, k === 'water' ? 'proposalWater' : 'proposal']));

let map = null, options = null, renderer = null, theme = 'light', slotAccepted = null;
let yearFilter = null, statusMode = 'all', revision = 0, lastCalls = 0, lastZoomFloor = null, resampleTimer = null;
const batches = new Map();
const groups = Object.fromEntries(GROUPS.map((g) => [g, { visible: true, objects: 0 }]));
let enabled = true;   // the Settings '3D models' master switch: a group is drawn only when this and its own flag are on
const materials = new Map();
const scene = new THREE.Scene();
const camera = new THREE.Camera();
camera.matrixAutoUpdate = false;
const lights = { ambient: new THREE.AmbientLight(0xffffff, 0.6), sun: new THREE.DirectionalLight(0xffffff, 1.4) };
// Azimuth 315°, altitude 45° (the hillshade's light): x east, y north, z up in the local frame.
lights.sun.position.set(-0.5, 0.5, Math.SQRT1_2);
scene.add(lights.ambient, lights.sun, lights.sun.target);
const uniforms = { uExag: { value: 1 }, uWidthScale: { value: 1 }, uPipeScale: { value: 1 }, uYear: { value: 0 }, uFade: { value: 1 } };

// ---------- materials and the shared terrain-placement shader ----------

/** Vertex placement shared by every material: z_world = (ground + height) × exaggeration, cross-sections widened when zoomed out.
 *  aGround is the unexaggerated ground (or water level) per vertex or instance; aAcross the vertex's offset from its centre line
 *  so the body can be widened without moving it; aYear -1 = never filtered, 0 = undated, else the year. */
function placeOnTerrain(material, pipe) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms, { uWidthScale: pipe ? uniforms.uPipeScale : uniforms.uWidthScale });
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aGround;\nattribute vec2 aAcross;\nattribute float aYear;\n'
        + 'uniform float uExag;\nuniform float uWidthScale;\nuniform float uYear;')
      .replace('#include <begin_vertex>', 'vec3 transformed = vec3(position.xy + aAcross * (uWidthScale - 1.0), (aGround + position.z) * uExag);\n'
        + '#ifdef USE_INSTANCING\ntransformed = vec3((instanceMatrix * vec4(transformed.xy, 0.0, 1.0)).xy, transformed.z);\n#endif\n'
        + 'if (uYear > 0.5 && aYear > -0.5 && (aYear < 0.5 || aYear > uYear + 0.5)) transformed = vec3(0.0);')
      // The instance matrix only rotates and scales the footprint (applied above); the default chunk would also scale the height.
      .replace('#include <project_vertex>', 'vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);\ngl_Position = projectionMatrix * mvPosition;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uFade;')
      .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.a *= uFade;');
  };
  material.customProgramCacheKey = () => 'atlas3d';
  return material;
}

/** Status classes: 'operational', 'building' (under construction / in progress), 'planned' (planned / proposed) and 'proposal'. */
function statusClass(status) {
  if (status === 'under construction' || status === 'in progress') return 'building';
  if (status === 'planned' || status === 'proposed') return 'planned';
  return 'operational';
}

function styleMaterial(material) {
  const { token, status } = material.userData;
  const colour = new THREE.Color(COLOURS[theme][token]);
  let opacity = TOKEN_OPACITY[token] ?? 1;
  if (status === 'building') { colour.lerp(new THREE.Color(BUILDING_TINT), 0.35); opacity = Math.min(opacity, 0.7); }
  else if (status === 'planned') opacity = Math.min(opacity, 0.35);
  else if (status === 'proposal') opacity = Math.min(opacity, 0.55);
  material.color.copy(colour);
  material.emissive.copy(colour).multiplyScalar(theme === 'dark' ? 0.25 : 0);
  material.opacity = opacity;
  material.depthWrite = status !== 'planned';
}

function materialFor(token, status, pipe = false) {
  const key = `${token}|${status}|${pipe ? 'px' : ''}`;
  let material = materials.get(key);
  if (!material) {
    material = placeOnTerrain(new THREE.MeshLambertMaterial({ transparent: true, side: THREE.DoubleSide }), pipe);
    material.userData = { token, status };
    styleMaterial(material);
    materials.set(key, material);
  }
  return material;
}

function applyTheme() {
  lights.ambient.intensity = theme === 'dark' ? 0.4 : 0.6;
  lights.sun.intensity = theme === 'dark' ? 0.9 : 1.4;
  for (const material of materials.values()) styleMaterial(material);
  if (map) map.triggerRepaint();
}

// ---------- local frames, batches, samples ----------

function localFrame(lon, lat) {
  const origin = mapboxgl.MercatorCoordinate.fromLngLat([lon, lat], 0);
  const s = origin.meterInMercatorCoordinateUnits();
  const placement = new THREE.Matrix4().makeTranslation(origin.x, origin.y, 0).multiply(new THREE.Matrix4().makeScale(s, -s, s));
  const toLocal = (lng, lt) => { const m = mapboxgl.MercatorCoordinate.fromLngLat([lng, lt], 0); return { x: (m.x - origin.x) / s, y: -(m.y - origin.y) / s }; };
  return { origin, s, placement, toLocal };
}

function groundAt(lon, lat) {
  const z = map.queryTerrainElevation([lon, lat], { exaggerated: false });
  return z === null || z === undefined || Number.isNaN(z) ? null : z;
}

/** The batch for one object: group, status, zoom band and the 0.5° cell of its anchor point; the cell centre is the local origin. */
function batchFor(group, status, band, lon, lat) {
  const cx = Math.floor(lon / CELL_DEG), cy = Math.floor(lat / CELL_DEG);
  const key = `${group}|${status}|${band}|${cx}|${cy}`;
  let batch = batches.get(key);
  if (!batch) {
    batch = { key, group, status, band, frame: localFrame((cx + 0.5) * CELL_DEG, (cy + 0.5) * CELL_DEG), samples: [], parts: [], instances: [],
              meshes: [], instanced: [], root: new THREE.Group(), bbox: [Infinity, Infinity, -Infinity, -Infinity], objects: 0, inView: false };
    batches.set(key, batch);
  }
  return batch;
}

/** Registers a ground sample point (sampled now when the DEM tile is there, else the fallback until a re-sample) and returns its local position. */
function sampleAt(batch, lon, lat, fallback) {
  const { x, y } = batch.frame.toLocal(lon, lat);
  batch.samples.push({ lon, lat, ground: groundAt(lon, lat), fallback });
  const b = batch.bbox;
  b[0] = Math.min(b[0], lon); b[1] = Math.min(b[1], lat); b[2] = Math.max(b[2], lon); b[3] = Math.max(b[3], lat);
  return { x, y, sample: batch.samples.length - 1 };
}

/** Points every STEP_M along a lon/lat line, each with its ground sample. A null fallback carries the last ground seen along the line. */
function densify(batch, coords, fallback) {
  const pts = [];
  let prev = null, carry = fallback;
  const push = (lon, lat) => {
    const p = sampleAt(batch, lon, lat, carry === null ? 0 : carry);
    const g = batch.samples[p.sample].ground;
    if (fallback === null && g !== null) { carry = g; batch.samples[p.sample].fallback = g; }
    pts.push(p);
  };
  for (const [lon, lat] of coords) {
    if (prev) {
      const a = batch.frame.toLocal(prev[0], prev[1]), b = batch.frame.toLocal(lon, lat);
      const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / STEP_M));
      for (let k = 1; k <= n; k++) push(prev[0] + (lon - prev[0]) * k / n, prev[1] + (lat - prev[1]) * k / n);
    } else push(lon, lat);
    prev = [lon, lat];
  }
  return pts;
}

const median = (values) => { const s = [...values].sort((a, b) => a - b); return s.length ? (s[(s.length - 1) >> 1] + s[s.length >> 1]) / 2 : null; };
const minGround = (pts, g) => Math.min(...pts.map((p) => g[p.sample]));

// ---------- geometry parts ----------
// A part is one token's share of an object: vertices in local metres with the mode that sets their aGround on every (re)sample:
// 0 = the ground at the vertex's sample point, 1 = the part's level clamped to that ground, 2 = the part's level.

function newPart(batch, token, year, levelOf = null, pipe = false) {
  const part = { token, pipe, year, levelOf, positions: [], across: [], samples: [], modes: [], indices: [], start: 0, geometry: null };
  batch.parts.push(part);
  return part;
}

function pushVertex(part, x, y, z, ax, ay, sample, mode) {
  part.positions.push(x, y, z); part.across.push(ax, ay); part.samples.push(sample); part.modes.push(mode);
  return part.samples.length - 1;
}

function pushQuad(part, a, b, c, d) { part.indices.push(a, b, c, a, c, d); }

/** Sweeps a cross-section profile ({ a: across, z, mode }) along densified points; every profile edge keeps its own vertices so the
 *  faces shade flat across the section and smooth along the line. */
function sweep(part, pts, profile, closed, caps) {
  const n = pts.length;
  if (n < 2) return;
  const dirs = pts.map((p, j) => {
    const q = pts[Math.min(j + 1, n - 1)], o = pts[Math.max(j - 1, 0)];
    const l = Math.hypot(q.x - o.x, q.y - o.y) || 1;
    return [(q.x - o.x) / l, (q.y - o.y) / l];
  });
  const edges = closed ? profile.length : profile.length - 1;
  const base = part.samples.length, per = edges * 2;
  for (let j = 0; j < n; j++) {
    const nx = -dirs[j][1], ny = dirs[j][0];
    for (let e = 0; e < edges; e++) {
      for (const p of [profile[e], profile[(e + 1) % profile.length]]) {
        pushVertex(part, pts[j].x + p.a * nx, pts[j].y + p.a * ny, p.z, p.a * nx, p.a * ny, pts[j].sample, p.mode);
      }
    }
  }
  for (let j = 0; j < n - 1; j++) for (let e = 0; e < edges; e++) {
    const v = base + j * per + e * 2;
    pushQuad(part, v, v + 1, v + per + 1, v + per);
  }
  if (!caps) return;
  for (const j of [0, n - 1]) {
    const nx = -dirs[j][1], ny = dirs[j][0];
    const first = part.samples.length;
    for (const p of profile) pushVertex(part, pts[j].x + p.a * nx, pts[j].y + p.a * ny, p.z, p.a * nx, p.a * ny, pts[j].sample, p.mode);
    for (let i = 1; i < profile.length - 1; i++) part.indices.push(first, first + i, first + i + 1);
  }
}

/** A box standing at (cx, cy), `along` metres in direction dir and `across` metres across it, bottom and top as { z, mode }. */
function post(part, cx, cy, dir, along, across, bottom, top, sample) {
  const nx = -dir[1], ny = dir[0];
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) => [u * along / 2 * dir[0] + v * across / 2 * nx, u * along / 2 * dir[1] + v * across / 2 * ny]);
  const vertex = (c, level) => pushVertex(part, cx + c[0], cy + c[1], level.z, c[0], c[1], sample, level.mode);
  for (let i = 0; i < 4; i++) {
    const c0 = corners[i], c1 = corners[(i + 1) % 4];
    pushQuad(part, vertex(c0, bottom), vertex(c1, bottom), vertex(c1, top), vertex(c0, top));
  }
  pushQuad(part, ...corners.map((c) => vertex(c, top)));
}

/** A flat polygon (outer ring of local points with samples) at the part's level: reservoir and pool surfaces. */
function surface(part, ring, lift) {
  const pts = ring[0].x === ring[ring.length - 1].x && ring[0].y === ring[ring.length - 1].y ? ring.slice(0, -1) : ring;
  if (pts.length < 3) return;
  const first = part.samples.length;
  for (const p of pts) pushVertex(part, p.x, p.y, lift, 0, 0, p.sample, 2);
  for (const [a, b, c] of THREE.ShapeUtils.triangulateShape(pts.map((p) => new THREE.Vector2(p.x, p.y)), [])) part.indices.push(first + a, first + b, first + c);
}

function circleProfile(radius, offset, sides, mode) {
  const profile = [];
  for (let i = 0; i < sides; i++) { const t = i / sides * 2 * Math.PI; profile.push({ a: offset + radius * Math.cos(t), z: radius + radius * Math.sin(t), mode }); }
  return profile;
}

// ---------- instanced prototypes: pump houses and tunnel portals ----------

/** Prototype geometries are unit footprints (scaled per instance) whose aAcross is the footprint offset itself, so widening works as for parts. */
function prototype(geometry) {
  const n = geometry.attributes.position.count, across = new Float32Array(n * 2), position = geometry.attributes.position;
  for (let i = 0; i < n; i++) { across[i * 2] = position.getX(i); across[i * 2 + 1] = position.getY(i); }
  geometry.setAttribute('aAcross', new THREE.BufferAttribute(across, 2));
  return geometry;
}

function archPortal() {
  const profile = [[-PORTAL_W / 2, 0], [PORTAL_W / 2, 0]];
  const r = PORTAL_W / 2, springing = PORTAL_H - r;
  for (let i = 0; i <= 12; i++) { const t = i / 12 * Math.PI; profile.push([r * Math.cos(t), springing + r * Math.sin(t)]); }
  const positions = [], indices = [], d = PORTAL_D / 2;
  const triangles = THREE.ShapeUtils.triangulateShape(profile.map(([x, z]) => new THREE.Vector2(x, z)), []);
  for (const y of [-d, d]) {
    const first = positions.length / 3;
    for (const [x, z] of profile) positions.push(x, y, z);
    for (const [a, b, c] of triangles) indices.push(first + a, first + b, first + c);
  }
  const m = profile.length;
  for (let i = 0; i < m; i++) {
    const [x0, z0] = profile[i], [x1, z1] = profile[(i + 1) % m], first = positions.length / 3;
    positions.push(x0, -d, z0, x1, -d, z1, x1, d, z1, x0, d, z0);
    indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

const PROTOTYPES = {
  wall: prototype(new THREE.BoxGeometry(1, 1, PUMP_WALL_M).translate(0, 0, PUMP_WALL_M / 2)),
  roof: prototype(new THREE.BoxGeometry(1, 1, PUMP_ROOF_M).translate(0, 0, PUMP_WALL_M + PUMP_ROOF_M / 2)),
  portal: prototype(archPortal()),
};

function instance(batch, proto, token, x, y, rotation, sx, sy, sample, year) {
  batch.instances.push({ proto, token, x, y, rotation, sx, sy, sample, year });
}

// ---------- object builders (shared by the data files and the proposal) ----------

function addDam(batch, pts, height, tokens, token, year) {
  const base = Math.max(12, 0.7 * height);
  const part = newPart(batch, tokens[token], year, (g) => minGround(pts, g) + height);
  sweep(part, pts, [{ a: -base / 2, z: -DAM_BELOW_M, mode: 0 }, { a: -DAM_CREST_W / 2, z: 0, mode: 1 }, { a: DAM_CREST_W / 2, z: 0, mode: 1 },
                    { a: base / 2, z: -DAM_BELOW_M, mode: 0 }], false, true);
}

/** Point `s` metres along densified points: position, direction and the nearest sample. */
function along(pts, s) {
  let run = 0;
  for (let j = 0; j < pts.length - 1; j++) {
    const a = pts[j], b = pts[j + 1], l = Math.hypot(b.x - a.x, b.y - a.y);
    if (run + l >= s || j === pts.length - 2) {
      const t = l ? Math.min(1, (s - run) / l) : 0;
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, dir: [(b.x - a.x) / (l || 1), (b.y - a.y) / (l || 1)], sample: (t < 0.5 ? a : b).sample };
    }
    run += l;
  }
  return null;
}

function addBarrage(batch, pts, height, tokens, year) {
  const crest = (g) => minGround(pts, g) + height;
  const deck = newPart(batch, tokens.deck, year, crest);
  sweep(deck, pts, [{ a: -DECK_W / 2, z: -DECK_T, mode: 1 }, { a: DECK_W / 2, z: -DECK_T, mode: 1 }, { a: DECK_W / 2, z: 0, mode: 1 }, { a: -DECK_W / 2, z: 0, mode: 1 }], true, true);
  const piers = newPart(batch, tokens.pier, year, crest), gates = newPart(batch, tokens.gate, year, crest);
  let length = 0;
  for (let j = 0; j < pts.length - 1; j++) length += Math.hypot(pts[j + 1].x - pts[j].x, pts[j + 1].y - pts[j].y);
  for (let s = PIER_STEP / 2; s < length; s += PIER_STEP) {
    const p = along(pts, s);
    post(piers, p.x, p.y, p.dir, PIER_ALONG, PIER_ACROSS, { z: 0, mode: 0 }, { z: 0, mode: 1 }, p.sample);
    if (s + PIER_STEP < length) {
      const q = along(pts, s + PIER_STEP / 2);
      post(gates, q.x, q.y, q.dir, 0.6, PIER_STEP - PIER_ALONG, { z: 0, mode: 0 }, { z: GATE_FRACTION * height, mode: 0 }, q.sample);
    }
  }
}

function addPipes(batch, pts, tokens, year, pipe) {
  for (const offset of [-PIPE_GAP, PIPE_GAP]) sweep(newPart(batch, tokens.pipe, year, null, pipe), pts, circleProfile(PIPE_R, offset, 6, 0), true, true);
}

function addTunnel(batch, pts, tokens, year) {
  sweep(newPart(batch, tokens.tunnel, year), pts, circleProfile(TUNNEL_R, 0, 8, 0), true, true);
  for (const [a, b] of [[pts[0], pts[1]], [pts[pts.length - 1], pts[pts.length - 2]]]) {
    if (!b) continue;
    instance(batch, 'portal', tokens.portal, a.x, a.y, Math.atan2(b.y - a.y, b.x - a.x) - Math.PI / 2, 1, 1, a.sample, year);
  }
}

function addCanal(batch, pts, tokens, year) {
  sweep(newPart(batch, tokens.lining, year), pts, [{ a: -6, z: 0, mode: 0 }, { a: -5, z: 3, mode: 0 }, { a: -4, z: 0.5, mode: 0 }, { a: 4, z: 0.5, mode: 0 },
                                                   { a: 5, z: 3, mode: 0 }, { a: 6, z: 0, mode: 0 }], false, false);
  sweep(newPart(batch, tokens.water, year), pts, [{ a: -4.5, z: 2, mode: 0 }, { a: 4.5, z: 2, mode: 0 }], false, false);
}

function addPumpHouse(batch, lon, lat, mw, rotation, tokens, fallback, year) {
  const p = sampleAt(batch, lon, lat, fallback);
  const length = Math.min(140, Math.max(30, 30 + 0.12 * mw)), width = 0.45 * length;
  instance(batch, 'wall', tokens.wall, p.x, p.y, rotation, length, width, p.sample, year);
  instance(batch, 'roof', tokens.roof, p.x, p.y, rotation, length * 1.06, width * 1.08, p.sample, year);
}

function addSurface(batch, polygon, level, token, year, fallback, refine) {
  const rings = polygon.type === 'MultiPolygon' ? polygon.coordinates.map((p) => p[0]) : [polygon.coordinates[0]];
  for (const ring of rings) {
    const pts = ring.map(([lon, lat]) => sampleAt(batch, lon, lat, fallback));
    const part = newPart(batch, token, year, (g, samples) => {
      if (!refine) return level;
      // Terrain-DEM along the mapped shoreline is the water level once enough tiles are there (spec 8.7.4).
      const valid = pts.map((p) => samples[p.sample].ground).filter((v) => v !== null);
      return valid.length >= LEVEL_MIN_SAMPLES && valid.length * 2 >= pts.length ? median(valid) : (level ?? median(pts.map((p) => g[p.sample])));
    });
    surface(part, pts, WATER_LIFT);
  }
}

function barrageHeight(height, known, elev) {
  if (!known || height === null || height === undefined) return DAM_UNKNOWN_M;
  // A listed value at or above the ground is a water level (Tummidihetti's 148 m is its FRL): draw level − ground.
  return elev !== null && elev !== undefined && height >= elev - 5 ? Math.max(BARRAGE_MIN_M, height - elev) : height;
}

// ---------- data files ----------

function buildDams(dams, lines) {
  if (!dams || !lines) return;
  for (const f of lines.features) {
    const dam = dams[f.properties.i], coords = f.geometry.coordinates;
    if (!dam || dam.approx || coords.length < 2) continue;
    const mid = coords[coords.length >> 1], status = statusClass(dam.status), year = dam.opened || dam.began || 0;
    const batch = batchFor('dams', status, BANDS.dams, mid[0], mid[1]);
    const pts = densify(batch, coords, dam.elev_m ?? null);
    const known = f.properties.height_known !== false;
    if (dam.kind === 'barrage') addBarrage(batch, pts, barrageHeight(f.properties.height, known, dam.elev_m), TOKENS, year);
    else addDam(batch, pts, known ? f.properties.height : DAM_UNKNOWN_M, TOKENS, known ? 'dam' : 'damUnknown', year);
    batch.objects++;
  }
}

function buildReservoirs(dams, reservoirs) {
  if (!dams || !reservoirs) return;
  for (const f of reservoirs.features) {
    const dam = dams[f.properties.i];
    if (!dam) continue;
    const first = f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates[0][0][0] : f.geometry.coordinates[0][0];
    const batch = batchFor('reservoirs', statusClass(f.properties.status), BANDS.reservoirs, first[0], first[1]);
    addSurface(batch, f.geometry, f.properties.level_m, TOKENS.water, dam.opened || dam.began || 0, f.properties.level_m ?? dam.elev_m ?? 0, true);
    batch.objects++;
  }
}

/** Long axis across the schematic link that leaves the pump house (its `via` or `from` names it), else east-west. */
function pumpRotation(pump, links, frame) {
  if (!links) return 0;
  const names = [pump.name, pump.osm_name].filter(Boolean).map((s) => s.toLowerCase());
  const link = links.features.find((f) => ['via', 'from'].some((k) => f.properties[k] && names.includes(f.properties[k].toLowerCase())));
  if (!link || link.geometry.type !== 'LineString' || link.geometry.coordinates.length < 2) return 0;
  const here = frame.toLocal(pump.lon, pump.lat), local = link.geometry.coordinates.map(([lon, lat]) => frame.toLocal(lon, lat));
  let best = 0, bestD = Infinity;
  local.forEach((p, i) => { const d = Math.hypot(p.x - here.x, p.y - here.y); if (d < bestD) { bestD = d; best = i; } });
  const a = local[best], b = best + 1 < local.length ? local[best + 1] : local[best - 1];
  return Math.atan2(b.y - a.y, b.x - a.x) + Math.PI / 2;
}

function buildPumps(pumps, links) {
  if (!pumps) return;
  for (const p of pumps) {
    if (p.approx || !(p.kind === 'pump' || p.kind === 'tunnel')) continue;
    const batch = batchFor('pumps', statusClass(p.status), BANDS.pumps, p.lon, p.lat), year = parseInt(p.since, 10) || 0;
    if (p.kind === 'pump') addPumpHouse(batch, p.lon, p.lat, parseFloat(p.power) || 0, pumpRotation(p, links, batch.frame), TOKENS, p.elev_m ?? 0, year);
    else { const s = sampleAt(batch, p.lon, p.lat, p.elev_m ?? 0); instance(batch, 'portal', TOKENS.portal, s.x, s.y, 0, 1, 1, s.sample, year); }
    batch.objects++;
  }
}

function buildConduits(conduits) {
  if (!conduits) return;
  for (const f of conduits.features) {
    const coords = f.geometry.coordinates;
    if (f.geometry.type !== 'LineString' || coords.length < 2) continue;
    const mid = coords[coords.length >> 1], year = f.properties.year || 0;
    const batch = batchFor('conduits', f.properties.construction ? 'building' : 'operational', BANDS.conduits, mid[0], mid[1]);
    const pts = densify(batch, coords, null);
    if (f.properties.kind === 'main') addPipes(batch, pts, TOKENS, year, true);
    else if (f.properties.kind === 'tunnel') addTunnel(batch, pts, TOKENS, year);
    else addCanal(batch, pts, TOKENS, year);
    batch.objects++;
  }
}

// ---------- proposal (handed over by app.js; never fetched here) ----------

function buildProposal(data, geo) {
  for (const f of geo?.features || []) {
    const p = f.properties, g = f.geometry;
    if (!['dam', 'pool', 'pressure main', 'tunnel'].includes(p.kind) || p.approx) continue;
    if (p.kind === 'pool') {
      if (g.type !== 'Polygon' && g.type !== 'MultiPolygon') continue;
      const first = g.type === 'MultiPolygon' ? g.coordinates[0][0][0] : g.coordinates[0][0];
      const batch = batchFor('proposal', 'proposal', BANDS.pool, first[0], first[1]);
      addSurface(batch, g, p.frl_m, PROPOSAL_TOKENS.water, -1, p.frl_m, false);
      batch.objects++;
      continue;
    }
    if (g.type !== 'LineString' || g.coordinates.length < 2) continue;
    const mid = g.coordinates[g.coordinates.length >> 1];
    const batch = batchFor('proposal', 'proposal', BANDS.proposal, mid[0], mid[1]);
    const pts = densify(batch, g.coordinates, null);
    if (p.kind === 'dam') addDam(batch, pts, p.crest_m || DAM_UNKNOWN_M, PROPOSAL_TOKENS, 'dam', -1);
    else if (p.kind === 'pressure main') addPipes(batch, pts, PROPOSAL_TOKENS, -1, true);
    else addTunnel(batch, pts, PROPOSAL_TOKENS, -1);
    batch.objects++;
  }
  const pumps = [];
  for (const work of data?.works || []) for (const pump of work.pumps || []) pumps.push(pump);
  // New trunk-stage lifts only where the stage was placed on the map; place-name and hand-placed stages keep their dotted 2D ring.
  for (const system of data?.systems || []) for (const stage of system.stages || []) {
    if (stage.lift_m > 0 && !stage.existing && stage.placed_by === 'map' && stage.lon !== undefined) pumps.push(stage);
  }
  for (const pump of pumps) {
    if (pump.approx || !(pump.lon !== undefined && pump.lat !== undefined)) continue;
    const batch = batchFor('proposal', 'proposal', BANDS.proposal, pump.lon, pump.lat);
    addPumpHouse(batch, pump.lon, pump.lat, pump.mw || 0, 0, PROPOSAL_TOKENS, 0, -1);
    batch.objects++;
  }
}

// ---------- building the GPU batches ----------

function finalizeBatch(batch) {
  const merged = new Map();
  for (const part of batch.parts) {
    const material = materialFor(part.token, batch.status, part.pipe);
    let acc = merged.get(material);
    if (!acc) merged.set(material, acc = { positions: [], across: [], years: [], indices: [], parts: [], count: 0 });
    part.start = acc.count;
    for (const v of part.positions) acc.positions.push(v);
    for (const v of part.across) acc.across.push(v);
    for (const v of part.indices) acc.indices.push(part.start + v);
    for (let k = 0; k < part.samples.length; k++) acc.years.push(part.year);
    acc.parts.push(part);
    acc.count += part.samples.length;
  }
  for (const [material, acc] of merged) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(acc.positions, 3));
    geometry.setAttribute('aAcross', new THREE.Float32BufferAttribute(acc.across, 2));
    geometry.setAttribute('aYear', new THREE.Float32BufferAttribute(acc.years, 1));
    geometry.setAttribute('aGround', new THREE.BufferAttribute(new Float32Array(acc.count), 1));
    geometry.setIndex(acc.indices);
    geometry.computeVertexNormals();
    for (const part of acc.parts) part.geometry = geometry;
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    batch.root.add(mesh); batch.meshes.push(mesh);
  }
  const instanced = new Map();
  for (const item of batch.instances) {
    const key = `${item.proto}|${item.token}`;
    if (!instanced.has(key)) instanced.set(key, []);
    instanced.get(key).push(item);
  }
  const matrix = new THREE.Matrix4(), rotation = new THREE.Matrix4(), scale = new THREE.Matrix4();
  for (const items of instanced.values()) {
    const geometry = PROTOTYPES[items[0].proto].clone();
    geometry.setAttribute('aGround', new THREE.InstancedBufferAttribute(new Float32Array(items.length), 1));
    geometry.setAttribute('aYear', new THREE.InstancedBufferAttribute(new Float32Array(items.map((it) => it.year)), 1));
    const mesh = new THREE.InstancedMesh(geometry, materialFor(items[0].token, batch.status), items.length);
    mesh.frustumCulled = false;
    items.forEach((it, i) => {
      matrix.makeTranslation(it.x, it.y, 0).multiply(rotation.makeRotationZ(it.rotation)).multiply(scale.makeScale(it.sx, it.sy, 1));
      mesh.setMatrixAt(i, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    batch.root.add(mesh); batch.meshes.push(mesh); batch.instanced.push({ mesh, items });
  }
  batch.parts.forEach((part) => { part.positions = part.across = part.indices = null; });   // the typed attributes hold them now
  applyGround(batch);
}

/** Writes aGround for every vertex and instance of a batch from its current samples (ground or fallback). */
function applyGround(batch) {
  const g = batch.samples.map((s) => s.ground ?? s.fallback);
  for (const part of batch.parts) {
    const attr = part.geometry.attributes.aGround, level = part.levelOf ? part.levelOf(g, batch.samples) : 0;
    for (let k = 0; k < part.samples.length; k++) {
      const ground = g[part.samples[k]], mode = part.modes[k];
      attr.setX(part.start + k, mode === 0 ? ground : mode === 1 ? Math.max(level, ground) : level);
    }
    attr.needsUpdate = true;
  }
  for (const { mesh, items } of batch.instanced) {
    const attr = mesh.geometry.attributes.aGround;
    items.forEach((it, i) => attr.setX(i, g[it.sample]));
    attr.needsUpdate = true;
  }
}

function disposeBatch(batch) {
  for (const mesh of batch.meshes) { mesh.geometry.dispose(); if (mesh.dispose) mesh.dispose(); }
  batches.delete(batch.key);
}

function countObjects() {
  for (const group of GROUPS) { groups[group].objects = 0; groups[group].batches = 0; }
  for (const batch of batches.values()) { groups[batch.group].objects += batch.objects; groups[batch.group].batches++; }
}

// ---------- ground re-sampling ----------

function resampleNow() {
  resampleTimer = null;
  let changed = false;
  for (const batch of batches.values()) {
    if (!batch.inView) continue;
    let touched = false;
    for (const s of batch.samples) {
      const ground = groundAt(s.lon, s.lat);
      if (ground !== null && (s.ground === null || Math.abs(s.ground - ground) > 0.01)) { s.ground = ground; touched = true; }
    }
    if (touched) { applyGround(batch); changed = true; }
  }
  if (changed) map.triggerRepaint();
}

function scheduleResample() { if (!resampleTimer) resampleTimer = setTimeout(resampleNow, RESAMPLE_MS); }

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

// ---------- the custom layer ----------

function batchShown(batch, zoom, bounds) {
  if (!enabled || !groups[batch.group].visible) return 0;
  if (statusMode === 'built' && batch.status !== 'operational' && batch.group !== 'proposal') return 0;
  if (zoom < batch.band) return 0;
  const b = batch.bbox;
  if (b[2] < bounds[0] || b[0] > bounds[2] || b[3] < bounds[1] || b[1] > bounds[3]) return 0;
  return Math.min(1, (zoom - batch.band) / FADE_ZOOM);
}

function paddedBounds() {
  const b = map.getBounds(), w = (b.getEast() - b.getWest()) * BOUNDS_PAD, h = (b.getNorth() - b.getSouth()) * BOUNDS_PAD;
  return [b.getWest() - w, b.getSouth() - h, b.getEast() + w, b.getNorth() + h];
}

const layer = {
  id: LAYER_ID, type: 'custom', renderingMode: '3d', slot: 'middle',
  onAdd(m, gl) {
    if (!renderer || renderer.getContext() !== gl) {
      renderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true });
      renderer.autoClear = false;
      renderer.info.autoReset = false;
    }
  },
  onRemove() {},
  render(gl, matrix) {
    if (!renderer) return;
    const canvas = map.getCanvas(), zoom = map.getZoom();
    renderer.resetState();
    renderer.setViewport(0, 0, canvas.width, canvas.height);
    renderer.info.reset();
    uniforms.uExag.value = exaggerationNow();
    uniforms.uWidthScale.value = Math.min(WIDTH_CAP, Math.max(1, 2 ** (11 - zoom)));
    const metresPerPixel = 78271.517 * Math.cos(map.getCenter().lat * Math.PI / 180) / 2 ** zoom;
    uniforms.uPipeScale.value = Math.max(uniforms.uWidthScale.value, PIPE_PX * metresPerPixel / PIPE_R);   // pipes stay 1.5 px wide, uncapped
    uniforms.uYear.value = yearFilter || 0;
    const mapMatrix = new THREE.Matrix4().fromArray(matrix), bounds = paddedBounds();
    for (const batch of batches.values()) {
      const fade = batchShown(batch, zoom, bounds);
      batch.inView = fade > 0;
      if (!batch.inView) continue;
      uniforms.uFade.value = fade;
      camera.projectionMatrix.copy(mapMatrix).multiply(batch.frame.placement);
      camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
      scene.add(batch.root);
      renderer.render(scene, camera);
      scene.remove(batch.root);
    }
    lastCalls = renderer.info.render.calls;
    const floor = Math.floor(zoom);
    if (floor !== lastZoomFloor) { lastZoomFloor = floor; scheduleResample(); }   // the DEM tile level changes the rendered surface
  },
};

function addLayer() {
  if (map.getLayer(LAYER_ID)) return;
  try { map.addLayer(layer); if (slotAccepted === null) slotAccepted = true; } catch (error) {
    const { slot, ...withoutSlot } = layer;
    map.addLayer(withoutSlot); slotAccepted = false;
    console.warn(`3D: custom layer added without slot (${error.message})`);
  }
}

async function optionalJson(url) {
  try { const response = await fetch(url); return response.ok ? await response.json() : null; } catch (_) { return null; }
}

function themeFromDocument() {
  const stamped = document.documentElement.dataset.theme;
  return stamped || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

/** options.theme is the map's theme (app.js mapTheme: dark in the Night scene whatever the UI theme) when it is a function. */
function currentTheme() {
  const t = options && options.theme;
  return typeof t === 'function' ? t() : t || themeFromDocument();
}

// ---------- public API (spec 8.7.2) ----------

const api = {
  async init(m, opts) {
    map = m; options = opts; theme = currentTheme() === 'dark' ? 'dark' : 'light';
    const [dams, pumps, links, damLines, reservoirs, conduits] = await Promise.all(Object.values(FILES).map(optionalJson));
    buildDams(dams, damLines);
    buildReservoirs(dams, reservoirs);
    buildPumps(pumps, links);
    buildConduits(conduits);
    for (const batch of batches.values()) if (!batch.meshes.length) finalizeBatch(batch);
    countObjects();
    applyTheme();
    addLayer();
    map.on('style.load', addLayer);                      // a scene switch drops custom layers
    // The flow animation repaints every frame, so 'idle' rarely fires: moves and DEM tile loads trigger the re-sampling too.
    map.on('idle', scheduleResample);
    map.on('moveend', scheduleResample);
    map.on('sourcedata', (event) => { if (event.sourceId === 'mapbox-dem' && event.tile) scheduleResample(); });
    new MutationObserver(() => api.setTheme(currentTheme())).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => api.setTheme(currentTheme()));
    revision++;
    map.triggerRepaint();
  },
  setTheme(t) {
    const next = t === 'dark' ? 'dark' : 'light';
    if (next === theme) return;
    theme = next; applyTheme();
  },
  setVisible(group, on) {
    for (const g of group === 'all' ? GROUPS : [group]) if (groups[g]) groups[g].visible = Boolean(on);
    if (map) map.triggerRepaint();
  },
  setEnabled(on) { enabled = Boolean(on); if (map) map.triggerRepaint(); },
  setYear(year) { yearFilter = year === null || year === undefined ? null : Number(year); if (map) map.triggerRepaint(); },
  setStatus(mode) { statusMode = mode === 'built' ? 'built' : 'all'; if (map) map.triggerRepaint(); },
  setData(name, payload) {
    if (name !== 'proposal') return;
    for (const batch of [...batches.values()]) if (batch.group === 'proposal') disposeBatch(batch);
    buildProposal(payload?.data, payload?.geo);
    for (const batch of batches.values()) if (!batch.meshes.length) finalizeBatch(batch);
    countObjects();
    revision++;
    if (map) map.triggerRepaint();
  },
  setExaggeration() { if (map) map.triggerRepaint(); },
  probe([lon, lat]) {
    const groundM = groundAt(lon, lat), exaggeration = exaggerationNow();
    return { groundM, exaggeration, target: options.exaggeration(), z: groundM === null ? null : groundM * exaggeration };
  },
  stats() {
    const styleLayer = map && map.getLayer(LAYER_ID);
    return { layer: Boolean(styleLayer), slot: styleLayer ? (styleLayer.slot ?? null) : null, slotAccepted, revision, theme,
             groups: Object.fromEntries(GROUPS.map((g) => [g, { objects: groups[g].objects, visible: enabled && groups[g].visible, batches: groups[g].batches || 0 }])),
             enabled, calls: lastCalls };
  },
};

window.Atlas3D = api;
window.dispatchEvent(new Event('atlas3d:ready'));

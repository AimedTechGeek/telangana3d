/* Telangana Relief: MapLibre 3D terrain served from local Terrarium tiles. */
'use strict';

const TILE_URL = 'tiles/{z}/{x}/{y}.png';
const TILE_MAX_ZOOM = 11;          // must match build_web_data.MAX_ZOOM
const TILE_PX = 256;
const DEM_BOUNDS = [77, 15, 82, 20];
const HOME = { center: [79.35, 17.75], zoom: 7.05, pitch: 56, bearing: -18 };
const RELIEF_STOPS = [              // metres above sea level -> colour (hypsometric tint)
  [1, '#27624a'], [75, '#3b7f55'], [150, '#6ea263'], [250, '#a9c279'], [350, '#d6d48e'],
  [450, '#dcc07e'], [550, '#cfa06a'], [650, '#b8805a'], [750, '#a0664f'], [850, '#cfbfb3'], [950, '#f4f1ec'],
];
const LEGEND_TICKS = [0, 150, 300, 450, 600, 750, 900];
const LEGEND_MAX = 950;
const CITY_BAR_MAX = 700;           // bar length scale, m
const LABEL_ZOOM = 7.6;             // towns and district names appear above this zoom
const LANDMARKS = [                 // heights in metres (statue without its base), icons in index.html
  { name: 'Gateway of India', height: 26, icon: 'gateway' },
  { name: 'Charminar', height: 56, icon: 'charminar' },
  { name: 'Qutub Minar', height: 73, icon: 'qutub' },
  { name: 'Statue of Unity', height: 182, icon: 'statue' },
];
const MAX_LANDMARK_ICONS = 6;
const ORBIT_DEG_PER_FRAME = 0.035;

const MAP_THEMES = {
  light: {
    background: '#e9e6df', mask: '#efece5', maskOpacity: 0.5,
    district: '#3b3a36', districtOpacity: 0.55, state: '#161616', stateCasing: '#ffffff',
    contour: '#5a4634', river: '#2a78d6', riverGlow: '#ffffff', minorRiver: '#4f8fd9',
    shadow: '#2b2016', highlight: '#fff4e2', accent: '#4e3d2e',
    sky: { 'sky-color': '#cfe3f6', 'horizon-color': '#eef3f8', 'fog-color': '#e9e6df' },
  },
  dark: {
    background: '#0e0f12', mask: '#0e0f12', maskOpacity: 0.58,
    district: '#d8d4cc', districtOpacity: 0.38, state: '#f0efec', stateCasing: '#000000',
    contour: '#d8d4cc', river: '#3987e5', riverGlow: '#0b1a33', minorRiver: '#5f9ae8',
    shadow: '#000000', highlight: '#b9a68c', accent: '#000000',
    sky: { 'sky-color': '#0b1020', 'horizon-color': '#1b2233', 'fog-color': '#0e0f12' },
  },
};

const $ = (id) => document.getElementById(id);
const debug = { errors: [], notes: {}, phase: 'script' };
const DEBUG = new URLSearchParams(location.search).has('debug');
function writeDebug() { if (DEBUG) $('debug').textContent = JSON.stringify(debug); }
window.addEventListener('error', (event) => { debug.errors.push(String(event.message)); writeDebug(); });
window.addEventListener('unhandledrejection', (event) => { debug.errors.push(String(event.reason)); writeDebug(); });

// ---------- theme ----------
function currentTheme() {
  const stamped = document.documentElement.dataset.theme;
  if (stamped) return stamped;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('theme', theme); } catch (_) { /* storage unavailable */ }
  if (map && map.getLayer('background')) applyMapTheme();
}
try { const saved = localStorage.getItem('theme'); if (saved) document.documentElement.dataset.theme = saved; } catch (_) { /* ignore */ }

// ---------- style ----------
function reliefExpression(theme) {
  // Exactly 0 m only occurs on the flat plane outside the DEM, so it takes the page colour.
  return ['interpolate', ['linear'], ['elevation'], 0, MAP_THEMES[theme].background, ...RELIEF_STOPS.flat()];
}

function chipOn(name) {
  const chip = document.querySelector(`.chip[data-toggle="${name}"]`);
  return chip.getAttribute('aria-pressed') === 'true' ? 'visible' : 'none';
}

function buildStyle(theme) {
  const t = MAP_THEMES[theme];
  return {
    version: 8,
    sources: {
      // MapLibre wants the terrain mesh and the shading layers on separate sources.
      dem: { type: 'raster-dem', tiles: [TILE_URL], tileSize: TILE_PX, encoding: 'terrarium',
             minzoom: 5, maxzoom: TILE_MAX_ZOOM, bounds: DEM_BOUNDS },
      shade: { type: 'raster-dem', tiles: [TILE_URL], tileSize: TILE_PX, encoding: 'terrarium',
               minzoom: 5, maxzoom: TILE_MAX_ZOOM, bounds: DEM_BOUNDS },
      mask: { type: 'geojson', data: 'data/mask.geojson' },
      state: { type: 'geojson', data: 'data/state.geojson' },
      districts: { type: 'geojson', data: 'data/districts.geojson' },
      rivers: { type: 'geojson', data: 'data/rivers.geojson' },
      contours: { type: 'geojson', data: 'data/contours.geojson' },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': t.background } },
      { id: 'relief', type: 'color-relief', source: 'shade', paint: { 'color-relief-color': reliefExpression(theme) } },
      { id: 'hillshade', type: 'hillshade', source: 'shade', layout: { visibility: chipOn('hillshade') }, paint: {
          'hillshade-method': 'standard', 'hillshade-illumination-direction': 315, 'hillshade-exaggeration': 0.75,
          'hillshade-shadow-color': t.shadow, 'hillshade-highlight-color': t.highlight, 'hillshade-accent-color': t.accent } },
      { id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': t.mask, 'fill-opacity': t.maskOpacity } },
      { id: 'contours', type: 'line', source: 'contours', layout: { visibility: chipOn('contours'), 'line-join': 'round' }, paint: {
          'line-color': t.contour, 'line-opacity': 0.55,
          'line-width': ['case', ['==', ['%', ['get', 'elev'], 500], 0], 1.4, 0.6] } },
      { id: 'districts', type: 'line', source: 'districts', layout: { visibility: chipOn('districts'), 'line-join': 'round' }, paint: {
          'line-color': t.district, 'line-opacity': t.districtOpacity,
          'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.5, 10, 1.2] } },
      { id: 'state-casing', type: 'line', source: 'state', layout: { 'line-join': 'round' }, paint: {
          'line-color': t.stateCasing, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3, 10, 6], 'line-opacity': 0.6 } },
      { id: 'state', type: 'line', source: 'state', layout: { 'line-join': 'round' }, paint: {
          'line-color': t.state, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.4, 10, 2.6] } },
      { id: 'rivers-minor', type: 'line', source: 'rivers', filter: ['!', ['in', ['get', 'name'], ['literal', ['Godavari', 'Krishna']]]],
        layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': t.minorRiver, 'line-width': 1.2, 'line-opacity': 0.8 } },
      { id: 'rivers-glow', type: 'line', source: 'rivers', filter: ['in', ['get', 'name'], ['literal', ['Godavari', 'Krishna']]],
        layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: {
          'line-color': t.riverGlow, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 4, 10, 9], 'line-opacity': 0.55, 'line-blur': 2 } },
      { id: 'rivers-major', type: 'line', source: 'rivers', filter: ['in', ['get', 'name'], ['literal', ['Godavari', 'Krishna']]],
        layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: {
          'line-color': t.river, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.8, 10, 4] } },
    ],
    terrain: { source: 'dem', exaggeration: Number($('exag').value) },
    sky: { ...t.sky, 'fog-ground-blend': 0.6, 'horizon-fog-blend': 0.7, 'sky-horizon-blend': 0.85,
           'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 9, 1, 12, 0] },
  };
}

const map = new maplibregl.Map({
  container: 'map',
  style: buildStyle(currentTheme()),
  center: HOME.center, zoom: HOME.zoom, pitch: HOME.pitch, bearing: HOME.bearing,
  minZoom: 5.6, maxZoom: 13.5, maxPitch: 75,
  maxBounds: [[76.4, 14.5], [82.6, 20.6]],
  attributionControl: false, hash: false, antialias: true,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-right');
map.on('error', (event) => { const message = event && event.error ? event.error.message : String(event); debug.errors.push(message); console.error(message); writeDebug(); });
debug.phase = 'map-created'; writeDebug();

function applyMapTheme() {
  // The style is the single source of truth for colours; a diffed setStyle
  // updates paint properties and the sky without reloading sources.
  map.setStyle(buildStyle(currentTheme()), { diff: true });
}

// ---------- elevation under the cursor (decoded from the Terrarium tiles) ----------
const tileCache = new Map();        // "z/x/y" -> Uint8ClampedArray | Promise
const TILE_CACHE_LIMIT = 48;

function loadTilePixels(key) {
  if (tileCache.has(key)) return tileCache.get(key);
  const promise = new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = TILE_PX;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, TILE_PX, TILE_PX).data;
      if (tileCache.size >= TILE_CACHE_LIMIT) tileCache.delete(tileCache.keys().next().value);
      tileCache.set(key, pixels);
      resolve(pixels);
    };
    image.onerror = () => { tileCache.delete(key); resolve(null); };
    image.src = TILE_URL.replace('{z}/{x}/{y}', key);
  });
  tileCache.set(key, promise);
  return promise;
}

/** Elevation in metres above sea level; null while the tile loads, undefined outside the DEM. */
function elevationAt(lng, lat) {
  if (lng < DEM_BOUNDS[0] || lng > DEM_BOUNDS[2] || lat < DEM_BOUNDS[1] || lat > DEM_BOUNDS[3]) return undefined;
  const n = 2 ** TILE_MAX_ZOOM;
  const x = (lng + 180) / 360 * n;
  const latRad = lat * Math.PI / 180;
  const y = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n;
  const tx = Math.floor(x), ty = Math.floor(y);
  const px = Math.min(TILE_PX - 1, Math.floor((x - tx) * TILE_PX));
  const py = Math.min(TILE_PX - 1, Math.floor((y - ty) * TILE_PX));
  const entry = tileCache.get(`${TILE_MAX_ZOOM}/${tx}/${ty}`);
  if (!(entry instanceof Uint8ClampedArray)) { loadTilePixels(`${TILE_MAX_ZOOM}/${tx}/${ty}`); return null; }
  const i = (py * TILE_PX + px) * 4;
  return entry[i] * 256 + entry[i + 1] + entry[i + 2] / 256 - 32768;
}

const cursorElev = $('cursor-elev'), cursorPos = $('cursor-pos');
let pendingCursor = null;
function showCursor(lngLat) {
  const elevation = elevationAt(lngLat.lng, lngLat.lat);
  if (elevation === undefined) { clearCursor(); return; }
  if (elevation === null) { pendingCursor = lngLat; setTimeout(() => { if (pendingCursor === lngLat) showCursor(lngLat); }, 120); return; }
  cursorElev.textContent = Math.round(elevation).toLocaleString('en-IN');
  cursorPos.textContent = `${Math.abs(lngLat.lat).toFixed(3)}°${lngLat.lat >= 0 ? 'N' : 'S'}  ${Math.abs(lngLat.lng).toFixed(3)}°${lngLat.lng >= 0 ? 'E' : 'W'}`;
  showComparison(elevation);
}

/** Tallest landmark that fits into the elevation at least once (so the count stays small). */
function landmarkFor(elevation) {
  let pick = LANDMARKS[0];
  for (const landmark of LANDMARKS) if (elevation >= landmark.height) pick = landmark;
  return pick;
}
function landmarkIcon(icon, fraction) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'lm'); svg.setAttribute('viewBox', '0 0 24 32'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `#lm-${icon}`); svg.appendChild(use);
  if (fraction >= 1) return svg;
  const part = document.createElement('span');   // clipped from the top: a building cut at the elevation
  part.className = 'lm-part';
  part.style.height = `${Math.max(2, Math.round(fraction * 24))}px`;
  part.appendChild(svg);
  return part;
}
function showComparison(elevation) {
  const landmark = landmarkFor(Math.max(elevation, 0));
  const ratio = Math.max(elevation, 0) / landmark.height;
  const whole = Math.min(Math.floor(ratio), MAX_LANDMARK_ICONS);
  const fraction = ratio - Math.floor(ratio);
  const row = $('lm-row');
  row.textContent = '';
  for (let i = 0; i < whole; i++) row.appendChild(landmarkIcon(landmark.icon, 1));
  if (whole < MAX_LANDMARK_ICONS && fraction >= 0.08) row.appendChild(landmarkIcon(landmark.icon, fraction));
  const text = $('lm-text');
  text.textContent = '';
  text.append('≈ ', bold(`${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)} ×`), ` ${landmark.name} (${landmark.height} m)`);
  $('cursor-compare').hidden = false;
}
let cursorFrame = 0;
map.on('mousemove', (event) => {
  if (cursorFrame) return;
  cursorFrame = requestAnimationFrame(() => { cursorFrame = 0; showCursor(event.lngLat); });
});
function clearCursor() {
  cursorElev.textContent = '—'; cursorPos.textContent = 'Move the pointer over the terrain';
  $('cursor-compare').hidden = true;
}
map.on('mouseout', clearCursor);

// ---------- legend ----------
(function buildLegend() {
  $('ramp').style.background = `linear-gradient(90deg, ${RELIEF_STOPS.map(([m, c]) => `${c} ${(m / LEGEND_MAX * 100).toFixed(1)}%`).join(', ')})`;
  const ticks = $('ramp-ticks');
  for (const metres of LEGEND_TICKS) {
    const span = document.createElement('span');
    span.style.left = `${metres / LEGEND_MAX * 100}%`;
    span.textContent = metres === 0 ? '0 m' : String(metres);
    ticks.appendChild(span);
  }
})();

// ---------- controls ----------
$('exag').addEventListener('input', (event) => {
  const value = Number(event.target.value);
  $('exag-out').value = `${value}×`;
  map.setTerrain({ source: 'dem', exaggeration: value });
  map.triggerRepaint();
});

let orbiting = false;
function orbitStep() {
  if (!orbiting) return;
  map.setBearing(map.getBearing() + ORBIT_DEG_PER_FRAME);
  requestAnimationFrame(orbitStep);
}
const toggles = {
  hillshade: (on) => map.setLayoutProperty('hillshade', 'visibility', on ? 'visible' : 'none'),
  contours: (on) => map.setLayoutProperty('contours', 'visibility', on ? 'visible' : 'none'),
  districts: (on) => { map.setLayoutProperty('districts', 'visibility', on ? 'visible' : 'none'); document.body.classList.toggle('districts-off', !on); },
  labels: (on) => document.body.classList.toggle('labels-off', !on),
  orbit: (on) => { orbiting = on; if (on) orbitStep(); },
};
for (const chip of document.querySelectorAll('.chip[data-toggle]')) {
  chip.addEventListener('click', () => {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    toggles[chip.dataset.toggle](on);
  });
}
map.on('dragstart', () => { if (orbiting) document.querySelector('[data-toggle="orbit"]').click(); });
$('reset').addEventListener('click', () => map.flyTo({ ...HOME, duration: 1800, essential: true }));
$('theme').addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
$('collapse').addEventListener('click', () => { $('panel').classList.add('hidden'); $('expand').hidden = false; });
$('expand').addEventListener('click', () => { $('panel').classList.remove('hidden'); $('expand').hidden = true; });
map.on('zoom', () => document.body.classList.toggle('z-far', map.getZoom() < LABEL_ZOOM));
document.body.classList.toggle('z-far', HOME.zoom < LABEL_ZOOM);

// ---------- markers ----------
const cityMarkers = new Map();
function addCityMarker(city) {
  const el = document.createElement('div');
  el.className = `mk-city ${city.place}`;
  const dot = document.createElement('span'); dot.className = 'dot';
  const label = document.createElement('span'); label.className = 'lbl';
  const name = document.createElement('span'); name.textContent = city.name;
  const elev = document.createElement('span'); elev.className = 'e'; elev.textContent = `${city.elev} m`;
  label.append(name, elev); el.append(dot, label);
  el.addEventListener('click', () => flyToCity(city));
  const marker = new maplibregl.Marker({ element: el, anchor: 'left', offset: [-5, 0] }).setLngLat([city.lon, city.lat]).addTo(map);
  cityMarkers.set(city.name, marker);
}
function addDistrictLabels(points, cityNames) {
  for (const feature of points.features) {
    if (cityNames.has(feature.properties.shapeName.toLowerCase())) continue;  // the city label already names it
    const el = document.createElement('div');
    el.className = 'mk-district';
    el.textContent = feature.properties.shapeName;
    new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(feature.geometry.coordinates).addTo(map);
  }
}
function flyToCity(city) {
  for (const [name, marker] of cityMarkers) marker.getElement().classList.toggle('active', name === city.name);
  for (const row of document.querySelectorAll('#city-list .row')) row.classList.toggle('active', row.dataset.city === city.name);
  map.flyTo({ center: [city.lon, city.lat], zoom: 10.6, pitch: 64, bearing: -28, duration: 2400, essential: true });
}

// ---------- cities list ----------
function renderCities(cities, profiles) {
  const list = $('city-list');
  const rows = cities.map((city) => ({ ...city, kind: 'city' }));
  for (const [river, profile] of Object.entries(profiles)) {
    const lowest = profile.points.reduce((a, b) => (b.elev < a.elev ? b : a));
    rows.push({ name: river, district: 'lowest river bed in Telangana', elev: lowest.elev, lon: lowest.lon, lat: lowest.lat, kind: 'river', place: 'river' });
  }
  rows.sort((a, b) => b.elev - a.elev);
  for (const row of rows) {
    const li = document.createElement('li');
    if (row.kind === 'river') li.className = 'river';
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'row'; button.dataset.city = row.name;
    const name = document.createElement('span'); name.className = 'name'; name.textContent = row.name;
    const small = document.createElement('small'); small.textContent = row.district || ''; name.appendChild(small);
    const bar = document.createElement('span'); bar.className = 'bar';
    bar.style.width = `${Math.max(2, Math.min(100, row.elev / CITY_BAR_MAX * 100))}%`;
    const value = document.createElement('span'); value.className = 'val'; value.textContent = `${row.elev} m`;
    button.append(name, bar, value);
    button.addEventListener('click', () => (row.kind === 'river'
      ? map.flyTo({ center: [row.lon, row.lat], zoom: 10.2, pitch: 62, bearing: -20, duration: 2400, essential: true })
      : flyToCity(row)));
    li.appendChild(button);
    list.appendChild(li);
  }
}

// ---------- river profile chart ----------
const SVG_NS = 'http://www.w3.org/2000/svg';
const CHART = { w: 328, h: 150, l: 38, r: 10, t: 16, b: 24 };
const profileState = { river: 'Godavari', profiles: null, index: 0, marker: null };

function svgEl(tag, attrs, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  if (text !== undefined) el.textContent = text;
  return el;
}
function niceStep(range, target) {
  const raw = range / target, magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * magnitude).find((step) => step >= raw);
}

function renderProfile() {
  const profile = profileState.profiles[profileState.river];
  const svg = $('profile');
  while (svg.lastChild && svg.lastChild.tagName !== 'title') svg.removeChild(svg.lastChild);
  const { w, h, l, r, t, b } = CHART;
  const points = profile.points;
  const maxD = points[points.length - 1].d;
  const yStep = niceStep(profile.max_elev - profile.min_elev || 1, 3);
  const yMin = Math.floor(profile.min_elev / yStep) * yStep, yMax = Math.ceil(profile.max_elev / yStep) * yStep;
  const x = (d) => l + d / maxD * (w - l - r);
  const y = (e) => t + (1 - (e - yMin) / (yMax - yMin || 1)) * (h - t - b);

  for (let e = yMin; e <= yMax; e += yStep) {
    svg.appendChild(svgEl('line', { class: 'grid', x1: l, x2: w - r, y1: y(e), y2: y(e) }));
    svg.appendChild(svgEl('text', { class: 'tick', x: l - 5, y: y(e) + 3, 'text-anchor': 'end' }, String(e)));
  }
  const xStep = niceStep(maxD, 4);
  for (let d = 0; d <= maxD; d += xStep) {
    svg.appendChild(svgEl('text', { class: 'tick', x: x(d), y: h - 8, 'text-anchor': d === 0 ? 'start' : 'middle' }, d === 0 ? '0 km' : String(d)));
  }
  svg.appendChild(svgEl('line', { class: 'axis', x1: l, x2: w - r, y1: y(yMin), y2: y(yMin) }));
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.d).toFixed(1)} ${y(p.elev).toFixed(1)}`).join(' ');
  svg.appendChild(svgEl('path', { class: 'area', d: `${path} L${x(maxD).toFixed(1)} ${y(yMin)} L${l} ${y(yMin)} Z` }));
  svg.appendChild(svgEl('path', { class: 'line', d: path }));
  for (const landmark of profile.landmarks) {
    const point = points.reduce((a, p) => (Math.abs(p.d - landmark.d) < Math.abs(a.d - landmark.d) ? p : a));
    svg.appendChild(svgEl('circle', { class: 'lm', cx: x(point.d), cy: y(point.elev), r: 4 }));
    svg.appendChild(svgEl('text', { class: 'lm-text', x: x(point.d), y: y(point.elev) - 9, 'text-anchor': 'middle' }, landmark.name));
  }
  svg.appendChild(svgEl('line', { id: 'cross', class: 'cross', x1: 0, x2: 0, y1: t, y2: y(yMin), visibility: 'hidden' }));
  svg.appendChild(svgEl('circle', { id: 'cross-dot', class: 'dot', r: 4.5, visibility: 'hidden' }));
  const hit = svgEl('rect', { class: 'hit', x: l, y: 0, width: w - l - r, height: h });
  hit.addEventListener('pointermove', (event) => {
    const box = svg.getBoundingClientRect();
    const d = ((event.clientX - box.left) / box.width * w - l) / (w - l - r) * maxD;
    highlightProfile(nearestIndex(points, d), true);
  });
  hit.addEventListener('pointerleave', () => { $('profile-tip').hidden = true; });
  hit.addEventListener('click', () => {
    const p = points[profileState.index];
    map.flyTo({ center: [p.lon, p.lat], zoom: 10.4, pitch: 62, bearing: -20, duration: 2000, essential: true });
  });
  svg.appendChild(hit);
  profileState.scales = { x, y };

  const first = points[0], last = points[points.length - 1];
  const summary = $('river-summary');
  summary.textContent = '';
  summary.append('Enters at ', bold(`${first.elev} m`), ', leaves at ', bold(`${last.elev} m`),
                 ` · drops ${first.elev - last.elev} m over ${Math.round(profile.length_km)} km · lowest bed `, bold(`${profile.min_elev} m`));
  const tbody = $('profile-table').tBodies[0];
  tbody.textContent = '';
  for (let i = 0; i < points.length; i += 10) {
    const tr = document.createElement('tr');
    const td1 = document.createElement('td'); td1.textContent = points[i].d.toFixed(0);
    const td2 = document.createElement('td'); td2.textContent = String(points[i].elev);
    tr.append(td1, td2); tbody.appendChild(tr);
  }
  $('scrub').max = String(points.length - 1);
  highlightProfile(Math.min(profileState.index, points.length - 1), false);
}
function bold(text) { const el = document.createElement('b'); el.textContent = text; return el; }
function nearestIndex(points, d) {
  let best = 0;
  for (let i = 1; i < points.length; i++) if (Math.abs(points[i].d - d) < Math.abs(points[best].d - d)) best = i;
  return best;
}
function highlightProfile(index, showTip) {
  const profile = profileState.profiles[profileState.river];
  const point = profile.points[index];
  profileState.index = index;
  const { x, y } = profileState.scales;
  const cross = $('cross'), dot = $('cross-dot');
  cross.setAttribute('x1', x(point.d)); cross.setAttribute('x2', x(point.d)); cross.setAttribute('visibility', 'visible');
  dot.setAttribute('cx', x(point.d)); dot.setAttribute('cy', y(point.elev)); dot.setAttribute('visibility', 'visible');
  $('scrub').value = String(index);
  const tip = $('profile-tip');
  if (showTip) {
    tip.textContent = '';
    tip.append(bold(`${point.elev} m`), ' ', spanText(`· ${point.d.toFixed(0)} km`));
    const box = $('profile').getBoundingClientRect();
    tip.style.left = `${x(point.d) / CHART.w * box.width}px`;
    tip.style.top = `${y(point.elev) / CHART.h * box.height}px`;
    tip.hidden = false;
  }
  if (!profileState.marker) {
    const el = document.createElement('div'); el.className = 'mk-scrub';
    profileState.marker = new maplibregl.Marker({ element: el }).setLngLat([point.lon, point.lat]).addTo(map);
  } else {
    profileState.marker.setLngLat([point.lon, point.lat]);
  }
}
function spanText(text) { const el = document.createElement('span'); el.textContent = text; return el; }
$('scrub').addEventListener('input', (event) => highlightProfile(Number(event.target.value), true));
for (const tab of document.querySelectorAll('[role="tab"]')) {
  tab.addEventListener('click', () => {
    for (const other of document.querySelectorAll('[role="tab"]')) other.setAttribute('aria-selected', String(other === tab));
    profileState.river = tab.dataset.river;
    profileState.index = 0;
    renderProfile();
  });
}

// ---------- data + boot ----------
async function loadJson(url) { const response = await fetch(url); if (!response.ok) throw new Error(`${url}: ${response.status}`); return response.json(); }

map.on('load', async () => {
  debug.phase = 'style-loaded'; writeDebug();
  try {
    const [cities, profiles, districtPoints] = await Promise.all([
      loadJson('data/cities.json'), loadJson('data/rivers.json'), loadJson('data/district_points.geojson')]);
    profileState.profiles = profiles;
    cities.forEach(addCityMarker);
    addDistrictLabels(districtPoints, new Set(cities.map((c) => c.name.toLowerCase())));
    renderCities(cities, profiles);
    renderProfile();
    debug.phase = 'data-loaded'; writeDebug();
    if (DEBUG) {
      const hyderabad = cities.find((c) => c.name === 'Hyderabad');
      await loadTilePixels(tileKeyFor(hyderabad.lon, hyderabad.lat));
      debug.notes.hyderabad = { listed: hyderabad.elev, decoded: Math.round(elevationAt(hyderabad.lon, hyderabad.lat)) };
      debug.notes.cities = cities.length;
      debug.notes.profiles = Object.fromEntries(Object.entries(profiles).map(([k, v]) => [k, v.points.length]));
    }
  } catch (error) {
    debug.errors.push(String(error));
    $('toast').textContent = `Data failed to load: ${error.message}`;
    return;
  }
  // 'idle' never fires while DOM markers sit on 3D terrain, so wait for the tiles instead.
  const settle = () => {
    if (!map.loaded()) { map.once('render', settle); return; }
    $('toast').classList.add('gone');
    debug.phase = 'ready';
    if (DEBUG) { debug.notes.terrain = Boolean(map.getTerrain()); debug.notes.layers = map.getStyle().layers.map((l) => l.id); writeDebug(); document.title = 'READY ' + document.title; }
  };
  settle();
});
function tileKeyFor(lng, lat) {
  const n = 2 ** TILE_MAX_ZOOM, latRad = lat * Math.PI / 180;
  return `${TILE_MAX_ZOOM}/${Math.floor((lng + 180) / 360 * n)}/${Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n)}`;
}

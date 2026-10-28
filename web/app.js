/* Telangana Relief: Mapbox GL JS, the Standard basemap under the atlas layers, Mapbox Terrain-DEM for the 3D surface. */
'use strict';

const DEM_TILESET = 'mapbox://mapbox.mapbox-terrain-dem-v1';   // 3D surface, hillshade, relief tint and the cursor readout
const BASEMAPS = { standard: 'mapbox://styles/mapbox/standard', satellite: 'mapbox://styles/mapbox/standard-satellite' };
let basemap = 'standard';          // standard | satellite
let roadLabelsShown = false;       // the basemap's road shields and names, only once zoomed in (see updateLabelDensity)
let lightMode = 'theme';           // theme | dawn | day | dusk | night: the basemap's light preset
const lightPresetFor = (theme) => (lightMode === 'theme' ? MAP_THEMES[theme].lightPreset : lightMode);
const labelData = {};              // label source id -> GeoJSON, built from the data at boot; the style picks them up (generateId gives feature ids)
const FONT = ['DIN Pro Medium', 'Arial Unicode MS Regular'];   // Mapbox-hosted fonts for every label
let scrubPoint = { type: 'FeatureCollection', features: [] };   // the river profile position on the map
const TILE_PX = 256;               // Web Mercator tile width the metres-per-pixel formula is written for
const HOME = { center: [79.35, 17.75], zoom: 7.3, pitch: 66, bearing: -18 };
// Telangana's relief is about 1 km across a 500 km state, so the exaggeration follows the zoom: the slider value applies
// at district level, more than twice that at state level so the plateau stands out, half of it in towns where streets stay true.
const EXAGGERATION_BY_ZOOM = [[6, 2.2], [8, 1.6], [10, 1], [12.5, 0.5]];
let terrainRise = 1;                       // 0–1 while the terrain rises into a 3D view
function terrainExaggeration() {
  const scale = Number($('exag').value) * terrainRise;
  return ['interpolate', ['linear'], ['zoom'], ...EXAGGERATION_BY_ZOOM.flatMap(([z, f]) => [z, Math.max(0.01, scale * f)])];
}
/** Raises the terrain from flat to full over `ms`, so the switch into 3D shows the elevation differences growing. */
function riseTerrain(ms = 1800) {
  const start = performance.now();
  const step = (now) => {
    terrainRise = Math.min(1, (now - start) / ms);
    terrainRise = 1 - (1 - terrainRise) ** 3;
    map.setTerrain({ source: 'mapbox-dem', exaggeration: terrainExaggeration() });
    if (terrainRise < 1) requestAnimationFrame(step); else terrainRise = 1;
  };
  terrainRise = 0.05;
  requestAnimationFrame(step);
}
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
    contour: '#5a4634', flowGlow: '#ffffff', flowDash: '#eef7ff', link: '#c2410c', linkDash: '#fff4e8', cropOpacity: 0.82,
    canal: '#c2187f', canalOld: '#8a6f84', canalDash: '#fff0fa', canalCasing: '#ffffff',
    tank: '#3b95dc', tankEdge: '#1b5a93', tankRamp: ['#e6eef5', '#1d5f99'],
    gwDepth: [[0, '#0b5fa5'], [2, '#4f9bd8'], [5, '#a9d4ef'], [10, '#f2e2b8'], [20, '#d98b3c'], [40, '#7a2e0d']],   // metres below ground
    gwChange: [[-6, '#b2182b'], [-2, '#ef8a62'], [0, '#f4f1ea'], [2, '#67a9cf'], [6, '#2166ac']], gwStroke: '#ffffff',       // fell … rose
    prop: '#0f766e', propPool: '#4f46e5', propPump: '#b45309', propTrunk: '#7c3aed', propPulse: '#ffffff', propCmdExisting: 'rgba(34,197,94,0.22)', propCmdNew: 'rgba(20,184,166,0.32)',
    flow: ['#86d9e3', '#36aee6', '#2566d8', '#1a3aa6', '#5f2aa8'],   // FLOW_CLASSES: cyan -> blue -> navy -> purple
    shadow: '#2b2016', highlight: '#fff4e2', accent: '#4e3d2e',
    label: '#1f1d1a', labelMuted: '#6b6560', labelHalo: 'rgba(255,255,255,0.92)', labelActive: '#c2410c', iconBg: '#ffffff', damIcon: '#b4532a', barrageIcon: '#0f7f78', peakIcon: '#1a3aa6',
    lightPreset: 'day', reliefOpacity: 0.62, heat: ['#9fd0f0', '#3b95dc', '#1b5a93'],
    fog: { range: [0.6, 9], color: '#e3e9ee', 'high-color': '#b7d0ea', 'space-color': '#e9f0f6', 'horizon-blend': 0.08, 'star-intensity': 0 },
  },
  dark: {
    background: '#0e0f12', mask: '#0e0f12', maskOpacity: 0.58,
    district: '#d8d4cc', districtOpacity: 0.38, state: '#f0efec', stateCasing: '#000000',
    contour: '#d8d4cc', flowGlow: '#0b1a33', flowDash: '#ffffff', link: '#fb923c', linkDash: '#fff7ed', cropOpacity: 0.9,
    canal: '#ff6fd0', canalOld: '#d2b4c8', canalDash: '#fff0fa', canalCasing: '#2a0d20',
    tank: '#4fb3ff', tankEdge: '#bfe3ff', tankRamp: ['#161c26', '#3f8fd0'],
    gwDepth: [[0, '#9fd8ff'], [2, '#5eb0ea'], [5, '#2f6f9f'], [10, '#4a4238'], [20, '#b86b2a'], [40, '#ff9d5c']],
    gwChange: [[-6, '#ff6b6b'], [-2, '#c97a6a'], [0, '#2a2f38'], [2, '#5f9bd0'], [6, '#8fd0ff']], gwStroke: '#0b1a33',
    prop: '#2dd4bf', propPool: '#818cf8', propPump: '#fbbf24', propTrunk: '#c4b5fd', propPulse: '#ffffff', propCmdExisting: 'rgba(74,222,128,0.20)', propCmdNew: 'rgba(45,212,191,0.30)',
    flow: ['#2f96a8', '#3cbbea', '#6a9cff', '#a9bdff', '#dcaaff'],   // FLOW_CLASSES: teal -> sky -> blue -> lilac on the dark surface
    shadow: '#000000', highlight: '#b9a68c', accent: '#000000',
    label: '#f1efe9', labelMuted: '#b5b0a8', labelHalo: 'rgba(14,15,18,0.9)', labelActive: '#fb923c', iconBg: '#1b1e26', damIcon: '#f2996b', barrageIcon: '#4fd1c5', peakIcon: '#a9bdff',
    lightPreset: 'night', reliefOpacity: 0.55, heat: ['#1f3b55', '#3f8fd0', '#bfe3ff'],
    fog: { range: [0.6, 9], color: '#0f1520', 'high-color': '#1a2a45', 'space-color': '#04060c', 'horizon-blend': 0.06, 'star-intensity': 0.4 },
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
  if (map && map.getLayer('relief')) ensureIcons(theme).then(() => { applyMapTheme(); renderFlowLegend(); renderGwLegend(); syncArrowImage(); });
}
try { const saved = localStorage.getItem('theme'); if (saved) document.documentElement.dataset.theme = saved; } catch (_) { /* ignore */ }

// ---------- style ----------
// Relief tint: the Terrain-DEM tiles read as a plain raster and decoded by raster-color-mix
// (Mapbox encoding, channels 0–1): height = −10000 + (R·256² + G·256 + B)·0.1.
const DEM_COLOR_MIX = [255 * 6553.6, 255 * 25.6, 255 * 0.1, -10000];
const RELIEF_RANGE_M = 1000;        // the colour ramp is sampled over 0–1000 m
const BAND_M = 100;
const bandsOn = () => document.querySelector('.chip[data-toggle="bands"]').getAttribute('aria-pressed') === 'true';
function reliefExpression(theme) {
  if (!bandsOn()) return ['interpolate', ['linear'], ['raster-value'], 0, MAP_THEMES[theme].background, ...RELIEF_STOPS.flat()];
  const bands = [];                        // each 100 m band takes the ramp colour of its middle height, so steps are countable
  for (let m = BAND_M; m < RELIEF_RANGE_M; m += BAND_M) bands.push(m, rampColour(RELIEF_STOPS, m + BAND_M / 2));
  return ['step', ['raster-value'], rampColour(RELIEF_STOPS, BAND_M / 2), ...bands];
}

// River flow styling: width and colour follow log10 of the average discharge.
const FLOW_WIDTH_STOPS = [[-1, 0.6], [0, 1.0], [1, 1.9], [2, 3.0], [3, 5.2], [3.6, 8]];  // log10(m³/s) -> px
// Colour classes (m³/s lower bounds): stepped so thin lines still read as different flows.
const FLOW_CLASSES = [
  { from: 0, label: '< 10' }, { from: 10, label: '10–100' }, { from: 100, label: '100–1K' },
  { from: 1000, label: '1K–2K' }, { from: 2000, label: '2K+' },
];
const FLOW_LOG_Q = ['log10', ['max', ['get', 'q'], 0.1]];
// Animation: changing line-dasharray makes MapLibre rebuild the source tiles, so
// the page carries one layer per dash phase and only cycles their opacity.
// Dashes are measured in line widths, so wider rivers get longer dashes that
// cover more pixels per tick: that is the speed difference. Every class moves
// one tenth of a period per tick, which always reads as forward motion.
const FLOW_DASH = { length: 2.2, gap: 2.4 };          // in line widths
const FLOW_DASH_STEPS = 10;                           // phase layers, all drawn every frame: keep small
const FLOW_DASH_MIN_CMS = 20;                         // animate streams from 20 m³/s; smaller ones stay static
const FLOW_TICK_MS = 70;
const PULSE_MS = 2600, PULSE_LENGTH = 0.22;          // one pulse runs the length of a link or trunk stage in 2.6 s
const pulseWindow = (p) => [p, Math.min(1, p + PULSE_LENGTH)];
const FLOW_DASH_OPACITY = 0.9;
let flowStep = 0;
let flowAnimating = true;
let styleReady = true;                               // false only while a basemap switch reloads the style

function flowWidthExpr(scale) {
  const px = (zoomScale) => ['interpolate', ['linear'], FLOW_LOG_Q, ...FLOW_WIDTH_STOPS.flatMap(([l, w]) => [l, w * scale * zoomScale])];
  return ['interpolate', ['linear'], ['zoom'], 6, px(0.7), 9, px(1.3), 12, px(2.2)];
}
function flowColorExpr(theme) {
  const colours = MAP_THEMES[theme].flow;
  return ['step', ['get', 'q'], colours[0], ...FLOW_CLASSES.slice(1).flatMap((cls, i) => [cls.from, colours[i + 1]])];
}
/** The dash pattern shifted by `step` tenths of a period, so successive steps slide the dashes downstream. */
function dashPatternAt(step) {
  const round = (v) => Math.round(v * 100) / 100;
  const period = FLOW_DASH.length + FLOW_DASH.gap;
  const p = round((step % FLOW_DASH_STEPS) / FLOW_DASH_STEPS * period);
  if (p <= FLOW_DASH.gap) return [0, p, FLOW_DASH.length, round(FLOW_DASH.gap - p)];
  const shift = round(p - FLOW_DASH.gap);
  return [round(FLOW_DASH.length - shift), FLOW_DASH.gap, shift, 0];
}

// Cropland rasters (GLAD): one PNG per period plus the change map, all on the same Mercator extent.
let cropMode = 'off';                      // off | before | after | change
let cropBounds = null;                     // [west, south, east, north] from cropland.json
function cropCoords() {
  const [w, s, e, n] = cropBounds;
  return [[w, n], [e, n], [e, s], [w, s]];
}
function cropLayers(t) {
  if (!cropBounds) return [];
  return ['before', 'after', 'change'].map((mode) => ({
    id: `crop-${mode}`, type: 'raster', source: `crop-${mode}`,
    layout: { visibility: cropMode === mode ? 'visible' : 'none' },
    paint: { 'raster-opacity': t.cropOpacity, 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
  }));
}
function cropSources() {
  if (!cropBounds) return {};
  return Object.fromEntries(['before', 'after', 'change'].map((mode) => [
    `crop-${mode}`, { type: 'image', url: `data/cropland_${mode}.png`, coordinates: cropCoords() }]));
}

// Canals (OpenStreetMap): thin dashed cyan lines, dashes sliding in the flow direction.
let canalMode = 'after';                   // off | after | all
let canalsLoaded = false;
const CANAL_DASH = [3, 2.2];               // in line widths, longer than the river dashes
// Status filter (all | built | pending) shared by dams, pump houses, links and canals.
let statusMode = 'all';
const isPending = (status) => status !== 'operational';
const statusShown = (status) => statusMode === 'all' || (statusMode === 'pending') === isPending(status);
const STATUS_LABEL = { operational: 'operating', 'in progress': 'under construction', 'under construction': 'under construction', planned: 'planned', proposed: 'proposed' };
const linkStatusFilter = () => (statusMode === 'all' ? ['literal', true] : [statusMode === 'built' ? '==' : '!=', ['get', 'status'], 'operational']);
// OSM marks the Sitarama canals under construction; every other canal counts as built.
const canalFilter = () => ['all', canalMode === 'all' ? ['literal', true] : ['==', ['get', 'era'], 'after'],
                           statusMode === 'all' ? ['literal', true] : ['==', ['get', 'construction'], statusMode === 'pending']];
function canalLayers(t) {
  if (!canalsLoaded) return [];
  const vis = canalMode === 'off' ? 'none' : 'visible';
  const isNew = ['==', ['get', 'era'], 'after'];
  const isTunnel = ['==', ['get', 'kind'], 'tunnel'];
  const isMain = ['==', ['get', 'kind'], 'main'];
  // MapLibre allows one zoom interpolation per expression, so the kind and era cases sit inside each stop.
  // `s` scales the base width per kind; older canals draw at 60 %.
  const kindWidth = (base, s) => ['case',
    isTunnel, ['case', isNew, base * s.tunnel, base * 0.6 * s.tunnel],
    isMain, ['case', isNew, base * s.main, base * 0.6 * s.main],
    ['case', isNew, base * s.canal, base * 0.6 * s.canal]];
  const width = (s) => ['interpolate', ['linear'], ['zoom'], 6, kindWidth(1.4, s), 9, kindWidth(2.6, s), 12, kindWidth(4.2, s)];
  return [
    // Casing: canals get a thin contrast edge; tunnels a wide one so they read as a tube; mains in between.
    { id: 'canals-casing', type: 'line', source: 'canals', filter: canalFilter(), layout: { 'line-join': 'round', 'line-cap': 'round', visibility: vis },
      paint: { 'line-color': t.canalCasing, 'line-width': width({ canal: 1.9, tunnel: 3.2, main: 2.4 }),
               'line-opacity': ['case', isNew, ['case', isTunnel, 0.9, 0.75], 0.4] } },
    { id: 'canals-line', type: 'line', source: 'canals', filter: canalFilter(), layout: { 'line-join': 'round', 'line-cap': 'round', visibility: vis },
      paint: { 'line-color': ['case', isNew, t.canal, t.canalOld], 'line-width': width({ canal: 1, tunnel: 1.6, main: 1.2 }),
               'line-opacity': ['case', isNew, 0.95, 0.7],
               'line-dasharray': ['case', isTunnel, ['literal', [0.6, 1.1]], isMain, ['literal', [1, 0]], ['literal', CANAL_DASH]] } },
    ...Array.from({ length: FLOW_DASH_STEPS }, (_, k) => ({
      id: `canals-dash-${k}`, type: 'line', source: 'canals', filter: ['all', canalFilter(), ['==', ['get', 'directed'], true]],
      layout: { 'line-join': 'round', 'line-cap': 'butt', visibility: vis },
      paint: { 'line-color': t.canalDash, 'line-width': width({ canal: 0.45, tunnel: 0.7, main: 0.45 }),
               'line-dasharray': ['literal', canalDashAt(k)], 'line-opacity': k === flowStep ? 0.9 : 0 } })),
    { id: 'canals-hit', type: 'line', source: 'canals', filter: canalFilter(), layout: { visibility: vis },
      paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 12 } },
  ];
}
/** Canal dash pattern shifted by `step` tenths of a period (same mechanism as the rivers). */
function canalDashAt(step) {
  const round = (v) => Math.round(v * 100) / 100;
  const [length, gap] = CANAL_DASH, period = length + gap;
  const p = round((step % FLOW_DASH_STEPS) / FLOW_DASH_STEPS * period);
  if (p <= gap) return [0, p, length, round(gap - p)];
  const shift = round(p - gap);
  return [round(length - shift), gap, shift, 0];
}
function applyCanalFilters() {
  if (!canalsLoaded) return;
  const vis = canalMode === 'off' ? 'none' : 'visible';
  const ids = ['canals-casing', 'canals-line', 'canals-hit', ...Array.from({ length: FLOW_DASH_STEPS }, (_, k) => `canals-dash-${k}`)];
  for (const id of ids) {
    map.setLayoutProperty(id, 'visibility', vis);
    map.setFilter(id, id.startsWith('canals-dash') ? ['all', canalFilter(), ['==', ['get', 'directed'], true]] : canalFilter());
  }
}
function setCanalMode(mode) {
  canalMode = mode;
  for (const button of document.querySelectorAll('[data-canal]')) button.setAttribute('aria-pressed', String(button.dataset.canal === mode));
  applyCanalFilters();
  if (mode === 'off') canalPopup.remove();
}
for (const button of document.querySelectorAll('[data-canal]')) button.addEventListener('click', () => setCanalMode(button.dataset.canal));

// Tanks (OpenStreetMap water bodies) and the Mission Kakatiya restoration counts by district.
let tankMode = 'tanks';                    // off | tanks | kakatiya
let tanksLoaded = false;
let tankSummary = null;
const TANK_POLYGON_ZOOM = 9;               // real outlines from here up, centroid dots below
const TANK_HEAT_ZOOM = 8.5;                // a heatmap of tank density below this, fading into the dots
const districtCentres = new Map();         // district -> [lon, lat]
const tankVisibility = () => (tankMode !== 'off' && statusMode !== 'pending' ? 'visible' : 'none');   // tanks all exist today
function tankLayers(t) {
  if (!tanksLoaded) return [];
  const vis = tankVisibility();
  // Dot radius grows with the square root of the water spread; one zoom interpolation per expression.
  const radius = ['interpolate', ['linear'], ['zoom'],
    6, ['min', 4, ['+', 0.8, ['*', 0.05, ['sqrt', ['get', 'area_ha']]]]],
    9, ['min', 16, ['+', 1.6, ['*', 0.25, ['sqrt', ['get', 'area_ha']]]]]];
  return [
    { id: 'tanks-kakatiya', type: 'fill', source: 'districts', layout: { visibility: tankMode === 'kakatiya' ? 'visible' : 'none' },
      paint: { 'fill-color': kakatiyaFill(t), 'fill-opacity': 0.7 } },
    { id: 'tanks-fill', type: 'fill', source: 'tanks', minzoom: TANK_POLYGON_ZOOM, layout: { visibility: vis },
      paint: { 'fill-color': t.tank, 'fill-opacity': 0.72 } },
    { id: 'tanks-outline', type: 'line', source: 'tanks', minzoom: TANK_POLYGON_ZOOM, layout: { visibility: vis, 'line-join': 'round' },
      paint: { 'line-color': t.tankEdge, 'line-width': 0.8, 'line-opacity': 0.8 } },
    { id: 'tanks-heat', type: 'heatmap', source: 'tank-points', maxzoom: TANK_HEAT_ZOOM, layout: { visibility: vis }, paint: {
        'heatmap-weight': ['interpolate', ['linear'], ['sqrt', ['get', 'area_ha']], 0, 0.05, 30, 1],
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5.6, 20, TANK_HEAT_ZOOM, 38],   // wide enough to merge into a density field
        'heatmap-intensity': 0.45,
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.2, t.heat[0], 0.6, t.heat[1], 1, t.heat[2]],
        'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], TANK_HEAT_ZOOM - 1, 0.42, TANK_HEAT_ZOOM, 0] } },
    { id: 'tanks-dots', type: 'circle', source: 'tank-points', minzoom: TANK_HEAT_ZOOM - 1, maxzoom: TANK_POLYGON_ZOOM, layout: { visibility: vis },
      paint: { 'circle-radius': radius, 'circle-color': t.tank, 'circle-opacity': 0.85, 'circle-stroke-color': t.tankEdge, 'circle-stroke-width': 0.5 } },
  ];
}
/** District fill shaded by tanks taken up under Mission Kakatiya (square-root scale, darkest = most). */
function kakatiyaFill(t) {
  if (!tankSummary) return 'rgba(0,0,0,0)';
  const max = Math.max(...tankSummary.districts.map((d) => kakatiyaTotal(d) || 0));
  const expression = ['match', ['get', 'shapeName']];
  for (const d of tankSummary.districts) {
    const total = kakatiyaTotal(d);
    if (total) expression.push(d.district, mixColour(t.tankRamp[0], t.tankRamp[1], Math.sqrt(total / max)));
  }
  expression.push('rgba(0,0,0,0)');
  return expression;
}
/** Mulugu and Narayanpet were carved out in 2019: their tanks sit in the parent district's 2016 count. */
function kakatiyaTotal(d) {
  const source = d.mk_counted_in ? tankSummary.districts.find((row) => row.district === d.mk_counted_in) : d;
  return source ? source.mk_total : null;
}
function mixColour(a, b, f) {
  const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const [x, y] = [rgb(a), rgb(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * f)).join(',')})`;
}
function applyTankVisibility() {
  if (!tanksLoaded) return;
  for (const id of ['tanks-fill', 'tanks-outline', 'tanks-heat', 'tanks-dots']) map.setLayoutProperty(id, 'visibility', tankVisibility());
  map.setLayoutProperty('tanks-kakatiya', 'visibility', tankMode === 'kakatiya' ? 'visible' : 'none');
}
function setTankMode(mode) {
  tankMode = mode;
  for (const button of document.querySelectorAll('[data-tank]')) button.setAttribute('aria-pressed', String(button.dataset.tank === mode));
  document.body.classList.toggle('tank-mk', mode === 'kakatiya');
  applyTankVisibility();
  applyDistrictLabels();
  if (mode === 'off') tankPopup.remove();
}
for (const button of document.querySelectorAll('[data-tank]')) button.addEventListener('click', () => setTankMode(button.dataset.tank));

// Groundwater: India-WRIS monitoring wells, depth to water in May before and after 2014.
let gwMode = 'off';                        // off | before | after | change
let gwLoaded = false;
let gwData = null;                         // groundwater_summary.json
const gwVisibility = () => (gwMode !== 'off' && statusMode !== 'pending' ? 'visible' : 'none');
const gwField = () => (gwMode === 'off' ? 'change' : gwMode);               // the field a hidden layer is styled for
const gwRamp = (t, field) => (field === 'change' ? t.gwChange : t.gwDepth);
/** Colour of a value on a ramp of [stop, colour] pairs, clamped at the ends. */
function rampColour(ramp, value) {
  if (value <= ramp[0][0]) return ramp[0][1];
  for (let i = 1; i < ramp.length; i++) {
    if (value <= ramp[i][0]) return mixColour(ramp[i - 1][1], ramp[i][1], (value - ramp[i - 1][0]) / (ramp[i][0] - ramp[i - 1][0]));
  }
  return ramp[ramp.length - 1][1];
}
function gwWellColour(t, field) { return ['interpolate', ['linear'], ['get', field], ...gwRamp(t, field).flat()]; }
/** District fill from the summary: mean depth before or after, or the median change of its wells. */
function gwDistrictFill(t, field) {
  const expression = ['match', ['get', 'shapeName']];
  for (const d of (gwData ? gwData.districts : [])) if (d[field] !== null) expression.push(d.district, rampColour(gwRamp(t, field), d[field]));
  return expression.length > 2 ? [...expression, 'rgba(0,0,0,0)'] : 'rgba(0,0,0,0)';
}
function gwLayers(t) {
  if (!gwLoaded) return [];
  const field = gwField();
  return [
    { id: 'gw-districts', type: 'fill', source: 'districts', layout: { visibility: gwVisibility() },
      paint: { 'fill-color': gwDistrictFill(t, field), 'fill-opacity': 0.55 } },
    { id: 'gw-wells', type: 'circle', source: 'groundwater', filter: ['has', field], layout: { visibility: gwVisibility() },
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 2.6, 9, 5, 12, 9], 'circle-color': gwWellColour(t, field),
               'circle-opacity': 0.92, 'circle-stroke-color': t.gwStroke, 'circle-stroke-width': 0.6 } },
  ];
}
function applyGwMode() {
  if (!gwLoaded) return;
  const t = MAP_THEMES[currentTheme()];
  const field = gwField();
  map.setLayoutProperty('gw-districts', 'visibility', gwVisibility());
  map.setLayoutProperty('gw-wells', 'visibility', gwVisibility());
  map.setPaintProperty('gw-districts', 'fill-color', gwDistrictFill(t, field));
  map.setFilter('gw-wells', ['has', field]);
  map.setPaintProperty('gw-wells', 'circle-color', gwWellColour(t, field));
}
function setGwMode(mode) {
  gwMode = mode;
  for (const button of document.querySelectorAll('[data-gw]')) button.setAttribute('aria-pressed', String(button.dataset.gw === mode));
  applyGwMode();
  renderGwLegend();
  if (mode === 'off') gwPopup.remove();
}
for (const button of document.querySelectorAll('[data-gw]')) button.addEventListener('click', () => setGwMode(button.dataset.gw));

// Proposal: river water for 90 % of farmland, computed by propose_water.py (reservoirs, lift deliveries, routes, commands).
let proposalMode = 'off';                  // off | on
let proposalLoaded = false;
let proposalData = null;                   // proposal.json
let proposalGeo = null;                    // proposal.geojson, also handed to the map source
const propVisibility = () => (proposalMode === 'on' ? 'visible' : 'none');
// Elevated line: the `hg` array (water height above ground, sampled evenly along the line) sets the height at each point.
const RIBBON = { 'line-elevation-reference': 'ground', 'line-z-offset': ['at-interpolated', ['*', ['line-progress'], ['-', ['length', ['get', 'hg']], 1]], ['get', 'hg']] };
function proposalLayers(t) {
  if (!proposalLoaded) return [];
  const vis = propVisibility();
  const kind = (k) => ['==', ['get', 'kind'], k];
  return [
    { id: 'prop-command-existing', type: 'fill', source: 'proposal', filter: kind('command_existing'), layout: { visibility: vis }, paint: { 'fill-color': t.propCmdExisting } },
    { id: 'prop-command-new', type: 'fill', source: 'proposal', filter: kind('command_new'), layout: { visibility: vis }, paint: { 'fill-color': t.propCmdNew } },
    { id: 'prop-pool', type: 'fill', source: 'proposal', filter: kind('pool'), layout: { visibility: vis }, paint: { 'fill-color': t.propPool, 'fill-opacity': 0.6 } },
    { id: 'prop-pool-line', type: 'line', source: 'proposal', filter: kind('pool'), layout: { visibility: vis }, paint: { 'line-color': t.propPool, 'line-width': 1.5 } },
    // Routes ride the terrain as ribbons: lifted off the ground by the water's height above it (aqueducts, rising mains), on it elsewhere.
    { id: 'prop-canal', type: 'line', source: 'proposal', filter: ['in', ['get', 'kind'], ['literal', ['canal', 'cut', 'aqueduct', 'pressure main']]],
      layout: { visibility: vis, 'line-cap': 'round', 'line-join': 'round', ...RIBBON },
      paint: { 'line-color': ['match', ['get', 'kind'], 'pressure main', t.propPump, t.prop], 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 2.2, 10, 4.2] } },
    { id: 'prop-tunnel', type: 'line', source: 'proposal', filter: kind('tunnel'), layout: { visibility: vis },
      paint: { 'line-color': t.prop, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 2.6, 10, 4.8], 'line-dasharray': [0.5, 1.3] } },
    { id: 'prop-delivery', type: 'circle', source: 'proposal', filter: kind('delivery'), layout: { visibility: vis },
      paint: { 'circle-radius': 7, 'circle-color': t.prop, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 } },
    { id: 'prop-pump', type: 'circle', source: 'proposal', filter: kind('pump'), layout: { visibility: vis },
      paint: { 'circle-radius': 5, 'circle-color': t.propPump, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.2 } },
    { id: 'prop-trunk-existing', type: 'line', source: 'proposal', filter: ['all', kind('trunk'), ['==', ['get', 'existing'], true]], layout: { visibility: vis, ...RIBBON },
      paint: { 'line-color': t.propTrunk, 'line-width': 2, 'line-opacity': 0.7, 'line-dasharray': [2, 1.5] } },
    { id: 'prop-trunk-new', type: 'line', source: 'proposal', filter: ['all', kind('trunk'), ['==', ['get', 'existing'], false]], layout: { visibility: vis, 'line-cap': 'round', 'line-join': 'round', ...RIBBON },
      paint: { 'line-color': t.propTrunk, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3.2, 10, 6] } },
    { id: 'prop-trunk-pulse', type: 'line', source: 'proposal', filter: kind('trunk'), layout: { visibility: vis, 'line-cap': 'round', 'line-join': 'round', ...RIBBON },
      paint: { 'line-color': 'rgba(0,0,0,0)', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3.6, 10, 6.4],
               'line-trim-offset': pulseWindow(0), 'line-trim-color': t.propPulse, 'line-trim-fade-range': [0.45, 0.45] } },
  ];
}
function setProposalMode(mode) {
  proposalMode = mode;
  for (const button of document.querySelectorAll('[data-proposal]')) button.setAttribute('aria-pressed', String(button.dataset.proposal === mode));
  document.body.classList.toggle('proposal-off', mode === 'off');
  if (proposalLoaded) for (const layer of proposalLayers(MAP_THEMES[currentTheme()])) map.setLayoutProperty(layer.id, 'visibility', propVisibility());
  if (mode === 'off') proposalPopup.remove();
}
for (const button of document.querySelectorAll('[data-proposal]')) button.addEventListener('click', () => setProposalMode(button.dataset.proposal));
document.body.classList.add('proposal-off');

function chipOn(name) {
  const chip = document.querySelector(`.chip[data-toggle="${name}"]`);
  return chip.getAttribute('aria-pressed') === 'true' ? 'visible' : 'none';
}

/** Which Mapbox Standard slot an atlas layer renders in: polygons and rasters under the basemap's roads, lines above them, labels on top. */
function slotFor(layer) {
  if (layer.type === 'symbol') return 'top';
  return ['line', 'circle'].includes(layer.type) ? 'middle' : 'bottom';
}
function basemapConfig(theme) {
  const labels = { showPlaceLabels: false, showPointOfInterestLabels: false, showTransitLabels: false, showRoadLabels: roadLabelsShown };
  return basemap === 'satellite' ? labels : { ...labels, lightPreset: lightPresetFor(theme), theme: 'faded', show3dObjects: true };
}
function buildStyle(theme) {
  const t = MAP_THEMES[theme];
  const style = {
    version: 8,
    imports: [{ id: 'basemap', url: BASEMAPS[basemap], config: basemapConfig(theme) }],
    glyphs: 'mapbox://fonts/mapbox/{fontstack}/{range}.pbf',
    projection: { name: 'mercator' },
    sources: {
      'mapbox-dem': { type: 'raster-dem', url: DEM_TILESET, tileSize: 512, maxzoom: 14 },
      'relief-dem': { type: 'raster', url: DEM_TILESET, tileSize: 512, maxzoom: 14 },   // the same tiles read as colours for the relief tint
      mask: { type: 'geojson', data: 'data/mask.geojson' },
      state: { type: 'geojson', data: 'data/state.geojson' },
      districts: { type: 'geojson', data: 'data/districts.geojson' },
      flow: { type: 'geojson', data: 'data/flow.geojson' },
      contours: { type: 'geojson', data: 'data/contours.geojson' },
      links: { type: 'geojson', data: 'data/links.geojson', lineMetrics: true },
      ...cropSources(),
      ...(canalsLoaded ? { canals: { type: 'geojson', data: 'data/canals.geojson' } } : {}),
      ...(tanksLoaded ? { tanks: { type: 'geojson', data: 'data/tanks.geojson' }, 'tank-points': { type: 'geojson', data: 'data/tank_points.geojson' } } : {}),
      ...(gwLoaded ? { groundwater: { type: 'geojson', data: 'data/groundwater.geojson' } } : {}),
      ...(proposalLoaded ? { proposal: { type: 'geojson', data: proposalGeo, lineMetrics: true } } : {}),
      ...Object.fromEntries(Object.entries(labelData).map(([id, data]) => [id, { type: 'geojson', data, generateId: true }])),
      scrub: { type: 'geojson', data: scrubPoint },
    },
    layers: [
      { id: 'relief', type: 'raster', source: 'relief-dem', layout: { visibility: chipOn('relief') }, paint: {
          'raster-color': reliefExpression(theme), 'raster-color-mix': DEM_COLOR_MIX, 'raster-color-range': [0, RELIEF_RANGE_M],
          'raster-opacity': ['interpolate', ['linear'], ['zoom'], 6, Math.min(0.95, t.reliefOpacity + 0.25), 9, t.reliefOpacity, 12.5, t.reliefOpacity * 0.45],
          'raster-resampling': 'linear', 'raster-fade-duration': 0 } },
      { id: 'hillshade', type: 'hillshade', source: 'mapbox-dem', layout: { visibility: chipOn('hillshade') }, paint: {
          'hillshade-illumination-direction': 315, 'hillshade-exaggeration': ['interpolate', ['linear'], ['zoom'], 6, 0.9, 10, 0.6],
          'hillshade-shadow-color': t.shadow, 'hillshade-highlight-color': t.highlight, 'hillshade-accent-color': t.accent } },
      ...cropLayers(t),                      // under the mask so land outside the state stays dimmed
      { id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': t.mask, 'fill-opacity': t.maskOpacity } },
      { id: 'contours', type: 'line', source: 'contours', layout: { visibility: chipOn('contours'), 'line-join': 'round' }, paint: {
          'line-color': t.contour, 'line-opacity': 0.55,
          'line-width': ['case', ['==', ['%', ['get', 'elev'], 500], 0], 1.4, 0.6] } },
      { id: 'contour-labels', type: 'symbol', source: 'contours', minzoom: 8.6, filter: ['==', ['%', ['get', 'elev'], 200], 0],
        layout: { visibility: chipOn('contours'), 'symbol-placement': 'line', 'symbol-spacing': 260, 'text-field': ['concat', ['get', 'elev'], ' m'], 'text-font': FONT,
                  'text-size': 10.5, 'text-rotation-alignment': 'map', 'text-pitch-alignment': 'map', 'text-max-angle': 45, 'text-allow-overlap': false, 'text-padding': 6 },
        paint: { 'text-color': t.contour, 'text-halo-color': t.labelHalo, 'text-halo-width': 1.2, 'text-opacity': 0.9 } },
      ...tankLayers(t),                      // tanks and the Mission Kakatiya shading sit under the district lines
      ...gwLayers(t),                        // groundwater wells and district shading, same slot
      ...proposalLayers(t),                  // proposed reservoirs, routes and commands
      { id: 'districts', type: 'line', source: 'districts', layout: { visibility: chipOn('districts'), 'line-join': 'round' }, paint: {
          'line-color': t.district, 'line-opacity': t.districtOpacity,
          'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.5, 10, 1.2] } },
      { id: 'state-casing', type: 'line', source: 'state', layout: { 'line-join': 'round' }, paint: {
          'line-color': t.stateCasing, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3, 10, 6], 'line-opacity': 0.6 } },
      { id: 'state', type: 'line', source: 'state', layout: { 'line-join': 'round' }, paint: {
          'line-color': t.state, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.4, 10, 2.6] } },
      { id: 'flow-glow', type: 'line', source: 'flow', filter: ['>=', ['get', 'q'], 300],
        layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: {
          'line-color': t.flowGlow, 'line-width': flowWidthExpr(2.2), 'line-opacity': 0.55, 'line-blur': 3 } },
      { id: 'flow-lines', type: 'line', source: 'flow', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: {
          'line-color': flowColorExpr(theme), 'line-width': flowWidthExpr(1), 'line-opacity': 0.95 } },
      ...Array.from({ length: FLOW_DASH_STEPS }, (_, k) => ({
        id: `flow-dash-${k}`, type: 'line', source: 'flow', filter: ['>=', ['get', 'q'], FLOW_DASH_MIN_CMS],
        layout: { 'line-join': 'round', 'line-cap': 'butt', visibility: chipOn('flow') },
        paint: { 'line-color': t.flowDash, 'line-width': flowWidthExpr(0.5), 'line-dasharray': dashPatternAt(k),
                 'line-opacity': k === flowStep ? FLOW_DASH_OPACITY : 0 } })),
      { id: 'flow-hit', type: 'line', source: 'flow', paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 12 } },
      ...canalLayers(t),
      // Kaleshwaram links: solid where water flows today, dashed where the link is still being built.
      { id: 'links-highlight', type: 'line', source: 'links', filter: ['==', ['get', 'link'], ''],
        layout: { 'line-join': 'round', 'line-cap': 'round', visibility: chipOn('links') },
        paint: { 'line-color': t.link, 'line-width': 12, 'line-opacity': 0.25, 'line-blur': 2 } },
      { id: 'links-casing', type: 'line', source: 'links', filter: linkStatusFilter(), layout: { 'line-join': 'round', 'line-cap': 'round', visibility: chipOn('links') },
        paint: { 'line-color': t.linkDash, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 5, 10, 7.5], 'line-opacity': 0.8 } },
      { id: 'links-line', type: 'line', source: 'links', filter: linkStatusFilter(), layout: { 'line-join': 'round', 'line-cap': 'round', visibility: chipOn('links') },
        paint: { 'line-color': t.link, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 2.6, 10, 4.2],
                 'line-opacity': ['case', ['==', ['get', 'status'], 'operational'], 0.9, 0.6],
                 'line-dasharray': ['case', ['==', ['get', 'status'], 'operational'], ['literal', [1, 0]], ['==', ['get', 'status'], 'planned'], ['literal', [0.6, 2.4]], ['literal', [2, 2]]] } },
      // Operating links carry a pulse of light travelling in the direction of pumping: a line-trim window moved every frame.
      { id: 'links-pulse', type: 'line', source: 'links', filter: ['all', ['==', ['get', 'status'], 'operational'], linkStatusFilter()],
        layout: { 'line-join': 'round', 'line-cap': 'round', visibility: chipOn('links') },
        paint: { 'line-color': 'rgba(0,0,0,0)', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 3.4, 10, 5.6],
                 'line-trim-offset': pulseWindow(0), 'line-trim-color': t.linkDash, 'line-trim-fade-range': [0.45, 0.45] } },
      // Static arrows give direction on links still being built.
      { id: 'links-arrows', type: 'symbol', source: 'links', filter: ['all', ['!=', ['get', 'status'], 'operational'], linkStatusFilter()],
        layout: { 'symbol-placement': 'line', 'symbol-spacing': 70, 'icon-image': 'arrow', 'icon-size': ['interpolate', ['linear'], ['zoom'], 6, 0.4, 10, 0.6],
                  'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true, visibility: chipOn('links') },
        paint: { 'icon-opacity': 0.7 } },
      { id: 'links-hit', type: 'line', source: 'links', filter: linkStatusFilter(), layout: { visibility: chipOn('links') },
        paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 16 } },
      { id: 'scrub', type: 'circle', source: 'scrub', paint: { 'circle-radius': 6, 'circle-color': t.labelActive, 'circle-stroke-color': t.iconBg, 'circle-stroke-width': 2 } },
      ...labelLayers(theme),
    ],
    terrain: { source: 'mapbox-dem', exaggeration: terrainExaggeration() },
    fog: t.fog,
  };
  for (const layer of style.layers) decorate(layer);
  return style;
}
// Slot in the Standard stack, and full emissive strength for data layers so the day/night lighting shades the
// terrain and basemap but never the atlas's own colours (the relief tint and hillshade stay lit, as scenery).
const EMISSIVE = { line: 'line-emissive-strength', fill: 'fill-emissive-strength', circle: 'circle-emissive-strength', raster: 'raster-emissive-strength' };
function decorate(layer) {
  layer.slot = slotFor(layer);
  const property = EMISSIVE[layer.type];
  if (property && layer.id !== 'relief') { layer.paint = layer.paint || {}; if (!(property in layer.paint)) layer.paint[property] = 1; }
  return layer;
}
/** addLayer with a `before` only when both layers share a slot (Mapbox refuses to order across slots). */
function addLayers(layers, beforeId) {
  for (const layer of layers) {
    decorate(layer);
    const before = beforeId && map.getLayer(beforeId) && slotFor(map.getLayer(beforeId)) === layer.slot ? beforeId : undefined;
    map.addLayer(layer, before);
  }
}

if (!window.MAPBOX_TOKEN) {
  $('toast').textContent = 'Mapbox token missing: set the MAPBOX_TOKEN environment variable and restart serve.py (see the README).';
  throw new Error('MAPBOX_TOKEN missing');
}
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const INTRO = { zoom: HOME.zoom - 0.9, pitch: 0, bearing: 0 };          // where the opening flight starts, on flat terrain
const playIntro = !location.hash && !reducedMotion && !DEBUG;
if (playIntro) terrainRise = 0.05;
const map = new mapboxgl.Map({
  container: 'map', accessToken: window.MAPBOX_TOKEN,
  style: buildStyle(currentTheme()),
  center: HOME.center, ...(playIntro ? INTRO : { zoom: HOME.zoom, pitch: HOME.pitch, bearing: HOME.bearing }),
  minZoom: 5.6, maxZoom: 13.5, maxPitch: 80,
  maxBounds: [[72.5, 11.5], [86.5, 23.5]],   // generous: Mapbox keeps the whole tilted view inside the bounds by zooming in, so a tight box would push the state view past zoom 7
  attributionControl: false, logoPosition: 'bottom-left', hash: true, antialias: true,   // the URL carries the view, so views can be shared
});
map.addControl(new mapboxgl.AttributionControl({ compact: true }), 'bottom-right');
map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new mapboxgl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-right');
map.on('error', (event) => { const message = event && event.error ? event.error.message : String(event); debug.errors.push(message); console.error(message); writeDebug(); });
debug.phase = 'map-created'; writeDebug();

// Direction arrows for the links, drawn on a canvas so no sprite is needed; recoloured per theme.
function arrowImage(colour) {
  const size = 32, canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.beginPath(); ctx.moveTo(6, 6); ctx.lineTo(26, 16); ctx.lineTo(6, 26); ctx.lineTo(11, 16); ctx.closePath();
  ctx.fillStyle = colour; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineJoin = 'round'; ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}
function syncArrowImage() {
  const image = arrowImage(MAP_THEMES[currentTheme()].link);
  if (map.hasImage('arrow')) map.updateImage('arrow', image); else map.addImage('arrow', image, { pixelRatio: 2 });
}
// ---------- icons: the SVG symbols in index.html rasterised on demand for the symbol layers ----------
// Image ids read "ic|symbol|colourKey|flags|theme"; flags: p = pending (dashed ring, cone badge), a = approximate (dotted outer ring),
// n = proposed (dashed ring), s = small. The theme is part of the id, so a theme change simply asks for new images.
const ICON_PX = 40, ICON_RATIO = 2;
const iconsInProgress = new Set();
function svgImage(symbol, colour, px) {
  const inner = document.getElementById(`ic-${symbol}`).innerHTML;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${px}" height="${px}" viewBox="0 0 16 16" style="color:${colour};fill:${colour}">${inner}</svg>`;
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  return image.decode().then(() => image);
}
async function renderIcon(id) {
  const [, symbol, colourKey, flags, theme] = id.split('|');
  const t = MAP_THEMES[theme] || MAP_THEMES[currentTheme()];
  const colour = t[colourKey] || t.link;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = ICON_PX;
  const ctx = canvas.getContext('2d');
  const c = ICON_PX / 2;
  const disc = (radius, fill, stroke, width, dash) => {
    ctx.beginPath(); ctx.arc(c, c, radius, 0, Math.PI * 2);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.lineWidth = width; ctx.strokeStyle = stroke; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]); }
  };
  if (symbol === 'dot') {                      // cities and towns
    disc(flags.includes('s') ? 4 : 5.5, colour, t.iconBg, 2);
  } else if (symbol === 'peak') {              // where a river leaves the state: a ring around a core
    disc(13, null, colour, 2); disc(5, colour, t.iconBg, 1.5);
  } else {
    disc(15, t.iconBg, colour, 2, flags.includes('p') || flags.includes('n') ? [3.5, 3] : null);
    if (flags.includes('a')) disc(18.5, null, colour, 1.5, [1.5, 3]);
    ctx.drawImage(await svgImage(symbol, colour, 40), c - 10, c - 10, 20, 20);
    if (flags.includes('p')) {                 // the "still being built" cone
      ctx.beginPath(); ctx.arc(c + 11, c + 11, 7.5, 0, Math.PI * 2); ctx.fillStyle = t.iconBg; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = t.link; ctx.stroke();
      ctx.drawImage(await svgImage('wip', t.link, 24), c + 5, c + 5, 12, 12);
    }
  }
  return ctx.getImageData(0, 0, ICON_PX, ICON_PX);
}
/** Every icon the label layers will ask for in a theme, rendered and added before the symbols lay out. */
async function ensureIcons(theme) {
  const ids = new Set(['ic|dot|label|', 'ic|dot|label|s', 'ic|wip|link|', 'ic|peak|peakIcon|']);
  for (const data of Object.values(labelData)) for (const f of data.features) if (f.properties.icon) ids.add(f.properties.icon);
  await Promise.all([...ids].map(async (base) => {
    const id = `${base}|${theme}`;
    if (map.hasImage(id) || iconsInProgress.has(id)) return;
    iconsInProgress.add(id);
    const image = await renderIcon(id);
    if (!map.hasImage(id)) map.addImage(id, image, { pixelRatio: ICON_RATIO });
    iconsInProgress.delete(id);
  }));
}
map.on('styleimagemissing', async (event) => {
  if (event.id === 'arrow') { syncArrowImage(); return; }
  if (!event.id.startsWith('ic|') || map.hasImage(event.id) || iconsInProgress.has(event.id)) return;
  iconsInProgress.add(event.id);
  const image = await renderIcon(event.id);
  if (!map.hasImage(event.id)) map.addImage(event.id, image, { pixelRatio: ICON_RATIO });
  iconsInProgress.delete(event.id);
});

function applyMapTheme() {
  // buildStyle stays the single source of truth for colours, but its result is applied property by property:
  // a diffed setStyle cannot cope with the Standard import and reloads the whole style, dropping our icons.
  const style = buildStyle(currentTheme());
  for (const layer of style.layers) {
    if (!map.getLayer(layer.id)) continue;
    for (const [key, value] of Object.entries(layer.paint || {})) map.setPaintProperty(layer.id, key, value);
    for (const [key, value] of Object.entries(layer.layout || {})) map.setLayoutProperty(layer.id, key, value);
  }
  if (basemap === 'standard') map.setConfigProperty('basemap', 'lightPreset', lightPresetFor(currentTheme()));
  map.setFog(MAP_THEMES[currentTheme()].fog);
}
function setLightMode(mode) {
  lightMode = mode;
  for (const button of document.querySelectorAll('[data-light]')) button.setAttribute('aria-pressed', String(button.dataset.light === mode));
  if (basemap === 'standard') map.setConfigProperty('basemap', 'lightPreset', lightPresetFor(currentTheme()));
}
for (const button of document.querySelectorAll('[data-light]')) button.addEventListener('click', () => setLightMode(button.dataset.light));
function setBasemap(mode) {
  basemap = mode;
  for (const button of document.querySelectorAll('[data-base]')) button.setAttribute('aria-pressed', String(button.dataset.base === mode));
  document.querySelector('.chip[data-toggle="relief"]').setAttribute('aria-pressed', String(mode === 'standard'));   // imagery shows only without the tint
  styleReady = false;                                               // the flow animation leaves the style alone while it loads
  map.once('style.load', () => { styleReady = true; ensureIcons(currentTheme()); });   // a new style starts without our images
  map.setStyle(buildStyle(currentTheme()), { diff: false });        // the Standard import cannot be diffed
}
for (const button of document.querySelectorAll('[data-base]')) button.addEventListener('click', () => setBasemap(button.dataset.base));

// ---------- elevation under the cursor (the terrain the map is drawing, so the number always matches the surface) ----------
/** Elevation in metres above sea level from the loaded terrain tiles; null where none is loaded yet. */
function elevationAt(lngLat) {
  const elevation = map.queryTerrainElevation(lngLat, { exaggerated: false });
  return elevation === null || elevation === undefined ? null : elevation;
}

const cursorElev = $('cursor-elev'), cursorPos = $('cursor-pos');
function showCursor(lngLat) {
  const elevation = elevationAt(lngLat);
  if (elevation === null) { clearCursor(); return; }
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
  if (cursorFrame || flight) return;
  cursorFrame = requestAnimationFrame(() => { cursorFrame = 0; showCursor(event.lngLat); });
});
function clearCursor() {
  cursorElev.textContent = '—'; cursorPos.textContent = 'Move the pointer over the terrain';
  $('cursor-compare').hidden = true;
}
map.on('mouseout', () => { if (!flight) clearCursor(); });

// ---------- legend ----------
function renderLegend() {
  const pct = (m) => `${(m / LEGEND_MAX * 100).toFixed(1)}%`;
  $('ramp').style.background = bandsOn()
    ? `linear-gradient(90deg, ${Array.from({ length: LEGEND_MAX / BAND_M }, (_, i) => { const c = rampColour(RELIEF_STOPS, i * BAND_M + BAND_M / 2); return `${c} ${pct(i * BAND_M)}, ${c} ${pct((i + 1) * BAND_M)}`; }).join(', ')})`
    : `linear-gradient(90deg, ${RELIEF_STOPS.map(([m, c]) => `${c} ${pct(m)}`).join(', ')})`;
}
(function buildLegend() {
  renderLegend();
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
  map.setTerrain({ source: 'mapbox-dem', exaggeration: terrainExaggeration() });
  map.triggerRepaint();
});

function setVisible(ids, on) { for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); }
let orbiting = false;
function orbitStep() {
  if (!orbiting) return;
  map.setBearing(map.getBearing() + ORBIT_DEG_PER_FRAME);
  requestAnimationFrame(orbitStep);
}
const toggles = {
  relief: (on) => map.setLayoutProperty('relief', 'visibility', on ? 'visible' : 'none'),
  bands: () => { map.setPaintProperty('relief', 'raster-color', reliefExpression(currentTheme())); renderLegend(); },
  hillshade: (on) => map.setLayoutProperty('hillshade', 'visibility', on ? 'visible' : 'none'),
  contours: (on) => setVisible(['contours', 'contour-labels'], on),
  districts: (on) => { map.setLayoutProperty('districts', 'visibility', on ? 'visible' : 'none'); document.body.classList.toggle('districts-off', !on); },
  labels: (on) => setVisible(LABEL_LAYERS.labels, on),
  dams: (on) => setVisible(['dam-labels'], on),
  links: (on) => {
    setVisible(['links-highlight', 'links-casing', 'links-line', 'links-pulse', 'links-arrows', 'links-hit', ...LABEL_LAYERS.links], on);
    if (!on) linkPopup.remove();
  },
  orbit: (on) => { orbiting = on; if (on) orbitStep(); },
  flow: (on) => {
    flowAnimating = on;
    for (let k = 0; k < FLOW_DASH_STEPS; k++) map.setLayoutProperty(`flow-dash-${k}`, 'visibility', on ? 'visible' : 'none');
    if (on) { flowLast = 0; requestAnimationFrame(animateFlow); }
  },
};

// Flow animation: show the next phase layer, hide the previous one (opacity only, no tile reload),
// and move the bubbles every frame.
let flowLast = 0, bubbleLast = 0;
function animateFlow(now) {
  if (!flowAnimating) { clearBubbles(); return; }
  if (!styleReady) { requestAnimationFrame(animateFlow); return; }
  if (now - flowLast >= FLOW_TICK_MS) {
    flowLast = now;
    const previous = flowStep;
    flowStep = (flowStep + 1) % FLOW_DASH_STEPS;
    map.setPaintProperty(`flow-dash-${previous}`, 'line-opacity', 0);
    map.setPaintProperty(`flow-dash-${flowStep}`, 'line-opacity', FLOW_DASH_OPACITY);
    if (canalsLoaded && canalMode !== 'off') {
      map.setPaintProperty(`canals-dash-${previous}`, 'line-opacity', 0);
      map.setPaintProperty(`canals-dash-${flowStep}`, 'line-opacity', 0.9);
    }
  }
  drawBubbles(bubbleLast ? Math.min((now - bubbleLast) / 1000, 0.1) : 0);
  bubbleLast = now;
  const window = pulseWindow((now % PULSE_MS) / PULSE_MS);
  for (const id of ['links-pulse', 'prop-trunk-pulse']) if (map.getLayer(id)) map.setPaintProperty(id, 'line-trim-offset', window);
  requestAnimationFrame(animateFlow);
}

// ---------- bubbles: particles riding the bigger rivers ----------
// [min m³/s, spacing km, radius px, speed px/s]: more water = denser, bigger, faster.
const BUBBLE_CLASSES = [[2000, 1.5, 3.2, 60], [1000, 2.2, 2.7, 48], [300, 3.2, 2.2, 38], [100, 5.0, 1.7, 30]];
const BUBBLE_FADE_M = 1000;                          // fade in/out over the ends of each reach
const EARTH_M_PER_DEG = 111320;
const bubbleCanvas = document.createElement('canvas');
bubbleCanvas.className = 'bubbles';
const bubbleCtx = bubbleCanvas.getContext('2d');
let bubbleReaches = [];

function prepareBubbles(geojson) {
  bubbleReaches = [];
  for (const feature of geojson.features) {
    const q = feature.properties.q;
    if (q < BUBBLE_CLASSES[BUBBLE_CLASSES.length - 1][0]) continue;
    const parts = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.coordinates;
    for (const coords of parts) {
      const cum = [0];
      for (let i = 1; i < coords.length; i++) {
        const dx = (coords[i][0] - coords[i - 1][0]) * EARTH_M_PER_DEG * Math.cos(coords[i][1] * Math.PI / 180);
        const dy = (coords[i][1] - coords[i - 1][1]) * EARTH_M_PER_DEG;
        cum.push(cum[i - 1] + Math.hypot(dx, dy));
      }
      const length = cum[cum.length - 1];
      const [, spacingKm, radius, speed] = BUBBLE_CLASSES.find((cls) => q >= cls[0]);
      const count = Math.max(1, Math.round(length / (spacingKm * 1000)));
      const offset = Math.random() * length;
      const lngs = coords.map((c) => c[0]), lats = coords.map((c) => c[1]);
      bubbleReaches.push({
        coords, cum, length, radius, speed,
        bbox: [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)],
        particles: Array.from({ length: count }, (_, i) => (offset + i * length / count) % length),
      });
    }
  }
  map.getCanvasContainer().insertBefore(bubbleCanvas, map.getCanvas().nextSibling);
  resizeBubbleCanvas();
}
function pointAlong(reach, distance) {
  const { coords, cum } = reach;
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= distance) lo = mid; else hi = mid; }
  const t = (distance - cum[lo]) / ((cum[hi] - cum[lo]) || 1);
  return [coords[lo][0] + (coords[hi][0] - coords[lo][0]) * t, coords[lo][1] + (coords[hi][1] - coords[lo][1]) * t];
}
function resizeBubbleCanvas() {
  const canvas = map.getCanvas(), ratio = window.devicePixelRatio || 1;
  bubbleCanvas.width = canvas.clientWidth * ratio; bubbleCanvas.height = canvas.clientHeight * ratio;
  bubbleCanvas.style.width = `${canvas.clientWidth}px`; bubbleCanvas.style.height = `${canvas.clientHeight}px`;
  bubbleCtx.setTransform(ratio, 0, 0, ratio, 0, 0);
}
function clearBubbles() { bubbleCtx.clearRect(0, 0, bubbleCanvas.width, bubbleCanvas.height); }
function drawBubbles(dt) {
  clearBubbles();
  if (!bubbleReaches.length || flight) return;        // the flight keeps the view clear
  const bounds = map.getBounds(), west = bounds.getWest(), south = bounds.getSouth(), east = bounds.getEast(), north = bounds.getNorth();
  const metresPerPixel = EARTH_M_PER_DEG * 360 * Math.cos(map.getCenter().lat * Math.PI / 180) / (TILE_PX * 2 ** map.getZoom());
  const width = map.getCanvas().clientWidth, height = map.getCanvas().clientHeight;
  for (const reach of bubbleReaches) {
    const [minLng, minLat, maxLng, maxLat] = reach.bbox;
    const step = reach.speed * metresPerPixel * dt;
    for (let i = 0; i < reach.particles.length; i++) reach.particles[i] = (reach.particles[i] + step) % reach.length;
    if (maxLng < west || minLng > east || maxLat < south || minLat > north) continue;
    // Zoomed out, bubbles would merge into a bead chain: draw every n-th so they stay apart.
    const spacingPx = reach.length / reach.particles.length / metresPerPixel;
    const skip = Math.max(1, Math.ceil(reach.radius * 2.4 / spacingPx));
    for (let i = 0; i < reach.particles.length; i += skip) {
      const distance = reach.particles[i];
      const point = map.project(pointAlong(reach, distance));
      if (point.x < -10 || point.y < -10 || point.x > width + 10 || point.y > height + 10) continue;
      const alpha = Math.min(1, distance / BUBBLE_FADE_M, (reach.length - distance) / BUBBLE_FADE_M);
      drawBubble(point.x, point.y, reach.radius, alpha);
    }
  }
}
// Bubbles keep one light body and a dark rim in both themes, so they show on
// every river colour (a bubble in its river's own colour vanished on the Krishna).
function drawBubble(x, y, radius, alpha) {
  const gradient = bubbleCtx.createRadialGradient(x - radius * 0.35, y - radius * 0.35, radius * 0.1, x, y, radius);
  gradient.addColorStop(0, `rgba(255,255,255,${0.95 * alpha})`);
  gradient.addColorStop(0.6, `rgba(205,238,255,${0.85 * alpha})`);
  gradient.addColorStop(1, `rgba(160,215,245,${0.6 * alpha})`);
  bubbleCtx.beginPath();
  bubbleCtx.arc(x, y, radius, 0, Math.PI * 2);
  bubbleCtx.fillStyle = gradient; bubbleCtx.fill();
  bubbleCtx.lineWidth = 1; bubbleCtx.strokeStyle = `rgba(11,29,74,${0.85 * alpha})`; bubbleCtx.stroke();
}
map.on('resize', resizeBubbleCanvas);

// Hovering a stream shows its average flow.
const flowPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: 'flow-popup' });
map.on('mousemove', 'flow-hit', (event) => {
  const reach = event.features[0].properties;
  const node = document.createElement('div');
  node.append(bold(`${Math.round(reach.q).toLocaleString('en-IN')} m³/s`), ' ',
              spanText(`average · ${reach.name || 'stream'} · ${Number(reach.up).toLocaleString('en-IN')} km² upstream`));
  flowPopup.setLngLat(event.lngLat).setDOMContent(node).addTo(map);
  map.getCanvas().style.cursor = 'pointer';
});
map.on('mouseleave', 'flow-hit', () => { flowPopup.remove(); map.getCanvas().style.cursor = ''; });

// ---------- river flow panel ----------
function flowWidth(q) {   // mirrors FLOW_WIDTH_STOPS at zoom scale 1
  const l = Math.log10(Math.max(q, 0.1)), stops = FLOW_WIDTH_STOPS;
  if (l <= stops[0][0]) return stops[0][1];
  if (l >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  const i = stops.findIndex((stop, k) => l >= stop[0] && l < stops[k + 1][0]);
  return stops[i][1] + (stops[i + 1][1] - stops[i][1]) * (l - stops[i][0]) / (stops[i + 1][0] - stops[i][0]);
}
function renderFlowLegend() {
  const legend = $('flow-legend');
  legend.textContent = '';
  const colours = MAP_THEMES[currentTheme()].flow;
  FLOW_CLASSES.forEach((cls, i) => {
    const swatch = document.createElement('span'); swatch.className = 'sw';
    const line = document.createElement('i');
    const sampleQ = i + 1 < FLOW_CLASSES.length ? Math.sqrt(Math.max(cls.from, 1) * FLOW_CLASSES[i + 1].from) : 3000;
    line.style.height = `${Math.max(4, flowWidth(sampleQ) * 1.6)}px`; line.style.background = colours[i];
    const label = document.createElement('span'); label.textContent = cls.label;
    swatch.append(line, label); legend.appendChild(swatch);
  });
  const unit = document.createElement('span'); unit.className = 'unit'; unit.textContent = 'm³/s';
  legend.appendChild(unit);
}
function textEl(tag, className, text) { const node = document.createElement(tag); node.className = className; node.textContent = text; return node; }
function flyToPoint(lon, lat, zoom) { map.flyTo({ center: [lon, lat], zoom, pitch: 60, bearing: -20, duration: 2200, essential: true }); }
function renderPeaks(summary) {
  const box = $('peaks');
  box.textContent = '';
  for (const [river, peak] of Object.entries(summary.peaks)) {
    const card = document.createElement('button'); card.type = 'button'; card.className = 'peak';
    const value = textEl('span', 'q', peak.q.toLocaleString('en-IN'));
    value.appendChild(textEl('small', '', 'm³/s'));
    card.append(textEl('span', 'river', river), value,
                textEl('span', 'sub', `peak where it leaves the state · ${peak.entry_q.toLocaleString('en-IN')} m³/s at entry · ${peak.up.toLocaleString('en-IN')} km² drained`));
    card.addEventListener('click', () => flyToPoint(peak.lon, peak.lat, 10));
    box.appendChild(card);
    addPeakMarker(river, peak);
  }
}
function addPeakMarker(river, peak) {
  if (!labelData.peaks) labelData.peaks = collection([]);
  labelData.peaks.features.push(pointFeature(peak.lon, peak.lat, { title: `${river} peak`, detail: ` ${peak.q.toLocaleString('en-IN')} m³/s`, lon: peak.lon, lat: peak.lat }));
}
function renderDistrictFlow(summary) {
  const list = $('district-flow');
  list.textContent = '';
  const maxQ = Math.max(...summary.districts.map((row) => row.mean_q));
  let river = null;
  for (const row of summary.districts) {
    if (row.river !== river) {
      river = row.river;
      const group = document.createElement('li'); group.className = 'group';
      group.append(document.createElement('i'), document.createTextNode(river));
      list.appendChild(group);
    }
    const item = document.createElement('li');
    const button = document.createElement('button'); button.type = 'button'; button.className = 'row';
    const bar = textEl('span', 'bar', ''); bar.style.width = `${Math.max(2, row.mean_q / maxQ * 100)}%`;
    button.append(textEl('span', 'name', row.district), bar, textEl('span', 'val', `${row.mean_q.toLocaleString('en-IN')} m³/s`));
    button.title = `${row.length_km} km of the ${row.river} in ${row.district}, up to ${row.max_q.toLocaleString('en-IN')} m³/s`;
    button.addEventListener('click', () => {
      for (const other of document.querySelectorAll('.district-flow .row')) other.classList.toggle('active', other === button);
      flyToPoint(row.lon, row.lat, 9.6);
    });
    item.appendChild(button); list.appendChild(item);
  }
}
for (const chip of document.querySelectorAll('.chip[data-toggle]')) {
  chip.addEventListener('click', () => {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    toggles[chip.dataset.toggle](on);
  });
}
function stopOrbit() { if (orbiting) document.querySelector('[data-toggle="orbit"]').click(); }
map.on('dragstart', stopOrbit);

// Left-drag mode: MapLibre only rotates with the right button or Ctrl, so a
// "rotates" mode turns left-drag into a full 360° orbit with tilt.
const ROTATE_DEG_PER_PX = 0.35;
let rotateDrag = null;
function setDragMode(mode) {
  for (const button of document.querySelectorAll('[data-drag]')) button.setAttribute('aria-pressed', String(button.dataset.drag === mode));
  if (mode === 'rotate') map.dragPan.disable(); else map.dragPan.enable();
  $('map').classList.toggle('rotate-mode', mode === 'rotate');
}
for (const button of document.querySelectorAll('[data-drag]')) button.addEventListener('click', () => setDragMode(button.dataset.drag));
map.getCanvasContainer().addEventListener('mousedown', (event) => {
  if (!$('map').classList.contains('rotate-mode') || event.button !== 0 || event.ctrlKey) return;
  stopOrbit();
  rotateDrag = { x: event.clientX, y: event.clientY, bearing: map.getBearing(), pitch: map.getPitch() };
  $('map').classList.add('rotating');
  event.preventDefault();
});
window.addEventListener('mousemove', (event) => {
  if (!rotateDrag) return;
  const pitch = rotateDrag.pitch - (event.clientY - rotateDrag.y) * ROTATE_DEG_PER_PX;
  map.jumpTo({ bearing: rotateDrag.bearing + (event.clientX - rotateDrag.x) * ROTATE_DEG_PER_PX,
               pitch: Math.min(Math.max(pitch, 0), map.getMaxPitch()) });
});
window.addEventListener('mouseup', () => { rotateDrag = null; $('map').classList.remove('rotating'); });
$('reset').addEventListener('click', () => map.flyTo({ ...HOME, duration: 1800, essential: true }));
$('view-2d').addEventListener('click', () => { stopFlight(); map.easeTo({ pitch: 0, bearing: 0, duration: 1200, essential: true }); });
$('view-3d').addEventListener('click', () => {
  stopFlight();
  if (map.getPitch() < 30) riseTerrain(1800);                       // from top-down: let the relief grow as the view tilts
  map.easeTo({ pitch: HOME.pitch, bearing: HOME.bearing, duration: 1800, essential: true });
});
$('theme').addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
$('collapse').addEventListener('click', () => { $('panel').classList.add('hidden'); $('expand').hidden = false; });
$('expand').addEventListener('click', () => { $('panel').classList.remove('hidden'); $('expand').hidden = true; });
$('filters-collapse').addEventListener('click', () => { $('filters').classList.add('hidden'); $('filters-expand').hidden = false; });

// Phones and tablets (<= 900 px): the side panels are bottom sheets; opening one closes the other. CSS does the rest.
document.querySelectorAll('.sheet-handle').forEach((handle) => handle.addEventListener('click', () => {
  const sheet = handle.parentElement;
  const open = !sheet.classList.contains('sheet-open');
  document.querySelectorAll('.sheet-open').forEach((s) => {
    s.classList.remove('sheet-open');
    s.querySelector('.sheet-handle').setAttribute('aria-expanded', 'false');
  });
  sheet.classList.toggle('sheet-open', open);
  handle.setAttribute('aria-expanded', String(open));
}));
$('filters-expand').addEventListener('click', () => { $('filters').classList.remove('hidden'); $('filters-expand').hidden = true; });
const updateLabelDensity = () => {
  const near = map.getZoom() >= LABEL_ZOOM;
  if (near === roadLabelsShown || !styleReady) return;
  roadLabelsShown = near;
  map.setConfigProperty('basemap', 'showRoadLabels', near);
};
map.on('zoom', updateLabelDensity);
map.on('moveend', updateLabelDensity);
map.on('load', updateLabelDensity);   // a view restored from the URL hash fires no zoom event
updateLabelDensity();

// ---------- labels: symbol layers from one GeoJSON source per kind, text in Mapbox fonts, icons from the SVG symbols ----------
const cityIndex = new Map();                // city name -> feature id, for the active state
const districtFeatures = new Map();         // district -> its label feature (carries the Mission Kakatiya count)
const labelActions = { 'prop-labels': [] }; // per-feature click handlers for the proposal labels
const LABEL_LAYERS = {
  labels: ['city-labels', 'town-labels', 'district-labels', 'peak-labels', 'prop-labels-far', 'prop-labels-near'],   // the Place labels chip
  links: ['pump-labels', 'wip-labels'],                                                                                // the Water links chip
};
let eraMode = 'all';
function pointFeature(lon, lat, properties) { return { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties }; }
function collection(features) { return { type: 'FeatureCollection', features }; }
const muted = (t, scale) => ({ 'font-scale': scale, 'text-color': t.labelMuted });
const eraFilter = () => (eraMode === 'all' ? ['literal', true] : ['all', ['has', 'year'], [eraMode === 'before' ? '<' : '>=', ['get', 'year'], ERA_YEAR]]);
const damFilter = () => ['all', linkStatusFilter(), eraFilter()];
const districtFilter = () => (tankMode === 'kakatiya' ? ['literal', true] : ['!', ['get', 'named_by_city']]);
const districtText = (t) => (tankMode === 'kakatiya'
  ? ['format', ['upcase', ['get', 'name']], {}, '\n', {}, ['get', 'mk'], { 'font-scale': 1.05, 'text-color': t.label }]
  : ['upcase', ['get', 'name']]);

/** A point symbol layer: icon on the point, text beside it on whichever side is free, text dropped before the icon when space is short. */
function labelLayer(id, source, t, { icon, text, sort, minzoom, filter, size = [11, 13], layout = {} }) {
  const stateColour = ['case', ['any', ['boolean', ['feature-state', 'hover'], false], ['boolean', ['feature-state', 'active'], false]], t.labelActive, t.label];
  return { id, type: 'symbol', source, ...(minzoom ? { minzoom } : {}), ...(filter ? { filter } : {}),
    layout: { 'icon-image': icon, 'icon-size': 1, 'icon-allow-overlap': true, 'text-field': text, 'text-font': FONT,
              'text-size': ['interpolate', ['linear'], ['zoom'], 6, size[0], 10, size[1]], 'text-variable-anchor': ['left', 'right'], 'text-radial-offset': 0.95,
              'text-justify': 'auto', 'text-max-width': 14, 'text-optional': true, 'symbol-sort-key': sort || 0, ...layout },
    paint: { 'text-color': stateColour, 'text-halo-color': t.labelHalo, 'text-halo-width': 1.3, 'text-halo-blur': 0.4 } };
}
function labelLayers(theme) {
  const t = MAP_THEMES[theme];
  const ic = (base) => ['concat', base, '|', theme];        // image id with the theme appended
  const layers = [];
  if (labelData.cities) {
    const text = ['format', ['get', 'name'], {}, ['get', 'elev'], muted(t, 0.85)];
    layers.push(labelLayer('city-labels', 'cities', t, { icon: ic('ic|dot|label|'), text, sort: ['get', 'sort'], filter: ['==', ['get', 'place'], 'city'], size: [12, 14], layout: { visibility: chipOn('labels') } }));
    layers.push(labelLayer('town-labels', 'cities', t, { icon: ic('ic|dot|label|s'), text, sort: ['get', 'sort'], filter: ['!=', ['get', 'place'], 'city'], minzoom: LABEL_ZOOM, layout: { visibility: chipOn('labels') } }));
  }
  if (labelData['district-points']) {
    layers.push({ id: 'district-labels', type: 'symbol', source: 'district-points', minzoom: tankMode === 'kakatiya' ? 0 : LABEL_ZOOM, filter: districtFilter(),
      layout: { 'text-field': districtText(t), 'text-font': FONT, 'text-size': 11, 'text-letter-spacing': 0.12, 'text-max-width': 10, 'symbol-sort-key': 10, visibility: chipOn('labels') },
      paint: { 'text-color': t.labelMuted, 'text-halo-color': t.labelHalo, 'text-halo-width': 1.2 } });
  }
  if (labelData.dams) {
    layers.push(labelLayer('dam-labels', 'dams', t, { icon: ic(['get', 'icon']), text: ['format', ['get', 'name'], {}, ['get', 'cap'], muted(t, 0.85), ['get', 'st'], muted(t, 0.8)],
      sort: ['get', 'sort'], filter: damFilter(), size: [11.5, 13.5], layout: { visibility: chipOn('dams') } }));
  }
  if (labelData.pumphouses) {
    const text = ['step', ['zoom'], '', LABEL_ZOOM, ['format', ['get', 'name'], {}, ['get', 'st'], muted(t, 0.8)]];   // icons only until zoomed in
    layers.push(labelLayer('pump-labels', 'pumphouses', t, { icon: ic(['get', 'icon']), text, sort: 5, filter: linkStatusFilter(), layout: { visibility: chipOn('links') } }));
  }
  if (labelData.wip) {
    layers.push(labelLayer('wip-labels', 'wip', t, { icon: ic('ic|wip|link|'), text: ['get', 'name'], sort: 6, filter: linkStatusFilter(), size: [10.5, 12], layout: { visibility: chipOn('links') } }));
  }
  if (labelData.peaks) {
    layers.push(labelLayer('peak-labels', 'peaks', t, { icon: ic('ic|peak|peakIcon|'), text: ['format', ['get', 'title'], {}, ['get', 'detail'], muted(t, 0.85)], sort: 1, layout: { visibility: chipOn('labels') } }));
  }
  if (labelData['prop-labels']) {
    const text = ['format', ['get', 'title'], {}, ['get', 'detail'], muted(t, 0.85), ' new', { 'font-scale': 0.8, 'text-color': t.prop }];
    const far = ['in', ['get', 'kind'], ['literal', ['reservoir', 'delivery', 'trunk']]];
    layers.push(labelLayer('prop-labels-far', 'prop-labels', t, { icon: ic(['get', 'icon']), text, sort: ['get', 'sort'], filter: far, layout: { visibility: propVisibility() } }));
    layers.push(labelLayer('prop-labels-near', 'prop-labels', t, { icon: ic(['get', 'icon']), text, sort: 8, filter: ['!', far], minzoom: LABEL_ZOOM, layout: { visibility: propVisibility() } }));
  }
  return layers;
}
/** Hover and click through the Interactions API: a pointer cursor and a hover state on the feature. */
function interactive(layerId, onClick) {
  const target = { layerId };
  map.addInteraction(`${layerId}-enter`, { type: 'mouseenter', target, handler: ({ feature }) => { map.getCanvas().style.cursor = 'pointer'; if (feature) map.setFeatureState(feature, { hover: true }); } });
  map.addInteraction(`${layerId}-leave`, { type: 'mouseleave', target, handler: ({ feature }) => { map.getCanvas().style.cursor = ''; if (feature) map.setFeatureState(feature, { hover: false }); } });
  if (onClick) map.addInteraction(`${layerId}-click`, { type: 'click', target, handler: (event) => { onClick(event.feature.properties, event.lngLat); return true; } });
}
function buildCityLabels(cities) {
  labelData.cities = collection(cities.map((city, i) => {
    cityIndex.set(city.name, i);
    return pointFeature(city.lon, city.lat, { i, name: city.name, elev: ` ${city.elev} m`, place: city.place, sort: -(city.population || 0) });
  }));
}
function buildDistrictLabels(points, cityNames) {
  labelData['district-points'] = collection(points.features.map((f) => {
    const name = f.properties.shapeName;
    const feature = pointFeature(f.geometry.coordinates[0], f.geometry.coordinates[1], { name, named_by_city: cityNames.has(name.toLowerCase()), mk: '' });
    districtFeatures.set(name, feature);
    districtCentres.set(name, f.geometry.coordinates);
    return feature;
  }));
}
function applyDistrictLabels() {
  if (!map.getLayer('district-labels')) return;
  map.setFilter('district-labels', districtFilter());
  map.setLayerZoomRange('district-labels', tankMode === 'kakatiya' ? 0 : LABEL_ZOOM, 24);
  map.setLayoutProperty('district-labels', 'text-field', districtText(MAP_THEMES[currentTheme()]));
}
async function addLabelSources() {
  await ensureIcons(currentTheme());
  for (const [id, data] of Object.entries(labelData)) if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data, generateId: true });
  addLayers(labelLayers(currentTheme()));
  interactive('city-labels', (p) => flyToCity(citiesData[p.i]));
  interactive('town-labels', (p) => flyToCity(citiesData[p.i]));
  interactive('dam-labels', (p) => { const dam = damsData[p.i]; openDamPopup(dam); flyToPoint(dam.lon, dam.lat, 11.5); });
  interactive('pump-labels', (p, lngLat) => notePopup.setLngLat(lngLat).setText(p.title).addTo(map));
  interactive('wip-labels', (p, lngLat) => notePopup.setLngLat(lngLat).setText(p.title).addTo(map));
  interactive('peak-labels', (p) => flyToPoint(p.lon, p.lat, 10));
  for (const id of ['prop-labels-far', 'prop-labels-near']) interactive(id, (p) => labelActions['prop-labels'][p.i]());
}
let citiesData = [], damsData = [];
const notePopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 12, className: 'flow-popup', maxWidth: '280px' });
// ---------- dams: markers and the year filter (Telangana was formed in 2014) ----------
const ERA_YEAR = 2014;
function damYear(dam) { return dam.opened || dam.began || null; }
function damInEra(dam, era) {
  const year = damYear(dam);
  return era === 'all' || (year !== null && (era === 'before' ? year < ERA_YEAR : year >= ERA_YEAR));
}
function setEra(era) {
  eraMode = era;
  for (const button of document.querySelectorAll('[data-era]')) button.setAttribute('aria-pressed', String(button.dataset.era === era));
  if (map.getLayer('dam-labels')) map.setFilter('dam-labels', damFilter());
}
function renderEraCounts(dams) {
  for (const button of document.querySelectorAll('[data-era]')) {
    const count = dams.filter((dam) => damInEra(dam, button.dataset.era)).length;
    const badge = button.querySelector('b') || button.appendChild(textEl('b', '', ''));
    badge.textContent = String(count);
  }
}
for (const button of document.querySelectorAll('[data-era]')) button.addEventListener('click', () => setEra(button.dataset.era));

// ---------- status filter: operating vs still to build ----------
function setStatusMode(mode) {
  statusMode = mode;
  for (const button of document.querySelectorAll('[data-status]')) button.setAttribute('aria-pressed', String(button.dataset.status === mode));
  if (map.getLayer('dam-labels')) map.setFilter('dam-labels', damFilter());
  for (const id of ['pump-labels', 'wip-labels']) if (map.getLayer(id)) map.setFilter(id, linkStatusFilter());
  for (const id of ['links-casing', 'links-line', 'links-hit']) if (map.getLayer(id)) map.setFilter(id, linkStatusFilter());
  if (map.getLayer('links-pulse')) map.setFilter('links-pulse', ['all', ['==', ['get', 'status'], 'operational'], linkStatusFilter()]);
  if (map.getLayer('links-arrows')) map.setFilter('links-arrows', ['all', ['!=', ['get', 'status'], 'operational'], linkStatusFilter()]);
  applyTankVisibility();
  applyGwMode();
  applyCanalFilters();
  if (mode !== 'all') { damPopup.remove(); linkPopup.remove(); canalPopup.remove(); }
}
function renderStatusCounts(dams, links) {
  const linkGroups = groupLinks(links);
  for (const button of document.querySelectorAll('[data-status]')) {
    const mode = button.dataset.status;
    const shown = (status) => mode === 'all' || (mode === 'pending') === isPending(status);
    const count = dams.filter((dam) => shown(dam.status)).length + [...linkGroups.values()].filter((group) => shown(group.status)).length;
    const badge = button.querySelector('b') || button.appendChild(textEl('b', '', ''));
    badge.textContent = String(count);
  }
}
for (const button of document.querySelectorAll('[data-status]')) button.addEventListener('click', () => setStatusMode(button.dataset.status));

const formatTmcft = (value) => `${value.toLocaleString('en-IN', { maximumFractionDigits: value < 10 ? 2 : 0 })} tmcft`;
const damYears = (dam) => (dam.began && dam.opened ? `${dam.began}–${dam.opened}` : dam.opened ? `${dam.opened}` : dam.began ? `since ${dam.began}` : null);
// Years of a work still to be built: planned (sanctioned), construction start, announced target.
function pendingYears(item) {
  const parts = [];
  if (item.planned) parts.push(`planned ${item.planned}`);
  if (item.began) parts.push(`construction since ${item.began}`);
  if (item.target) parts.push(`target ${item.target}`);
  return parts.length ? parts.join(' · ') : null;
}
const damPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 16, className: 'dam-popup', maxWidth: '320px' });

const damKindLabel = (dam) => (dam.kind === 'barrage' ? 'Barrage' : dam.river && dam.river.includes('off-river') ? 'Reservoir' : 'Dam');
const iconFlags = (item) => `${isPending(item.status) ? 'p' : ''}${item.approx ? 'a' : ''}`;
function buildDamLabels(dams) {
  damsData = dams;
  labelData.dams = collection(dams.map((dam, i) => pointFeature(dam.lon, dam.lat, {
    i, name: dam.name, status: dam.status, ...(damYear(dam) !== null ? { year: damYear(dam) } : {}),
    icon: `ic|${dam.kind}|${dam.kind}Icon|${iconFlags(dam)}`, sort: -(dam.capacity_tmcft || 0),
    cap: dam.capacity_tmcft ? ` ${formatTmcft(dam.capacity_tmcft)}` : '', st: isPending(dam.status) ? ` · ${STATUS_LABEL[dam.status]}` : '' })));
}

// ---------- Kaleshwaram links: pump houses, tunnel portals and the link list ----------
function buildPumpLabels(houses) {
  labelData.pumphouses = collection(houses.map((house) => pointFeature(house.lon, house.lat, {
    name: `${house.name}${house.power ? ` · ${house.power.replace('MW', ' MW')}` : ''}`, status: house.status,
    icon: `ic|${house.kind === 'tunnel' ? 'tunnel' : 'pump'}|link|${iconFlags(house)}`, st: isPending(house.status) ? ` · ${STATUS_LABEL[house.status]}` : '',
    title: `${house.name}${house.elev_m ? ` · terrain ${house.elev_m} m` : ''}${house.since ? ` · pumping since ${house.since}` : ''}`
         + `${house.approx ? ` · position approximate (${house.approx})` : ''} · ${house.source === 'OpenStreetMap' ? 'OpenStreetMap' : 'see the link popup for the source'}` })));
}

// ---------- cropland panel and mode ----------
const CROP_MODE_LABEL = { off: 'layer off', before: 'showing 2008–2011', after: 'showing 2016–2019', change: 'showing change' };
let cropData = null;

function setCropMode(mode) {
  cropMode = mode;
  for (const button of document.querySelectorAll('[data-crop]')) button.setAttribute('aria-pressed', String(button.dataset.crop === mode));
  for (const m of ['before', 'after', 'change']) if (map.getLayer(`crop-${m}`)) map.setLayoutProperty(`crop-${m}`, 'visibility', m === mode ? 'visible' : 'none');
  $('crop-mode-label').textContent = CROP_MODE_LABEL[mode];
  document.body.classList.toggle('crop-off', mode === 'off');   // the Cropland card shows only with a layer
  renderCropLegend();
}
for (const button of document.querySelectorAll('[data-crop]')) button.addEventListener('click', () => setCropMode(button.dataset.crop));
$('crop-close').addEventListener('click', () => setCropMode('off'));
document.body.classList.add('crop-off');

const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
function renderCropLegend() {
  const legend = $('crop-legend');
  legend.textContent = '';
  if (!cropData || cropMode === 'off') return;
  const bar = document.createElement('div'); bar.className = 'bar';
  const ticks = document.createElement('div'); ticks.className = 'ticks';
  if (cropMode === 'change') {
    const { loss, gain, change_full } = cropData.legend;
    bar.style.background = `linear-gradient(90deg, ${rgb(loss)}, rgba(${loss.join(',')},0.15) 45%, transparent 50%, rgba(${gain.join(',')},0.15) 55%, ${rgb(gain)})`;
    for (const text of [`−${change_full} pp · less cropland`, 'no change', `more cropland · +${change_full} pp`]) ticks.appendChild(textEl('span', '', text));
  } else {
    bar.style.background = `linear-gradient(90deg, ${cropData.legend.ramp.map(([v, c]) => `rgba(${c.join(',')},${0.25 + 0.65 * v / 100}) ${v}%`).join(', ')})`;
    for (const text of ['0 %', '25', '50', '75', '100 % of cell under crops']) ticks.appendChild(textEl('span', '', text));
  }
  legend.append(bar, ticks);
}

function renderCropland(data) {
  cropData = data;
  const before = data.state[String(data.before.year)], after = data.state[String(data.after.year)];
  const summary = $('crop-summary');
  summary.textContent = '';
  summary.append('Cropland covered ', bold(`${before.pct} %`), ` of Telangana in ${before.epoch} and `, bold(`${after.pct} %`), ` in ${after.epoch}: about `,
                 bold(`${(after.km2 - before.km2).toLocaleString('en-IN')} km²`), ' more, on the GLAD 3 km grid. The whole 2000–2019 run: ',
                 Object.values(data.state).map((row) => `${row.pct} %`).join(' → '), '.');
  const tbody = $('crop-official').tBodies[0];
  tbody.textContent = '';
  for (const row of data.official) {
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    const link = document.createElement('a'); link.href = row.source; link.target = '_blank'; link.rel = 'noopener'; link.textContent = row.label;
    label.appendChild(link);
    const b = document.createElement('td'); b.textContent = row.before;
    const a = document.createElement('td'); a.textContent = row.after;
    tr.append(label, b, a); tbody.appendChild(tr);
  }
  renderCropTable(data);
  renderCropLegend();
}

// Cultivated area table: cropland km² from GLAD converted to acres (1 km² = 247.105 acres).
const ACRES_PER_KM2 = 247.105;
const lakhAcres = (km2) => (km2 * ACRES_PER_KM2 / 1e5).toFixed(2);
const acres = (km2) => Math.round(km2 * ACRES_PER_KM2);
const signed = (value) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toLocaleString('en-IN')}`;

function renderCropTable(data) {
  const before = data.state[String(data.before.year)], after = data.state[String(data.after.year)];
  const rows = [...data.districts].sort((a, b) => (b.km2_after - b.km2_before) - (a.km2_after - a.km2_before));
  const tbody = $('crop-table').tBodies[0];
  tbody.textContent = '';
  const addRow = (cells, className, onClick) => {
    const tr = document.createElement('tr');
    if (className) tr.className = className;
    for (const [text, cls] of cells) { const td = document.createElement('td'); if (cls) td.className = cls; td.textContent = text; tr.appendChild(td); }
    if (onClick) tr.addEventListener('click', onClick);
    tbody.appendChild(tr);
    return tr;
  };
  const stateDelta = after.km2 - before.km2;
  addRow([['Telangana', ''], [lakhAcres(before.km2), ''], [lakhAcres(after.km2), ''], [signed(acres(stateDelta)), stateDelta > 0 ? 'up' : 'down']], 'total', null);
  for (const row of rows) {
    const delta = row.km2_after - row.km2_before;
    const tr = addRow([[row.district, ''], [lakhAcres(row.km2_before), ''], [lakhAcres(row.km2_after), ''], [signed(acres(delta)), delta > 0 ? 'up' : delta < 0 ? 'down' : '']], '', () => {
      for (const other of tbody.querySelectorAll('tr')) other.classList.toggle('active', other === tr);
      if (cropMode === 'off') setCropMode('change');
      map.flyTo({ center: [row.lon, row.lat], zoom: 9.3, pitch: 45, bearing: -15, duration: 2000, essential: true });
    });
    tr.title = `${row.district}: ${row.pct_before} % of the district under crops in ${data.before.epoch}, ${row.pct_after} % in ${data.after.epoch} (${row.km2_before.toLocaleString('en-IN')} → ${row.km2_after.toLocaleString('en-IN')} km²)`;
  }
  const header = ['District', `Cropland ${data.before.epoch} (acres)`, `Cropland ${data.after.epoch} (acres)`, 'Change (acres)', `Cover ${data.before.epoch} (%)`, `Cover ${data.after.epoch} (%)`, 'Change (percentage points)'];
  const csv = [header, ['Telangana', acres(before.km2), acres(after.km2), acres(stateDelta), before.pct, after.pct, (after.pct - before.pct).toFixed(1)],
    ...rows.map((r) => [r.district, acres(r.km2_before), acres(r.km2_after), acres(r.km2_after - r.km2_before), r.pct_before, r.pct_after, r.change_pp])]
    .map((cells) => cells.map((c) => (typeof c === 'string' && /[",]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(',')).join('\r\n');
  $('crop-csv').href = URL.createObjectURL(new Blob(['﻿' + csv + '\r\n// Source: GLAD global cropland extent (Potapov et al. 2021), 3 km cells, mean cover per district x district area; schematic, not survey data.'], { type: 'text/csv;charset=utf-8' }));
}

// ---------- Kaleshwaram canal network: planned vs built vs mapped ----------
function renderCanalNetwork(summary) {
  const tbody = $('canal-network').tBodies[0];
  tbody.textContent = '';
  const row = (label, planned, done, note) => {
    const tr = document.createElement('tr');
    for (const [text, cls] of [[label, 'lbl'], [planned, 'num'], [done, 'num'], [note, 'note']]) {
      const td = document.createElement('td'); td.className = cls; td.textContent = text; tr.appendChild(td);
    }
    tbody.appendChild(tr);
  };
  const kmText = (v) => `${Math.round(v).toLocaleString('en-IN')} km`;
  for (const [label, planned] of summary.network.planned) row(label, kmText(planned), '—', 'planned');
  for (const [label, planned, done] of summary.network.cag) row(label, kmText(planned), kmText(done), `${Math.round(done / planned * 100)} % by ${summary.network.cag_asof}`);
  const osm = summary.osm_km;
  const after = (osm.after_canal || 0) + (osm.after_tunnel || 0) + (osm.after_main || 0);
  row('Mapped in OSM, post-2014', '—', kmText(after), `${kmText((osm.after_tunnel || 0) + (osm.after_main || 0))} of it tunnels and pipes`);
  const links = document.createElement('p'); links.className = 'hint';
  const a1 = document.createElement('a'); a1.href = summary.network.planned_source; a1.target = '_blank'; a1.rel = 'noopener'; a1.textContent = 'Irrigation Dept';
  const a2 = document.createElement('a'); a2.href = summary.network.cag_source; a2.target = '_blank'; a2.rel = 'noopener'; a2.textContent = 'CAG audit (2024)';
  links.append('Planned lengths: ', a1, ' · completed lengths: ', a2, ', an audited snapshot, not today\'s total; dug is not the same as lined and connected to fields.');
  $('canal-network').after(links);
}

// ---------- canal popup ----------
const canalPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup canal-popup', maxWidth: '300px' });
function openCanalPopup(p, lngLat) {
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  const era = p.era === 'after' ? 'dug after 2014' : p.era === 'before' ? 'pre-2014 project' : 'date unknown';
  const kindLabel = { tunnel: 'canal tunnel', main: 'pressurised tunnel / pipe', canal: 'canal' }[p.kind] || 'canal';
  head.append(textEl('span', 'kind canal', `${kindLabel} · ${era}`), textEl('strong', '', p.name || `Unnamed ${kindLabel}`));
  content.appendChild(head);
  const list = document.createElement('dl');
  for (const [term, value] of [['Scheme', p.scheme || null], ['Length', `${p.km} km (this OSM segment)`], ['Flow', p.directed ? 'dashes move downstream' : 'direction not recorded'],
                               ['Status', p.construction ? 'tagged under construction in OSM' : null]]) {
    if (value) list.append(textEl('dt', '', term), textEl('dd', '', value));
  }
  content.appendChild(list);
  const link = document.createElement('a');
  link.href = `https://www.openstreetmap.org/way/${p.id}`; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'OpenStreetMap ↗';
  content.appendChild(link);
  canalPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
map.on('click', 'canals-hit', (event) => { event.originalEvent.stopPropagation(); openCanalPopup(event.features[0].properties, event.lngLat); });
map.on('mouseenter', 'canals-hit', () => { map.getCanvas().style.cursor = 'pointer'; });
map.on('mouseleave', 'canals-hit', () => { map.getCanvas().style.cursor = ''; });

// ---------- tank popup and the Tanks card ----------
const tankPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup tank-popup', maxWidth: '300px' });
const indian = (value) => Number(value).toLocaleString('en-IN');
function openTankPopup(p, lngLat) {
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', 'kind tank', `${p.water || 'water body'} · OpenStreetMap`), textEl('strong', '', p.name || 'Unnamed tank'));
  const dl = document.createElement('dl');
  const row = (label, value) => dl.append(textEl('dt', '', label), textEl('dd', '', value));
  row('Water spread', `${indian(p.area_ha)} ha`);
  row('District', p.district);
  const district = tankSummary && tankSummary.districts.find((d) => d.district === p.district);
  const total = district ? kakatiyaTotal(district) : null;
  if (total) row('Mission Kakatiya', `${indian(total)} tanks taken up in ${district.mk_counted_in || p.district}, 2015–18`);
  content.append(head, dl, textEl('p', 'fine', 'OpenStreetMap records no construction or restoration date for tanks, and the restored tanks are not published with locations, so the Mission Kakatiya figure is the district total.'));
  const link = document.createElement('a');
  link.href = `https://www.openstreetmap.org/${p.osm_id[0] === 'w' ? 'way' : 'relation'}/${p.osm_id.slice(1)}`;
  link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Source: OpenStreetMap ↗';
  content.appendChild(link);
  tankPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
for (const id of ['tanks-fill', 'tanks-dots']) {
  map.on('click', id, (event) => { event.originalEvent.stopPropagation(); openTankPopup(event.features[0].properties, event.lngLat); });
  map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
}
function renderTanks(data) {
  const mk = data.mission_kakatiya;
  $('tank-count').textContent = `${indian(data.osm_tanks)} mapped`;
  const summary = $('tank-summary');
  summary.textContent = '';
  summary.append('OpenStreetMap has ', bold(indian(data.osm_tanks)), ` water bodies of at least ${data.osm_min_ha} ha inside Telangana (${indian(data.osm_named)} named), a water spread of `,
                 bold(`${indian(Math.round(data.osm_area_ha / 100))} km²`), '. Most are village tanks (cheruvu, kunta) built centuries ago; OSM records no construction or restoration date.');
  const ayacut = mk.phases.reduce((sum, p) => sum + (p.ayacut_lakh_acres || 0), 0);
  const line = $('mk-summary');
  line.textContent = '';
  line.append(`Launched ${mk.launched} to restore all `, bold(indian(mk.tanks_enumerated)), ' minor irrigation tanks in five years. By ', mk.asof, ', ',
              bold(indian(mk.taken_up)), ' had been taken up in four phases and ', bold(indian(mk.completed_by_report)), ' completed, stabilising ',
              bold(`${ayacut.toFixed(2)} lakh acres`), ` (Government of India report). Wikipedia puts the final count at ${indian(mk.wikipedia_completed)} tanks for ₹${indian(mk.wikipedia_crore)} crore.`);
  const phases = $('mk-phases').tBodies[0];
  phases.textContent = '';
  for (const p of mk.phases) {
    const tr = document.createElement('tr');
    tr.append(textEl('td', '', `${p.phase} (${p.years})`), textEl('td', '', indian(p.taken_up)),
              textEl('td', '', p.completed === null ? 'sanctioned' : indian(p.completed)), textEl('td', '', p.crore === null ? '—' : indian(p.crore)));
    phases.appendChild(tr);
  }
  const tbody = $('tank-table').tBodies[0];
  tbody.textContent = '';
  const rows = [...data.districts].sort((a, b) => (kakatiyaTotal(b) || 0) - (kakatiyaTotal(a) || 0) || a.district.localeCompare(b.district));
  for (const d of rows) {
    if (d.district === 'Hyderabad' && !d.osm_tanks) continue;
    const tr = document.createElement('tr');
    tr.append(textEl('td', '', d.district), textEl('td', '', indian(d.osm_tanks)));
    const restored = textEl('td', d.mk_total ? '' : 'na', d.mk_total ? indian(d.mk_total) : d.mk_counted_in ? `in ${d.mk_counted_in}` : '—');
    if (d.mk_phases) restored.title = `Phases I–IV: ${d.mk_phases.join(' · ')}`;
    tr.appendChild(restored);
    tr.addEventListener('click', () => {
      const centre = districtCentres.get(d.district);
      if (centre) flyToPoint(centre[0], centre[1], 9);
      for (const other of tbody.querySelectorAll('tr')) other.classList.toggle('active', other === tr);
    });
    tbody.appendChild(tr);
  }
  for (const d of data.districts) {
    const feature = districtFeatures.get(d.district);
    if (!feature) continue;
    const total = kakatiyaTotal(d);
    feature.properties.mk = d.mk_counted_in ? `in ${d.mk_counted_in}` : total ? `${indian(total)} tanks` : '';
  }
  if (map.getSource('district-points')) map.getSource('district-points').setData(labelData['district-points']);
}

// ---------- groundwater: well and district popups, legend, year curve and the Groundwater card ----------
const gwPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup gw-popup', maxWidth: '320px' });
const metres = (value) => `${Number(value).toFixed(1)} m`;
const signedMetres = (value) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)} m`;
const gwYears = (window) => `${window.years[0]}–${String(window.years[1]).slice(2)}`;
const changeWords = (value) => (value > 0 ? `rose ${metres(value)}` : value < 0 ? `fell ${metres(-value)}` : 'unchanged');
function svgEl(tag, attributes) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}
/** Depth-to-water curve with the ground at the top, so a falling line is a falling water table. Breaks at missing years. */
function depthChart(points, width, height, axes) {
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'gw-svg', role: 'img' });
  const pad = axes ? { l: 30, r: 18, t: 6, b: 16 } : { l: 3, r: 3, t: 3, b: 3 };
  const years = points.map((p) => p[0]);
  const [y0, y1] = [Math.min(...years), Math.max(...years)];
  const deepest = Math.max(...points.map((p) => p[1]), 1) * 1.08;
  const x = (year) => pad.l + ((year - y0) / Math.max(1, y1 - y0)) * (width - pad.l - pad.r);
  const y = (depth) => pad.t + (depth / deepest) * (height - pad.t - pad.b);
  if (axes) {
    for (const depth of [0, deepest / 2, deepest]) {
      svg.append(svgEl('line', { x1: pad.l, x2: width - pad.r, y1: y(depth), y2: y(depth), class: 'grid' }));
      const label = svgEl('text', { x: pad.l - 4, y: y(depth) + 3, 'text-anchor': 'end' });
      label.textContent = `${Math.round(depth)} m`;
      svg.append(label);
    }
    for (const year of [y0, 2014, y1]) {
      const label = svgEl('text', { x: x(year), y: height - 4, 'text-anchor': 'middle' });
      label.textContent = String(year);
      svg.append(label);
    }
  }
  if (y0 <= 2014 && y1 > 2014) svg.append(svgEl('line', { x1: x(2014.5), x2: x(2014.5), y1: pad.t, y2: height - pad.b, class: 'era' }));
  let d = '';
  let previous = null;
  for (const [year, depth] of points) {
    d += `${previous !== null && year - previous <= 1 ? 'L' : 'M'}${x(year).toFixed(1)} ${y(depth).toFixed(1)} `;
    previous = year;
  }
  svg.append(svgEl('path', { d: d.trim(), class: 'depth' }));
  for (const [year, depth] of points) svg.append(svgEl('circle', { cx: x(year).toFixed(1), cy: y(depth).toFixed(1), r: axes ? 2.2 : 1.6, class: 'dot' }));
  return svg;
}
function gwSourceLink() {
  const link = document.createElement('a');
  link.href = gwData.source.url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Source: India-WRIS via India Data Portal ↗';
  return link;
}
function openGwPopup(p, lngLat) {
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', 'kind gw', `${p.well || 'monitoring well'} · ${p.agency}`), textEl('strong', '', p.name));
  const dl = document.createElement('dl');
  const row = (label, value) => dl.append(textEl('dt', '', label), textEl('dd', '', value));
  if (p.before !== undefined) row(`May ${gwYears(gwData.before)}`, `${metres(p.before)} below ground · ${p.n_before} seasons`);
  if (p.after !== undefined) row(`May ${gwYears(gwData.after)}`, `${metres(p.after)} below ground · ${p.n_after} seasons`);
  if (p.change !== undefined) row('Change', `water table ${changeWords(p.change)}`);
  if (p.latest !== undefined) row(`Latest · May ${p.latest_year}`, metres(p.latest));
  if (p.well_depth) row('Well depth', metres(p.well_depth));
  row('District', p.district);
  content.append(head, dl);
  const series = typeof p.series === 'string' ? JSON.parse(p.series) : p.series;   // MapLibre hands nested properties over as JSON text
  if (series && series.length > 1) {
    content.append(depthChart(series, 272, 64, false),
                   textEl('p', 'fine', `Depth to water each May, ${series[0][0]}–${series[series.length - 1][0]}; the dashed line is 2014. Ground is at the top, so a falling line is a falling water table.`));
  }
  content.appendChild(gwSourceLink());
  gwPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
function openGwDistrictPopup(d, lngLat) {
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', 'kind gw', 'district · India-WRIS wells'), textEl('strong', '', d.district));
  const dl = document.createElement('dl');
  const row = (label, value) => dl.append(textEl('dt', '', label), textEl('dd', '', value));
  row('Wells', `${indian(d.wells)} with May readings, ${indian(d.wells_both)} measured in both windows`);
  row(`May ${gwYears(gwData.before)}`, `${metres(d.before)} below ground, mean of those wells`);
  row(`May ${gwYears(gwData.after)}`, `${metres(d.after)} below ground`);
  row('Median change', `water table ${changeWords(d.change)} · rose in ${d.rising} of ${d.wells_both} wells`);
  content.append(head, dl, textEl('p', 'fine', 'Click a well for its own readings.'), gwSourceLink());
  gwPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
map.on('click', 'gw-wells', (event) => { event.originalEvent.stopPropagation(); openGwPopup(event.features[0].properties, event.lngLat); });
map.on('mouseenter', 'gw-wells', () => { map.getCanvas().style.cursor = 'pointer'; });
map.on('mouseleave', 'gw-wells', () => { map.getCanvas().style.cursor = ''; });
map.on('click', 'gw-districts', (event) => {
  const above = ['gw-wells', 'tanks-fill', 'tanks-dots'].filter((id) => map.getLayer(id));
  if (map.queryRenderedFeatures(event.point, { layers: above }).length) return;           // the well or tank popup takes the click
  const d = gwData && gwData.districts.find((row) => row.district === event.features[0].properties.shapeName);
  if (!d || d.change === null) return;
  event.originalEvent.stopPropagation();
  openGwDistrictPopup(d, event.lngLat);
});
function renderGwLegend() {
  const legend = $('gw-legend');
  legend.textContent = '';
  if (!gwData) return;
  const field = gwField();
  const ramp = gwRamp(MAP_THEMES[currentTheme()], field);
  const [low, high] = [ramp[0][0], ramp[ramp.length - 1][0]];
  const bar = textEl('div', 'bar', '');
  bar.style.background = `linear-gradient(90deg, ${ramp.map(([v, c]) => `${c} ${Math.round(((v - low) / (high - low)) * 100)}%`).join(', ')})`;
  const ticks = textEl('div', 'ticks', '');
  const labels = field === 'change' ? [`fell ${Math.abs(low)} m or more`, 'no change', `rose ${high} m or more`] : ['at the surface', `${(low + high) / 2} m`, `${high} m or deeper`];
  for (const text of labels) ticks.appendChild(textEl('span', '', text));
  const title = gwMode === 'off' ? 'Layer off: choose Before 2014, After 2014 or Change under Layers.'
    : field === 'change' ? `Change in depth to water, May ${gwYears(gwData.before)} to May ${gwYears(gwData.after)}; blue wells and districts gained water.`
      : `Depth to water in May ${gwYears(gwData[field])}, metres below ground; blue is shallow.`;
  legend.append(textEl('p', 'hint', title), bar, ticks);
}
function renderGroundwater(data) {
  gwData = data;
  const s = data.state;
  $('gw-count').textContent = `${indian(s.wells)} wells`;
  $('gw-before-years').textContent = `m, ${gwYears(data.before)}`;
  $('gw-after-years').textContent = `m, ${gwYears(data.after)}`;
  const summary = $('gw-summary');
  summary.textContent = '';
  summary.append('India-WRIS publishes May readings from ', bold(indian(s.wells)), ` monitoring wells inside Telangana (${indian(s.cgwb)} CGWB, ${indian(s.wells - s.cgwb)} state department). In the `,
                 bold(indian(s.wells_both)), ` wells measured in both windows the water table stood `, bold(metres(s.before)), ` below ground in May ${gwYears(data.before)} and `,
                 bold(metres(s.after)), ` in May ${gwYears(data.after)}: a median change of `, bold(signedMetres(s.change)), ` (it rose in ${Math.round((100 * s.rising) / s.wells_both)} % of wells).`);
  const chart = $('gw-chart');
  chart.textContent = '';
  chart.appendChild(depthChart(data.chart.map((c) => [c.year, c.depth]), 320, 120, true));
  const last = data.chart[data.chart.length - 1];
  $('gw-chart-hint').textContent = `Mean of ${indian(data.chart_wells)} wells with at least ${data.chart_min_seasons} May readings, each measured against its own long-run mean so the growing network does not fake a trend. No statewide May survey in 2020–21; ${last.wells} wells reported in ${last.year}.`;
  const tbody = $('gw-table').tBodies[0];
  tbody.textContent = '';
  const rows = data.districts.filter((d) => d.change !== null).sort((a, b) => b.change - a.change || a.district.localeCompare(b.district));
  for (const d of [...rows, { ...s, district: 'Telangana', total: true }]) {
    const tr = document.createElement('tr');
    if (d.total) tr.className = 'total';
    tr.append(textEl('td', '', d.district), textEl('td', '', indian(d.wells_both)), textEl('td', '', d.before.toFixed(1)), textEl('td', '', d.after.toFixed(1)),
              textEl('td', d.change > 0 ? 'up' : d.change < 0 ? 'down' : '', signedMetres(d.change)));
    tr.title = `${d.district}: ${d.wells_both} wells with May readings in both windows; the water table rose in ${d.rising} of them`;
    if (!d.total) {
      tr.addEventListener('click', () => {
        if (gwMode === 'off') setGwMode('change');
        const centre = districtCentres.get(d.district);
        if (centre) map.flyTo({ center: centre, zoom: 9, duration: 1200 });
        for (const other of tbody.rows) other.classList.toggle('active', other === tr);
      });
    }
    tbody.appendChild(tr);
  }
  renderGwLegend();
}

// ---------- proposal: popups, map labels and the Proposal card ----------
const proposalPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup prop-popup', maxWidth: '330px' });
const crore = (value) => `₹${indian(Math.round(value))} crore`;
const proposalWork = (id) => proposalData && proposalData.works.find((w) => w.id === id);
const PROP_KIND_LABEL = { pool: 'proposed reservoir', delivery: 'proposed lift delivery', tunnel: 'proposed tunnel', canal: 'proposed canal', cut: 'proposed deep cut', aqueduct: 'proposed aqueduct or siphon', 'pressure main': 'proposed pressure main' };
const TUNNEL_ABOVE_M = 30;
function openTrunkPopup(p, lngLat) {
  const system = proposalData.systems.find((s) => s.name === p.system);
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', 'kind trunk', `${p.existing ? 'existing' : 'proposed'} trunk stage ${p.stage} · ${p.conveyance}`), textEl('strong', '', `${p.from} → ${p.to}`));
  const dl = document.createElement('dl');
  const row = (label, value) => dl.append(textEl('dt', '', label), textEl('dd', '', value));
  row('System', p.system);
  row('Pool level', `${p.to_level_m} m above sea${p.lift_m ? `, lifted ${p.lift_m} m in this stage` : ', by gravity'}`);
  row('Carries', `${p.tmc_per_year} TMC a year gross for the system, ${indian(p.design_cms)} m³/s over ${system ? system.pump_days : ''} pumping days`);
  if (p.lift_m) row('Pumps', `${indian(p.mw)} MW${p.existing ? ' of augmentation at the existing stage (not priced: depends on its spare capacity)' : ' new'}`);
  row('Length', `${p.km} km of ${p.conveyance}`);
  if (system) row('Districts', system.districts.join(', '));
  content.append(head, dl, textEl('p', 'fine', `${system ? system.notes + ' ' : ''}Levels are approximate full-reservoir levels from the engineering review, to be checked against the project report.`));
  proposalPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
function openProposalPopup(p, lngLat) {
  if (p.kind === 'trunk') return openTrunkPopup(p, lngLat);
  const work = proposalWork(p.id);
  if (!work) return;
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', 'kind prop', p.kind === 'pump' ? `pump house · stage ${p.stage} of ${work.stages}` : PROP_KIND_LABEL[p.kind]),
              textEl('strong', '', p.kind === 'pump' ? p.name : work.name));
  const dl = document.createElement('dl');
  const row = (label, value) => dl.append(textEl('dt', '', label), textEl('dd', '', value));
  if (p.kind === 'canal' || p.kind === 'tunnel') {
    row('Length', `${p.km} km of ${p.kind}, part of the ${work.route_km} km route from ${work.source}`);
    row('Carries', `${p.through_tmc} TMC a year to ${work.name}`);
    if (p.kind === 'tunnel') row('Why a tunnel', `the ground here stands more than ${TUNNEL_ABOVE_M} m above the water level of ${work.frl_m} m`);
  } else if (p.kind === 'pump') {
    row('Lift', `${p.lift_m} m in this stage`);
    row('Pumps', `${p.mw} MW for ${work.design_cms} m³/s over a ${proposalData.norms.costs.pump_days}-day season`);
    row('Carries', `${work.annual_tmc} TMC a year from ${work.source} to ${work.name}`);
  } else {
    row('Serves', `${work.serves} district · ${work.annual_tmc} TMC a year`);
    if (work.kind === 'reservoir') {
      row('Storage', `${work.storage_tmc} TMC behind a ${work.crest_m} m high, ${work.dam_km} km long dam`);
      row('Submerges', `${work.area_km2} km², of which ${work.cropland_km2} km² farmland`);
      row('Full level', `${work.frl_m} m above sea (river bed ${work.bed_m} m)`);
    } else {
      row('Delivery level', `${work.frl_m} m above sea; land below it is commanded by gravity, balancing tanks priced in`);
    }
    row('Fed from', `${work.source} (${work.feed_kind}${work.feed_scheme ? `, already filled by ${work.feed_scheme}` : ''}${work.intake && work.intake !== work.source ? `; water taken from the ${work.basin} at ${work.intake}` : ''})`);
    if (work.chain && work.chain.length) row('Stages', `${[...work.chain].reverse().join(' → ')} → ${work.name}: lifted in ${work.chain.length + 1} hops like Kaleshwaram's`);
    if (work.through_tmc > work.annual_tmc) row('Passes on', `${(work.through_tmc - work.annual_tmc).toFixed(1)} TMC a year to higher works fed from this reservoir; pumps and route are sized for ${work.through_tmc} TMC`);
    row('Lift', `${work.lift_m} m new${work.base_lift_m ? ` + ${work.base_lift_m} m already made by the scheme that fills ${work.source}` : ''}`);
    row('Route', `${work.route_km} km inside the state: ${work.canal_km} km canal${work.cut_km ? `, ${work.cut_km} km deep cut` : ''}${work.tunnel_km ? `, ${work.tunnel_km} km tunnel` : ''}${work.main_km ? `, ${work.main_km} km pressure main` : ''}${work.aqueduct_km ? `, ${work.aqueduct_km} km aqueduct or siphon` : ''}; ${work.stages ? `${work.stages} pump stage${work.stages === 1 ? '' : 's'}, ${indian(work.mw)} MW installed` : 'gravity, no pumping'}${work.augment_mw ? `; ${indian(work.augment_mw)} MW more at the existing scheme's pumps (not priced)` : ''}`);
    row('Season', `${work.design_cms} m³/s over ${work.pump_days} pumping days, ${work.gross_tmc} TMC gross with 12 % losses`);
    if (work.high_lift) row('Warning', `lifted ${work.total_lift_m} m in all: power alone is about ₹${indian(Math.round(work.energy_cr_per_year * 1e7 / (work.annual_tmc * 10000)))} an acre a year`);
    row('Cost', `${crore(work.capex_cr)}: works ${crore(work.cost_cr)}, conveyance ${crore(work.capex_conveyance_cr)}, distribution ${crore(work.capex_distribution_cr)}; power ${crore(work.energy_cr_per_year)} a year, of which ${crore(work.energy_new_cr_per_year)} for the new lift`);
    if (work.over_cap) row('Water', 'No intake had this much to spare under the surplus rule; the cheapest route is shown anyway.');
  }
  content.append(head, dl, textEl('p', 'fine', 'Computed from the 200 m terrain model under planning norms; routes are straight lines, not alignments. Method and norms in the Proposal card.'));
  proposalPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
for (const id of ['prop-pool', 'prop-canal', 'prop-tunnel', 'prop-delivery', 'prop-pump', 'prop-trunk-new', 'prop-trunk-existing']) {
  map.on('click', id, (event) => { event.originalEvent.stopPropagation(); openProposalPopup(event.features[0].properties, event.lngLat); });
  map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
}
/** A proposed work on the map: icon, name, figure (TMC, MW, km) and a "new" tag; clicking opens its popup. */
const PROP_ICON_COLOUR = { reservoir: 'propPool', delivery: 'prop', canal: 'prop', tunnel: 'prop', pump: 'propPump', main: 'propPump', trunk: 'propTrunk' };
function propMarker(kind, symbol, lngLat, title, detail, onClick) {
  if (!labelData['prop-labels']) labelData['prop-labels'] = collection([]);
  const i = labelActions['prop-labels'].push(onClick) - 1;
  labelData['prop-labels'].features.push(pointFeature(lngLat[0], lngLat[1], { i, kind, title, detail: ` ${detail}`, icon: `ic|${symbol}|${PROP_ICON_COLOUR[kind]}|n`, sort: kind === 'reservoir' ? 1 : 3 }));
}
/** Midpoint of a lon/lat polyline, for the canal and tunnel labels. */
function lineMidpoint(coords) {
  const lengths = [0];
  for (let i = 1; i < coords.length; i++) {
    const dx = (coords[i][0] - coords[i - 1][0]) * Math.cos((coords[i][1] * Math.PI) / 180);
    lengths.push(lengths[i - 1] + Math.hypot(dx, coords[i][1] - coords[i - 1][1]));
  }
  const half = lengths[lengths.length - 1] / 2;
  const i = lengths.findIndex((l) => l >= half);
  if (i <= 0) return coords[0];
  const f = (half - lengths[i - 1]) / (lengths[i] - lengths[i - 1] || 1);
  return [coords[i - 1][0] + f * (coords[i][0] - coords[i - 1][0]), coords[i - 1][1] + f * (coords[i][1] - coords[i - 1][1])];
}
const PROP_LABEL_MIN_KM = 4;
function addProposalMarkers(data, geo) {
  for (const w of data.works) {
    const open = () => openProposalPopup({ kind: w.kind === 'reservoir' ? 'pool' : 'delivery', id: w.id }, [w.lon, w.lat]);
    if (w.kind === 'reservoir') propMarker('reservoir', 'dam', [w.lon, w.lat], w.name, `${w.storage_tmc} TMC`, open);
    else propMarker('delivery', 'tank', [w.lon, w.lat], `${w.serves} delivery`, `${w.annual_tmc} TMC/yr`, open);
    for (const p of w.pumps) {
      propMarker('pump', 'pump', [p.lon, p.lat], `P${p.stage}`, `${p.mw} MW · lift ${p.lift_m} m`,
                 () => openProposalPopup({ kind: 'pump', id: w.id, stage: p.stage, name: `${w.name} · stage ${p.stage}`, lift_m: p.lift_m, mw: p.mw }, [p.lon, p.lat]));
    }
  }
  for (const f of geo.features) {
    if (!['canal', 'tunnel', 'pressure main'].includes(f.properties.kind) || f.properties.km < PROP_LABEL_MIN_KM) continue;
    const mid = lineMidpoint(f.geometry.coordinates);
    propMarker(f.properties.kind === 'pressure main' ? 'main' : f.properties.kind, f.properties.kind === 'pressure main' ? 'pump' : f.properties.kind, mid,
               `${f.properties.km} km ${f.properties.kind}`, `${f.properties.through_tmc} TMC/yr`, () => openProposalPopup(f.properties, mid));
  }
  for (const s of data.systems) {
    for (const st of s.stages) {
      if (st.existing || st.placed_by === 'map') continue;          // existing structures already carry their own markers
      const tail = st.to.includes('canal tail');
      const open = () => openTrunkPopup({ ...st, kind: 'trunk', system: s.name, stage: s.stages.indexOf(st) + 1, tmc_per_year: s.tmc_per_year, design_cms: s.design_cms }, [st.lon, st.lat]);
      propMarker('trunk', tail ? 'canal' : 'dam', [st.lon, st.lat], st.to.replace(' (new)', ''), `${st.to_level_m} m · ${s.tmc_per_year} TMC/yr`, open);
    }
  }
}
function renderProposal(data) {
  proposalData = data;
  const s = data.demand.state;
  const t = data.totals;
  const n = data.norms;
  $('prop-count').textContent = `${t.reservoirs + t.deliveries} works · ${indian(t.annual_tmc)} TMC`;
  const summary = $('prop-summary');
  summary.textContent = '';
  summary.append(`Land cover says ${s.cultivable_pct} % of Telangana is cultivable (the rest is forest, towns, water and steep ground) and `, bold(`${s.cropland_pct} %`),
                 ` is cropped already, ${s.cropland_of_cultivable_pct} % of the cultivable land, so 80 % is met today. Taking it to ${Math.round(100 * n.target_share)} % adds `,
                 bold(`${s.new_lakh_acres} lakh acres`), ` and, with assured water for the ${Math.round(100 * n.rainfed_share)} % of fields that live on rain, needs `,
                 bold(`${indian(Math.round(s.tmc))} TMC`), ` a year. The sketch meets ${t.demand_met_pct} % of that with `, bold(`${t.reservoirs} new reservoirs`),
                 ` (${t.storage_tmc} TMC of storage) and `, bold(`${t.deliveries} lift deliveries`), ` to districts without a usable dam site: ${t.pump_houses} pump houses (${indian(t.mw)} MW), `,
                 `${indian(t.tunnel_km)} km of tunnel and ${indian(t.canal_km)} km of canal, about `, bold(crore(t.capex_cr)), ` to build and ${crore(t.energy_cr_per_year)} of power a year. `,
                 `${t.feeds['river intake']} works draw straight from a river intake, ${t.feeds['existing reservoir']} from reservoirs that existing schemes already fill, ${t.feeds['new trunk stage']} from new trunk stages, ${t.feeds['existing canal']} by tapping existing canals and ${t.feeds['proposed reservoir']} cascade through reservoirs proposed here. `,
                 `Behind them, ${t.systems} multi-stage trunk systems carry ${indian(Math.round(t.systems_tmc))} TMC a year gross up the plateau: `, bold(crore(t.systems_capex_new_cr)), ` of new stages (${indian(t.systems_new_mw)} MW), ${indian(t.systems_augment_mw)} MW of enlargement at existing stages, and `, bold(crore(t.systems_energy_cr_per_year)), ` of power a year.`);
  const envelopes = $('prop-envelopes').tBodies[0];
  envelopes.textContent = '';
  for (const e of data.envelopes) {
    const tr = document.createElement('tr');
    tr.append(textEl('td', '', e.river), textEl('td', '', indian(Math.round(e.award))), textEl('td', '', indian(Math.round(e.committed))), textEl('td', '', indian(Math.round(e.free_within_award))),
              textEl('td', '', indian(Math.round(e.free_if_requested))), textEl('td', e.beyond_request > 0 ? 'down' : 'up', indian(Math.round(e.proposal_draws))));
    envelopes.appendChild(tr);
  }
  const godavari = data.envelopes.find((e) => e.river === 'Godavari');
  const krishna = data.envelopes.find((e) => e.river === 'Krishna');
  $('prop-envelope-note').textContent = `Shares: Godavari 967.94 TMC (758.76 cleared by the CWC, 148.82 cleared for availability, 60.26 reserve, per the Chief Minister's letter of September 2021); Krishna 299 TMC interim, fully committed. In June 2025 the state asked the Centre for 1,000 + 500. `
    + (godavari.beyond_request > 0 ? `The Godavari draw here exceeds even the 1,000 TMC asked for by ${indian(Math.round(godavari.beyond_request))} TMC: the water exists (HydroRIVERS puts the mean flow leaving the state at about ${indian(godavari.mean_flow_tmc)} TMC a year) but needs a new inter-state award and monsoon capture. ` : '')
    + (krishna.beyond_request > 0 ? `The Krishna draw exceeds the 500 TMC asked for by ${indian(Math.round(krishna.beyond_request))} TMC.` : `The Krishna draw fits the 500 TMC asked for but not today's 299 TMC share.`);
  const works = $('prop-works').tBodies[0];
  works.textContent = '';
  $('prop-works-count').textContent = `${t.reservoirs} reservoirs · ${t.deliveries} deliveries`;
  for (const w of [...data.works].sort((a, b) => b.annual_tmc - a.annual_tmc)) {
    const tr = document.createElement('tr');
    tr.className = w.kind;
    tr.append(textEl('td', '', w.name.replace(' lift delivery', ' (lift)')), textEl('td', '', w.annual_tmc.toFixed(1)), textEl('td', '', indian(w.lift_m)),
              textEl('td', 'feed', ({ 'river intake': 'river', 'existing reservoir': 'reservoir', 'existing canal': 'canal', 'proposed reservoir': 'proposed' })[w.feed_kind] || w.feed_kind), textEl('td', '', w.tunnel_km.toFixed(0)), textEl('td', '', indian(w.capex_cr)));
    tr.title = `${w.name}: serves ${w.serves}, fed from ${w.source} (${w.feed_kind}), ${w.route_km} km route${w.kind === 'reservoir' ? `, ${w.storage_tmc} TMC storage` : ''}, ${w.stages} pump stage(s), ${indian(w.mw)} MW${w.chain && w.chain.length ? `, via ${w.chain.join(' and ')}` : ''}`;
    tr.addEventListener('click', () => {
      if (proposalMode === 'off') setProposalMode('on');
      map.flyTo({ center: [w.lon, w.lat], zoom: 9, duration: 1200 });
      map.once('moveend', () => openProposalPopup({ kind: w.kind === 'reservoir' ? 'pool' : 'delivery', id: w.id }, [w.lon, w.lat]));
      for (const other of works.rows) other.classList.toggle('active', other === tr);
    });
    works.appendChild(tr);
  }
  const districts = $('prop-districts').tBodies[0];
  districts.textContent = '';
  const coverage = new Map(data.coverage.map((c) => [c.district, c]));
  const rows = [...data.demand.districts].sort((a, b) => b.tmc - a.tmc);
  for (const d of rows) {
    const c = coverage.get(d.district) || {};
    const served = (c.gravity_existing_pct || 0) + (c.gravity_new_pct || 0);
    const tr = document.createElement('tr');
    tr.append(textEl('td', '', d.district), textEl('td', '', d.cropland_of_cultivable_pct === null ? '—' : d.cropland_of_cultivable_pct.toFixed(0)),
              textEl('td', '', d.new_lakh_acres.toFixed(2)), textEl('td', '', d.tmc.toFixed(1)), textEl('td', served >= 60 ? 'up' : '', served.toFixed(0)));
    tr.title = `${d.district}: ${d.cultivable_pct} % of the district cultivable, ${d.cropland_pct} % cropped; gravity from existing reservoirs ${c.gravity_existing_pct} %, from proposed ${c.gravity_new_pct} %, the rest needs pressurised or lift distribution; works: ${(c.works || []).join(', ') || 'none'}`;
    tr.addEventListener('click', () => {
      const centre = districtCentres.get(d.district);
      if (proposalMode === 'off') setProposalMode('on');
      if (centre) map.flyTo({ center: centre, zoom: 9, duration: 1200 });
    });
    districts.appendChild(tr);
  }
  const total = document.createElement('tr');
  total.className = 'total';
  total.append(textEl('td', '', 'Telangana'), textEl('td', '', s.cropland_of_cultivable_pct.toFixed(0)), textEl('td', '', s.new_lakh_acres.toFixed(1)), textEl('td', '', indian(Math.round(s.tmc))),
               textEl('td', '', (t.gravity_existing_pct + t.gravity_new_pct).toFixed(0)));
  districts.appendChild(total);
  const systemsBox = $('prop-systems');
  systemsBox.textContent = '';
  $('prop-systems-count').textContent = `${data.systems.length} systems · ${indian(Math.round(t.systems_tmc))} TMC`;
  for (const s of data.systems) {
    const details = document.createElement('details');
    details.className = 'table prop-system';
    const summary = document.createElement('summary');
    summary.append(textEl('b', '', s.name), textEl('span', 'e', `${s.tmc_per_year} TMC · ${indian(s.design_cms)} m³/s · ${s.new_stages} new + ${s.existing_stages} existing stages · summit ${s.summit_lift_m} m · ${crore(s.capex_new_cr)}`));
    const list = document.createElement('ol');
    for (const st of s.stages) {
      const li = textEl('li', st.existing ? 'existing' : 'new', '');
      li.append(textEl('span', 'nm', `${st.from} → ${st.to.replace(' (new)', '')}`),
                textEl('span', 'e', `${st.to_level_m} m${st.lift_m ? ` · lift ${st.lift_m} m` : ' · gravity'} · ${st.conveyance} ${st.km} km${st.lift_m ? ` · ${indian(st.mw)} MW` : ''}`),
                textEl('span', 'st', st.existing ? 'existing' : 'new'));
      li.addEventListener('click', (event) => { event.stopPropagation(); if (proposalMode === 'off') setProposalMode('on'); map.flyTo({ center: [st.lon, st.lat], zoom: 9.5, duration: 1200 }); });
      list.appendChild(li);
    }
    const note = textEl('p', 'hint', `${s.districts.join(', ')}. ${s.notes} Power at the summit ${crore(s.power_cr_per_tmc_at_summit)} per TMC.`);
    details.append(summary, list, note);
    summary.addEventListener('click', () => { if (!details.open && proposalMode === 'off') setProposalMode('on'); });
    systemsBox.appendChild(details);
  }
  const caveats = $('prop-caveats');
  caveats.textContent = '';
  for (const text of data.caveats || []) caveats.appendChild(textEl('li', '', text));
  const norms = $('prop-norms');
  norms.textContent = '';
  const c = n.costs;
  const items = [
    `Target: cropland at ${Math.round(100 * n.target_share)} % of cultivable land in every district (ESA WorldCover 2021 crop, grass, shrub and bare classes on slopes up to ${n.max_slope_pct} %; forest, built-up, water and steep ground left out). At 80 % the state is already there; 90 % would need ${indian(s.tmc_at_90)} TMC.`,
    `Water: ${indian(n.duty_new_acres_per_tmc)} acres a TMC for newly irrigated land (allows about 5 % paddy), ${indian(n.duty_stabilise_acres_per_tmc)} acres a TMC to assure the ${Math.round(100 * n.rainfed_share)} % of existing cropland taken as rainfed and not yet promised to a scheme (a placeholder: the official 42 % rainfed share includes ayacut of Kaleshwaram, Palamuru, Sitarama and Devadula); ${Math.round(100 * n.losses)} % added at the intake for evaporation and seepage; storage ${n.storage_per_annual} × the annual draw.`,
    `Reservoir sites: every HydroRIVERS reach of order 4 or more inside the state, a dam every 5 km, heights of ${n.crest_options_m.join(', ')} m, pools flooded on the 200 m DEM behind a dam line scanned across the valley; rejected when the dam would exceed 16 km, the pool leaks past 30 km or across the state border, drowns a town or built-up land, or takes more than ${n.max_cropland_km2_per_tmc} km² of farmland per TMC. Cheapest storage per district wins, at least 15 km apart.`,
    `Sources: river intakes may newly give ${Math.round(100 * n.river_surplus_share)} % of the dependable monsoon flow (taken as ${Math.round(100 * n.dependable_monsoon_of_mean)} % of HydroRIVERS' mean annual flow); existing canals up to ${Math.round(100 * n.tap_share)} % of their design discharge; the Krishna total is capped at the 2025 request. Source levels are operating levels from the review, not ground heights. Pumping seasons: Godavari upper reaches 100 days, Sammakka Sagar 110, Sitamma Sagar 120, Krishna 60; ${n.pump_hours} h a day, ${Math.round(100 * (n.standby - 1))} % standby, ${Math.round(100 * n.pump_efficiency)} % wire-to-water efficiency.`,
    `Routes: shortest path inside the state on a ${n.route_cell_m / 1000} km grid. Gravity when the source level clears the work level plus ${n.canal_fall_m_per_km} m/km of canal fall and ${n.stage_loss_m} m; otherwise pump stages of ${n.stage_min_m}–${n.stage_max_m} m, each pump house at the toe of the next rise with a pressure main up the rising leg; along the hydraulic grade line, ground more than ${n.tunnel_cover_m} m above the water for 1 km or more is tunnelled, ${n.cut_cover_m}–${n.tunnel_cover_m} m is deep cut, ground ${n.aqueduct_depth_m} m below needs an aqueduct or siphon; canals at ${n.canal_sinuosity} × the routed length. Gravity command = cultivable land within ${n.command_km} km and below the pool level by ${n.command_head_m} m plus ${n.command_fall_m_per_km} m per km.`,
    `Costs (₹ crore, indicative, from the review): ${c.storage_per_tmc_cr} per TMC of storage + ${c.embankment_km_h2_cr} × km × height² for the bund + land at ${c.farmland_per_ha_cr}/ha farmland, ${c.forest_per_ha_cr}/ha forest, ${c.other_land_per_ha_cr}/ha other; pumps ${c.pump_per_mw_cr} per MW installed; tunnel ${c.tunnel_per_km_cr} per km, canal ${c.canal_per_km_cr} per km, pressure main ${c.pressure_main_per_km_cr} per km (Q in m³/s), deep cut ${c.cut_factor} × and aqueduct ${c.aqueduct_factor} × the canal rate; distribution ${c.distribution_per_tmc_cr} per TMC a year; power ₹${c.power_rs_per_kwh} a unit over a present-value factor of ${c.energy_years}. Enlarging the pumps of existing schemes that water passes through is listed in MW but not priced. Benchmarks: ${Object.entries(n.cost_benchmarks).map(([k, v]) => `${k} (${v[0]})`).join('; ')}.`,
    `Trunk systems: the six systems, their stage levels, lifts and conveyance come from the engineering review; existing stages are reused and their pumps enlarged, new stages are priced with the rates above. Last-mile works are priced separately and draw from the nearest stage pool, so trunk and works costs add, while the trunk power already covers lifting the works' water to that pool.`,
    'Not modelled: river regulation between states and environmental flows, real alignments and land along them, villages inside pools, head-reservoir yields behind tapped canals, groundwater and tanks as conjunctive sources, crop choice and phasing.',
  ];
  for (const text of items) norms.appendChild(textEl('li', '', text));
}

// ---------- link popup ----------
const linkPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, offset: 10, className: 'dam-popup link-popup', maxWidth: '340px' });
linkPopup.on('close', () => map.setFilter('links-highlight', ['==', ['get', 'link'], '']));
const linkKey = (p) => `${p.scheme} · ${p.link}`;

function linkYears(p) {
  const parts = [];
  if (p.planned) parts.push(`planned ${p.planned}`);
  if (p.began) parts.push(`construction ${p.began}`);
  if (p.water) parts.push(`first water ${p.water}`);
  if (p.done) parts.push(`complete ${p.done}`);
  if (p.target && !p.done) parts.push(`target ${p.target}`);
  return parts.length ? parts.join(' · ') : null;
}
function linkElevation(p) {
  if (p.elev_from === null || p.elev_to === null) return null;
  const change = p.lift_m > 0 ? `rise +${p.lift_m} m (lifted)` : p.lift_m < 0 ? `fall ${Math.abs(p.lift_m)} m (gravity)` : 'level';
  return `${p.elev_from} m → ${p.elev_to} m · ${change}`;
}
function openLinkPopup(p, lngLat) {
  damPopup.remove();
  map.setFilter('links-highlight', ['==', ['get', 'link'], p.link]);
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  head.append(textEl('span', `kind link ${p.status === 'operational' ? '' : 'planned'}`, `${p.scheme} · ${p.kind}`), textEl('strong', '', `${p.link}: ${p.from} → ${p.to}`));
  content.appendChild(head);
  const rows = [
    ['Status', STATUS_LABEL[p.status] || p.status],
    ['Via', p.via || null],
    ['Years', linkYears(p)],
    ['Terrain', linkElevation(p)],
    ['Distance', `${p.straight_km} km straight line`],
    ['Note', p.note],
  ];
  const list = document.createElement('dl');
  for (const [term, value] of rows) {
    if (!value) continue;
    list.append(textEl('dt', '', term), textEl('dd', term === 'Note' ? 'prose' : '', value));
  }
  content.appendChild(list);
  content.appendChild(textEl('p', 'fine', 'Terrain heights are the DEM at each structure, not water levels; the line is schematic, not the canal route.'));
  const link = document.createElement('a');
  link.href = p.source; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Source ↗';
  content.appendChild(link);
  linkPopup.setLngLat(lngLat).setDOMContent(content).addTo(map);
}
map.on('click', 'links-hit', (event) => { event.originalEvent.stopPropagation(); openLinkPopup(event.features[0].properties, event.lngLat); });
map.on('mouseenter', 'links-hit', () => { map.getCanvas().style.cursor = 'pointer'; });
map.on('mouseleave', 'links-hit', () => { map.getCanvas().style.cursor = ''; });

function buildWorkInProgressLabels(links) {
  const seen = new Set();
  labelData.wip = collection([]);
  for (const feature of links.features) {
    const p = feature.properties;
    if (p.status === 'operational' || seen.has(linkKey(p))) continue;
    seen.add(linkKey(p));
    const coords = feature.geometry.coordinates, mid = coords[Math.floor(coords.length / 2)];
    labelData.wip.features.push(pointFeature(mid[0], mid[1], { name: `${p.link} · ${STATUS_LABEL[p.status] || p.status}`, status: p.status, title: `${p.link}: ${p.from} → ${p.to} · ${p.note}` }));
  }
}

/** Link features grouped into chains: "scheme · link" -> { scheme, link, chain, features, status, props }. */
function groupLinks(links) {
  const groups = new Map();
  for (const feature of links.features) {
    const p = feature.properties, key = linkKey(p);
    const group = groups.get(key) || { scheme: p.scheme, link: p.link, chain: [p.from], features: [], status: p.status, props: p };
    if (group.chain[group.chain.length - 1] !== p.from) group.chain.push(p.from);
    group.chain.push(p.to);
    group.features.push(feature);
    groups.set(key, group);
  }
  return groups;
}
function focusLinkGroup(group, button) {
  for (const other of document.querySelectorAll('.link-list .row')) other.classList.toggle('active', other === button);
  const bounds = new mapboxgl.LngLatBounds();
  for (const feature of group.features) for (const coord of feature.geometry.coordinates) bounds.extend(coord);
  map.fitBounds(bounds, { padding: { top: 80, bottom: 80, left: 400, right: 340 }, pitch: 50, bearing: -15, duration: 1800, maxZoom: 10.5 });
  const first = group.features[0], mid = first.geometry.coordinates[Math.floor(first.geometry.coordinates.length / 2)];
  openLinkPopup(first.properties, mid);
}
function linkRow(group) {
  const button = document.createElement('button'); button.type = 'button';
  button.className = `row${group.status === 'operational' ? '' : ' planned'}`;
  const chain = textEl('span', 'chain', group.chain.join(' → '));
  const years = linkYears(group.props);
  chain.appendChild(textEl('small', '', `${STATUS_LABEL[group.status] || group.status}${years ? ` · ${years}` : ''}`));
  button.append(textEl('span', 'tag', group.link), chain);
  button.addEventListener('click', () => focusLinkGroup(group, button));
  return button;
}
function schemeHeader(list, scheme) {
  const header = document.createElement('li'); header.className = 'group';
  header.append(document.createElement('i'), document.createTextNode(scheme));
  list.appendChild(header);
}

function renderLinkList(links) {
  const list = $('link-list');
  list.textContent = '';
  let scheme = null;
  for (const group of groupLinks(links).values()) {
    if (group.scheme !== scheme) { scheme = group.scheme; schemeHeader(list, scheme); }
    const item = document.createElement('li');
    item.appendChild(linkRow(group)); list.appendChild(item);
  }
}

// ---------- "Still to be built": every pending structure, link and unlocated work by scheme ----------
function renderPendingList(dams, links, notes) {
  const bySchemes = new Map();                 // scheme -> [{ kind, label, status, years, onClick, note }]
  const add = (scheme, row) => { if (!bySchemes.has(scheme)) bySchemes.set(scheme, []); bySchemes.get(scheme).push(row); };
  for (const dam of damsData) {
    if (!isPending(dam.status)) continue;
    add(dam.scheme || 'Other projects', {
      kind: damKindLabel(dam).toLowerCase(), label: dam.name, status: dam.status, years: pendingYears(dam),
      extra: [dam.capacity_tmcft ? formatTmcft(dam.capacity_tmcft) : null, dam.approx ? 'position approximate' : null].filter(Boolean).join(' · '),
      onClick: (button) => { for (const other of document.querySelectorAll('.link-list .row')) other.classList.toggle('active', other === button); openDamPopup(dam); flyToPoint(dam.lon, dam.lat, 11); },
    });
  }
  for (const group of groupLinks(links).values()) {
    if (!isPending(group.status)) continue;
    add(group.scheme, { kind: `${group.props.kind} link`, label: `${group.link}: ${group.chain.join(' → ')}`, status: group.status,
                        years: pendingYears(group.props), extra: null, onClick: (button) => focusLinkGroup(group, button) });
  }
  for (const note of notes) add(note.scheme, { kind: note.kind, label: note.item, status: note.status, years: null, extra: note.note, url: note.url, onClick: null });
  const list = $('pending-list');
  list.textContent = '';
  let structures = 0, linkCount = 0, unlocated = 0;
  for (const [scheme, rows] of bySchemes) {
    schemeHeader(list, scheme);
    for (const row of rows) {
      const item = document.createElement('li');
      const small = `${STATUS_LABEL[row.status] || row.status}${row.years ? ` · ${row.years}` : ''}${row.extra ? ` · ${row.extra}` : ''}`;
      if (row.onClick) {
        const button = document.createElement('button'); button.type = 'button';
        button.className = `row planned${row.status === 'proposed' ? ' proposed' : ''}`;
        const chain = textEl('span', 'chain', row.label); chain.appendChild(textEl('small', '', small));
        button.append(textEl('span', 'tag', row.kind), chain);
        button.addEventListener('click', () => row.onClick(button));
        item.appendChild(button);
        if (row.kind.endsWith('link')) linkCount++; else structures++;
      } else {
        item.className = 'note';
        const chain = textEl('span', 'chain', `${row.label} · no published location`);
        const detail = textEl('small', '', small);
        if (row.url) { const a = document.createElement('a'); a.href = row.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = ' source ↗'; detail.appendChild(a); }
        chain.appendChild(detail);
        item.append(textEl('span', 'tag', row.kind), chain);
        unlocated++;
      }
      list.appendChild(item);
    }
  }
  $('pending-count').textContent = `${structures} structures · ${linkCount} links · ${unlocated} unlocated`;
  return { structures, links: linkCount, unlocated };
}

function openDamPopup(dam) {
  damPopup.remove();
  linkPopup.remove();
  const content = document.createElement('div');
  const head = textEl('div', 'head', '');
  const pending = isPending(dam.status);
  head.append(textEl('span', `kind ${dam.kind}${pending ? ' pending' : ''}`, `${damKindLabel(dam)}${pending ? ` · ${STATUS_LABEL[dam.status]}` : ''}`),
              textEl('strong', '', dam.name));
  content.appendChild(head);
  const rows = [
    ['Status', pending ? `${STATUS_LABEL[dam.status]}${dam.target ? `, target ${dam.target}` : ''}` : null],
    ['Scheme', dam.scheme],
    ['Height', dam.height ? `${dam.height} m` : null],
    ['Terrain', dam.elev_m ? `${dam.elev_m} m above sea level` : null],
    [pending ? 'Years' : 'Built', pending ? pendingYears(dam) : damYears(dam)],
    ['Average inflow', dam.inflow_q ? `${dam.inflow_q.toLocaleString('en-IN')} m³/s${dam.inflow_name ? ` · ${dam.inflow_name}` : ''}` : null],
    [pending ? 'Planned capacity' : 'Gross capacity', dam.capacity_tmcft ? formatTmcft(dam.capacity_tmcft) : null],
    ['River', dam.river && !dam.river.includes('off-river') ? dam.river : null],
    ['Note', dam.note],
  ];
  const list = document.createElement('dl');
  for (const [term, value] of rows) {
    if (!value) continue;
    list.append(textEl('dt', '', term), textEl('dd', term === 'Note' ? 'prose' : '', value));
  }
  content.appendChild(list);
  if (dam.approx) content.appendChild(textEl('p', 'fine', `Position approximate: ${dam.approx} (OpenStreetMap), not the structure itself.`));
  const link = document.createElement('a');
  link.href = dam.url; link.target = '_blank'; link.rel = 'noopener';
  link.textContent = dam.url.includes('wikipedia.org') ? 'Source: Wikipedia ↗' : dam.url.includes('wikidata.org') ? 'Source: Wikidata ↗' : 'Source ↗';
  content.appendChild(link);
  damPopup.setLngLat([dam.lon, dam.lat]).setDOMContent(content).addTo(map);
}
function flyToCity(city) {
  if (!city) return;
  for (const [name, id] of cityIndex) map.setFeatureState({ source: 'cities', id }, { active: name === city.name });
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
  renderFlowChart(profile);

  const first = points[0], last = points[points.length - 1];
  const summary = $('river-summary');
  summary.textContent = '';
  summary.append('Enters at ', bold(`${first.elev} m`), ', leaves at ', bold(`${last.elev} m`),
                 ` · drops ${first.elev - last.elev} m over ${Math.round(profile.length_km)} km · flow grows from `,
                 bold(`${profile.min_q.toLocaleString('en-IN')}`), ' to ', bold(`${profile.max_q.toLocaleString('en-IN')} m³/s`));
  const tbody = $('profile-table').tBodies[0];
  tbody.textContent = '';
  for (let i = 0; i < points.length; i += 10) {
    const tr = document.createElement('tr');
    for (const text of [points[i].d.toFixed(0), String(points[i].elev), String(points[i].q)]) {
      const td = document.createElement('td'); td.textContent = text; tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  $('scrub').max = String(points.length - 1);
  highlightProfile(Math.min(profileState.index, points.length - 1), false);
}
const FLOW_CHART = { w: 328, h: 110, l: 38, r: 10, t: 10, b: 22 };
function renderFlowChart(profile) {
  const svg = $('flow-profile');
  while (svg.lastChild && svg.lastChild.tagName !== 'title') svg.removeChild(svg.lastChild);
  const { w, h, l, r, t, b } = FLOW_CHART;
  const points = profile.points;
  const maxD = points[points.length - 1].d;
  const yStep = niceStep(profile.max_q || 1, 3);
  const yMax = Math.ceil(profile.max_q / yStep) * yStep;
  const x = (d) => l + d / maxD * (w - l - r);
  const y = (q) => t + (1 - q / yMax) * (h - t - b);
  for (let q = 0; q <= yMax; q += yStep) {
    svg.appendChild(svgEl('line', { class: 'grid', x1: l, x2: w - r, y1: y(q), y2: y(q) }));
    svg.appendChild(svgEl('text', { class: 'tick', x: l - 5, y: y(q) + 3, 'text-anchor': 'end' }, q >= 1000 ? `${q / 1000}K` : String(q)));
  }
  const xStep = niceStep(maxD, 4);
  for (let d = 0; d <= maxD; d += xStep) {
    svg.appendChild(svgEl('text', { class: 'tick', x: x(d), y: h - 8, 'text-anchor': d === 0 ? 'start' : 'middle' }, d === 0 ? '0 km' : String(d)));
  }
  svg.appendChild(svgEl('line', { class: 'axis', x1: l, x2: w - r, y1: y(0), y2: y(0) }));
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.d).toFixed(1)} ${y(p.q).toFixed(1)}`).join(' ');
  svg.appendChild(svgEl('path', { class: 'area', d: `${path} L${x(maxD).toFixed(1)} ${y(0)} L${l} ${y(0)} Z` }));
  svg.appendChild(svgEl('path', { class: 'line', d: path }));
  svg.appendChild(svgEl('line', { id: 'cross2', class: 'cross', x1: 0, x2: 0, y1: t, y2: y(0), visibility: 'hidden' }));
  svg.appendChild(svgEl('circle', { id: 'cross2-dot', class: 'dot', r: 4.5, visibility: 'hidden' }));
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
  profileState.flowScales = { x, y };
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
  const flow = profileState.flowScales, cross2 = $('cross2'), dot2 = $('cross2-dot');
  cross2.setAttribute('x1', flow.x(point.d)); cross2.setAttribute('x2', flow.x(point.d)); cross2.setAttribute('visibility', 'visible');
  dot2.setAttribute('cx', flow.x(point.d)); dot2.setAttribute('cy', flow.y(point.q)); dot2.setAttribute('visibility', 'visible');
  $('scrub').value = String(index);
  const tip = $('profile-tip');
  if (showTip) {
    tip.textContent = '';
    tip.append(bold(`${point.elev} m`), ' ', spanText(`· ${point.q.toLocaleString('en-IN')} m³/s · ${point.d.toFixed(0)} km`));
    const box = $('profile').getBoundingClientRect();
    tip.style.left = `${x(point.d) / CHART.w * box.width}px`;
    tip.style.top = `${y(point.elev) / CHART.h * box.height}px`;
    tip.hidden = false;
  }
  scrubPoint = collection([pointFeature(point.lon, point.lat, {})]);
  if (map.getSource('scrub')) map.getSource('scrub').setData(scrubPoint);
}
function spanText(text) { const el = document.createElement('span'); el.textContent = text; return el; }

// ---------- flight along a river: a free camera follows the river bed downstream, the chart and readout follow the camera ----------
const FLIGHT = { kmPerSecond: 9, aboveGroundM: 2600, behindKm: 5, aheadKm: 7, pitch: 62 };
let flight = null;                          // { points, total, d, last }
function pointAtKm(points, d) {
  let lo = 0, hi = points.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (points[mid].d <= d) lo = mid; else hi = mid; }
  const a = points[lo], b = points[hi], f = (d - a.d) / ((b.d - a.d) || 1);
  return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f, elev: a.elev + (b.elev - a.elev) * f, q: a.q + (b.q - a.q) * f };
}
function startFlight() {
  stopOrbit();
  const points = profileState.profiles[profileState.river].points;
  flight = { points, total: points[points.length - 1].d, d: Math.max(0, points[profileState.index].d), last: 0 };
  $('fly').textContent = 'Stop';
  $('fly').setAttribute('aria-pressed', 'true');
  document.body.classList.add('flying');
  requestAnimationFrame(flightStep);
}
function stopFlight() {
  if (!flight) return;
  flight = null;
  $('fly').textContent = 'Fly the river';
  $('fly').setAttribute('aria-pressed', 'false');
  document.body.classList.remove('flying');
  clearCursor();
}
function flightStep(now) {
  if (!flight) return;
  if (flight.last) flight.d += FLIGHT.kmPerSecond * Math.min((now - flight.last) / 1000, 0.1);
  flight.last = now;
  if (flight.d >= flight.total) { stopFlight(); return; }
  const here = pointAtKm(flight.points, flight.d);
  const behind = pointAtKm(flight.points, Math.max(0, flight.d - FLIGHT.behindKm));
  const ahead = pointAtKm(flight.points, Math.min(flight.total, flight.d + FLIGHT.aheadKm));
  const ground = map.queryTerrainElevation([behind.lon, behind.lat], { exaggerated: true });
  const camera = map.getFreeCameraOptions();
  camera.position = mapboxgl.MercatorCoordinate.fromLngLat([behind.lon, behind.lat], (ground === null ? here.elev * Number($('exag').value) * 1.6 : ground) + FLIGHT.aboveGroundM);
  const dx = (ahead.lon - behind.lon) * Math.cos((behind.lat * Math.PI) / 180), dy = ahead.lat - behind.lat;
  camera.setPitchBearing(FLIGHT.pitch, (Math.atan2(dx, dy) * 180) / Math.PI);   // a fixed tilt, heading downstream
  map.setFreeCameraOptions(camera);
  highlightProfile(nearestIndex(flight.points, flight.d), false);
  cursorElev.textContent = Math.round(here.elev).toLocaleString('en-IN');
  cursorPos.textContent = `${profileState.river} · river bed · ${Math.round(here.q).toLocaleString('en-IN')} m³/s · ${Math.round(flight.d)} km`;
  showComparison(here.elev);
  requestAnimationFrame(flightStep);
}
$('fly').addEventListener('click', () => (flight ? stopFlight() : startFlight()));
for (const event of ['mousedown', 'wheel', 'touchstart']) map.getCanvasContainer().addEventListener(event, stopFlight, { passive: true });
window.addEventListener('keydown', (event) => { if (event.key === 'Escape') stopFlight(); });
$('scrub').addEventListener('input', (event) => highlightProfile(Number(event.target.value), true));
for (const tab of document.querySelectorAll('[role="tab"]')) {
  tab.addEventListener('click', () => {
    for (const other of document.querySelectorAll('[role="tab"]')) other.setAttribute('aria-selected', String(other === tab));
    stopFlight();
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
    const [cities, profiles, districtPoints, flowSummary, flowReaches, dams, links, pumphouses, cropland, pendingNotes] = await Promise.all([
      loadJson('data/cities.json'), loadJson('data/rivers.json'), loadJson('data/district_points.geojson'),
      loadJson('data/flow_summary.json'), loadJson('data/flow.geojson'), loadJson('data/dams.json'),
      loadJson('data/links.geojson'), loadJson('data/pumphouses.json'), loadJson('data/cropland.json'),
      loadJson('data/pending.json').catch(() => [])]);
    cropBounds = cropland.bounds;
    for (const [id, source] of Object.entries(cropSources())) map.addSource(id, source);
    addLayers(cropLayers(MAP_THEMES[currentTheme()]), 'mask');
    renderCropland(cropland);
    const canals = await loadJson('data/canals.geojson').catch(() => null);   // absent until fetch_data.py gets OSM canals
    if (canals) {
      canalsLoaded = true;
      map.addSource('canals', { type: 'geojson', data: canals });
      addLayers(canalLayers(MAP_THEMES[currentTheme()]), 'links-highlight');
      debug.notes.canals = canals.features.length;
      const canalSummary = await loadJson('data/canals_summary.json').catch(() => null);
      if (canalSummary) renderCanalNetwork(canalSummary);
    } else {
      document.querySelector('[data-canal]').closest('.fgroup').hidden = true;
    }
    debug.notes.cropDistricts = cropland.districts.length;
    prepareBubbles(flowReaches);
    buildDamLabels(dams);
    renderEraCounts(dams);
    buildPumpLabels(pumphouses);
    renderLinkList(links);
    buildWorkInProgressLabels(links);
    renderStatusCounts(dams, links);
    debug.notes.pending = renderPendingList(dams, links, pendingNotes);
    debug.notes.dams = dams.length;
    debug.notes.links = links.features.length;
    debug.notes.bubbles = bubbleReaches.reduce((n, reach) => n + reach.particles.length, 0);
    profileState.profiles = profiles;
    citiesData = cities;
    buildCityLabels(cities);
    buildDistrictLabels(districtPoints, new Set(cities.map((c) => c.name.toLowerCase())));
    const tanks = await loadJson('data/tanks_summary.json').catch(() => null);   // absent until fetch_data.py gets OSM water bodies
    if (tanks) {
      tanksLoaded = true;
      tankSummary = tanks;
      map.addSource('tanks', { type: 'geojson', data: 'data/tanks.geojson' });
      map.addSource('tank-points', { type: 'geojson', data: 'data/tank_points.geojson' });
      addLayers(tankLayers(MAP_THEMES[currentTheme()]), 'districts');
      renderTanks(tanks);
      debug.notes.tanks = tanks.osm_tanks;
    } else {
      document.querySelector('[data-tank]').closest('.fgroup').hidden = true;
      $('tank-card').hidden = true;
    }
    const groundwater = await loadJson('data/groundwater_summary.json').catch(() => null);   // absent until fetch_data.py gets the WRIS export
    if (groundwater) {
      gwLoaded = true;
      gwData = groundwater;
      map.addSource('groundwater', { type: 'geojson', data: 'data/groundwater.geojson' });
      addLayers(gwLayers(MAP_THEMES[currentTheme()]), 'districts');
      renderGroundwater(groundwater);
      debug.notes.groundwater = groundwater.state.wells;
    } else {
      document.querySelector('[data-gw]').closest('.fgroup').hidden = true;
      $('gw-card').hidden = true;
    }
    const proposal = await loadJson('data/proposal.json').catch(() => null);   // absent until propose_water.py has run
    if (proposal) {
      proposalLoaded = true;
      proposalGeo = await loadJson('data/proposal.geojson');
      map.addSource('proposal', { type: 'geojson', data: proposalGeo, lineMetrics: true });
      addLayers(proposalLayers(MAP_THEMES[currentTheme()]), 'districts');
      renderProposal(proposal);
      addProposalMarkers(proposal, proposalGeo);
      debug.notes.proposal = proposal.works.length;
    } else {
      document.querySelector('[data-proposal]').closest('.fgroup').hidden = true;
      $('proposal-card').hidden = true;
    }
    renderCities(cities, profiles);
    renderProfile();
    renderFlowLegend();
    renderPeaks(flowSummary);
    renderDistrictFlow(flowSummary);
    await addLabelSources();                // every label source is built by now: cities, districts, dams, pump houses, cones, peaks, proposal
    debug.notes.flowDistricts = flowSummary.districts.length;
    debug.phase = 'data-loaded'; writeDebug();
    if (DEBUG) {
      debug.notes.cities = cities.length;
      debug.notes.profiles = Object.fromEntries(Object.entries(profiles).map(([k, v]) => [k, v.points.length]));
      debug.hyderabad = cities.find((c) => c.name === 'Hyderabad');
    }
  } catch (error) {
    debug.errors.push(String(error));
    $('toast').textContent = `Data failed to load: ${error.message}`;
    return;
  }
  // The flow animation starts only now: its paint updates keep map.loaded() false.
  const settle = () => {
    if (!map.loaded()) { map.once('render', settle); return; }
    $('toast').classList.add('gone');
    if (playIntro) { map.easeTo({ ...HOME, duration: 3600, easing: (x) => 1 - (1 - x) ** 3, essential: true }); riseTerrain(3600); }   // the terrain rises into view
    if (flowAnimating) requestAnimationFrame(animateFlow);
    debug.phase = 'ready';
    if (DEBUG) {
      const h = debug.hyderabad, decoded = elevationAt([h.lon, h.lat]);
      debug.notes.hyderabad = { listed: h.elev, decoded: decoded === null ? null : Math.round(decoded) };   // listed = Copernicus 1 km median, decoded = Mapbox Terrain-DEM
      debug.notes.terrain = Boolean(map.getTerrain()); debug.notes.layers = map.getStyle().layers.map((l) => l.id); writeDebug(); document.title = 'READY ' + document.title;
    }
  };
  settle();
});

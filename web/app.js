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
    contour: '#5a4634', flowGlow: '#ffffff', flowDash: '#eef7ff', link: '#c2410c', linkDash: '#fff4e8', cropOpacity: 0.82,
    canal: '#c2187f', canalOld: '#8a6f84', canalDash: '#fff0fa', canalCasing: '#ffffff',
    tank: '#3b95dc', tankEdge: '#1b5a93', tankRamp: ['#e6eef5', '#1d5f99'],
    flow: ['#86d9e3', '#36aee6', '#2566d8', '#1a3aa6', '#5f2aa8'],   // FLOW_CLASSES: cyan -> blue -> navy -> purple
    shadow: '#2b2016', highlight: '#fff4e2', accent: '#4e3d2e',
    sky: { 'sky-color': '#cfe3f6', 'horizon-color': '#eef3f8', 'fog-color': '#e9e6df' },
  },
  dark: {
    background: '#0e0f12', mask: '#0e0f12', maskOpacity: 0.58,
    district: '#d8d4cc', districtOpacity: 0.38, state: '#f0efec', stateCasing: '#000000',
    contour: '#d8d4cc', flowGlow: '#0b1a33', flowDash: '#ffffff', link: '#fb923c', linkDash: '#fff7ed', cropOpacity: 0.9,
    canal: '#ff6fd0', canalOld: '#d2b4c8', canalDash: '#fff0fa', canalCasing: '#2a0d20',
    tank: '#4fb3ff', tankEdge: '#bfe3ff', tankRamp: ['#161c26', '#3f8fd0'],
    flow: ['#2f96a8', '#3cbbea', '#6a9cff', '#a9bdff', '#dcaaff'],   // FLOW_CLASSES: teal -> sky -> blue -> lilac on the dark surface
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
  if (map && map.getLayer('background')) { applyMapTheme(); renderFlowLegend(); syncArrowImage(); }
}
try { const saved = localStorage.getItem('theme'); if (saved) document.documentElement.dataset.theme = saved; } catch (_) { /* ignore */ }

// ---------- style ----------
function reliefExpression(theme) {
  // Exactly 0 m only occurs on the flat plane outside the DEM, so it takes the page colour.
  return ['interpolate', ['linear'], ['elevation'], 0, MAP_THEMES[theme].background, ...RELIEF_STOPS.flat()];
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
const FLOW_DASH_OPACITY = 0.9;
let flowStep = 0;
let flowAnimating = true;

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
const districtLabels = new Map();          // district -> label element (carries the Mission Kakatiya count)
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
    { id: 'tanks-dots', type: 'circle', source: 'tank-points', maxzoom: TANK_POLYGON_ZOOM, layout: { visibility: vis },
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
  for (const id of ['tanks-fill', 'tanks-outline', 'tanks-dots']) map.setLayoutProperty(id, 'visibility', tankVisibility());
  map.setLayoutProperty('tanks-kakatiya', 'visibility', tankMode === 'kakatiya' ? 'visible' : 'none');
}
function setTankMode(mode) {
  tankMode = mode;
  for (const button of document.querySelectorAll('[data-tank]')) button.setAttribute('aria-pressed', String(button.dataset.tank === mode));
  document.body.classList.toggle('tank-mk', mode === 'kakatiya');
  applyTankVisibility();
  if (mode === 'off') tankPopup.remove();
}
for (const button of document.querySelectorAll('[data-tank]')) button.addEventListener('click', () => setTankMode(button.dataset.tank));

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
      flow: { type: 'geojson', data: 'data/flow.geojson' },
      contours: { type: 'geojson', data: 'data/contours.geojson' },
      links: { type: 'geojson', data: 'data/links.geojson' },
      ...cropSources(),
      ...(canalsLoaded ? { canals: { type: 'geojson', data: 'data/canals.geojson' } } : {}),
      ...(tanksLoaded ? { tanks: { type: 'geojson', data: 'data/tanks.geojson' }, 'tank-points': { type: 'geojson', data: 'data/tank_points.geojson' } } : {}),
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': t.background } },
      { id: 'relief', type: 'color-relief', source: 'shade', paint: { 'color-relief-color': reliefExpression(theme) } },
      { id: 'hillshade', type: 'hillshade', source: 'shade', layout: { visibility: chipOn('hillshade') }, paint: {
          'hillshade-method': 'standard', 'hillshade-illumination-direction': 315, 'hillshade-exaggeration': 0.75,
          'hillshade-shadow-color': t.shadow, 'hillshade-highlight-color': t.highlight, 'hillshade-accent-color': t.accent } },
      ...cropLayers(t),                      // under the mask so land outside the state stays dimmed
      { id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': t.mask, 'fill-opacity': t.maskOpacity } },
      { id: 'contours', type: 'line', source: 'contours', layout: { visibility: chipOn('contours'), 'line-join': 'round' }, paint: {
          'line-color': t.contour, 'line-opacity': 0.55,
          'line-width': ['case', ['==', ['%', ['get', 'elev'], 500], 0], 1.4, 0.6] } },
      ...tankLayers(t),                      // tanks and the Mission Kakatiya shading sit under the district lines
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
      // Static arrows give direction on links still being built; operating links get moving chevrons on the canvas.
      { id: 'links-arrows', type: 'symbol', source: 'links', filter: ['all', ['!=', ['get', 'status'], 'operational'], linkStatusFilter()],
        layout: { 'symbol-placement': 'line', 'symbol-spacing': 70, 'icon-image': 'arrow', 'icon-size': ['interpolate', ['linear'], ['zoom'], 6, 0.4, 10, 0.6],
                  'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true, visibility: chipOn('links') },
        paint: { 'icon-opacity': 0.7 } },
      { id: 'links-hit', type: 'line', source: 'links', filter: linkStatusFilter(), layout: { visibility: chipOn('links') },
        paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 16 } },
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
  attributionControl: false, hash: true, antialias: true,   // the URL carries the view, so views can be shared
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-right');
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
map.on('styleimagemissing', (event) => { if (event.id === 'arrow') syncArrowImage(); });

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
  dams: (on) => document.body.classList.toggle('dams-off', !on),
  links: (on) => {
    const visibility = on ? 'visible' : 'none';
    for (const id of ['links-highlight', 'links-casing', 'links-line', 'links-arrows', 'links-hit']) map.setLayoutProperty(id, 'visibility', visibility);
    document.body.classList.toggle('links-off', !on);
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
// Operating Kaleshwaram links carry moving chevrons so the direction of pumping is unmistakable.
const LINK_CHEVRON = { spacingM: 4000, speedPx: 45, size: 4.5 };
let linkTracks = [];

function prepareLinkParticles(links) {
  linkTracks = [];
  for (const feature of links.features) {
    if (feature.properties.status !== 'operational') continue;
    const coords = feature.geometry.coordinates, cum = [0];
    for (let i = 1; i < coords.length; i++) {
      const dx = (coords[i][0] - coords[i - 1][0]) * EARTH_M_PER_DEG * Math.cos(coords[i][1] * Math.PI / 180);
      const dy = (coords[i][1] - coords[i - 1][1]) * EARTH_M_PER_DEG;
      cum.push(cum[i - 1] + Math.hypot(dx, dy));
    }
    const length = cum[cum.length - 1];
    const count = Math.max(2, Math.round(length / LINK_CHEVRON.spacingM));
    const lngs = coords.map((c) => c[0]), lats = coords.map((c) => c[1]);
    linkTracks.push({ coords, cum, length, bbox: [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)],
                      particles: Array.from({ length: count }, (_, i) => i * length / count) });
  }
}

function drawLinkChevrons(dt, metresPerPixel, west, south, east, north, width, height) {
  if (document.body.classList.contains('links-off') || statusMode === 'pending') return;   // chevrons mark operating links only
  const colour = MAP_THEMES[currentTheme()].link;
  for (const track of linkTracks) {
    const step = LINK_CHEVRON.speedPx * metresPerPixel * dt;
    for (let i = 0; i < track.particles.length; i++) track.particles[i] = (track.particles[i] + step) % track.length;
    const [minLng, minLat, maxLng, maxLat] = track.bbox;
    if (maxLng < west || minLng > east || maxLat < south || minLat > north) continue;
    for (const distance of track.particles) {
      const here = map.project(pointAlong(track, distance));
      const ahead = map.project(pointAlong(track, Math.min(distance + 300, track.length)));
      if (here.x < -20 || here.y < -20 || here.x > width + 20 || here.y > height + 20) continue;
      const angle = Math.atan2(ahead.y - here.y, ahead.x - here.x);
      const alpha = Math.min(1, distance / 1500, (track.length - distance) / 1500);
      drawChevron(here.x, here.y, angle, LINK_CHEVRON.size, colour, alpha);
    }
  }
}
function drawChevron(x, y, angle, size, colour, alpha) {
  bubbleCtx.save();
  bubbleCtx.translate(x, y); bubbleCtx.rotate(angle); bubbleCtx.globalAlpha = alpha;
  bubbleCtx.beginPath();
  bubbleCtx.moveTo(size, 0); bubbleCtx.lineTo(-size * 0.8, size * 0.9); bubbleCtx.lineTo(-size * 0.3, 0); bubbleCtx.lineTo(-size * 0.8, -size * 0.9); bubbleCtx.closePath();
  bubbleCtx.fillStyle = colour; bubbleCtx.fill();
  bubbleCtx.lineWidth = 1; bubbleCtx.strokeStyle = 'rgba(255,255,255,0.95)'; bubbleCtx.lineJoin = 'round'; bubbleCtx.stroke();
  bubbleCtx.restore();
}

function drawBubbles(dt) {
  clearBubbles();
  if (!bubbleReaches.length) return;
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
  drawLinkChevrons(dt, metresPerPixel, west, south, east, north, width, height);
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
const flowPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: 'flow-popup' });
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
  const node = document.createElement('div'); node.className = 'mk-peak';
  const label = textEl('span', 'lbl', `${river} peak`);
  label.appendChild(textEl('span', 'e', `${peak.q.toLocaleString('en-IN')} m³/s`));
  node.append(textEl('span', 'ring', ''), textEl('span', 'core', ''), label);
  node.addEventListener('click', () => flyToPoint(peak.lon, peak.lat, 10));
  new maplibregl.Marker({ element: node, anchor: 'center' }).setLngLat([peak.lon, peak.lat]).addTo(map);
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
$('theme').addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
$('collapse').addEventListener('click', () => { $('panel').classList.add('hidden'); $('expand').hidden = false; });
$('expand').addEventListener('click', () => { $('panel').classList.remove('hidden'); $('expand').hidden = true; });
$('filters-collapse').addEventListener('click', () => { $('filters').classList.add('hidden'); $('filters-expand').hidden = false; });
$('filters-expand').addEventListener('click', () => { $('filters').classList.remove('hidden'); $('filters-expand').hidden = true; });
const updateLabelDensity = () => document.body.classList.toggle('z-far', map.getZoom() < LABEL_ZOOM);
map.on('zoom', updateLabelDensity);
map.on('load', updateLabelDensity);   // a view restored from the URL hash fires no zoom event
updateLabelDensity();

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
    const name = feature.properties.shapeName;
    const el = document.createElement('div');
    el.className = 'mk-district' + (cityNames.has(name.toLowerCase()) ? ' named-by-city' : '');   // the city label already names it
    el.append(textEl('span', 'nm', name), textEl('b', 'cnt', ''));
    districtLabels.set(name, el);
    districtCentres.set(name, feature.geometry.coordinates);
    new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(feature.geometry.coordinates).addTo(map);
  }
}
// ---------- dams: markers and the year filter (Telangana was formed in 2014) ----------
const ERA_YEAR = 2014;
const damMarkers = [];                       // { dam, element }
function damYear(dam) { return dam.opened || dam.began || null; }
function damInEra(dam, era) {
  const year = damYear(dam);
  return era === 'all' || (year !== null && (era === 'before' ? year < ERA_YEAR : year >= ERA_YEAR));
}
function setEra(era) {
  for (const button of document.querySelectorAll('[data-era]')) button.setAttribute('aria-pressed', String(button.dataset.era === era));
  for (const { dam, element } of damMarkers) element.classList.toggle('era-hidden', !damInEra(dam, era));
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
const pumpMarkers = [];                      // { house, element }
const wipMarkers = [];                       // link cones: { status, element }
function setStatusMode(mode) {
  statusMode = mode;
  for (const button of document.querySelectorAll('[data-status]')) button.setAttribute('aria-pressed', String(button.dataset.status === mode));
  for (const { dam, element } of damMarkers) element.classList.toggle('status-hidden', !statusShown(dam.status));
  for (const { house, element } of pumpMarkers) element.classList.toggle('status-hidden', !statusShown(house.status));
  for (const { status, element } of wipMarkers) element.classList.toggle('status-hidden', !statusShown(status));
  for (const id of ['links-casing', 'links-line', 'links-hit']) if (map.getLayer(id)) map.setFilter(id, linkStatusFilter());
  if (map.getLayer('links-arrows')) map.setFilter('links-arrows', ['all', ['!=', ['get', 'status'], 'operational'], linkStatusFilter()]);
  applyTankVisibility();
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
function statusBadge() {
  const badge = document.createElement('span'); badge.className = 'badge'; badge.title = 'under construction or proposed';
  const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use'); use.setAttribute('href', '#ic-wip'); svg.appendChild(use); badge.appendChild(svg);
  return badge;
}

// The label carries name and capacity; while a dam's popup is open it shrinks to the name.
const damPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 16, className: 'dam-popup', maxWidth: '320px' });
let openDamNode = null;
damPopup.on('close', () => { if (openDamNode) openDamNode.classList.remove('open'); openDamNode = null; });

const damKindLabel = (dam) => (dam.kind === 'barrage' ? 'Barrage' : dam.river && dam.river.includes('off-river') ? 'Reservoir' : 'Dam');
function addDamMarker(dam) {
  const node = document.createElement('div');
  node.className = `mk-dam ${dam.kind}${isPending(dam.status) ? ` pending ${dam.status === 'proposed' ? 'proposed' : 'uc'}` : ''}${dam.approx ? ' approx' : ''}`;
  damMarkers.push({ dam, element: node });
  const icon = document.createElement('span'); icon.className = 'ic';
  const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use'); use.setAttribute('href', `#ic-${dam.kind}`); svg.appendChild(use); icon.appendChild(svg);
  if (isPending(dam.status)) icon.appendChild(statusBadge());
  const label = textEl('span', 'lbl', dam.name);
  if (dam.capacity_tmcft) label.appendChild(textEl('span', 'e', formatTmcft(dam.capacity_tmcft)));
  if (isPending(dam.status)) label.appendChild(textEl('span', 'st', STATUS_LABEL[dam.status]));
  node.append(icon, label);
  node.title = `${damKindLabel(dam)}${dam.river && !dam.river.includes('off-river') ? ` on the ${dam.river}` : ''}${isPending(dam.status) ? ` · ${STATUS_LABEL[dam.status]}` : ''}`
             + `${dam.approx ? ` · position approximate (${dam.approx})` : ''} · click for details`;
  node.addEventListener('click', (event) => { event.stopPropagation(); openDamPopup(dam, node); flyToPoint(dam.lon, dam.lat, 11.5); });
  new maplibregl.Marker({ element: node, anchor: 'left', offset: [-11, 0] }).setLngLat([dam.lon, dam.lat]).addTo(map);
}

// ---------- Kaleshwaram links: pump houses, tunnel portals and the link list ----------
function addPumpMarker(house) {
  const node = document.createElement('div');
  node.className = `mk-pump${isPending(house.status) ? ' pending' : ''}${house.approx ? ' approx' : ''}`;
  pumpMarkers.push({ house, element: node });
  const icon = document.createElement('span'); icon.className = 'ic';
  const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use'); use.setAttribute('href', house.kind === 'tunnel' ? '#ic-tunnel' : '#ic-pump'); svg.appendChild(use); icon.appendChild(svg);
  if (isPending(house.status)) icon.appendChild(statusBadge());
  const label = textEl('span', 'lbl', `${house.name}${house.power ? ` · ${house.power.replace('MW', ' MW')}` : ''}`);
  if (isPending(house.status)) label.appendChild(textEl('span', 'st', STATUS_LABEL[house.status]));
  node.append(icon, label);
  node.title = `${house.name}${house.elev_m ? ` · terrain ${house.elev_m} m` : ''}${house.since ? ` · pumping since ${house.since}` : ''}`
             + `${house.approx ? ` · position approximate (${house.approx})` : ''} · ${house.source === 'OpenStreetMap' ? 'OpenStreetMap' : 'see the link popup for the source'}`;
  new maplibregl.Marker({ element: node, anchor: 'left', offset: [-10, 0] }).setLngLat([house.lon, house.lat]).addTo(map);
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
const canalPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup canal-popup', maxWidth: '300px' });
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
const tankPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 8, className: 'dam-popup tank-popup', maxWidth: '300px' });
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
    const label = districtLabels.get(d.district);
    if (!label) continue;
    const total = kakatiyaTotal(d);
    label.querySelector('.cnt').textContent = d.mk_counted_in ? `in ${d.mk_counted_in}` : total ? `${indian(total)} tanks` : '';
  }
}

// ---------- link popup ----------
const linkPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 10, className: 'dam-popup link-popup', maxWidth: '340px' });
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

function addWorkInProgressMarkers(links) {
  const seen = new Set();
  for (const feature of links.features) {
    const p = feature.properties;
    if (p.status === 'operational' || seen.has(linkKey(p))) continue;
    seen.add(linkKey(p));
    const coords = feature.geometry.coordinates, mid = coords[Math.floor(coords.length / 2)];
    const node = document.createElement('div'); node.className = 'mk-wip';
    const icon = document.createElement('span'); icon.className = 'ic';
    const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(SVG_NS, 'use'); use.setAttribute('href', '#ic-wip'); svg.appendChild(use); icon.appendChild(svg);
    node.append(icon, textEl('span', 'lbl', `${p.link} · ${STATUS_LABEL[p.status] || p.status}`));
    node.title = `${p.link}: ${p.from} → ${p.to} · ${p.note}`;
    wipMarkers.push({ status: p.status, element: node });
    new maplibregl.Marker({ element: node, anchor: 'left', offset: [-11, 0] }).setLngLat(mid).addTo(map);
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
  const bounds = new maplibregl.LngLatBounds();
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
  for (const entry of damMarkers) {
    const { dam, element } = entry;
    if (!isPending(dam.status)) continue;
    add(dam.scheme || 'Other projects', {
      kind: damKindLabel(dam).toLowerCase(), label: dam.name, status: dam.status, years: pendingYears(dam),
      extra: [dam.capacity_tmcft ? formatTmcft(dam.capacity_tmcft) : null, dam.approx ? 'position approximate' : null].filter(Boolean).join(' · '),
      onClick: (button) => { for (const other of document.querySelectorAll('.link-list .row')) other.classList.toggle('active', other === button); openDamPopup(dam, element); flyToPoint(dam.lon, dam.lat, 11); },
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

function openDamPopup(dam, node) {
  damPopup.remove();                                   // closes any other dam's popup (restoring its label)
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
  node.classList.add('open');
  openDamNode = node;
  damPopup.setLngLat([dam.lon, dam.lat]).setDOMContent(content).addTo(map);
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
    const [cities, profiles, districtPoints, flowSummary, flowReaches, dams, links, pumphouses, cropland, pendingNotes] = await Promise.all([
      loadJson('data/cities.json'), loadJson('data/rivers.json'), loadJson('data/district_points.geojson'),
      loadJson('data/flow_summary.json'), loadJson('data/flow.geojson'), loadJson('data/dams.json'),
      loadJson('data/links.geojson'), loadJson('data/pumphouses.json'), loadJson('data/cropland.json'),
      loadJson('data/pending.json').catch(() => [])]);
    cropBounds = cropland.bounds;
    for (const [id, source] of Object.entries(cropSources())) map.addSource(id, source);
    for (const layer of cropLayers(MAP_THEMES[currentTheme()])) map.addLayer(layer, 'mask');
    renderCropland(cropland);
    const canals = await loadJson('data/canals.geojson').catch(() => null);   // absent until fetch_data.py gets OSM canals
    if (canals) {
      canalsLoaded = true;
      map.addSource('canals', { type: 'geojson', data: canals });
      for (const layer of canalLayers(MAP_THEMES[currentTheme()])) map.addLayer(layer, 'links-highlight');
      debug.notes.canals = canals.features.length;
      const canalSummary = await loadJson('data/canals_summary.json').catch(() => null);
      if (canalSummary) renderCanalNetwork(canalSummary);
    } else {
      document.querySelector('[data-canal]').closest('.fgroup').hidden = true;
    }
    debug.notes.cropDistricts = cropland.districts.length;
    prepareBubbles(flowReaches);
    dams.forEach(addDamMarker);
    renderEraCounts(dams);
    pumphouses.forEach(addPumpMarker);
    renderLinkList(links);
    prepareLinkParticles(links);
    addWorkInProgressMarkers(links);
    renderStatusCounts(dams, links);
    debug.notes.pending = renderPendingList(dams, links, pendingNotes);
    debug.notes.dams = dams.length;
    debug.notes.links = links.features.length;
    debug.notes.bubbles = bubbleReaches.reduce((n, reach) => n + reach.particles.length, 0);
    profileState.profiles = profiles;
    cities.forEach(addCityMarker);
    addDistrictLabels(districtPoints, new Set(cities.map((c) => c.name.toLowerCase())));
    const tanks = await loadJson('data/tanks_summary.json').catch(() => null);   // absent until fetch_data.py gets OSM water bodies
    if (tanks) {
      tanksLoaded = true;
      tankSummary = tanks;
      map.addSource('tanks', { type: 'geojson', data: 'data/tanks.geojson' });
      map.addSource('tank-points', { type: 'geojson', data: 'data/tank_points.geojson' });
      for (const layer of tankLayers(MAP_THEMES[currentTheme()])) map.addLayer(layer, 'districts');
      renderTanks(tanks);
      debug.notes.tanks = tanks.osm_tanks;
    } else {
      document.querySelector('[data-tank]').closest('.fgroup').hidden = true;
      $('tank-card').hidden = true;
    }
    renderCities(cities, profiles);
    renderProfile();
    renderFlowLegend();
    renderPeaks(flowSummary);
    renderDistrictFlow(flowSummary);
    debug.notes.flowDistricts = flowSummary.districts.length;
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
  // The flow animation starts only now: its paint updates keep map.loaded() false.
  const settle = () => {
    if (!map.loaded()) { map.once('render', settle); return; }
    $('toast').classList.add('gone');
    if (flowAnimating) requestAnimationFrame(animateFlow);
    debug.phase = 'ready';
    if (DEBUG) { debug.notes.terrain = Boolean(map.getTerrain()); debug.notes.layers = map.getStyle().layers.map((l) => l.id); writeDebug(); document.title = 'READY ' + document.title; }
  };
  settle();
});
function tileKeyFor(lng, lat) {
  const n = 2 ** TILE_MAX_ZOOM, latRad = lat * Math.PI / 180;
  return `${TILE_MAX_ZOOM}/${Math.floor((lng + 180) / 360 * n)}/${Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n)}`;
}

/* Telangana atlas shell: the five lenses, the details drawer, the bottom timeline, settings, the About sheet and the phone sheet.
   A classic script that runs after app.js and drives it through its functions (setCanalMode, setTankMode, setGwMode, setCropMode,
   setProposalMode, toggles, setYear); everything from the later packages (setThematic, Atlas3D, AtlasTour) is guarded. */
'use strict';

const $$ = (selector) => document.querySelectorAll(selector);
const isPhone = () => matchMedia('(max-width: 900px)').matches;

// ---------- lens model ----------
const lensState = { id: 'height', detailsOpen: false, sheet: 'peek', groundLayer: 'gw', groundValue: 'change', toolPanel: false, drawerBefore: false };
const LENS_IDS = ['height', 'rivers', 'since2014', 'ground', 'proposal'];
const MODEL_GROUPS = ['dams', 'reservoirs', 'pumps', 'conduits', 'proposal'];
// What each lens turns on: canalMode, the dams/links chips, tankMode, proposalMode, the thematic (grey relief) mode, the 3D groups,
// the timeline ('hidden' | 'now' | '2014' = jump to 2014 on entry | 'ground' = only with Depth/Cover) and the plan badge. Cameras: desktop.
const LENSES = {
  height: { title: 'How high is it?', canal: 'off', dams: true, links: false, tank: 'off', proposal: 'off', thematic: false,
    models: ['dams', 'reservoirs'], timeline: 'hidden', badge: false, camera: { center: [79.35, 17.75], zoom: 7.2, pitch: 50, bearing: -18 } },
  rivers: { title: 'Rivers & lifts', canal: 'after', dams: true, links: true, tank: 'tanks', proposal: 'off', thematic: false,
    models: ['dams', 'reservoirs', 'pumps', 'conduits'], timeline: 'now', badge: false, camera: { center: [79.30, 18.35], zoom: 8.3, pitch: 62, bearing: -28 } },
  since2014: { title: 'Since 2014', canal: 'after', dams: true, links: true, tank: 'kakatiya', proposal: 'off', thematic: true,
    models: ['dams', 'reservoirs', 'pumps', 'conduits'], timeline: '2014', badge: false, camera: { center: [79.35, 17.75], zoom: 7.2, pitch: 45, bearing: -10 } },
  ground: { title: 'Groundwater & crops', canal: 'off', dams: false, links: false, tank: 'off', proposal: 'off', thematic: true,
    models: [], timeline: 'ground', badge: false, camera: { center: [79.35, 17.85], zoom: 7.0, pitch: 20, bearing: 0 } },
  proposal: { title: 'Proposal', canal: 'off', dams: true, links: false, tank: 'off', proposal: 'on', thematic: true,
    models: ['proposal', 'dams', 'reservoirs'], timeline: 'hidden', badge: true, camera: { center: [79.35, 17.85], zoom: 7.0, pitch: 40, bearing: -10 } },
};
const GROUND_SWITCH_YEAR = 2015;           // Depth/Cover: years before it show the before-2014 window, later years the after window

/** Presses or releases every copy of a chip and applies its toggle (the dams/links/pending chips sit in two lens cards). */
function setChip(name, on) {
  for (const chip of $$(`.chip[data-toggle="${name}"]`)) chip.setAttribute('aria-pressed', String(on));
  if (toggles[name]) toggles[name](on);
}
function lensCamera() { return LENSES[lensState.id].camera; }
function lensPadding() {
  if (isPhone()) return { top: 48, bottom: $('lens-panel').offsetHeight, left: 0, right: 0 };
  return { left: 360, top: 64, right: lensState.detailsOpen ? 396 : 0, bottom: 72 };
}
function flyToLens(id) {
  const base = LENSES[id].camera;
  const camera = { ...base, zoom: isPhone() ? base.zoom - 0.8 : base.zoom, padding: lensPadding() };
  stopFlight();
  if (reducedMotion) map.jumpTo(camera); else map.flyTo({ ...camera, duration: 2200, essential: true });
}
/** The year is reset only when it differs: at script start the map has no style yet, and the defaults already say "Now". */
function resetYear() { if (yearActive || yearValue !== YEAR_MAX) setYear(YEAR_MAX, false); }
function syncTimeline() {
  const mode = LENSES[lensState.id].timeline;
  const ground = mode === 'ground';
  $('timeline').hidden = mode === 'hidden' || (ground && lensState.groundValue === 'change');
  $('timeline').classList.toggle('windowed', ground);   // no Play: the slider only picks the before/after window here
  if (ground) stopYearPlay();
}

/** The 3D groups of the current lens. The first setLens runs before three3d.js has loaded, so app.js's 'atlas3d:init' re-applies them. */
function applyLensModels() {
  if (!window.Atlas3D) return;
  const models = LENSES[lensState.id].models;
  for (const group of MODEL_GROUPS) Atlas3D.setVisible(group, models.includes(group));
}
document.addEventListener('atlas3d:init', applyLensModels);

function setLens(id, { fly = true, fromTour = false } = {}) {
  const lens = LENSES[id];
  if (!lens) return;
  const entering = id !== lensState.id;
  lensState.id = id;
  if (entering) {                            // a lens change ends every camera animation
    stopFlight();
    setChip('orbit', false);
    if (!fromTour && window.AtlasTour && AtlasTour.isRunning()) AtlasTour.stop();
  }
  for (const tab of $$('#lenses [role="tab"]')) {
    const on = tab.dataset.lens === id;
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;
  }
  for (const card of $$('.lens-card')) card.hidden = card.dataset.lens !== id;
  renderDrawer();
  setCanalMode(lens.canal);
  setChip('dams', lens.dams);
  setChip('links', lens.links);
  setTankMode(lens.tank);
  if (id === 'ground') applyGround(); else { setGwMode('off'); setCropMode('off'); }
  setProposalMode(lens.proposal);
  if (typeof setThematic === 'function') setThematic(lens.thematic);
  applyLensModels();
  if (lens.timeline === 'hidden' || lens.timeline === 'now') resetYear();
  else if (lens.timeline === '2014' && entering) setYear(2014);
  syncTimeline();
  $('plan-badge').hidden = !lens.badge;
  if (fly && entering) flyToLens(id);
  document.dispatchEvent(new CustomEvent('atlas:lens', { detail: { id } }));
}
for (const tab of $$('#lenses [role="tab"]')) tab.addEventListener('click', () => setLens(tab.dataset.lens));
$('lenses').addEventListener('keydown', (event) => {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
  let index;
  if (step) index = (LENS_IDS.indexOf(lensState.id) + step + LENS_IDS.length) % LENS_IDS.length;
  else if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = LENS_IDS.length - 1;
  else return;
  event.preventDefault();
  setLens(LENS_IDS[index]);
  document.querySelector(`#lenses [data-lens="${LENS_IDS[index]}"]`).focus();
});

// ---------- ground lens: layer (wells or cropland), value (depth/cover or change), period from the timeline ----------
const groundPeriod = () => (yearActive && yearValue < GROUND_SWITCH_YEAR ? 'before' : 'after');
/** The timeline readout in this lens names the window shown: no dams or links are drawn here, so app.js's counts would mislead. */
function groundWindowText() {
  const period = groundPeriod();
  if (lensState.groundLayer === 'gw') return gwData ? `May ${gwYears(gwData[period])} wells` : '';
  return cropData ? `cropland ${cropData[period].epoch}` : '';
}
function applyGround() {
  const change = lensState.groundValue === 'change';
  const mode = change ? 'change' : groundPeriod();
  if (lensState.groundLayer === 'gw') { setCropMode('off'); setGwMode(mode); } else { setGwMode('off'); setCropMode(mode); }
  $('year-readout').textContent = groundWindowText();   // after setYear has written its own readout (atlas:year fires last)
  for (const button of $$('[data-ground-layer] button')) button.setAttribute('aria-pressed', String(button.dataset.value === lensState.groundLayer));
  for (const button of $$('[data-ground-value] button')) {
    button.setAttribute('aria-pressed', String(button.dataset.value === lensState.groundValue));
    if (button.dataset.value === 'depth') button.textContent = lensState.groundLayer === 'gw' ? 'Depth' : 'Cover';
  }
  $('gw-legend').hidden = lensState.groundLayer !== 'gw';
  $('crop-legend').hidden = lensState.groundLayer !== 'crop';
}
for (const button of $$('[data-ground-layer] button')) button.addEventListener('click', () => { lensState.groundLayer = button.dataset.value; applyGround(); });
for (const button of $$('[data-ground-value] button')) button.addEventListener('click', () => { lensState.groundValue = button.dataset.value; applyGround(); syncTimeline(); });
document.addEventListener('atlas:year', (event) => {
  if (lensState.id === 'ground' && lensState.groundValue !== 'change') applyGround();
  if (window.Atlas3D) Atlas3D.setYear(event.detail.year);
});

// ---------- drawer: the lens's details, or the Sketch tool panel while that tool is on ----------
const drawer = $('drawer');
function renderDrawer() {
  const tool = lensState.toolPanel;
  for (const panel of $$('.lens-details')) panel.hidden = tool || panel.dataset.lens !== lensState.id;
  $('sketch-card').hidden = !tool;
  $('drawer-title').textContent = tool ? 'Sketch a canal' : LENSES[lensState.id].title;
}
let drawerHideTimer = null;
function openDrawer() {
  clearTimeout(drawerHideTimer);
  lensState.detailsOpen = true;
  drawer.hidden = false;
  void drawer.offsetWidth;                   // laid out closed first, so the slide-in transition runs
  drawer.classList.add('open');
  document.body.classList.add('drawer-open');   // the map tools, the Mapbox controls and the timeline move out from under it
  drawer.inert = false;
  drawer.setAttribute('aria-hidden', 'false');
  for (const button of $$('.details-btn')) button.setAttribute('aria-expanded', 'true');
}
function closeDrawer() {
  if (lensState.toolPanel && document.body.classList.contains('sketch-off')) { lensState.toolPanel = false; renderDrawer(); }   // the "plugin did not load" notice
  const focusInside = drawer.contains(document.activeElement);
  lensState.detailsOpen = false;
  drawer.classList.remove('open');
  document.body.classList.remove('drawer-open');
  drawer.inert = true;
  drawer.setAttribute('aria-hidden', 'true');
  clearTimeout(drawerHideTimer);             // display: none once the slide is over: out of the layout, innerText and the tab order
  drawerHideTimer = setTimeout(() => { if (!lensState.detailsOpen) drawer.hidden = true; }, reducedMotion ? 0 : 400);
  for (const button of $$('.details-btn')) button.setAttribute('aria-expanded', 'false');
  if (focusInside) { const button = document.querySelector(`#lens-${lensState.id} .details-btn`); if (button) button.focus(); }
}
/** Called by app.js's setSketch: the Sketch card takes the drawer while the tool is on, and the drawer goes back to how it was. */
function showToolPanel(on) {
  if (on) {
    if (!lensState.toolPanel) lensState.drawerBefore = lensState.detailsOpen;
    lensState.toolPanel = true;
    renderDrawer();
    openDrawer();
  } else if (lensState.toolPanel) {
    lensState.toolPanel = false;
    renderDrawer();
    if (!lensState.drawerBefore) closeDrawer();
  }
}
for (const button of $$('.details-btn')) button.addEventListener('click', () => {
  if (lensState.detailsOpen) { closeDrawer(); return; }
  openDrawer();
  $('drawer-close').focus();
});
$('drawer-close').addEventListener('click', closeDrawer);

// ---------- phone: the lens panel is a bottom sheet with three heights ----------
const SHEET_STATES = ['peek', 'half', 'full'];
function setSheet(state) {
  lensState.sheet = state;
  $('lens-panel').dataset.sheet = state;
  $('sheet-handle').setAttribute('aria-expanded', String(state !== 'peek'));
}
$('sheet-handle').addEventListener('click', () => setSheet(SHEET_STATES[(SHEET_STATES.indexOf(lensState.sheet) + 1) % SHEET_STATES.length]));

// ---------- settings popover ----------
const settings = $('settings'), settingsButton = $('settings-btn');
function openSettings() {
  settings.hidden = false;
  settingsButton.setAttribute('aria-expanded', 'true');
  settings.style.right = isPhone() ? '' : `${Math.round(window.innerWidth - settingsButton.getBoundingClientRect().right)}px`;   // right-aligned under its button
  const first = [...settings.querySelectorAll('input, button')].find((el) => el.offsetParent !== null);
  if (first) first.focus();
}
function closeSettings(restoreFocus = true) {
  if (settings.hidden) return;
  settings.hidden = true;
  settingsButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) settingsButton.focus();
}
settingsButton.addEventListener('click', () => (settings.hidden ? openSettings() : closeSettings()));
document.addEventListener('click', (event) => {
  if (!settings.hidden && !settings.contains(event.target) && !settingsButton.contains(event.target)) closeSettings(false);
});

// ---------- About & sources: a modal sheet with a focus trap ----------
const about = $('about');
let aboutOpener = null;
function openAbout(opener) {
  closeSettings(false);
  aboutOpener = opener || document.activeElement;
  about.hidden = false;
  $('about-close').focus();
}
function closeAbout() {
  if (about.hidden) return;
  about.hidden = true;
  if (aboutOpener && aboutOpener.focus && aboutOpener.offsetParent !== null) aboutOpener.focus(); else $('about-btn').focus();
  aboutOpener = null;
}
$('about-btn').addEventListener('click', () => openAbout($('about-btn')));
for (const button of $$('[data-open-about]')) button.addEventListener('click', () => openAbout(settingsButton));
$('about-close').addEventListener('click', closeAbout);
about.addEventListener('keydown', (event) => {
  if (event.key !== 'Tab') return;
  const focusable = [...about.querySelectorAll('button, a[href], input, [tabindex]:not([tabindex="-1"])')].filter((el) => el.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (!about.hidden) closeAbout();
  else if (!settings.hidden) closeSettings();
  else if (lensState.detailsOpen) closeDrawer();
});

// ---------- timeline ----------
/** The 2014 mark sits where the slider's thumb would be for 2014 (the thumb is about 16 px wide). */
function positionYearMark() {
  const input = $('year');
  const min = Number(input.min), max = Number(input.max);
  const fraction = Math.min(1, Math.max(0, (2014 - min) / Math.max(1, max - min)));
  $('year-2014').style.left = `calc(8px + (100% - 16px) * ${fraction.toFixed(4)})`;
}
positionYearMark();
$('year-2014').addEventListener('click', () => setYear(2014));
$('year-now').addEventListener('click', () => setYear(YEAR_MAX, false));

// ---------- map tools ----------
$('reset').addEventListener('click', () => flyToLens(lensState.id));

// ---------- headline numbers and card placeholders, from the loaded data ----------
const summaryFiles = Promise.all([
  fetch('data/canals_summary.json').then((r) => (r.ok ? r.json() : null)).catch(() => null),
  fetch('data/pumphouses.json').then((r) => (r.ok ? r.json() : null)).catch(() => null),
]);
const round10 = (value) => Math.round(value / 10) * 10;
/** Writes a headline value; `small` is a second line (a name) and null hides the whole number. */
function setHeadline(id, text, small) {
  const dd = $(id);
  if (!dd) return;
  const box = dd.closest('.hl');
  if (text === null || text === undefined) { box.hidden = true; return; }
  box.hidden = false;
  dd.textContent = text;
  if (small) dd.appendChild(textEl('small', '', small));
}
function fillPlaceholder(name, text) { for (const span of $$(`[data-fill="${name}"]`)) span.textContent = text; }
function fillHeadlines(canalSummary, pumphouses) {
  const cities = citiesData || [];
  const hyderabad = cities.find((c) => c.name === 'Hyderabad');
  const highest = cities.length ? cities.reduce((a, b) => (b.elev > a.elev ? b : a)) : null;
  setHeadline('hl-height-1', hyderabad ? `${hyderabad.elev} m` : null);
  setHeadline('hl-height-2', highest ? `${highest.elev} m` : null, highest && highest.name);
  let lowest = null;
  for (const [river, profile] of Object.entries(profileState.profiles || {})) {
    for (const point of profile.points) if (!lowest || point.elev < lowest.elev) lowest = { river, elev: point.elev };
  }
  setHeadline('hl-height-3', lowest ? `${lowest.elev} m` : null, lowest && lowest.river);
  if (lowest) { fillPlaceholder('lowBed', String(lowest.elev)); fillPlaceholder('lowRiver', lowest.river); }
  if (highest) { fillPlaceholder('highTown', String(highest.elev)); fillPlaceholder('highTownName', highest.name); }

  const dam = (name) => damsData.find((d) => d.name === name);
  const top = dam('Konda Pochamma Sagar'), bottom = dam('Medigadda Barrage');
  setHeadline('hl-rivers-1', top && bottom && top.elev_m && bottom.elev_m ? `≈ ${round10(top.elev_m - bottom.elev_m)} m` : null);
  const working = pumphouses ? pumphouses.filter((h) => h.kind === 'pump' && h.status === 'operational').length : null;
  setHeadline('hl-rivers-2', working === null ? null : String(working));
  const godavari = flowSummaryData && flowSummaryData.peaks && flowSummaryData.peaks.Godavari;
  setHeadline('hl-rivers-3', godavari ? `${Math.round(godavari.q).toLocaleString('en-IN')} m³/s` : null);

  const osm = canalSummary && canalSummary.osm_km;
  const dug = osm ? (osm.after_canal || 0) + (osm.after_tunnel || 0) + (osm.after_main || 0) : null;
  setHeadline('hl-since2014-1', dug === null ? null : `${Math.round(dug).toLocaleString('en-IN')} km`);
  setHeadline('hl-since2014-2', tankSummary ? tankSummary.mission_kakatiya.taken_up.toLocaleString('en-IN') : null);
  const state = gwData && gwData.state;
  const windows = gwData ? `May ${gwYears(gwData.before)} → May ${gwYears(gwData.after)}` : '';
  setHeadline('hl-since2014-3', state ? changeWords(state.change) : null);
  if (gwData) { $('hl-since2014-3-label').textContent = `Water table, median change, ${windows} means`; $('hl-ground-1-label').textContent = `Water table, median change, ${windows}`; }
  setHeadline('hl-ground-1', state ? signedMetres(state.change) : null);
  setHeadline('hl-ground-2', state && state.wells_both ? `${Math.round((100 * state.rising) / state.wells_both)} %` : null);
  const crop = cropData && cropData.state;
  setHeadline('hl-ground-3', crop ? `${crop[String(cropData.before.year)].pct} % → ${crop[String(cropData.after.year)].pct} %` : null);
  if (proposalData && proposalData.norms) fillPlaceholder('targetPct', String(Math.round(100 * proposalData.norms.target_share)));
}
/** District shading of the Since 2014 lens: the map's own tank ramp, light (few) to dark (many tanks taken up). */
function renderKakatiyaRamp() {
  const [low, high] = MAP_THEMES[currentTheme()].tankRamp;
  $('mk-ramp').style.background = `linear-gradient(90deg, ${low}, ${high})`;
}
renderKakatiyaRamp();
new MutationObserver(renderKakatiyaRamp).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderKakatiyaRamp);
document.addEventListener('atlas:data', async () => {
  positionYearMark();                        // setupYears has set the slider's minimum by now
  const [canalSummary, pumphouses] = await summaryFiles;
  fillHeadlines(canalSummary, pumphouses);
  if (lensState.id === 'ground') applyGround();   // the legends exist only once the data is in
});

setLens('height', { fly: false });           // the intro flight from app.js frames the view

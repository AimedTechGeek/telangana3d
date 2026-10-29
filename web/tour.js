'use strict';
// "Follow the water" tour: seven stops up the Kaleshwaram lift chain, a caption per stop and a climb profile.
// Uses the app's globals (map, damsData, linksData, pumphousesData, setLens) when present and fetches what is missing.
(function () {
  const STOPS = ['Medigadda Barrage', 'Saraswati Barrage', 'Parvati Barrage', 'Sripada Yellampalli Project', 'Mid Manair Dam', 'Mallanna Sagar', 'Konda Pochamma Sagar'];
  const FLY_MS = 4000, DWELL_MS = 7000, ZOOM = 12.5, PITCH = 62;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  let running = false, playing = false, index = 0, stops = [], links = [], houses = [], panel = null, timer = null, starting = false;
  const listeners = [];                                   // [target, type, handler, options] removed on stop

  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const svgEl = (tag, attrs) => { const node = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v); return node; };
  const listen = (target, type, handler, options) => { target.addEventListener(type, handler, options); listeners.push([target, type, handler, options]); };
  const fetchJson = async (url) => { const response = await fetch(url); if (!response.ok) throw new Error(`${url}: ${response.status}`); return response.json(); };

  /** Initial compass bearing in degrees from one point to another. */
  function bearingTo(from, to) {
    const rad = Math.PI / 180, dLon = (to.lon - from.lon) * rad;
    const y = Math.sin(dLon) * Math.cos(to.lat * rad);
    const x = Math.cos(from.lat * rad) * Math.sin(to.lat * rad) - Math.sin(from.lat * rad) * Math.cos(to.lat * rad) * Math.cos(dLon);
    return (Math.atan2(y, x) / rad + 360) % 360;
  }
  const bearingAt = (i) => (i < stops.length - 1 ? bearingTo(stops[i], stops[i + 1]) : bearingTo(stops[i - 1], stops[i]));
  const climbM = () => Math.round((stops[stops.length - 1].elev_m - stops[0].elev_m) / 10) * 10;

  async function loadData() {
    const dams = typeof damsData !== 'undefined' && damsData.length ? damsData : await fetchJson('data/dams.json');
    const linkCollection = typeof linksData !== 'undefined' && linksData && linksData.features ? linksData : await fetchJson('data/links.geojson');
    links = linkCollection.features.map((f) => f.properties);
    houses = typeof pumphousesData !== 'undefined' && pumphousesData.length ? pumphousesData : await fetchJson('data/pumphouses.json');
    stops = STOPS.map((name) => dams.find((d) => d.name === name)).filter(Boolean);
    if (stops.length < 2) throw new Error('tour stops missing from dams.json');
  }

  const megawatts = (house) => { const m = house && house.power ? /([\d.]+)\s*MW/i.exec(house.power) : null; return m ? Number(m[1]) : null; };
  function linkText(i) {
    if (i === 0) return 'Water is taken from the Godavari here: the first of the lifts.';
    const link = links.find((p) => p.from === stops[i - 1].name && p.to === stops[i].name && p.kind === 'lift')
      || links.find((p) => p.from === stops[i - 1].name && p.to === stops[i].name);
    if (!link) return '';
    const house = link.via ? houses.find((h) => h.osm_name === link.via || h.name === link.via) : null;
    const mw = megawatts(house);
    let text = `${link.link}: lifted ${link.lift_m} m from ${link.from}`;
    if (link.via) text += ` through ${link.via}${mw ? ` (${mw} MW)` : ''}`;
    else if (link.note) text += `. ${link.note}`;
    return text;
  }
  function factsText(dam) {
    const parts = [`terrain ${dam.elev_m} m`];
    if (dam.capacity_tmcft) parts.push(`${dam.capacity_tmcft} TMC capacity`);
    if (dam.opened) parts.push(`opened ${dam.opened}`); else if (dam.began) parts.push(`construction began ${dam.began}`);
    return parts.join(' · ');
  }

  // ---------- the climb profile ----------
  const W = 400, H = 118, X0 = 34, X1 = W - 34, Y_BASE = 96, Y_SPAN = 74;
  function drawProfile(svg) {
    svg.textContent = '';
    const top = Math.max(...stops.map((s) => s.elev_m));
    const x = (i) => X0 + (X1 - X0) * i / (stops.length - 1);
    const y = (elev) => Y_BASE - Y_SPAN * elev / top;
    const last = index === stops.length - 1;
    const points = stops.map((s, i) => `${x(i).toFixed(1)},${y(s.elev_m).toFixed(1)}`);
    svg.append(svgEl('polygon', { class: 'tour-area', points: `${x(0)},${Y_BASE} ${points.join(' ')} ${x(stops.length - 1)},${Y_BASE}` }));
    svg.append(svgEl('polyline', { class: 'tour-line', points: points.join(' '), fill: 'none' }));
    svg.append(svgEl('line', { class: 'tour-base', x1: 4, x2: W - 4, y1: y(stops[0].elev_m), y2: y(stops[0].elev_m) }));
    if (last) {
      const topY = y(stops[stops.length - 1].elev_m), baseY = y(stops[0].elev_m), gx = W - 14;
      svg.append(svgEl('line', { class: 'tour-base', x1: 4, x2: W - 4, y1: topY, y2: topY }));
      svg.append(svgEl('line', { class: 'tour-climb-line', x1: gx, x2: gx, y1: topY, y2: baseY }));
      svg.append(svgEl('path', { class: 'tour-climb-arrow', d: `M${gx - 4},${topY + 7} L${gx},${topY} L${gx + 4},${topY + 7} M${gx - 4},${baseY - 7} L${gx},${baseY} L${gx + 4},${baseY - 7}` }));
      const label = svgEl('text', { class: 'tour-climb-label', x: gx - 8, y: (topY + baseY) / 2 + 4, 'text-anchor': 'end' });
      label.textContent = `about ${climbM()} m`;
      svg.append(label);
    }
    stops.forEach((s, i) => {
      const current = i === index;
      const dot = svgEl('circle', { class: `tour-dot${current ? ' current' : ''}`, cx: x(i), cy: y(s.elev_m), r: current ? 6 : 4 });
      const title = svgEl('title'); title.textContent = `${s.name}, terrain ${s.elev_m} m`; dot.append(title);
      dot.addEventListener('click', () => goTo(i));
      svg.append(dot);
      const elev = svgEl('text', { class: `tour-elev${current ? ' current' : ''}`, x: x(i), y: y(s.elev_m) - (current ? 11 : 9), 'text-anchor': 'middle' });
      elev.textContent = `${s.elev_m}`;
      const num = svgEl('text', { class: 'tour-num', x: x(i), y: H - 6, 'text-anchor': 'middle' });
      num.textContent = String(i + 1);
      svg.append(elev, num);
    });
  }

  // ---------- panel ----------
  function buildPanel() {
    panel = el('aside', 'tour-panel');
    panel.id = 'tour-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Follow the water tour');
    const caption = el('div', 'tour-caption');
    caption.setAttribute('aria-live', 'polite');
    caption.append(el('div', 'tour-step'), el('h3', 'tour-name'), el('p', 'tour-facts'), el('p', 'tour-link'), el('p', 'tour-climb'), el('p', 'tour-source'));
    const svg = svgEl('svg', { class: 'tour-profile', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Climb profile: terrain height at the seven stops' });
    const controls = el('div', 'tour-controls');
    const button = (cls, text, handler) => { const b = el('button', `tour-btn ${cls}`, text); b.type = 'button'; b.addEventListener('click', handler); return b; };
    controls.append(button('tour-prev', 'Prev', () => goTo(index - 1)), button('tour-play', 'Pause', togglePlay),
                    button('tour-next', 'Next', () => goTo(index + 1)), button('tour-close', 'Close', stop));
    panel.append(caption, svg, controls);
    document.body.append(panel);
  }
  const part = (cls) => panel.querySelector(`.${cls}`);
  function render() {
    const dam = stops[index], last = index === stops.length - 1;
    part('tour-step').textContent = `Follow the water · stop ${index + 1} of ${stops.length}`;
    part('tour-name').textContent = dam.name;
    part('tour-facts').textContent = factsText(dam);
    part('tour-link').textContent = linkText(index);
    part('tour-link').hidden = !part('tour-link').textContent;
    part('tour-climb').textContent = last ? `Water lifted about ${climbM()} m — terrain at the structures, not the pumped head` : '';
    part('tour-climb').hidden = !last;
    const source = part('tour-source');
    source.textContent = '';
    if (dam.url && /^https:\/\//.test(dam.url)) {
      const a = el('a', '', `Source: ${new URL(dam.url).hostname.replace(/^en\./, '').replace(/\.org$/, '')}`);
      a.href = dam.url; a.target = '_blank'; a.rel = 'noopener';
      source.append(a);
    }
    part('tour-prev').disabled = index === 0;
    part('tour-next').disabled = last;
    part('tour-play').textContent = playing ? 'Pause' : 'Play';
    drawProfile(panel.querySelector('.tour-profile'));
  }

  // ---------- motion ----------
  function clearTimer() { if (timer) { clearTimeout(timer); timer = null; } }
  function schedule() {
    clearTimer();
    if (!playing || index >= stops.length - 1) { if (index >= stops.length - 1) playing = false; return; }
    timer = setTimeout(() => goTo(index + 1), (reduced ? 0 : FLY_MS) + DWELL_MS);   // the dwell counts from arrival
  }
  function goTo(i) {
    if (!running || i < 0 || i >= stops.length) return;
    index = i;
    const dam = stops[i];
    const camera = { center: [dam.lon, dam.lat], zoom: ZOOM, pitch: PITCH, bearing: bearingAt(i) };
    map.stop();
    if (reduced) map.jumpTo(camera); else map.flyTo({ ...camera, duration: FLY_MS, essential: true });
    schedule();
    render();
  }
  function pause() { if (!playing) return; playing = false; clearTimer(); if (panel) part('tour-play').textContent = 'Play'; }
  function togglePlay() {
    if (playing) { pause(); return; }
    playing = true;
    if (index >= stops.length - 1) index = 0;
    goTo(index);                                           // Play on the last stop restarts from the first
  }

  async function start() {
    if (running || starting) return;
    starting = true;
    try {
      if (typeof map === 'undefined') throw new Error('map is not ready');
      await loadData();
    } catch (error) {
      starting = false;
      console.warn('Tour not started:', error.message);
      return;
    }
    starting = false;
    running = true; playing = true;
    if (typeof setLens === 'function') setLens('rivers', { fly: false, fromTour: true });
    buildPanel();
    const container = map.getCanvasContainer();
    // The user taking the camera ends autoplay (the panel stays, Play resumes).
    map.on('dragstart', pause);
    listeners.push([map, 'dragstart', pause, null]);
    listen(container, 'wheel', pause, { passive: true });
    listen(container, 'touchstart', pause, { passive: true });
    listen(document, 'keydown', (event) => { if (event.key === 'Escape') stop(); });
    goTo(0);
  }
  function stop() {
    if (!running) return;
    running = false; playing = false;
    clearTimer();
    for (const [target, type, handler, options] of listeners.splice(0)) {
      if (target === map) map.off(type, handler); else target.removeEventListener(type, handler, options);
    }
    if (panel) { panel.remove(); panel = null; }
  }

  window.AtlasTour = { start, stop, isRunning: () => running };
  const bind = () => { const button = document.getElementById('tour-start'); if (button) button.addEventListener('click', start); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind); else bind();
})();

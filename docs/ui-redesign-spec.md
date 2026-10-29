# Telangana atlas UI redesign: spec (branch `ui-redesign`)

Status: planning spec, 30 October 2026. Base commit `c056332` (branch `ui-redesign`).
Inputs: the product-owner brief (`redesign_brief.md`, scratchpad of the planning session), the five advisor
reports (product owner, visual designer, IA/simplicity, cartographer, Mapbox engineer) and the code on this branch.
Where the advisors and the brief disagree, the brief wins (bubbles stay, no place search, five lenses, no "Explore" mode).

Line numbers below refer to `web/app.js` at `c056332` and are hints only; function names are the contract.

---

## 0. Ground rules for every package

| Rule | Detail |
|---|---|
| Free services only | Mapbox GL JS map loads, Standard / Standard Satellite, Terrain-DEM, our hosted tilesets and uploaded fonts. No Search/Geocoding, Static Images or Directions. three.js from jsDelivr (free). |
| Honesty | Every caveat that exists today keeps a home (section 7). Nothing new is presented as surveyed fact: 3D shapes are generic stand-ins and say so. |
| Ownership | A package edits only what section 10 gives it. Whoever deletes a DOM element also deletes the JS that binds that element **in its own region**; a function that another package's region calls is not deleted, only its call sites are removed by their owner (dead definitions are removed post-merge, package E). |
| Cross-package calls | Calls into another package's new function are guarded (`typeof setThematic === 'function'`, `window.Atlas3D && ...`, `window.AtlasTour && ...`) so each worktree runs on its own before the merge. |
| Worktree setup | `web/data/` and `web/mapbox-token.js` are git-ignored. In a new worktree: copy `C:\LocalData\3DViews\web\data` to `<worktree>\web\data`, then delete the `"flow_particles"` key from the copy's `web/data/tilesets.json` (the particle feature is being removed; this makes its code path dead in every worktree). `serve.py` writes `mapbox-token.js` from the `MAPBOX_TOKEN` environment variable. Run tests with your package's own `ATLAS_PORT` (A 8771, B 8772, C 8773, D 8774). |
| Checks | `node --check web/<file>.js` for every JS file touched; `uv run python web_smoke_test.py` and `uv run python web_sketch_test.py` must pass in the worktree. Screenshots go to `out/` (git-ignored) and must be looked at, not only written. Viewports: desktop 1600x1000, phone 390x844. |
| Conventions | Classic scripts, `'use strict'`, `$()` helper, `textEl()`/`bold()` DOM builders, no framework, no build step. Comments explain why, as in app.js. |

---

## 1. Target layout

### 1.1 DOM (index.html, top to bottom)

```
<body>
  <div id="map" role="application" aria-label="3D terrain map of Telangana"></div>

  <header id="topbar" class="topbar">
    <div class="brand">
      <h1 class="title">Telangana relief &amp; water atlas</h1>
      <p class="subtitle">How Telangana moves river water uphill: heights, lifts and what changed since 2014</p>
    </div>
    <div class="seg scene" role="group" aria-label="Scene">            <!-- desktop only (hidden <= 900 px) -->
      <button type="button" data-scene="map" aria-pressed="true">Map</button>
      <button type="button" data-scene="satellite" aria-pressed="false">Satellite</button>
      <button type="button" data-scene="night" aria-pressed="false">Night</button>
    </div>
    <button id="theme" class="icon-btn" ...>(sun/moon svgs as today)</button>
    <button id="settings-btn" class="icon-btn" aria-haspopup="dialog" aria-expanded="false" aria-controls="settings">(gear svg)</button>
    <button id="about-btn" class="text-btn" aria-haspopup="dialog" aria-controls="about">About &amp; sources</button>
  </header>

  <aside id="lens-panel" class="lens-panel" data-sheet="peek" aria-label="Story">
    <button id="sheet-handle" class="sheet-handle" type="button" aria-expanded="false" aria-controls="lens-panel">(phone only)</button>
    <nav id="lenses" class="lenses" role="tablist" aria-label="Story">
      <button role="tab" type="button" data-lens="height"   aria-selected="true">Height</button>
      <button role="tab" type="button" data-lens="rivers"   aria-selected="false">Rivers &amp; lifts</button>
      <button role="tab" type="button" data-lens="since2014" aria-selected="false">Since 2014</button>
      <button role="tab" type="button" data-lens="ground"   aria-selected="false">Groundwater &amp; crops</button>
      <button role="tab" type="button" data-lens="proposal" aria-selected="false">Proposal</button>
    </nav>
    <section id="lens-height" class="lens-card" data-lens="height" role="tabpanel"> ... </section>
    <section id="lens-rivers" class="lens-card" data-lens="rivers" role="tabpanel" hidden> ... </section>
    <section id="lens-since2014" ... hidden> ... </section>
    <section id="lens-ground" ... hidden> ... </section>
    <section id="lens-proposal" ... hidden> ... </section>
  </aside>

  <aside id="drawer" class="drawer" aria-label="Details" aria-hidden="true">   <!-- closed by default -->
    <header class="drawer-head"><h2 id="drawer-title">Details</h2><button id="drawer-close" class="icon-btn" aria-label="Close details">x</button></header>
    <div id="details-height"   class="lens-details" data-lens="height"> ... </div>
    <div id="details-rivers"   class="lens-details" data-lens="rivers" hidden> ... </div>
    <div id="details-since2014" class="lens-details" data-lens="since2014" hidden> ... </div>
    <div id="details-ground"   class="lens-details" data-lens="ground" hidden> ... </div>
    <div id="details-proposal" class="lens-details" data-lens="proposal" hidden> ... </div>
    <section id="sketch-card" class="tool-panel"> (today's Sketch card body, same inner ids) </section>
  </aside>

  <div id="timeline" class="timeline" role="group" aria-label="Years" hidden> ... (section 4) </div>

  <div id="map-tools" class="map-tools" role="toolbar" aria-label="Map tools">
    <button id="view-toggle" class="chip tool" type="button" aria-pressed="true" title="Tilted 3D view or straight down">3D</button>
    <button class="chip tool" type="button" data-toggle="orbit" aria-pressed="false">Orbit</button>
    <button class="chip tool" type="button" data-toggle="sketch" aria-pressed="false" title="...">Sketch</button>
    <button id="reset" class="chip tool" type="button">Reset</button>
  </div>

  <div id="readout" class="readout" aria-live="polite" hidden>     <!-- tap/click elevation; no placeholder -->
    <div class="hero"><span id="cursor-elev"></span><span class="unit">m above sea level</span></div>
    <p class="coords" id="cursor-pos"></p>
    <p class="compare" id="cursor-compare" hidden><span class="lm-row" id="lm-row"></span><span class="lm-text" id="lm-text"></span></p>
    <button id="readout-close" class="icon-btn" aria-label="Close">x</button>
  </div>

  <div id="plan-badge" class="plan-badge" hidden>Planning sketch, not a design</div>

  <div id="settings" class="popover" role="dialog" aria-label="Settings" hidden> ... (section 5) </div>
  <div id="about" class="sheet" role="dialog" aria-modal="true" aria-labelledby="about-title" hidden> ... (section 6) </div>

  <div id="toast" class="toast" role="status">Loading terrain…</div>
  (landmark and icon <symbol> sprite exactly as today)
  <pre id="debug" hidden></pre>
  <script src="mapbox-token.js"></script>
  <script src="app.js"></script>
  <script src="ui.js"></script>
  <script src="tour.js"></script>
  <script type="module" src="three3d.js"></script>
</body>
```
and in `<head>`, after `style.css`: `<link rel="stylesheet" href="tour.css">`.

Every lens card has this inner structure (class names fixed):

```
<section id="lens-<id>" class="lens-card" data-lens="<id>">
  <h2 class="lens-title">…</h2>
  <p class="lens-text">… (<= 80 words, section 3.4) …</p>
  <dl class="headline">                       <!-- 1-3 numbers -->
    <div class="hl"><dt>…label…</dt><dd id="hl-<id>-1">…</dd></div> …
  </dl>
  <div class="lens-controls">…lens-specific chips/segments…</div>
  <div class="lens-legend">…own legend…</div>
  <p class="lens-caveat">…one visible caveat line…</p>
  <p class="lens-source">Source: …</p>
  <button class="details-btn" type="button" aria-expanded="false" aria-controls="drawer">Details</button>
</section>
```

### 1.2 Where today's content goes

| Today (id or block) | New home |
|---|---|
| `.head-card` title, eyebrow | `#topbar .brand` |
| `#cursor-elev`, `#cursor-pos`, `#cursor-compare`, `#lm-row`, `#lm-text` | `#readout` (same ids) |
| `#ramp`, `#ramp-ticks` (elevation legend) | `#lens-height .lens-legend` (same ids) |
| Sketch card `#sketch-card` and all `#sketch-*` ids | `#drawer > section#sketch-card.tool-panel` |
| Rivers card: `#flow-legend` | `#lens-rivers .lens-legend` |
| Rivers card: `#flow-motion`, `#peaks`, `#district-flow`, river tabs (`[data-river]`), `#river-summary`, `#fly`, `.chip[data-toggle="bed"]`, `#profile`, `#profile-tip`, `#flow-profile`, `#scrub`, `#profile-table` | `#details-rivers` |
| Water works: dam legend, `#link-list`, `#canal-network`, `#pending-list`, `#pending-count` | `#details-rivers` (dam/barrage icon key moves to the rivers legend) |
| Proposal card: `#prop-count`, `#prop-summary`, `#prop-envelopes`, `#prop-envelope-note`, `#prop-systems`, `#prop-systems-count`, `#prop-works`, `#prop-works-count`, `#prop-districts`, `#prop-caveats`, `#prop-norms` | `#details-proposal`, wrapper keeps `id="proposal-card"` |
| Tanks card: `#tank-count`, `#tank-summary`, `#mk-summary`, `#mk-phases`, `#tank-table` | `#details-since2014`, wrapper keeps `id="tank-card"` |
| Groundwater card: `#gw-count`, `#gw-summary`, `#gw-legend`, `#gw-chart`, `#gw-chart-hint`, `#gw-table`, `#gw-before-years`, `#gw-after-years` | `#details-ground`, wrapper keeps `id="gw-card"`; `#gw-legend` moves to `#lens-ground .lens-legend` |
| Cropland aside: `#crop-mode-label`, `#crop-summary`, `#crop-blend-row`, `#crop-blend`, `#crop-blend-out`, `#crop-legend`, `#crop-official`, `#crop-csv`, `#crop-table` | `#details-ground` (`#crop-legend` to `#lens-ground .lens-legend`) |
| Cities card `#city-list` | `#details-height` |
| Terrain card: `#exag`, `#exag-out`, bands/contours chips | `#settings` |
| Layers card: districts, labels, flow chips | `#settings` |
| Layers card: dams, links chips | `#lens-rivers .lens-controls` (and `#lens-since2014`, sharing state) |
| Layers card: canal, tank, gw, crop, proposal segments | replaced by lens defaults and lens controls (section 3) |
| Filters card: Years slider `#year`, `#year-out`, `#year-play`, `#year-readout` | `#timeline` (same ids) |
| Navigation card: Orbit, Sketch, Reset | `#map-tools` |
| `.credits` footer | `#about` (last section) |
| Every hint paragraph | its caveat line, its legend, or `#about` (section 7) |

Overlay control groups keep a `data-group` attribute so the data-missing fallbacks can hide them:
`data-group="canal"`, `"tank"`, `"gw"`, `"crop"`, `"proposal"` on every element that only makes sense with that dataset.

### 1.3 Deleted controls

| Control | Selector today | Replaced by |
|---|---|---|
| Panel collapse / expand | `#collapse`, `#expand`, `#filters-collapse`, `#filters-expand`, both `.sheet-handle` | drawer close, `#sheet-handle` |
| Two columns | `#panel`, `#right-stack`, `#filters`, `#crop-card` aside, `#crop-close` | lens panel + drawer |
| Basemap tabs | `[data-base]` | `[data-scene]` |
| Light presets Theme/Dawn/Day/Dusk/Night | `[data-light]` | Scene "Night" |
| Relief colours chip | `[data-toggle="relief"]` | Satellite scene turns relief off |
| Hillshade chip | `[data-toggle="hillshade"]` | always on |
| River particles chip | `[data-toggle="particles"]` | deleted feature |
| Left-drag Pans/Rotates | `[data-drag]`, `.drag-mode` | right-drag/Ctrl-drag (tooltip on `#map-tools`) |
| Top-down / 3D chips | `#view-2d`, `#view-3d` | `#view-toggle` |
| Dam era filter | `[data-era]` | timeline + 2014 bookmark |
| Works status filter | `[data-status]` | `data-toggle="pending"` chip ("Planned & under construction") in rivers/since2014 lens controls; status still shown by line style |
| All years | `#year-reset` | `#year-now` |
| Open-by-default cards | every `details.card[open]` | closed drawer |

### 1.4 Breakpoints and geometry

| Width | Layout |
|---|---|
| >= 901 px (desktop) | `#topbar` fixed top, 56 px, full width, glass (`--panel`). `#lens-panel` fixed left 16 px, top 68 px, width 344 px, max-height `calc(100dvh - 68px - 88px)`, scrolls inside. `#drawer` fixed right 16 px, top 68 px, bottom 16 px, width 380 px, `transform: translateX(calc(100% + 24px))` when closed, `.open` slides in. `#timeline` fixed bottom 16 px, centred between the lens panel and the right edge, width `min(720px, 100vw - 344px - 96px)`, height 56 px. `#map-tools` fixed right 16 px, bottom 150 px (above the Mapbox navigation control), vertical stack. `#readout` fixed bottom 88 px, left 376 px (beside the lens panel). `#plan-badge` fixed top 68 px, centred. `#settings` anchored under `#settings-btn` (right aligned, width 300 px). `#about` right sheet, width 560 px, full height, scrolls. |
| <= 900 px (phone/tablet) | `#topbar` 48 px: `.title` only (shortened by CSS to one line, `.subtitle` and `.seg.scene` and `#about-btn` hidden; scene and About are inside `#settings`). `#lens-panel` becomes the single bottom sheet: `data-sheet="peek"` 132 px (handle + horizontally scrolling `#lenses` + `.headline` row), `"half"` 55dvh (+ text, controls, legend, caveat), `"full"` 92dvh. `#sheet-handle` cycles peek -> half -> full -> peek. "Details" opens `#drawer` as a full-screen sheet over everything (close button returns to the lens sheet). `#timeline` sits above the sheet (bottom = sheet height + 8 px), full width minus 16 px gutters, no readout text. `#map-tools` right 10 px, above the timeline. Mapbox bottom controls get `margin-bottom` equal to the sheet peek. |
| <= 480 px | headline numbers 2 per row; lens chips 13 px; nothing else changes. |
| All | Touch targets >= 40 px under 900 px; no text below 12 px under 900 px; 16 px side gutter; no horizontal page scroll; `prefers-reduced-motion` drops transitions. |

### 1.5 CSS class names (fixed, new)

`topbar brand title subtitle seg scene text-btn lens-panel lenses lens-card lens-title lens-text headline hl lens-controls lens-legend lens-caveat lens-source details-btn drawer drawer-head lens-details tool-panel timeline tl-play tl-track tl-mark tl-now tl-readout map-tools tool readout plan-badge popover sheet about-section works-key`.
Kept from today: `chip icon-btn tabs hint summary eyebrow section-head legend-inline official crop-table link-list dam-popup flow-popup toast`.

### 1.6 CSS colour tokens (style.css `:root`, both dark blocks)

Changed values (everything else unchanged):

| Token | Light | Dark |
|---|---|---|
| `--river` | `#1f6fc4` | `#4aa8e8` |
| `--link` | `#c2410c` | `#fb923c` |
| `--canal` | `#c2410c` | `#fb923c` |
| `--canal-main` (new) | `#9a3412` | `#fdba74` |
| `--tank` | `#5aa6e0` | `#3f8fd0` |
| `--tank-edge` | `#1f6fc4` | `#9fd0ff` |
| `--prop` | `#0f766e` | `#2dd4bf` |
| `--prop-pool` | `#2dd4bf` | `#2dd4bf` |
| `--prop-pump` | `#115e59` | `#99f6e4` |
| `--prop-trunk` | `#0d9488` | `#5eead4` |
| `--plan` (new, badge) | `#b91c1c` | `#f87171` |

---

## 2. State and functions that cross package lines

| Name | Owner | Contract |
|---|---|---|
| `chipOn(name)` (app.js ~504) | A | Returns `'visible'`/`'none'` from the chip `.chip[data-toggle=name]` when it exists, else from `TOGGLE_DEFAULTS = { relief: true, hillshade: true, contours: true, bands: false, districts: true, labels: true, flow: true, dams: true, links: true, bed: false, particles: false, models3d: true, pending: true, orbit: false, sketch: false }`. Never throws for a missing chip. |
| `setScene(id)` (`'map'`/`'satellite'`/`'night'`) | B | Replaces `setLightMode` and `setBasemap`. B binds `[data-scene]` buttons (all copies) and keeps their `aria-pressed` in sync. |
| `setThematic(on)` | B | Mutes relief to grey hillshade (section 8.5). Called by `setLens`. |
| `exaggerationFactorAt(zoom)`, `terrainExaggeration()`, `terrainRise`, `riseTerrain()` | B keeps them | C reads them through `exaggerationNow()`. |
| `setLens(id, opts)`, `lensState` | A (ui.js) | Section 3. |
| `setYear(value, active)`, `yearActive`, `yearValue`, `YEAR_MAX`, `stopYearPlay()` | A | Semantics unchanged; dispatches `document` event `atlas:year` with `detail: { year: yearActive ? yearValue : null }`. |
| `setStatusMode('all'|'built')` | A | Driven by the `pending` chip (on = `'all'`). The `'pending'` mode is no longer reachable from the UI. |
| `setProposalMode('on'|'off')` | D | Same signature; on first `'on'` it lazy-loads `proposal.geojson` through `ensureProposal()`; also calls `Atlas3D.setVisible('proposal', on)`. |
| `ensureProposal()` | D | Memoised promise resolving `{ data: proposalData, geo: proposalGeo }` after source, layers, markers and label layers exist; calls `Atlas3D.setData('proposal', { data, geo })`. |
| `flyToWork(lon, lat)` | D | Section 9.2. |
| `window.Atlas3D` | C | Section 8.7. |
| `window.AtlasTour` | D | `{ start(), stop(), isRunning() }`, section 9.1. |
| `document` event `atlas:data` | A adds the one dispatch line in the load handler after `debug.phase = 'data-loaded'` | ui.js fills headline numbers on it. |
| `document` event `atlas:lens` | A | `detail: { id }`, after every `setLens`. |

---

## 3. Lens model

### 3.1 State (ui.js)

```js
const lensState = { id: 'height', detailsOpen: false, sheet: 'peek', groundLayer: 'gw', groundValue: 'change' };
const LENSES = { height: {...}, rivers: {...}, since2014: {...}, ground: {...}, proposal: {...} };   // table 3.2
```

### 3.2 What each lens turns on and off

| | height | rivers | since2014 | ground | proposal |
|---|---|---|---|---|---|
| `canalMode` | off | after | after | off | off |
| chips `dams` / `links` | on / off | on / on | on / on | off / off | on / off |
| `tankMode` | off | tanks (dots z7+) | kakatiya | off | off |
| `gwMode` | off | off | off | from `groundLayer`/`groundValue` + timeline | off |
| `cropMode` | off | off | off | from `groundLayer`/`groundValue` + timeline | off |
| `proposalMode` | off | off | off | off | on |
| `setThematic` | false | false | true | true | true |
| flow animation | as the Settings chip | same | same | same | same |
| 3D groups (`Atlas3D.setVisible`) | dams, reservoirs | dams, reservoirs, pumps, conduits | dams, reservoirs, pumps, conduits | none | proposal, dams, reservoirs |
| `#timeline` | hidden, `setYear(YEAR_MAX,false)` | visible, Now | visible, `setYear(2014)` on entry | visible only when `groundValue !== 'change'` | hidden, `setYear(YEAR_MAX,false)` |
| `#plan-badge` | hidden | hidden | hidden | hidden | visible |

The `pending` chip and the `dams`/`links` chips are shared state: a chip pressed in one lens stays as pressed in the others until a lens entry sets it (the table is applied on every lens entry).

Ground lens controls: `<div class="tabs" data-ground-layer>` Groundwater / Cropland, and `<div class="tabs" data-ground-value>` Depth (or Cover) / Change. With Depth/Cover the timeline drives the period: year `< 2015` -> `'before'`, otherwise `'after'` (the `atlas:year` handler calls `setGwMode`/`setCropMode`). With Change: `setGwMode('change')` or `setCropMode('change')`, timeline hidden.

### 3.3 `setLens(id, { fly = true } = {})`

1. Ignore unknown ids; when `id === lensState.id` only re-apply layers (no camera move).
2. Stop camera animations: `stopFlight()`, the orbit chip off, `window.AtlasTour && AtlasTour.stop()` unless the tour itself called `setLens`.
3. Tabs: `aria-selected`, show `#lens-<id>`, hide the others; drawer shows `#details-<id>` (unless the sketch tool panel is active); `#drawer-title` = lens title.
4. Apply table 3.2 through the existing functions: `setCanalMode`, `setTankMode`, `setGwMode`, `setCropMode`, `setProposalMode`, chip helper `setChip(name, on)` (sets `aria-pressed`, calls `toggles[name](on)`), `setThematic`, `Atlas3D.setVisible`, timeline visibility and year, `#plan-badge`.
5. Camera (when `fly` and the URL had no hash at load or the user picked the lens): `map.flyTo({ ...camera, padding, duration: 2200, essential: true })` with the camera from 3.5 and `padding = { left: 360, top: 64, right: lensState.detailsOpen ? 396 : 0, bottom: 72 }` on desktop, `{ top: 48, bottom: <sheet height> }` on phone. Reduced motion: `jumpTo`.
6. Dispatch `atlas:lens`.

Initial state: `setLens('height', { fly: false })` once at script start (the intro flight from app.js frames the state).

### 3.4 Card copy (<= 80 words each; `{}` = filled from data)

- **height** — "How high is it?" — "Telangana rises from {lowBed} m, where the {lowRiver} leaves the state, to {highTown} m at {highTownName}. Colours show height above sea level and the relief is raised so the plateau stands out. Tap or click anywhere for the height of that spot; Details lists every city." Caveat: "Heights are terrain models, not surveyed benchmarks; the relief is exaggerated." Source: "Copernicus DEM (cities), Mapbox Terrain-DEM (tap readout)".
- **rivers** — "Rivers & lifts" — "Rivers run east to the Bay of Bengal while much of the farmland sits higher. Lift schemes pump river water uphill in stages: Kaleshwaram climbs from Medigadda on the Godavari through barrages, pump houses, tunnels and reservoirs to Konda Pochamma Sagar. Wider, darker blue carries more water; orange is water moved by people." Button `#tour-start` "Follow the water". Controls: chips `dams` "Dams & reservoirs", `links` "Lifts & canals", `pending` "Planned & under construction". Caveat: "Link lines are schematic, not the real canal and tunnel routes; 3D works are generic stand-ins." Source: "HydroRIVERS, OpenStreetMap, Wikipedia, Irrigation Dept".
- **since2014** — "Since 2014" — "Telangana was formed in 2014. Drag the timeline or press Play to see dams, lifts and canals appear by the year they were done. Districts are shaded by the tanks taken up under Mission Kakatiya, 2015–18." Caveat: "Change, not cause: rainfall, groundwater recovery and tank restoration all play a part; tank restoration is counted per district, not per tank." Source: "OpenStreetMap, Wikipedia, Mission Kakatiya reports".
- **ground** — "Groundwater & crops" — "Depth to water in May at the state's monitoring wells, and the share of land under crops, before and after 2014. Blue wells and districts gained water. The relief turns grey so the overlay reads." Caveat: "Monsoon years swing the levels (2015–18 drought, 2020–22 wet); the public well data stop in May 2023. Change, not cause." Source: "India-WRIS (CGWB, Telangana GWD), GLAD cropland (Potapov et al. 2021)".
- **proposal** — "Proposal" — "What it might take to bring river water to {targetPct} % of the cultivable land in every district, computed from this map's terrain, river flows and land cover. Six multi-stage trunk systems lift water up the plateau; reservoirs and lift deliveries take it on to the districts." Caveat (styled with `--plan`): "A planning sketch, not a design: surveys, real hydrology and inter-state awards would change every number." Source: "`propose_water.py`, engineering review norms".

### 3.5 Cameras (desktop; phone: zoom − 0.8, same centre)

| Lens | center | zoom | pitch | bearing |
|---|---|---|---|---|
| height | [79.35, 17.75] | 7.2 | 50 | −18 |
| rivers | [79.30, 18.35] | 8.3 | 62 | −28 |
| since2014 | [79.35, 17.75] | 7.2 | 45 | −10 |
| ground | [79.35, 17.85] | 7.0 | 20 | 0 |
| proposal | [79.35, 17.85] | 7.0 | 40 | −10 |

`#reset` flies to the active lens camera (replaces `HOME` as the reset target; `HOME` stays for the intro).

### 3.6 Headline numbers and their sources

| Lens | Number (format) | Source |
|---|---|---|
| height | "Hyderabad" `{elev} m` | `citiesData` entry `name === 'Hyderabad'`, `.elev` |
| height | "Highest town" `{elev} m` + name | max `.elev` in `citiesData` |
| height | "Lowest river bed" `{elev} m` + river | min `points[].elev` over `profileState.profiles` |
| rivers | "Kaleshwaram climb" `≈ {round10(K − M)} m` | `damsData` `Konda Pochamma Sagar`.elev_m − `Medigadda Barrage`.elev_m (590 − 88 → "≈ 500 m"); the `dt` says "terrain at Medigadda → Konda Pochamma Sagar, not water levels" |
| rivers | "Pump houses working" `{n}` | `pumphouses.json`: `kind === 'pump' && status === 'operational'` |
| rivers | "Godavari leaving the state" `{q} m³/s` | `flowSummaryData.peaks.Godavari.q` |
| since2014 | "Canals, tunnels, mains dug after 2014 (OSM)" `{km} km` | `canals_summary.json` `osm_km.after_canal + after_tunnel + after_main` (fetched by ui.js, 1 KB) |
| since2014 | "Tanks taken up, Mission Kakatiya" `{n}` | `tankSummary.mission_kakatiya.taken_up` |
| since2014 | "Water table, median change" `{±x.x} m` | `gwData.state.change` (negative = fell; say "fell"/"rose") |
| ground | "Water table, median change" `{±x.x} m` | `gwData.state.change` with "May {before} → May {after}" |
| ground | "Wells where it rose" `{p} %` | `round(100 * gwData.state.rising / gwData.state.wells_both)` |
| ground | "Land under crops" `{a} % → {b} %` | `cropData.state[before.year].pct`, `cropData.state[after.year].pct` |
| proposal | "Last-mile works" `₹{x.xx} lakh crore` | `proposalData.totals.capex_cr / 1e5` (108687 → 1.09) — filled by D in `renderProposal` into `#hl-proposal-1` |
| proposal | "New trunk stages" `+ ₹{x.xx} lakh crore` | `totals.systems_capex_new_cr / 1e5` (→ 1.84) — `#hl-proposal-2` |
| proposal | "River water a year" `{n} TMC` | `Math.round(totals.annual_tmc)` (→ 352) — `#hl-proposal-3` |

Numbers are computed, never typed in. Height, rivers, since2014 and ground numbers are filled by ui.js on `atlas:data`; a missing dataset hides that `.hl`.

### 3.7 Legends per lens (`.lens-legend`)

| Lens | Legend |
|---|---|
| height | `#ramp` + `#ramp-ticks` (as today) |
| rivers | `#flow-legend` (4 classes, section 8.1) + `.works-key`: dam icon, barrage icon, solid orange = operating, dashed = under construction, dotted = planned, dotted ring = position approximate, grey 3D = height unknown (15 m stand-in) |
| since2014 | Kakatiya ramp (light → dark = fewer → more tanks taken up) + the works key |
| ground | `#gw-legend` or `#crop-legend` (whichever layer is active) |
| proposal | compact key: teal reservoir, teal delivery, pump, canal/tunnel, trunk new (solid) / existing (dashed), command area |

---

## 4. Bottom timeline (replaces the era and status filters)

DOM (ids kept from today where they exist):
```
<div id="timeline" class="timeline" role="group" aria-label="Years" hidden title="(timeline rules, section 7)">
  <button id="year-play" class="chip tl-play" type="button" aria-pressed="false">Play</button>
  <div class="tl-track">
    <input type="range" id="year" min="1950" max="2026" step="1" value="2026" aria-label="Show works done by this year">
    <button id="year-2014" class="tl-mark" type="button">2014 · Telangana formed</button>
  </div>
  <button id="year-now" class="chip tl-now" type="button">Now</button>
  <output id="year-out" for="year">Now</output>
  <p id="year-readout" class="tl-readout" aria-live="polite"></p>
</div>
```
- `#year-2014` sits at the 2014 position of the track (computed from `min`/`max`), click = `setYear(2014)`.
- `#year-now` = `setYear(YEAR_MAX, false)`; `#year-out` shows "Now" when inactive (was "all").
- Play: as today (one year per 0.6 s from the minimum).
- Filters (unchanged rules, `yearFilter()`): `dam-labels`, `links-line`, `links-guide`, `links-pulse`, `links-arrows`, `links-hit`, `wip-labels`, every `canals-*` layer, and from now on `pump-labels` (label features get `year = Number(since)` when `since` is set). 3D: `Atlas3D.setYear(year|null)` (dams/barrages/reservoirs by `opened || began`, pump houses by `since`, conduits by the canal rule after → 2015, proposal never filtered).
- Ground lens: before/after rasters switch at 2015 (section 3.2).
- Not filtered: tanks, Kakatiya shading, groundwater wells/districts outside the ground lens, rivers.

---

## 5. Settings popover (`#settings`)

| Control | Element | Behaviour |
|---|---|---|
| Scene (phone only; desktop has it in the top bar) | second `.seg.scene` with `[data-scene]` | B's `setScene` binds all copies |
| Vertical exaggeration | `<label class="slider">` with `#exag` (1–6, step 0.5, default 3) and `#exag-out` | handler unchanged (B) |
| Contours | `.chip[data-toggle="contours"]` (default on; the layer only draws from z9.5) | |
| Elevation bands | `.chip[data-toggle="bands"]` | |
| Place labels | `.chip[data-toggle="labels"]` | |
| District lines | `.chip[data-toggle="districts"]` | |
| Flow animation | `.chip[data-toggle="flow"]` | |
| 3D models | `.chip[data-toggle="models3d"]` | `Atlas3D.setVisible('all', on)` |
| About & sources (phone only) | `button.text-btn` opening `#about` | |
| One hint line | "Exaggeration is the slider value at district level, more at state level, never less up close." | |

Opens on `#settings-btn` click, closes on Esc, outside click or a second click; `aria-expanded` kept in sync; focus moves to the first control and back to the button on close.

---

## 6. About & sources sheet (`#about`)

Modal sheet with `<h2 id="about-title">About & sources</h2>` and one `<section class="about-section">` per heading, in this order: **How to read the map** (scene, tap readout, navigation), **Height**, **Rivers & lifts**, **Since 2014**, **Groundwater & crops**, **Proposal**, **3D models**, **Timeline**, **Data & credits** (today's `.credits` text verbatim, links to `README.md`/`DATA_SOURCES.md` on GitHub). Esc and a close button close it; focus is trapped while open.

---

## 7. Where every caveat goes

| Caveat (today's wording, shortened here) | Visible next to the claim | Full text |
|---|---|---|
| Sketch: ground read every 500 m, ridge can be missed; screening check, not a survey | Sketch tool panel (unchanged) | About › Rivers & lifts |
| River flow is the HydroRIVERS long-term model average | rivers legend source line | About › Rivers & lifts |
| River line takes the relief colour of its bed | `#details-rivers` (bed line) | — |
| Dam labels show gross capacity; heights, years, inflow from Wikipedia, HydroRIVERS | rivers `.lens-source` | About › Rivers & lifts |
| Link lines are schematic, not real canal and tunnel alignments | rivers `.lens-caveat`, link popup (kept) | About › Rivers & lifts |
| Statuses as reported up to October 2026, they change often | `#details-rivers` above `#pending-list` | About › Rivers & lifts |
| Dashed outline with a cone = under construction or proposed; dotted ring = position approximate (village, not the structure) | `.works-key` | About › Rivers & lifts |
| OSM records no dig dates, so the project decides the canal era; after 2014 = Kaleshwaram, Palamuru-Rangareddy, Sitarama | `.works-key` one line | About › Rivers & lifts |
| Canal network table: audited snapshot, not today's total; dug ≠ lined and connected | `#details-rivers` (rendered by app.js, unchanged) | — |
| Tanks: OSM has no construction or restoration dates; restored tanks have no published locations, so before/after is per district | since2014 `.lens-caveat`, tank popup (kept) | About › Since 2014 |
| Mulugu and Narayanpet counted inside Jayashankar and Mahabubnagar | `#details-since2014` | — |
| Groundwater: CGWB + state wells, May means of 2010–14 and 2015–23; drought/wet years; data stop May 2023; state reports "more than 4 m" against 2016/2019 lows | ground `.lens-caveat` (short) | `#details-ground` + About › Groundwater & crops |
| Cropland: GLAD 3 km cells, 2008–11 vs 2016–19 | ground `.lens-source` | About › Groundwater & crops |
| Change, not cause (water projects one reason among rainfall, groundwater, Kakatiya) | since2014 and ground `.lens-caveat` | About |
| Proposal is a planning sketch, not a design; surveys, hydrology, awards would change every number | `#plan-badge` + proposal `.lens-caveat` + popups (kept) | `#details-proposal` + About › Proposal |
| Proposal symbol essay (reservoir, delivery, pump, canal, tunnel, trunk, command) | proposal legend (symbols only) | About › Proposal |
| Proposal engineering caveats and norms lists | `#details-proposal` (`#prop-caveats`, `#prop-norms`) | — |
| Basemap: Standard or Satellite; Satellite turns relief colours off | — | About › How to read the map |
| Exaggeration varies with zoom | Settings hint line | About › Height |
| Bands every 100 m; contours carry height every 200 m | — | About › Height |
| Timeline rules: dams opened else began (construction start when the opening year is unknown); links done, else water, began, planned; canals after 2014 count as 2015, older as 1970; undated works hide while active; Play = 1 year / 0.6 s | `#timeline` `title` | About › Timeline |
| Navigation: right-drag or Ctrl-drag rotates and tilts, scroll zooms, two fingers rotate | `#map-tools` `title` | About › How to read the map |
| Credits footer | — | About › Data & credits |
| **New, 3D models**: generic stand-ins, not as-built drawings. Dam bodies follow OSM crest lines at the listed height (15 m stand-in, lighter colour, when unknown); barrage piers every 20 m and gates are schematic; where a barrage's listed height is at or above its ground level it is read as a water level and drawn as level − ground (at least 12 m); pump houses are generic buildings sized by MW and several real ones are underground caverns; tunnels are drawn at the surface along their OSM line; reservoir surfaces sit at the terrain height along OSM's mapped shoreline, not a surveyed full level (proposal pools at the model's level); every height is raised by the same exaggeration as the terrain; works at approximate positions get no 3D model | rivers `.lens-caveat` (short) | About › 3D models |
| **New, Kaleshwaram climb**: ≈ 500 m is terrain at the structures, not the pumped head or water levels | rivers headline `dt`, tour panel | About › Rivers & lifts |

---

## 8. Phase 2: layers and look (package B)

### 8.1 Water grammar and colour tokens (`MAP_THEMES`)

| Key | Light | Dark | Notes |
|---|---|---|---|
| `flow` (4 classes) | `#9cd3f0 #4aa3e0 #1f6fc4 #0d3f8a` | `#3f7fa8 #4aa8e8 #7ab8ff #b5d8ff` | `FLOW_CLASSES` = `< 10`, `10–100`, `100–1K`, `1K+`; purple class deleted |
| `flowDash` | `#eef7ff` | `#ffffff` | unchanged |
| `flowGlow` | deleted | deleted | layer `flow-glow` deleted |
| `tank` / `tankEdge` | `#5aa6e0` / `#1f6fc4` | `#3f8fd0` / `#9fd0ff` | fill opacity 0.85 |
| `basemapColours.colorWater` | `#5aa6e0` | `#1f4f7a` | |
| `link` | `#c2410c` | `#fb923c` | operating solid, in progress dashed `[2,2]`, planned dotted `[0.6,2.4]` |
| `linkDash` | `#fff4e8` | `#fff7ed` | pulse colour; casing deleted |
| `canal` (after 2014) | `#c2410c` | `#fb923c` | "scheme colour" = the orange family |
| `canalMain` (new) | `#9a3412` | `#fdba74` | pressure mains |
| `canalTunnelCasing` (new) | `#fed7aa` | `#7c2d12` | tube look: wide casing + thin core |
| `canalOld` | `#a8836b` | `#a08876` | 60 % width, 0.6 opacity |
| `canalBuilding` (new) | `#ea580c` | `#f97316` | OSM `construction` (Sitarama), dashed `[2,2]` |
| `canalDash` | `#fff4e8` | `#fff7ed` | moving dashes, same rhythm as rivers |
| `canalCasing` | `#ffffff` | `#2a1408` | thin edge for open canals |
| `prop` | `#0f766e` | `#2dd4bf` | teal family only |
| `propPool` (fill / line) | `#2dd4bf` @0.5 / `#0f766e` | `#2dd4bf` @0.4 / `#5eead4` | indigo deleted |
| `propPump` | `#115e59` | `#99f6e4` | |
| `propTrunk` / `propTrunkExisting` (new) | `#0d9488` / `#5f9e98` | `#5eead4` / `#3c8f88` | purple deleted |
| `propCmdExisting` / `propCmdNew` | `rgba(13,148,136,0.12)` / `rgba(20,184,166,0.30)` | `rgba(45,212,191,0.10)` / `rgba(45,212,191,0.26)` | green deleted |
| `reliefOpacity` (now stops) | `[[6,0.88],[10,0.72],[13.5,0.58]]` | `[[6,0.82],[10,0.66],[13.5,0.52]]` | no fade below 0.5 close up |
| `thematicShadow` / `thematicHighlight` (new) | `rgba(43,32,22,0.35)` / `#ffffff` | `rgba(0,0,0,0.45)` / `#8a8a8a` | section 8.5 |
| `labelHalo` | `rgba(255,255,255,0.95)` | `rgba(14,15,18,0.92)` | |
| `heat` | deleted | deleted | heatmap deleted |

### 8.2 Widths and zoom bands

| Layer | Rule |
|---|---|
| `FLOW_WIDTH_STOPS` | `[[-1,0.6],[0,1.0],[1,1.9],[2,3.0],[3,5.6],[3.6,9.5]]` (biggest rivers wider) |
| `EXAGGERATION_BY_ZOOM` | `[[6,2.2],[9,1.6],[12,1.2],[13.5,1.0]]` (never below the slider value close up) |
| `relief` | `raster-emissive-strength: 1`; opacity from `reliefOpacity` stops |
| `hillshade` | own source `hillshade-dem` (`raster-dem`, same tileset, tileSize 512, maxzoom 14); `hillshade-emissive-strength: 1`; exaggeration `[6,0.8],[10,0.6]` |
| `contours` | minzoom 9.5, drawn **under** `mask` so outside the state they are dimmed (true clipping needs a re-published tileset: open question); visibility by the `contours` chip (default on) |
| `contour-labels` | minzoom 10.5 |
| `links-line` | maxzoom 9.5, width `[6,2.6],[9,3.4]`, status dash as 8.1, no `line-z-offset`, no casing |
| `links-guide` (new) | minzoom 9, width 1.5, dash `[3,3]`, opacity 0.4, colour `link`, same filter as `links-line` |
| `links-pulse` | maxzoom 9.5 |
| `links-highlight`, `links-hit` | no `line-z-offset` |
| `canals-*` | width (px) `[6,1.2],[9,2],[12,4]` × kind (canal 1, main 1.3, tunnel core 0.8 with casing 2.6); dash phase layers use `dashPatternAt` / `FLOW_TICK_MS` (river rhythm) |
| `tanks-dots` | minzoom 7, maxzoom 9; `tanks-fill`/`tanks-outline` from 9; `tanks-heat` deleted |
| proposal | at zoom < 8 only `prop-trunk-*`, `prop-pool`, `prop-pool-line`; `prop-canal`, `prop-tunnel`, `prop-delivery`, `prop-pump`, `prop-command-*` minzoom 8; `prop-dam-walls` deleted |
| Standard road labels | `ROAD_LABEL_ZOOM = 11` (separate from `LABEL_ZOOM`) |

### 8.3 Label tiers

| Tier | Layers | Style | Zooms |
|---|---|---|---|
| T1 district | `district-labels` | 11 px, upper case, letter-spacing 0.14, `labelMuted`, halo 1.5 | 7–10 (`maxzoom: 10`); Kakatiya mode all zooms with the count |
| T2 city/town | `city-labels`, `town-labels` | 13 px (cities 14), `label`, halo 2, dot icon | cities always, towns from 8 |
| T3 works | `dam-labels`, `pump-labels`, `peak-labels`, `prop-labels-*` | 12 px, `label`, halo 1.5, icon disc | dams: icons always, text below z8 only when `capacity_tmcft >= 15` (`capn` property added in `buildDamLabels`), all from 8; pumps: icons from 8, text from 9; proposal: reservoirs and trunk labels always, deliveries from 8, the rest from 9 |
| T4 values | the `format` value part (tmcft, m, m³/s, MW, TMC) | `font-scale` 0.9, `labelMuted` | with its T3 label |
| T5 status | the `st` part ("· under construction", "· planned") and `wip-labels` | `font-scale` 0.8, `labelMuted` | from 8.5 only (`['step', ['zoom'], '', 8.5, ['get','st']]`) |

### 8.4 Scenes

| Scene | Basemap import | `lightPreset` | Map tokens | Relief |
|---|---|---|---|---|
| map | Standard | light theme `day`, dark theme `dusk` | current theme | on |
| satellite | Standard Satellite | — | current theme | off |
| night | Standard | `night` | dark tokens whatever the UI theme, fog `star-intensity` 0.6 | on, emissive 1 |

`setScene` keeps the `setStyle({ diff: false })` path of today's `setBasemap` (sketch suspend/resume, icons); it no longer touches any chip. Satellite → relief off is internal state, not a chip.

### 8.5 Thematic mode (`setThematic(on)`)

On: `relief` visibility none; `hillshade-shadow-color` = `thematicShadow`, `hillshade-highlight-color` = `thematicHighlight`, `hillshade-accent-color` = `thematicShadow`; `flow-lines` `line-opacity` 0.5; mask opacity +0.1. Off: back to theme values (and relief only if the scene is not satellite). `applyMapTheme` respects the current thematic state.

### 8.6 Deleted by B

`flow-glow` (+ token), purple flow class, `links-casing`, the overhead link lift (`LINK_LIFT_M`, `LINK_LIFT_STEP_M`, `linkZoom`, `linkLift`, `linkLiftAt`, `linkLayout`, `LINK_LIFTED`, `refreshLinkLift` and its `zoom` handler and calls), `tanks-heat` (+ `TANK_HEAT_ZOOM`, `heat` tokens), fill-extrusion walls (`WALL_WIDTH_M`, `wallHeight`, `wallPaint`, `damWallLayers`, `setWallHeights` and its calls, `damLinesLoaded`, the `dam-lines` source, `prop-dam-walls`, the wall click/hover handlers, `dam-walls`/`prop-dam-walls` in `HOVER_BLOCKERS`, the wall handling in the basemap switch), the particle style code (`flowParticlesUrl`, `PARTICLE_*`, `flowParticleSources`, `flowParticleLayers`, `raster-particle` in `slotFor`), `lightMode`, `lightPresetFor`, `setLightMode`, `setBasemap` (→ `setScene`), `chipOn('relief'|'hillshade'|'particles')` uses. `damsWithAssumedWall` stays (popup text and 3D).

---

## 8.7 three.js 3D works layer (package C)

### 8.7.1 Loading

- New file `web/three3d.js`, an ES module loaded by `<script type="module" src="three3d.js">` (after app.js, ui.js, tour.js).
- `import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.min.js';` — pinned, core only, no import map, no addons (geometry merging is done by hand; polygons use `THREE.ShapeUtils.triangulateShape`).
- At the end of the module: `window.Atlas3D = api; window.dispatchEvent(new Event('atlas3d:ready'));`.
- If the CDN fails the module never runs: app.js keeps working with 2D icons; `debug.notes.atlas3d` stays absent.

### 8.7.2 Public API

```js
window.Atlas3D = {
  init(map, { exaggeration, theme }) -> Promise<void>,  // exaggeration(): current scalar = slider × zoom factor × terrainRise
  setTheme('light' | 'dark'),                          // also self-syncs from <html data-theme> + prefers-color-scheme
  setVisible(group, on),                               // 'all' | 'dams' | 'reservoirs' | 'pumps' | 'conduits' | 'proposal'
  setYear(year | null),                                // null = all
  setStatus('all' | 'built'),                          // 'built' hides non-operational objects
  setData('proposal', { data, geo }),                  // proposal.json + proposal.geojson; three3d never fetches them
  setExaggeration(),                                   // invalidate: triggerRepaint (exaggeration is read every frame)
  probe([lon, lat]) -> { groundM, exaggeration, z },   // test hook: the z the layer uses for ground there
  stats() -> { layer, revision, groups: { <group>: { objects, visible, batches } }, calls },
};
```

App bridge (package C, the only app.js code C writes; inserted between the frozen anchor lines `document.body.classList.add('sketch-off');` and `async function loadJson(url)`):

```js
// ---------- 3D works (three3d.js) ----------
function exaggerationNow() { return Math.max(0.01, Number($('exag').value) * exaggerationFactorAt(map.getZoom()) * terrainRise); }
function whenAtlas3D(fn) { if (window.Atlas3D) fn(window.Atlas3D); else window.addEventListener('atlas3d:ready', () => fn(window.Atlas3D), { once: true }); }
map.on('load', () => whenAtlas3D((atlas) => atlas.init(map, { exaggeration: exaggerationNow, theme: currentTheme() })
  .then(() => { if (proposalGeo && proposalData) atlas.setData('proposal', { data: proposalData, geo: proposalGeo }); debug.notes.atlas3d = atlas.stats(); writeDebug(); })
  .catch((error) => { debug.errors.push(`3D: ${error.message}`); writeDebug(); })));
```

### 8.7.3 Rendering

- One Mapbox custom layer `{ id: 'atlas3d', type: 'custom', renderingMode: '3d', slot: 'middle' }`, added on `init` and again on every `style.load` (a scene switch drops custom layers). If GL JS 3.33 rejects `slot` on a custom layer, add it without `slot` and record that in `stats()`; if a style switch with the layer present throws, remove it on `styledataloading` first. Both are verified, not assumed.
- `THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true })`, `autoClear = false`; `renderer.resetState()` before each render; `map.triggerRepaint()` only when something changed (the flow animation already repaints every frame).
- Frame: each batch has its own origin (the centroid of its objects; batches are built per 0.5° grid cell and per group/status) to avoid float32 jitter at z15–16. `camera.projectionMatrix = mapMatrix × T(originMercator) × S(s, −s, s)` with `s = origin.meterInMercatorCoordinateUnits()`; local x/y in metres east/north of the origin, z in metres.
- Terrain placement in the vertex shader (one shared chunk injected with `onBeforeCompile` into `MeshLambertMaterial`): `z_world = (aGround + position.z) * uExag`, where `aGround` is the unexaggerated ground (or water level) in metres per vertex/instance and `uExag = exaggeration()` read every frame. Structure heights are therefore raised with the terrain, exactly as the old walls were. Cross-sections use `aAcross` × `uWidthScale` (`uWidthScale = max(1, 2^(11 − zoom))`, capped at 8) so bodies stay visible below z11.
- Ground sampling: `map.queryTerrainElevation(lngLat, { exaggerated: false })`, cached per vertex; `null` (tile not loaded) falls back to the data's `elev_m`/level and is re-sampled on `idle` (throttled 500 ms) for batches in view, and again when `Math.floor(zoom)` changes (the DEM tile level changes the rendered surface).
- Culling and LOD: `frustumCulled = false`; each batch is hidden when its bbox (padded 20 %) is outside `map.getBounds()` or the zoom is below its group's band: reservoirs >= 8, dams/barrages >= 9, pumps >= 10, conduits >= 10.5, proposal pools >= 8, other proposal objects >= 9. Opacity fades in over 0.5 zoom.
- Instancing: pump houses and tunnel portals are `InstancedMesh` per (kind, status, theme material) with an instanced `aGround`; dams, barrages, reservoirs and conduits are merged `BufferGeometry` per batch. Target: `stats().calls <= 60` at Kaleshwaram z12 with every group on.
- Lighting: `AmbientLight` + `DirectionalLight` from azimuth 315°, altitude 45° (matches the hillshade); dark theme: lower intensity and `emissive` 0.25 so works read at night.
- No picking in v1: the existing symbol labels stay the click targets (popups unchanged).

### 8.7.4 Objects and data

| Group | Source | Shape | Height |
|---|---|---|---|
| dams | `dam_lines.geojson` features whose `dams[i].kind === 'dam'` | prism along the crest line: crest width 8 m, base width `max(12, 0.7 × H)` m, top flat at `min(ground along line) + H`, bottom 5 m below ground, clamped to 0 where the abutment ground is above the crest | `H = height` (`height_known === false` → 15 m stand-in, colour `damUnknown`) |
| barrages | `dam_lines.geojson` with `dams[i].kind === 'barrage'` | deck 10 m wide at crest level; piers 3 × 12 m every 20 m from ground to deck; gate panels between piers at 70 % of the height | `H` from dams.json; if `height >= elev_m − 5` the value is a water level: `H = max(12, height − elev_m)`; unknown → 15 m |
| reservoirs | `reservoirs.geojson` (new, built by C, 8.7.5) | flat triangulated polygon, 0.3 m above `level` | `level_m` from the file; refined at runtime to the median of `queryTerrainElevation` along >= 16 outline points once tiles are loaded |
| pumps | `pumphouses.json` (`kind === 'pump'`), skip `approx` | box building `L = clamp(30 + 0.12 × MW, 30, 140)` m, `W = 0.45 L`, walls 18 m + 4 m roof, long axis across the link that leaves it (`links.geojson` `via` or `from` name match), else 0° | MW parsed from `power` ("320MW") |
| pumps (portals) | `pumphouses.json` (`kind === 'tunnel'`), skip `approx` | arch portal 12 m wide, 10 m high | |
| conduits | `conduits.geojson` (new, built by C): OSM canals with `era === 'after'` and `kind` `main`/`tunnel`, plus ways whose `scheme` starts with `Sitarama` | `main`: twin pipes radius `max(1.6 m, 1.5 px)`; `tunnel`: translucent tube (opacity 0.45) along the surface with a portal at each end; `canal`: U-trough 12 m wide (lining + water strip) | densified every 100 m, ground sampled per vertex |
| proposal | `setData('proposal')`: geo `kind === 'dam'` (crest_m) and `'pool'` (frl_m), `'pressure main'`, `'tunnel'`; data `works[].pumps` (14) and new trunk-stage lifts (`systems[].stages` with `lift_m > 0`, `!existing`, `placed_by === 'map'`) | same shapes as above in the proposal style | dams `crest_m`; pools at `frl_m` |

Approximate positions (`approx` set, or trunk stages `placed_by` other than `'map'`) get no 3D model: their 2D icon with the dotted ring stays the only mark.

### 8.7.5 New derived files (C, `build_web_data.py`; `web/data` is git-ignored, so only the code is committed)

- `reservoirs.geojson`: for each dam in `dams.json`, the largest OSM water polygon from the tanks build (`build_tanks`) that touches a 3 km buffer of the dam point or its crest line, area >= 50 ha; properties `{ i, name, status, area_ha, level_m }`, `level_m` = median Copernicus DEM (`DemSampler`) along the outline. Dams without a match are skipped and listed in the build log.
- `conduits.geojson`: the canals selection in 8.7.4 with `{ id, kind, scheme, construction, km, year }`.
- `DAM_LINE_ALIASES`: inspect `data/raw/osm_dam_lines.json` for the dams that get no line today (Medigadda first); add an alias only when the OSM way lies within 2 km of the dam's position. Report the dams still without a line.

### 8.7.6 Status and theme colours (three3d.js constants)

| Token | Light | Dark |
|---|---|---|
| `dam` | `#b8805a` | `#c9946e` |
| `damUnknown` | `#dfb39d` | `#9c6650` |
| `barragePier` / `barrageDeck` / `gate` | `#8a8f94` / `#5f6b73` / `#0f7f78` | `#9aa3aa` / `#7b8790` / `#4fd1c5` |
| `pumpWall` / `pumpRoof` | `#e7e1d6` / `#c2410c` | `#b8b2a7` / `#fb923c` |
| `pipe` / `tunnel` / `lining` | `#9a3412` / `#c2410c` / `#cfc8bb` | `#fdba74` / `#fb923c` / `#8f8a82` |
| `water` (opacity 0.82) | `#5aa6e0` | `#3f8fd0` |
| `proposal` / `proposalWater` | `#14b8a6` / `#5eead4` | `#2dd4bf` / `#5eead4` |

Status: `operational` → opaque; `under construction` / `in progress` → colour mixed 35 % with `#f59e0b`, opacity 0.7; `planned` / `proposed` → opacity 0.35, `depthWrite: false`; proposal objects → proposal colours, opacity 0.55.

### 8.7.7 What replaces what

| Old | New |
|---|---|
| `dam-walls` / `prop-dam-walls` fill-extrusions | dam and barrage bodies (8.7.4); no 2D fallback (labels stay) |
| Overhead lifted schematic links (`line-z-offset`, casing) | flat 2D guides (8.2) + 3D conduits only on real OSM alignments and proposal routes; no 3D along schematic links |

---

## 9. Phase 3 (package D)

### 9.1 "Follow the water" tour (`web/tour.js`, `web/tour.css`)

- Stops (by exact `dams.json` name): Medigadda Barrage → Saraswati Barrage → Parvati Barrage → Sripada Yellampalli Project → Mid Manair Dam → Mallanna Sagar → Konda Pochamma Sagar.
- Each stop: camera `flyTo` centre on the dam, zoom 12.5, pitch 62, bearing towards the next stop, 4 s; caption with name, terrain `elev_m`, capacity, year, the link into it (`links.geojson`: lift, `via` pump house and its MW from `pumphouses.json`) and the source link.
- Climb profile: SVG pinned to the bottom of the screen (above the timeline), the 7 stops by `elev_m`, current stop highlighted; last stop shows "Water lifted about {round10(590 − 88)} m — terrain at the structures, not the pumped head".
- Controls: Prev, Pause/Play (auto-advance 7 s), Next, Close; Esc, drag, wheel or touch stop autoplay. Starts with `setLens('rivers', { fly: false })` when available. Reduced motion: `jumpTo`.
- DOM is created by tour.js (`#tour-panel`, classes `tour-*`), styles only in tour.css. Button `#tour-start` (in the rivers card, package A) calls `AtlasTour.start()`.

### 9.2 Fly-to a work

`flyToWork(lon, lat)`: `map.setMaxZoom(16)`; `flyTo({ center, zoom: 15, pitch: 65, bearing: map.getBearing(), duration: 2600, essential: true })`. Restore `MAX_ZOOM` (13.5) on a later `moveend` when the centre is more than 3 km from the target or the zoom is below 12 (ease back under 13.5 first, as `stopStructureOrbit` does). Used by dam label clicks, pump label clicks and the "Still to be built" list rows.

### 9.3 Proposal

Headline (3.6) filled in `renderProposal`; `proposal.json` still loads at boot (the sketch tool needs its norms); `proposal.geojson` (4.2 MB) loads on first use through `ensureProposal()`; the proposal map labels (`prop-labels` source, `prop-labels-far/near` layers, their interactions) are created then.

### 9.4 Data diet

- `flow_bubbles.geojson` (new, `build_web_data.py` `write_flow`): reaches with `q >= 300` only; the load handler fetches it instead of `flow.geojson` (fallback: `flow.geojson` when absent). `BUBBLE_CLASSES` drop the 100 m³/s class (brief: bubbles on rivers >= 300 m³/s).
- Load handler clean-up: delete the particle block, the `renderEraCounts(dams)` and `renderStatusCounts(dams, links)` calls; replace the `.closest('.fgroup').hidden = true` fallbacks with `[data-group="…"]` hiding.

---

## 10. Work packages and ownership

| Pkg | Kind | Title | Owns |
|---|---|---|---|
| A | ui | Shell layout, lenses, drawer, timeline, settings, About | `web/index.html`, `web/style.css`, new `web/ui.js`, new `web_ui_test.py`, `web_sketch_test.py`; in app.js: `chipOn`; cursor readout block (`elevationAt` stays) `showCursor`, `clearCursor`, the two `mousemove`/`mouseout` handlers → click readout; `setVisible`, `orbitStep`, `toggles`; chip wiring loop, `stopOrbit`, drag mode block, `reset`, `view-2d`/`view-3d`, `theme` button, collapse/expand and sheet-handle handlers; years/status block (`yearReadout` … `setStatusMode`, listeners; `renderStatusCounts` and the era functions left in place); `buildPumpLabels`; `$('crop-close')` listener; river tab selector (`[role="tab"]` → `[role="tab"][data-river]`); `setSketch` DOM lines; one `atlas:data` dispatch line after `debug.phase = 'data-loaded'` in the load handler |
| B | impl | Phase 2 layers and look, scenes | app.js style region: constants and functions from the top through `addLayers` except `chipOn` and `setProposalMode`/its listener (D); `applyMapTheme`, `setLightMode`, `setBasemap` → `setScene` + `[data-scene]` binding; `LINK_LIFT_STEP_M`/`refreshLinkLift`/zoom handler and the `#exag` input handler; `updateLabelDensity`; labels region (`LABEL_LAYERS` … `labelLayers`, `applyDistrictLabels`) except `addLabelSources`; `buildDamLabels`; `HOVER_BLOCKERS`; the wall click/hover handlers; `riseTerrain`; in the load handler only the `damLines` block (fetch stays, wall source/layer lines go) |
| C | three | three.js 3D works | new `web/three3d.js`; the app.js bridge block (8.7.2); `build_web_data.py` (`DAM_LINE_ALIASES`, new `build_reservoirs`, `build_conduits`, their `main()` lines after the dam-lines and tanks/canals blocks); `web_smoke_test.py` |
| D | impl | Phase 3: tour, fly-to, proposal headline and lazy load, data diet | new `web/tour.js`, `web/tour.css`, new `web_phase3_test.py`; app.js: `flyToPoint` area (new `flyToWork`), bubbles block (`BUBBLE_CLASSES` … `drawBubble`), `addLabelSources`, `setProposalMode` body (not its first three lines) + new `ensureProposal`, `renderProposal`, `renderPendingList` click handler, the load handler (except B's `damLines` block and A's dispatch line); `build_web_data.py` `write_flow` |
| E | chore | Docs, particle scripts, post-merge dead code | `README.md`, `DATA_SOURCES.md`, delete `publish_flow_raster.py`, `build_flow_raster.py`, `recipes/flow_particles.json`; post-merge only: remove definitions left dead by A–D (list in its prompt) |

Adjacency rule: where two packages own neighbouring lines (B's `damLines` block and D's proposal block; B's wall code and D's `setProposalMode`), each keeps at least two unchanged lines between its edits and the other's.

Merge order: B → C → D → A → E. After each merge: `node --check` on every web/*.js, smoke test, sketch test. After A: also `web_ui_test.py` and `web_phase3_test.py`.

---

## 11. Open questions

1. True clipping of contours to the state needs `tg-contours` re-published from clipped data (secret token). Until then contours sit under the mask.
2. Barrage heights in `dams.json` look like water levels for at least Tummidihetti (148 m, note says FRL 148 m) and Sammakka Sagar (83 m at 77 m ground). The 3D rule (8.7.4) works around it; the popup still shows the listed value. Fix at the source (`build_dams`) or keep?
3. 27 of 42 dams have no OSM crest line; after the alias pass some (possibly Medigadda) will still have none and get no 3D body.
4. Schematic links get no 3D geometry (they are not alignments). If a rising-main stub at each pump house is wanted, it is a follow-up.
5. Optional globe opening: not planned (the code notes a globe intro was tried and dropped).
6. The tileset `tecgeor.tg-flow-particles` and its source `tg-flow-velocity` can be deleted from the Mapbox account by the owner (Studio → Tilesets); nothing in the app reads them after this work.
7. Lens is not persisted in the URL; the map hash still carries the view.

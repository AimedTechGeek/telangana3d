# Telangana 3D terrain

Interactive 3D relief map of Telangana in the browser (elevation above sea
level, Godavari and Krishna river profiles, city elevations), plus a
path-traced 3D terrain block and a native forge3d viewer.

**Live map:** <https://aimedtechgeek.github.io/telangana3d/> (GitHub Pages,
served from the `gh-pages` branch, which holds the built `web/` folder).

## At a glance

| Theme | What the map shows | Where the numbers come from |
|---|---|---|
| Relief | 3D terrain with hillshade and a relief tint over the Mapbox Standard or Satellite basemap, 100 m contours, elevation under the cursor, city heights, Godavari and Krishna river-bed profiles | Mapbox Terrain-DEM for the surface, Copernicus GLO-90 DEM for the figures |
| River flow | Every stream drawn and animated by its long-term average discharge; peak flow where each river leaves the state; flow per district | HydroRIVERS (HydroSHEDS) |
| Water works | Dams, barrages, reservoirs, pump houses and the links that move water between them, each with status (operating, under construction, proposed), years, heights and capacity; a "Still to be built" list | Wikipedia and Wikidata infoboxes, OpenStreetMap, CAG audit, CWC replies, news (every entry cites its source) |
| Canals | Canals, tunnels and pressure mains dug after 2014 or all of them; the Kaleshwaram network figures against what OSM has mapped | OpenStreetMap, CAG |
| Tanks | About 4,800 village tanks and lakes; districts shaded by tanks restored under Mission Kakatiya 2015–18 | OpenStreetMap, Government of India report |
| Groundwater | 1,605 monitoring wells with depth to water in May before (2010–14) and after 2014 (2015–23), the change per well and district, a state curve 2005–2023 | India-WRIS via India Data Portal |
| Cropland | Share of land under crops before and after 2014 and the change, with cultivated area per district | GLAD global cropland (Potapov et al. 2021) |
| Proposal | A planning sketch of river water for 85 % of cultivable land: six multi-stage trunk systems, new reservoir sites, lift deliveries, pump stages, tunnels, canals, gravity commands and indicative costs, set against the state's river-water shares | Computed from the terrain, HydroRIVERS, ESA WorldCover and the works on the map, under an engineering review's norms |

Every figure on the map is traceable in [DATA_SOURCES.md](DATA_SOURCES.md);
sources that could not be reached are listed in
[README_UNREACHABLE_SOURCES.md](README_UNREACHABLE_SOURCES.md).

## Screenshots

The screenshots below predate the redesign of the web map (the layout, lenses,
timeline and 3D works described in the Web map section are not in them).

**Overview**: relief, river flow, dams and barrages with capacities, water links
with moving chevrons, tanks as blue dots, and the collapsible cards on both
sides.

![Overview, light theme](docs/screenshots/01-overview-light.jpg)

**Dark theme**: follows the OS setting, toggle in the top-left card.

![Overview, dark theme](docs/screenshots/02-overview-dark.jpg)

**Still to be built**: the Status filter keeps only the works under
construction or proposed (dashed outline and cone), with the pending links
and canals.

![Still to be built filter](docs/screenshots/03-still-to-build.jpg)

**Mission Kakatiya**: districts shaded and labelled by the tanks taken up for
restoration in 2015–18, from the Government of India report.

![Mission Kakatiya restoration by district](docs/screenshots/04-mission-kakatiya.jpg)

**Groundwater before and after 2014**: wells and districts coloured by the
change in May depth to water between 2010–14 and 2015–23 (red fell, blue
rose); the Groundwater card carries the state curve and the district table.

![Groundwater change since 2014](docs/screenshots/05-groundwater-change.jpg)

**Cropland change**: more (blue) or less (red) land under crops between
2008–11 and 2016–19, with the Cropland card's state figures.

![Cropland change](docs/screenshots/06-cropland-change.jpg)

**Kaleshwaram country up close**: Mid Manair, Ranganayaka Sagar and Mallanna
Sagar with the links, the canals and tunnels dug after 2014 (magenta) and the
real outlines of the tanks.

![Kaleshwaram reservoirs, canals and tanks](docs/screenshots/07-kaleshwaram-canals-tanks.jpg)

## Web map (Mapbox GL JS)

The map runs on Mapbox GL JS v3 (3.33.0) with the Mapbox Standard basemap (or
Standard Satellite) under the atlas layers and Mapbox Terrain-DEM as the 3D
surface, so it needs a Mapbox public token. Create one at account.mapbox.com with the
default public scopes, restrict it to `http://127.0.0.1:8765/*` (and the Pages
URL, see below), and put it in a User environment variable `MAPBOX_TOKEN`.
`serve.py` writes it into `web/mapbox-token.js`, which is git-ignored; nothing
else needs the token.

```powershell
uv run python serve.py      # http://127.0.0.1:8765/ opens in your browser
```

### Layout

- **Top bar:** the title and a one-line subtitle, the Map / Satellite / Night
  scene switch (desktop; on phones the switch sits inside Settings), the
  light/dark theme button, Settings and About & sources.
- **Five lenses** (the Story panel, left on desktop, a bottom sheet on phones).
  Each lens has a short text, one to three headline numbers, its own controls
  and legend, one caveat line, its source and a Details button:
  - **Height**: the elevation colour scale, the cities and their heights, and
    landmark silhouettes for scale. Tap or click anywhere for the height there.
  - **Rivers & lifts**: river flow, dams and barrages, the water links and canals
    that lift river water uphill, and the "Follow the water" tour.
  - **Since 2014**: the same works shown by the year they were done, with the
    Mission Kakatiya tank shading of districts.
  - **Groundwater & crops**: monitoring wells and districts by change in depth to
    water, and the cropland before and after 2014.
  - **Proposal**: a planning sketch of river water for 85 % of cultivable land.
    The map carries a "Planning sketch, not a design" badge while it is on.
- **Details drawer** (right, closed by default): the tables and lists behind the
  current lens, and the Sketch tool card while Sketch is on. On phones it opens
  full screen over the sheet.
- **Timeline** (bottom, shown by the lenses that need it): Play (one year every
  0.6 s), a year slider from 1950 to 2026, a bookmark at 2014 ("Telangana
  formed") and a "Now" button that returns to all works. The rules for which
  year a work carries are in About & sources, under Timeline.
- **Map tools** (right edge): the 3D / top-down toggle, Orbit, Sketch and Reset.
  Reset flies back to the camera of the lens you are in.
- **Settings**: vertical exaggeration (1 to 6, default 3), contours, elevation
  bands, place labels, district lines, flow animation and 3D models.
- **About & sources**: how to read the map, one section per lens, the 3D models,
  the timeline, and the data and credits (the same list as below and in
  [DATA_SOURCES.md](DATA_SOURCES.md)). Every caveat the map states is also
  written out there.

On phones and tablets (viewport 900 px wide or less) the Story panel is one
bottom sheet: a handle cycles it between a peek (the lens tabs and headline
numbers), half the screen and full screen. Details opens the drawer as a
full-screen sheet, and its close button returns to the sheet. The timeline sits
above the sheet, and the map keeps the rest of the viewport.

### Reading the map

- **Elevation:** tap or click a point on the terrain for its height above sea
  level and coordinates, with a landmark silhouette for scale (Gateway of India
  26 m, Charminar 56 m, Qutub Minar 73 m, Statue of Unity 182 m). Clicking a
  feature (a label, a link, a tank, a well, a district) opens its popup instead;
  the readout closes with its x button. There is no hover readout.
- **Hover:** a district (while District lines is on) shows its name, its mean
  river flow and its mapped tank count, and a stream shows its flow. Popups stay
  away from tank outlines, wells, dams, links and streams under the pointer and
  from any open popup.
- **Navigation:** left-drag pans; right-drag or Ctrl-drag rotates and tilts;
  scroll zooms; on touch screens two fingers rotate. The 3D / top-down toggle
  flattens the view, Orbit circles the selected work.
- **Flying to a work:** clicking a dam label, a pump-house label or a row in
  "Still to be built" flies to it at zoom 15, tilted (the map's maximum zoom is
  raised to 16 for the flight and restored afterwards).
- **Scenes:** Map uses Mapbox Standard in the light or dark theme; Satellite uses
  Standard Satellite and turns the relief tint off; Night uses Standard with its
  night light preset and dark colours whatever the theme.

### Height

Telangana rises from the river beds where the Godavari and Krishna leave the
state to the plateau towns. Colours show height above sea level, and the relief
is raised so the plateau stands out. Details lists every city, ranked by
elevation; click one to fly to it. The lowest river beds are listed beside them
for comparison. Heights are terrain models, not surveyed benchmarks.

### Rivers & lifts

- **River flow:** every stream drawn and animated by its long-term average
  discharge (HydroRIVERS): wider, darker and faster-moving dashes mean more water
  collected upstream. Bubbles ride the biggest rivers, those carrying 300 m³/s or
  more. Hover a stream for its m³/s and catchment area; peak markers show where
  the Godavari and Krishna carry the most water as they leave the state; a list
  gives the average flow of each river through every district it crosses. The
  flow animation is in Settings.
- **River bed:** the river selected in the River profiles of Details can be drawn
  on the map as a line that takes the relief colours of its bed; "Bed height
  line" in Details shows it, and a river flight turns it on and back off.
- **Dams and barrages:** the arch and gated-deck icons, labelled with name and
  gross capacity, including the Kaleshwaram barrages and the Mallanna Sagar,
  Konda Pochamma Sagar and Ranganayaka Sagar reservoirs. Clicking one flies to it
  and opens a popup with its height, construction-start and opening years, the
  average river inflow at that point (HydroRIVERS) and its capacity.
- **Water links:** orange lines show how water is moved between the structures
  by Kaleshwaram, the Sriram Sagar canals, the Srisailam Left Bank Canal,
  Kalwakurthy and Palamuru-Rangareddy. Operating links carry moving chevrons in
  the direction of flow; links still being built are dashed, and planned ones
  dotted. Click a link for its status, years (planned, construction, first water,
  complete), the terrain heights at both ends, the straight-line distance and the
  source. The lines are schematic, not real canal alignments, and are drawn flat
  over the ground with a guide line; 3D conduits appear only where OpenStreetMap
  maps a real canal, tunnel or pressure main.
- **3D works:** dams, barrages, reservoir surfaces, pump houses, tunnel portals,
  conduits and the proposal works are drawn in 3D (see 3D works below). With the
  "Planned & under construction" chip on, the pending works show with their
  status; the "Still to be built" list in Details gives them by scheme, with the
  years and the last announced target. Works with no published location are
  listed in grey.
- **Canals, tunnels and pressure mains** (OpenStreetMap): thin magenta dashed
  lines whose dashes move with the flow; canal tunnels are dotted with a wide
  casing, pressurised tunnels and pipes solid. "Lifts & canals" shows those dug
  after 2014 (Kaleshwaram and Sitarama works, by project since OSM has no dig
  dates). Click one for its name, scheme and length. The Details table sets the
  official Kaleshwaram network figures (planned 1,832 km; CAG: 57 % of main canals
  and 7 % of distributaries built by March 2022) against what OSM has mapped.
- **Lift tour:** "Follow the water" (see below).

### Since 2014

Telangana was formed in 2014. Drag the timeline or press Play to see dams,
lifts and canals appear by the year they were done. Districts are shaded by the
tanks taken up under Mission Kakatiya, 2015–18, and the Details table sets those
figures against the village tanks OpenStreetMap maps (about 4,800 tanks and
lakes of 0.5 ha or more, shown as blue dots sized by water spread, with their
outlines when zoomed in; click one for its name, area and district). The
headline numbers give the canals, tunnels and mains dug after 2014 in km, the
tanks taken up, and the median change in the water table from May before 2014 to
May after. The "Planned & under construction" chip applies here too.

### Groundwater & crops

- **Groundwater** (India-WRIS): 1,605 CGWB and state-department monitoring wells
  with their mean depth to water in May before 2014 (2010–14) and after (2015–23),
  the change per well and per district, a year-by-year state curve and popups
  with each well's readings. Depth is below ground, so the drought years 2015–18
  show as a fall and the wet 2020–22 monsoons as a recovery. The Details card has
  the state curve and the district table.
- **Cropland cover** (GLAD, Potapov et al. 2021): the Groundwater & crops lens
  switches a raster of the share of land under crops for 2008–2011 ("Before
  2014"), 2016–2019 ("After 2014") or the change between them. The timeline
  picks the period when the Depth or Cover view is on (before 2015 is "before",
  otherwise "after"); with Change the timeline is hidden. Details opens a card
  with the state and per-district cultivated area before and after (lakh acres,
  change in acres, CSV download) and the official irrigated-area statistics. A
  Blend slider cross-fades the two rasters when one of the periods is on. The
  data show the change, not its cause.
- The relief turns grey in this lens so the overlay reads.

### Proposal

A planning sketch, off by default, in the Proposal lens: what it would take to
put 85 % of the state's cultivable land under river water, computed by
`propose_water.py` from the terrain, HydroRIVERS flows, ESA WorldCover land cover
and the works already on the map, under norms set by a lift-irrigation engineering
review: new reservoirs sited on the DEM, lift deliveries for districts without a
dam site, six multi-stage trunk systems that reuse Kaleshwaram's, Devadula's and
Palamuru's stages and add new ones, the cheapest feed for each work (river
intake, existing reservoir or canal, trunk stage or cascade), pump stages,
tunnels, deep cuts, canals and pressure mains routed inside the state, and the
land gravity could then serve. Everything drawn is marked "new" with its TMC. The
Details card gives the water budget against the Godavari and Krishna shares,
every system and work with its lift, route and indicative cost, the per-district
need, the engineering caveats and the norms. The proposal's dams, pools and
pumps appear in 3D; a proposed reservoir is drawn at the full-reservoir level it
was sited for.

### Follow the water (tour)

"Follow the water" in the Rivers & lifts lens steps the camera through seven
stops, from Medigadda Barrage on the Godavari up to Konda Pochamma Sagar:
Medigadda → Saraswati → Parvati barrages → Sripada Yellampalli → Mid Manair →
Mallanna Sagar → Konda Pochamma Sagar. Each stop flies to the structure (zoom
12.5, pitch 62, four seconds) and gives a caption with its name, terrain height,
capacity, year, the lift link into it (through its pump house and that house's
MW) and the source. A climb profile along the bottom of the screen shows the
seven stops by height, with the current one highlighted; the last stop reads
"Water lifted about 500 m — terrain at the structures, not the pumped head".
Prev, Pause/Play (auto-advances every seven seconds) and Next move through it;
Esc, dragging, the wheel or touching the map stops the auto-advance. With reduced
motion the camera jumps.

### 3D works

Dams, barrages, reservoirs, pump houses, tunnel portals, conduits and the
proposal are drawn in 3D by `web/three3d.js`, an ES module that loads
three.js 0.169.0 (core build, from jsDelivr) and adds one custom layer to the
Mapbox map, so the works sit on the same terrain, lit like the hillshade and
raised by the same vertical exaggeration as the surface. If the three.js script
cannot load, the map keeps its 2D icons and labels and nothing else changes.

| Group | Drawn as |
|---|---|
| Dams | a prism along the OpenStreetMap crest line, as high as the listed height |
| Barrages | a deck with piers every 20 m and gates between them |
| Reservoirs | a flat water surface at the level read from the terrain along the mapped shoreline |
| Pump houses | boxes sized by installed MW; tunnel portals as arches |
| Conduits | OpenStreetMap canals dug after 2014: pressure pipes, tunnel tubes and canal troughs |
| Proposal | dams at their crest, pools at their level, pressure mains, tunnels, pump houses and trunk stages |

Operating works are solid; works under construction are tinted towards amber;
planned or proposed works are translucent. The 3D models chip in Settings turns
the whole layer off, and the timeline filters it by year like the 2D works.
Works at approximate positions (a village standing in for the structure) have
no 3D model; their dotted ring stays the only mark.

**All 3D shapes are generic stand-ins, not as-built drawings.** The listed
heights come from the sources in [DATA_SOURCES.md](DATA_SOURCES.md) section 8b,
where each caveat is spelled out. Where a height is unknown, a dam is drawn 15 m
high in a lighter colour. Barrage piers and gates are schematic, and tunnels are
drawn at the surface along their OpenStreetMap line. Reservoir levels are read
from the terrain, not surveyed full levels. Pump houses are generic buildings
and several real ones are underground. The Kaleshwaram climb of about 500 m
(Medigadda to Konda Pochamma Sagar) is terrain at the structures, not the pumped
head or the water levels.

### Sketch a canal

The "Sketch" chip in the map tools turns on [mapbox-gl-draw](https://github.com/mapbox/mapbox-gl-draw) with only
its line and bin buttons, in a Sketch card in the Details drawer. Click vertices, double-click to finish; dragging a vertex or deleting the
line updates the card, "Clear" removes it, and switching the chip off leaves
no layers behind. If the plugin script from the Mapbox CDN fails to load, the chip
stays off and the Sketch card says so. For the line it shows the length in km (haversine over the
vertices), an elevation profile read from the Terrain-DEM every 500 m (it
fits the line in view and says "terrain still loading" until every sample
is a number), start and end elevation, net fall and highest point, and a
verdict under the proposal model's norms (`norms` in `web/data/proposal.json`):
gravity is feasible when the end is lower than the start by the canal fall
plus the stage loss and no ground stands more than the tunnel cover above
the falling water line; otherwise it gives the lift needed (highest point
minus start plus those losses) and the stretches that would need a tunnel
(ground above the water line by more than the tunnel cover) or a deep cut
(more than the cut cover). It also lists the districts crossed and the
tanks within 2 km. Layer popups are hidden while the tool is on, since
clicks place vertices. The sketch is a screening check, a planning-sketch
tool, not a design. `web_sketch_test.py` runs the tool headless.

### Settings and About

Settings holds the exaggeration slider and the layer chips (contours, elevation
bands, place labels, district lines, flow animation, 3D models); on phones it
also holds the scene switch and About & sources. About & sources is the sheet
with every caveat in full, and the credits line of the map.

### Fonts

Panels use Inter (Google Fonts); map labels use Mapbox's DIN Pro. To set the
labels in Inter too, create a secret token with the `fonts:write` scope at
account.mapbox.com, put it in `MAPBOX_SECRET_TOKEN` (or `MAPBOX_ALL_ACCESS_TOKEN`, which
`upload_font.py` uses when the first is not set) and run `python upload_font.py`. It downloads Inter Regular, Medium and Bold from the
official rsms/inter release, uploads them to your Mapbox account through the
Fonts API and writes `web/data/fonts.json`; with that file present the map asks
for `Inter Medium` (label font constant `LABEL_FONT` in `web/app.js`), without
it DIN Pro stays. `serve.py` answers `data/fonts.json` and `data/tilesets.json` with an
empty `{}` while they do not exist, so the default page load logs no console errors; a
static host without that fallback (GitHub Pages) logs a harmless 404 for each file.
`tilesets.json` is read once, by a synchronous request at load (the style needs it at once).

State on 29 October 2026: `upload_font.py` was run against the account `tecgeor` and Inter Regular, Medium and
Bold are in its fonts list; `web/data/fonts.json` (`{"inter": true, ...}`) was written, and with it the map asks for
`Inter Medium` and the glyph requests answer 200. The first attempt failed with 422 "not supported or may be
corrupt" because the Fonts API wants the font file as the raw request body
(`Content-Type: application/octet-stream`), not a multipart form; the script now sends it that way.
Worth knowing: the map's glyph URL names the `mapbox` account (`mapbox://fonts/mapbox/{fontstack}`), and Mapbox
answered a request for `Inter Medium` there, and under any other account name and with no token, with the same
bytes (checked by md5 of glyph range 0-255), so Mapbox already serves Inter Medium to everyone and the upload was
not needed for the map as it is configured. Whether the uploaded copy is ever the one served was not determined.
`fonts.json` and `tilesets.json` are generated and git-ignored (`web/data/`): a fresh clone has neither, so the
map falls back to DIN Pro and to the GeoJSON files until you run the scripts here or copy the two files over.

### Camera

During a river flight the field of view narrows to 28 degrees (the `fov` camera
option, experimental in Mapbox GL JS 3.28 and later) and returns to the
previous value when the flight stops. The opening flight starts at zoom 5.2,
looking straight down from above the state, and settles at the home view.

Everything in `web/` is served as static files. The browser fetches Mapbox GL
JS, the Standard basemap, the Terrain-DEM tiles and the label fonts from Mapbox
(one map load per visit, free up to 50,000 a month) and the panel fonts from
Google.

## forge3d (native)

```powershell
uv run python view.py                 # native viewer window + console prompt
uv run python block.py                # path-traced block -> out/telangana_block.png
uv run python block.py --interactive  # rotate the block in the viewer
```

In the native viewer, left-drag orbits, the wheel zooms, W/A/S/D tilt and
rotate. It has no mouse pan, so type a place name at the prompt, `all`, `list`,
`x 60` (exaggeration, `x auto` to reset) or `q`.

## Rebuild the data

```powershell
uv run python fetch_data.py       # downloads into data/raw (~250 MB); the small OSM, Wikipedia
                                  # and Wikidata snapshots are committed, so only the big
                                  # stable files (DEM, HydroRIVERS, boundaries, GLAD) are fetched
uv run python prepare_data.py     # mosaic, reproject, clip -> data/
uv run python make_overlay.py     # map colours and lines -> data/overlay.png (forge3d)
uv run python build_web_data.py   # profiles, contours, layers -> web/data (and Terrarium tiles -> web/tiles, no longer used by the map);
                                  # also web/data/reservoirs.geojson, web/data/conduits.geojson (the 3D works)
                                  # and web/data/flow_bubbles.geojson (the canvas bubbles, reaches of 300 m³/s or more)
uv run python propose_water.py    # the Proposal view: reservoir sites, routes, pump houses -> web/data/proposal.*
uv run python web_smoke_test.py   # headless Edge check of the web map -> out/web_home.png
uv run python web_sketch_test.py  # headless Edge check of the Sketch tool -> out/web_sketch.png
uv run python web_ui_test.py      # headless Edge check of the lenses, drawer, timeline and settings
uv run python web_phase3_test.py  # headless Edge check of the Follow the water tour, fly-to and the proposal
```

## Publish to GitHub Pages

The site is the `web/` folder as built above (without `tiles/`, which the
Mapbox build no longer reads), pushed to the `gh-pages` branch together with
`.github/workflows/pages.yml` and a `.nojekyll` file. On every push to
`gh-pages` that workflow writes `mapbox-token.js` from the repository secret
`MAPBOX_TOKEN` and deploys the folder with `actions/deploy-pages`, so the
token is never committed (it is still visible to visitors, as any browser
token is, which is why it must be URL-restricted). One-time setup in the repo
settings: *Secrets and variables → Actions → New repository secret*
`MAPBOX_TOKEN`, a public `pk.` token restricted to
`https://aimedtechgeek.github.io/*`; and *Pages → Source: GitHub Actions*.
After rebuilding `web/`, redeploy from the repo root:

```bash
git worktree add ../telangana3d-pages gh-pages          # once per clone
SRC=$(git rev-parse --short HEAD)
rm -rf ../telangana3d-pages/data ../telangana3d-pages/tiles
cp -r web/data web/index.html web/app.js web/ui.js web/three3d.js web/tour.js web/style.css web/tour.css ../telangana3d-pages/
mkdir -p ../telangana3d-pages/.github/workflows && cp .github/workflows/pages.yml ../telangana3d-pages/.github/workflows/
cd ../telangana3d-pages && git add -A && git commit -m "Deploy the built map from $SRC" && git push
```

Every URL in `web/` is relative, so the same files work locally and under the
project path.

### Hosted tiles

State on 29 October 2026, account `tecgeor`: both scripts have been run. Live (latest job `success`):
`tg-flow`, `tg-tanks`, `tg-tank_points`, `tg-canals` (republished with the numeric `year` property the timeline
needs), `tg-contours`, `tg-districts`, `tg-state`, `tg-groundwater`.
**Not live: `tg-mask`.** Its job (the world-minus-state polygon) ran for over an hour and then failed with "Error
processing tileset ..., Please contact support", so `mask` is left out of `tilesets.json` and the map keeps its
GeoJSON; republishing it (`publish_tilesets.py mask`) was not retried. The tileset ids and the files
`web/data/tilesets.json` and `web/data/fonts.json` are generated and git-ignored: a fresh clone has neither and
needs `publish_tilesets.py` and `upload_font.py` run with your own tokens, or a copy of
those two files from a checkout that has them (the tilesets live in the `tecgeor` account, so the copied ids work
only where the Mapbox token can read that account's published tilesets; not tested with another token).

By default the map fetches about 18 MB of GeoJSON at boot. `publish_tilesets.py`
instead uploads the static layers to Mapbox as vector tilesets (Mapbox Tiling
Service) so the map loads only the tiles in view:

```bash
export MAPBOX_SECRET_TOKEN=sk....        # secret token with tilesets:read, tilesets:write, tilesets:list
                                         # (MAPBOX_ALL_ACCESS_TOKEN is used when MAPBOX_SECRET_TOKEN is not set)
uv run python publish_tilesets.py        # or name layers: publish_tilesets.py flow tanks
```

It covers `flow`, `tanks`, `tank_points`, `canals`, `contours`, `districts`,
`mask`, `state` and `groundwater` (zoom 5 to 12, simplified harder at low
zoom), publishes each as `<username>.tg-<layer>`, waits for the job and writes
`web/data/tilesets.json` (layer to `mapbox://` url and source layer). The user
name is read from the public token (`MAPBOX_TOKEN`, JWT field `u`) or given
with `--username`. Without the secret token the script exits with code 2.
The converter adds a numeric `year` property to the `canals` features (era
"after" = 2015, "before" = 1970) that the timeline filters on: **tilesets
published before this change lack it, so republish `canals`
(`publish_tilesets.py canals`) or the timeline hides every canal on the
hosted-tiles path.** The links are always GeoJSON, so they get theirs at load.

The map reads `data/tilesets.json` at boot: present, the mapped layers become
`vector` sources; absent, everything loads from GeoJSON exactly as before, so
deleting the file switches back. `links` and `proposal` always stay GeoJSON
(they need `lineMetrics` and change often); flow, tank counts, district label
points and the proposal are still fetched as small JSON where the panels
need them. `web/data/` is git-ignored, so copy `tilesets.json` along with the
rest when you redeploy. Re-run the script after rebuilding the data. Free tier
and terms: DATA_SOURCES.md, section 1c.

## Data and choices

Full provenance, licences, access dates and processing notes for every dataset
are in [DATA_SOURCES.md](DATA_SOURCES.md). The sources that could not be reached,
and what stands in for them, are listed by topic in
[README_UNREACHABLE_SOURCES.md](README_UNREACHABLE_SOURCES.md).

| Item | Source / value |
|---|---|
| Elevation | Copernicus GLO-90 DSM (AWS open data), smoothed (σ = 1 px); 200 m grid for forge3d, the river profiles, city heights and the proposal model. The web map's 3D surface, hillshade, relief tint and cursor readout come from Mapbox Terrain-DEM v1, so the readout always matches the surface drawn (Hyderabad reads 504 m there against 508 m in the Copernicus list) |
| State and 33 districts | geoBoundaries gbOpen India ADM1/ADM2 |
| Rivers | Natural Earth 10m centrelines (profiles, names) |
| River flow | HydroRIVERS v1.0 (HydroSHEDS): `DIS_AV_CMS`, the long-term average *naturalised* discharge from the WaterGAP model, i.e. before dams and irrigation withdrawals; reaches ≥ 1 m³/s. Per-district values are length-weighted means of the main stem inside the district |
| Cities | OpenStreetMap `place=city`, plus towns with population ≥ 40 000 (Overpass API); elevation = median DSM within 1 km |
| River profiles | DSM 10th percentile within 1.4 km of the centreline every 2 km, median-filtered, then capped so the bed never rises downstream (the coarse line strays onto the valley sides in the Krishna's Nallamala gorge) |
| Dams and barrages | Wikipedia: every page linked from "List of dams and reservoirs in Telangana" (plus the border dams and Kaleshwaram barrages) that has a dam infobox with coordinates; proposed or unfinished ones are skipped. Height = the infobox `dam_height` (above river bed), or height above foundation when that is all the page gives |
| Projection | Web Mercator for the web map; Lambert Conformal Conic for forge3d |
| Vertical exaggeration | Web: 3× default (1–6×); forge3d map 50×/30×/20× by zoom; block 12× |

Notes:
- geoBoundaries still has `Warangal (R)` and `Warangal (U)`. In August 2021
  they became Warangal and Hanumakonda, and some mandals moved between them,
  so the names *and* the shared boundary of these two districts may predate
  that change. Names are shown as published, except the source's `Hydrabad`
  typo, which is corrected.
- The DSM includes trees and buildings, so city values can sit a few metres
  above street level, and river beds are approximate.
- Flow figures are modelled long-term averages, not gauge readings: actual
  flow varies hugely between monsoon and dry season and is reduced by the
  Sriram Sagar, Nagarjuna Sagar and other projects.
- Dam heights are whatever the Wikipedia infobox states and are not all
  measured the same way; the Kaleshwaram barrages (Medigadda, Annaram,
  Sundilla) and the new Kaleshwaram reservoirs have no published height, so
  their labels carry none. Years are construction start and opening (no
  source records a proposal year); the smaller Kaleshwaram "online storages"
  are missing because nothing publishes their coordinates (see DATA_SOURCES.md).
- The forge3d viewer DEM uses a local grid (1 unit = 20 m) because the viewer
  clamps mouse-wheel zoom to a 100–50 000 unit radius.
- The block render is downsampled to 400 m and rendered in 800 px tiles to fit
  the path tracer's 512 MB budget.

# Telangana 3D terrain

Interactive 3D relief map of Telangana in the browser (elevation above sea
level, Godavari and Krishna river profiles, city elevations), plus a
path-traced 3D terrain block and a native forge3d viewer.

## Web map (MapLibre, runs locally)

```powershell
uv run python serve.py      # http://127.0.0.1:8765/ opens in your browser
```

- 3D terrain with hillshade and a colour scale in metres above sea level
- Hover anywhere for the elevation under the cursor, shown as a stack of
  landmark silhouettes for scale (Gateway of India 26 m, Charminar 56 m,
  Qutub Minar 73 m, Statue of Unity 182 m)
- **River flow:** every stream drawn by its long-term average discharge
  (HydroRIVERS): wider, darker and faster-moving dashes mean more water
  collected upstream. Hover a stream for its m³/s and catchment area; peak
  markers show where the Godavari and Krishna carry the most water; a list
  gives the average flow of each river through every district it crosses
- **Water links:** orange lines show how water is moved between the
  structures by Kaleshwaram, the Sriram Sagar canals, the Srisailam Left Bank
  Canal, Kalwakurthy and Palamuru-Rangareddy. Operating links carry moving
  chevrons in the direction of flow; links still being built are dashed with
  a work-in-progress cone. Click a link (on the map or in the list) for its
  status, years (planned, construction, first water, complete), terrain
  heights at both ends, straight-line distance and source. Lines are
  schematic, not real canal alignments
- Godavari and Krishna river-bed and flow profiles through the state; hover or
  drag the slider to follow the river on the map, click to fly there
- Dams (arch icon) and barrages (gated-deck icon), including the Kaleshwaram
  barrages and its Mallanna Sagar, Konda Pochamma Sagar and Ranganayaka Sagar
  reservoirs. Labels show name and gross capacity; clicking one zooms in and
  opens a popup with height, construction-start–opening years, the average
  river inflow at that point (HydroRIVERS) and capacity
- 27 cities and towns ranked by elevation, with the lowest river beds for
  comparison; click one to fly to it
- A "View & filters" card on the right groups the controls: Terrain
  (exaggeration, hillshade, contours), Layers (districts, place labels, flow
  animation, dams), the dams' opening-year filter (before / from 2014) and
  Navigation (drag mode, orbit, reset). Light/dark theme follows the OS
  setting; the toggle in the left panel overrides it
- Mouse: left-drag pans (switch "Left-drag" to *Rotates* for a full 360° orbit
  with tilt), right-drag or Ctrl-drag always rotates and tilts, scroll zooms

Everything is served from `web/` (no API keys, no internet needed after the
build apart from the MapLibre and font CDNs).

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
uv run python fetch_data.py       # downloads into data/raw (~210 MB)
uv run python prepare_data.py     # mosaic, reproject, clip -> data/
uv run python make_overlay.py     # map colours and lines -> data/overlay.png (forge3d)
uv run python build_web_data.py   # terrain tiles, profiles, contours -> web/ (~120 MB)
uv run python web_smoke_test.py   # headless Edge check of the web map -> out/web_home.png
```

## Data and choices

Full provenance, licences, access dates and processing notes for every dataset
are in [DATA_SOURCES.md](DATA_SOURCES.md).

| Item | Source / value |
|---|---|
| Elevation | Copernicus GLO-90 DSM (AWS open data), smoothed (σ = 1 px); 200 m grid for forge3d, Terrarium tiles z5–11 for the web map |
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

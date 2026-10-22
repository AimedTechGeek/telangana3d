# Telangana 3D terrain

Interactive 3D relief map of Telangana in the browser (elevation above sea
level, Godavari and Krishna river profiles, city elevations), plus a
path-traced 3D terrain block and a native forge3d viewer.

## Web map (MapLibre, runs locally)

```powershell
uv run python serve.py      # http://127.0.0.1:8765/ opens in your browser
```

- 3D terrain with hillshade and a colour scale in metres above sea level
- Hover anywhere for the elevation under the cursor
- Godavari and Krishna river-bed profiles through the state; hover or drag the
  slider to follow the river on the map, click to fly there
- 27 cities and towns ranked by elevation, with the lowest river beds for
  comparison; click one to fly to it
- Vertical exaggeration slider, 100 m contours, district lines, labels, orbit,
  light/dark theme (follows the OS setting; the toggle overrides it)
- Mouse: drag to pan, scroll to zoom, right-drag or Ctrl-drag to tilt and rotate

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

| Item | Source / value |
|---|---|
| Elevation | Copernicus GLO-90 DSM (AWS open data), smoothed (σ = 1 px); 200 m grid for forge3d, Terrarium tiles z5–11 for the web map |
| State and 33 districts | geoBoundaries gbOpen India ADM1/ADM2 |
| Rivers | Natural Earth 10m centrelines |
| Cities | OpenStreetMap `place=city`, plus towns with population ≥ 40 000 (Overpass API); elevation = median DSM within 1 km |
| River profiles | DSM 10th percentile within 1.4 km of the centreline every 2 km, median-filtered, then capped so the bed never rises downstream (the coarse line strays onto the valley sides in the Krishna's Nallamala gorge) |
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
- The forge3d viewer DEM uses a local grid (1 unit = 20 m) because the viewer
  clamps mouse-wheel zoom to a 100–50 000 unit radius.
- The block render is downsampled to 400 m and rendered in 800 px tiles to fit
  the path tracer's 512 MB budget.

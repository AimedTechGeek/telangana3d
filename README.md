# Telangana 3D terrain

An interactive 3D terrain map of Telangana and a 3D terrain block, made with
[forge3d](https://github.com/milos-agathon/forge3d).

## Run

```powershell
uv run python view.py               # interactive map
uv run python block.py              # path-traced block -> out/telangana_block.png
uv run python block.py --interactive  # rotate the block in the viewer
```

**Interactive map** — left-drag orbits, mouse wheel zooms, W/A/S/D tilt and rotate.
forge3d's terrain viewer has no mouse pan, so type a place in the console to fly
there: a city (`Hyderabad`, `Warangal`, `Karimnagar`, `Nizamabad`, `Khammam`),
any of the 33 district names, `all` for the whole state, `list`, or `q`.
`x 60` sets the vertical exaggeration (1–150); `x auto` goes back to the
zoom-based default (50× state, 30× district, 20× city).

## Rebuild the data

```powershell
uv run python fetch_data.py    # downloads into data/raw (~210 MB)
uv run python prepare_data.py  # mosaic, reproject, clip -> data/
uv run python make_overlay.py  # map colours and lines -> data/overlay.png
uv run python view.py --snapshots out   # optional check stills
```

## Data and choices

| Item | Source / value |
|---|---|
| Elevation | Copernicus GLO-90 DSM (AWS open data), resampled to 200 m, smoothed (σ = 1 px) |
| State and 33 districts | geoBoundaries gbOpen India ADM1/ADM2 |
| Rivers, cities | Natural Earth 10m (5 cities fall inside the state) |
| Projection | Lambert Conformal Conic centred on Telangana |
| Vertical exaggeration | Map: 50× / 30× / 20× by zoom level, adjustable; block: 12× (the plateau spans ~13–880 m over ~470 km) |

Notes:
- geoBoundaries still has `Warangal (R)` and `Warangal (U)`. In August 2021
  they became Warangal and Hanumakonda, and some mandals moved between them,
  so the names *and* the shared boundary of these two districts may predate
  that change. Names are shown as published, except the source's `Hydrabad`
  typo, which is corrected.
- The viewer DEM uses a local grid (1 unit = 20 m) because the viewer clamps
  mouse-wheel zoom to a 100–50 000 unit radius.
- The block render is downsampled to 400 m and rendered in 800 px tiles to fit
  the path tracer's 512 MB budget. Its walls are the heightfield's cliff edges
  down to the floor, not a separate mesh.

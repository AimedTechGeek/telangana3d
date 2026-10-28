"""Rasterise the river reaches into a two-band velocity GeoTIFF for Mapbox raster-particle.

    uv run python build_flow_raster.py      # web/data/flow.geojson -> data/flow_velocity.tif

Band 1 = u (east), band 2 = v (north), in EPSG:3857, about 250 m per pixel over the
map's extent. Each reach is painted along its length (centreline pixel plus a
1-pixel buffer) with the unit downstream direction times a speed that grows with
log10(discharge). HydroRIVERS lines are digitised downstream, which is the
direction build_web_data.py keeps in flow.geojson. Pixels off the rivers are 0.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

ROOT = Path(__file__).parent
FLOW = ROOT / "web" / "data" / "flow.geojson"
OUT = ROOT / "data" / "flow_velocity.tif"
BOUNDS = (77.0, 15.0, 82.0, 20.0)       # the map's DEM extent, lon/lat
PIXEL_M = 250.0
NODATA = -9999.0                        # declared for readers; every pixel is written (0 off the rivers)


def speed_for(q: float) -> float:
    """Raster speed units: 1 at 1 m3/s, 5 at 100, 7 at 1,000, 9 at 10,000. The layer's max-speed is 10."""
    return 1.0 + 2.0 * float(np.log10(max(q, 1.0)))


def main() -> None:
    to_mercator = Transformer.from_crs(4326, 3857, always_xy=True)
    west, south = to_mercator.transform(BOUNDS[0], BOUNDS[1])
    east, north = to_mercator.transform(BOUNDS[2], BOUNDS[3])
    width, height = int(round((east - west) / PIXEL_M)), int(round((north - south) / PIXEL_M))
    transform = from_origin(west, north, (east - west) / width, (north - south) / height)
    u = np.zeros((height, width), dtype="float32")
    v = np.zeros((height, width), dtype="float32")
    painted = np.zeros((height, width), dtype="float32")     # discharge already painted: the bigger river wins a crossing

    features = json.loads(FLOW.read_text(encoding="utf-8"))["features"]
    for feature in sorted(features, key=lambda f: f["properties"]["q"]):
        q = feature["properties"]["q"]
        speed = speed_for(q)
        geometry = feature["geometry"]
        lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        for coords in lines:
            xs, ys = to_mercator.transform([c[0] for c in coords], [c[1] for c in coords])
            for x0, y0, x1, y1 in zip(xs[:-1], ys[:-1], xs[1:], ys[1:]):
                length = float(np.hypot(x1 - x0, y1 - y0))
                if length == 0:
                    continue
                direction = ((x1 - x0) / length, (y1 - y0) / length)
                steps = max(2, int(length / (PIXEL_M / 2)) + 1)
                along = np.linspace(0, 1, steps)
                cols = ((x0 + (x1 - x0) * along - west) / (east - west) * width).astype(int)
                rows = ((north - (y0 + (y1 - y0) * along)) / (north - south) * height).astype(int)
                for col, row in zip(cols, rows):
                    r0, r1, c0, c1 = max(row - 1, 0), min(row + 2, height), max(col - 1, 0), min(col + 2, width)
                    if r0 >= r1 or c0 >= c1:
                        continue
                    block = painted[r0:r1, c0:c1]
                    mask = block <= q
                    block[mask] = q
                    u[r0:r1, c0:c1][mask] = direction[0] * speed
                    v[r0:r1, c0:c1][mask] = direction[1] * speed

    OUT.parent.mkdir(exist_ok=True)
    with rasterio.open(OUT, "w", driver="GTiff", height=height, width=width, count=2, dtype="float32",
                       crs="EPSG:3857", transform=transform, nodata=NODATA, compress="deflate") as dst:
        dst.write(u, 1)
        dst.write(v, 2)
        dst.set_band_description(1, "u")
        dst.set_band_description(2, "v")
    nonzero = int(np.count_nonzero((u != 0) | (v != 0)))
    print(f"{OUT.name}: bands 2, CRS EPSG:3857, {transform.a:.0f} x {-transform.e:.0f} m, "
          f"{width} x {height} px, {nonzero} non-zero pixels, speed max {float(np.hypot(u, v).max()):.1f}")


if __name__ == "__main__":
    main()

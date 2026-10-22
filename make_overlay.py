"""Paint the map overlay draped on the terrain: elevation tint, dimmed
surroundings, district and state boundaries, rivers and city dots.

Output: data/overlay.png, pixel-registered to data/telangana_dem.tif at
OVERSAMPLE x its resolution (UV 0..1 covers the DEM extent exactly).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image, ImageDraw
from rasterio.features import geometry_mask
from shapely.geometry.base import BaseGeometry

DATA = Path(__file__).parent / "data"
OVERSAMPLE = 2

# Hypsometric tint, elevation in metres.
TINT_STOPS = [
    (0, "#3f7f4a"), (150, "#6fa35a"), (300, "#a9c37a"),
    (450, "#e0d79a"), (600, "#c9a36b"), (750, "#9c7650"), (900, "#f2ece2"),
]
OUTSIDE_FADE = 0.65          # blend toward OUTSIDE_COLOR outside the state
OUTSIDE_COLOR = (236, 236, 232)
DISTRICT_LINE = ((60, 60, 60), 3)
STATE_LINE = ((25, 25, 25), 10)
STATE_HALO = ((255, 255, 255), 18)
RIVER_COLOR = (36, 110, 185)
MAJOR_RIVERS = {"Godavari": 7, "Krishna": 7}
MINOR_RIVER_WIDTH = 4
CITY_RADIUS = 9


def tint(dem: np.ndarray) -> np.ndarray:
    top = TINT_STOPS[-1][0]
    cmap = LinearSegmentedColormap.from_list(
        "hypso", [(elev / top, color) for elev, color in TINT_STOPS]
    )
    return (cmap(np.clip(dem / top, 0.0, 1.0))[..., :3] * 255).astype(np.uint8)


def to_pixels(geom: BaseGeometry, inverse) -> list[list[tuple[float, float]]]:
    """Return pixel-space rings/paths for any (multi)line or (multi)polygon."""
    parts = getattr(geom, "geoms", [geom])
    paths = []
    for part in parts:
        rings = [part.exterior, *part.interiors] if part.geom_type == "Polygon" else [part]
        for ring in rings:
            paths.append([inverse * xy for xy in ring.coords])
    return paths


def draw_lines(draw: ImageDraw.ImageDraw, geoms, inverse, color, width: int) -> None:
    for geom in geoms:
        for path in to_pixels(geom, inverse):
            draw.line(path, fill=color, width=width, joint="curve")


def main() -> None:
    with rasterio.open(DATA / "telangana_dem.tif") as src:
        dem = src.read(1, out_shape=(src.height * OVERSAMPLE, src.width * OVERSAMPLE))
        transform = src.transform * src.transform.scale(1 / OVERSAMPLE)

    state = gpd.read_file(DATA / "state.geojson")
    districts = gpd.read_file(DATA / "districts.geojson")
    rivers = gpd.read_file(DATA / "rivers.geojson")
    cities = gpd.read_file(DATA / "cities.geojson")

    rgb = tint(dem).astype(np.float32)
    outside = geometry_mask(state.geometry, out_shape=dem.shape, transform=transform)
    rgb[outside] = rgb[outside] * (1 - OUTSIDE_FADE) + np.array(OUTSIDE_COLOR) * OUTSIDE_FADE
    image = Image.fromarray(rgb.astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(image)
    inverse = ~transform

    draw_lines(draw, districts.boundary, inverse, *DISTRICT_LINE)
    draw_lines(draw, state.boundary, inverse, *STATE_HALO)
    draw_lines(draw, state.boundary, inverse, *STATE_LINE)
    # Rivers go on top: the Krishna and Godavari form long stretches of the state border.
    for _, river in rivers.iterrows():
        width = MAJOR_RIVERS.get(river["name"], MINOR_RIVER_WIDTH)
        draw_lines(draw, [river.geometry], inverse, RIVER_COLOR, width)
    for point in cities.geometry:
        col, row = inverse * (point.x, point.y)
        r = CITY_RADIUS
        draw.ellipse([col - r, row - r, col + r, row + r], fill=(255, 255, 255), outline=(20, 20, 20), width=3)

    image.save(DATA / "overlay.png", optimize=True)
    print(f"overlay {image.size[0]}x{image.size[1]} -> {DATA / 'overlay.png'}")


if __name__ == "__main__":
    main()

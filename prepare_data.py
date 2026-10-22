"""Turn data/raw/ downloads into analysis-ready Telangana layers in data/.

Outputs (all in the Telangana Lambert Conformal Conic CRS below):
- telangana_dem.tif          full rectangle around the state (interactive map)
- telangana_dem_clipped.tif  same grid, NaN outside the state (3D block)
- telangana_viewer_dem.tif   same heights in a local grid for forge3d's viewer (see below)
- state.geojson, districts.geojson, rivers.geojson, cities.geojson
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

# Conformal conic centred on the state keeps distances and shapes honest
# across its ~4 degrees of latitude and longitude.
TARGET_CRS = "+proj=lcc +lat_1=16.5 +lat_2=19.5 +lat_0=17.9 +lon_0=79.3 +datum=WGS84 +units=m +no_defs"
PIXEL_SIZE_M = 200.0
SMOOTHING_SIGMA_PX = 1.0
MARGIN_DEG = 0.15
STATE_ISO = "IN-TG"
EXPECTED_DISTRICTS = 33
# forge3d's terrain viewer clamps mouse-wheel zoom to a 100..50000 world-unit
# orbit radius. In metres the state (~470 km) cannot be framed, so the viewer
# DEM uses 10 units per pixel (1 unit = 20 m). Heights stay in metres, so a
# viewer z_scale of 1.0 is a 20x vertical exaggeration.
VIEWER_UNITS_PER_PIXEL = 10.0
RIVER_NAMES = ("Godavari", "Krishna", "Indravati", "Wainganga", "Tungabhadra", "Bhima")


def load_state() -> gpd.GeoDataFrame:
    states = gpd.read_file(RAW / "india_adm1.geojson")
    state = states[states.shapeISO == STATE_ISO]
    if len(state) != 1:
        raise ValueError(f"Expected one {STATE_ISO} feature, found {len(state)}")
    return state[["shapeName", "geometry"]]


def load_districts(state: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    districts = gpd.read_file(RAW / "india_adm2.geojson")
    inside = districts.representative_point().within(state.geometry.iloc[0])
    districts = districts[inside][["shapeName", "geometry"]].copy()
    if len(districts) != EXPECTED_DISTRICTS:
        raise ValueError(f"Expected {EXPECTED_DISTRICTS} districts, found {len(districts)}")
    # geoBoundaries misspells the capital district.
    districts["shapeName"] = districts["shapeName"].replace({"Hydrabad": "Hyderabad"})
    return districts


def read_zipped(name: str) -> gpd.GeoDataFrame:
    with zipfile.ZipFile(RAW / name) as archive:
        shp = next(n for n in archive.namelist() if n.endswith(".shp"))
    return gpd.read_file(f"zip://{(RAW / name).as_posix()}!{shp}")


def load_rivers(bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    rivers = read_zipped("rivers.zip").cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
    # name_en is ASCII; name carries diacritics (e.g. "Godävari").
    rivers = rivers[rivers["name_en"].isin(RIVER_NAMES)]
    return rivers[["name_en", "geometry"]].rename(columns={"name_en": "name"}).clip(bounds)


def load_cities(state: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    places = read_zipped("places.zip")
    cities = places[places.within(state.geometry.iloc[0])]
    return cities[["NAME", "POP_MAX", "geometry"]].rename(columns={"NAME": "name", "POP_MAX": "population"})


def mosaic_and_reproject(bounds: tuple[float, float, float, float]) -> tuple[np.ndarray, dict]:
    sources = [rasterio.open(p) for p in sorted((RAW / "dem").glob("*.tif"))]
    try:
        mosaic, mosaic_transform = merge(sources, bounds=bounds)
        src_crs = sources[0].crs
    finally:
        for src in sources:
            src.close()
    height, width = mosaic.shape[1:]
    transform, out_w, out_h = calculate_default_transform(
        src_crs, TARGET_CRS, width, height, *bounds, resolution=PIXEL_SIZE_M
    )
    dem = np.full((out_h, out_w), np.nan, dtype=np.float32)
    reproject(
        mosaic[0].astype(np.float32), dem,
        src_transform=mosaic_transform, src_crs=src_crs,
        dst_transform=transform, dst_crs=TARGET_CRS,
        resampling=Resampling.bilinear, dst_nodata=np.nan,
    )
    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1, "width": out_w, "height": out_h,
        "crs": TARGET_CRS, "transform": transform, "nodata": np.nan, "compress": "deflate",
    }
    return dem, profile


def clean_dem(dem: np.ndarray) -> np.ndarray:
    """Fill reprojection NaN wedges at the rectangle corners, clamp DSM
    artefacts below sea level (a few dozen pixels over reservoirs) to 0 m,
    and lightly smooth surface noise (trees, buildings) that the vertical
    exaggeration would otherwise turn into spikes."""
    dem = np.maximum(dem, 0.0)
    dem = np.where(np.isfinite(dem), dem, np.nanmin(dem))
    return gaussian_filter(dem, sigma=SMOOTHING_SIGMA_PX).astype(np.float32)


def write_tif(path: Path, data: np.ndarray, profile: dict) -> None:
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def main() -> None:
    state = load_state()
    minx, miny, maxx, maxy = state.total_bounds
    bounds = (minx - MARGIN_DEG, miny - MARGIN_DEG, maxx + MARGIN_DEG, maxy + MARGIN_DEG)

    districts = load_districts(state)
    rivers = load_rivers(bounds)
    cities = load_cities(state)

    dem, profile = mosaic_and_reproject(bounds)
    dem = clean_dem(dem)
    state_proj = state.to_crs(TARGET_CRS)
    outside = geometry_mask(state_proj.geometry, out_shape=dem.shape, transform=profile["transform"])
    write_tif(OUT / "telangana_dem.tif", dem, profile)
    write_tif(OUT / "telangana_dem_clipped.tif", np.where(outside, np.nan, dem).astype(np.float32), profile)
    viewer_profile = {**profile, "crs": None,
                      "transform": rasterio.Affine(VIEWER_UNITS_PER_PIXEL, 0, 0, 0, -VIEWER_UNITS_PER_PIXEL, 0)}
    write_tif(OUT / "telangana_viewer_dem.tif", dem, viewer_profile)

    state_proj.to_file(OUT / "state.geojson", driver="GeoJSON")
    for name, layer in (("districts", districts), ("rivers", rivers), ("cities", cities)):
        layer.to_crs(TARGET_CRS).to_file(OUT / f"{name}.geojson", driver="GeoJSON")

    inside = dem[~outside]
    print(f"DEM grid {dem.shape[1]}x{dem.shape[0]} @ {PIXEL_SIZE_M:.0f} m")
    print(f"Elevation inside state: min {inside.min():.0f} m, max {inside.max():.0f} m")
    print(f"Districts {len(districts)}, rivers {sorted(set(rivers['name']))}")
    print(f"Cities {len(cities)}: {sorted(cities['name'])}")


if __name__ == "__main__":
    main()

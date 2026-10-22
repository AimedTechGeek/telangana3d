"""Build everything the web map (web/) loads: terrain tiles, vector layers,
city elevations, river profiles and contours.

    uv run python build_web_data.py

Inputs: data/raw/ (fetch_data.py) and data/ (prepare_data.py).
Outputs:
- web/tiles/{z}/{x}/{y}.png   Terrarium-encoded elevation tiles, zoom 5-11
- web/data/*.geojson          state, districts, district label points, rivers,
                              contours, outside-state mask (all WGS84)
- web/data/cities.json        OSM cities/towns with elevation above sea level
- web/data/rivers.json        Godavari and Krishna elevation + average flow profiles
- web/data/flow.geojson       HydroRIVERS reaches with modelled average discharge (m3/s)
- web/data/flow_summary.json  peak flow per river and average flow per district
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import zipfile
from pathlib import Path

import contourpy
import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from scipy.ndimage import gaussian_filter, median_filter
from shapely.geometry import LineString, MultiLineString, Point, box, mapping
from shapely.ops import linemerge, unary_union

from prepare_data import TARGET_CRS, read_zipped

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
DATA = ROOT / "data"
WEB = ROOT / "web"
TILES = WEB / "tiles"
WEB_DATA = WEB / "data"
WGS84 = "EPSG:4326"
MERCATOR = "EPSG:3857"

MIN_ZOOM, MAX_ZOOM = 5, 11          # z11 = 76 m/px, close to the 90 m source
TILE_PX = 256
EARTH_CIRCUMFERENCE_M = 40075016.686
SOURCE_SMOOTH_SIGMA_PX = 1.0        # tames tree/building noise in the surface model
CONTOUR_SMOOTH_SIGMA_PX = 3.0
CONTOUR_INTERVAL_M = 100
CONTOUR_MIN_LENGTH_M = 3000.0
CONTOUR_SIMPLIFY_M = 120.0
PROFILE_STEP_M = 2000.0
PROFILE_RIVERS = ("Godavari", "Krishna")
RIVER_CORRIDOR_M = 15000.0          # keep river stretches this close to the state
RIVERBED_RADIUS_PX = 7              # 1.4 km at 200 m pixels around the coarse centreline
RIVERBED_PERCENTILE = 10            # low percentile = river bed, but ignores clamped reservoir pixels
PROFILE_MEDIAN_SAMPLES = 5          # drops single-sample spikes where the line leaves the channel
CITY_RADIUS_PX = 5                  # 1 km: median height = city level
CITY_MIN_POPULATION = 40000
CITY_NEAR_RIVER_M = 8000.0
EXCLUDED_PLACES = {"Secunderabad", "Mirjapur"}  # part of Hyderabad / mistagged node
PROFILE_DEM = DATA / "telangana_dem.tif"

# HydroRIVERS: DIS_AV_CMS is the long-term average naturalised discharge (m3/s,
# WaterGAP model), UPLAND_SKM the upstream catchment area.
HYDRORIVERS_ZIP = RAW / "hydrorivers_as.zip"
FLOW_BBOX = (76.5, 14.5, 82.5, 20.5)
FLOW_MIN_CMS = 1.0                  # drop the smallest streams (about 80 % of reaches)
FLOW_CLASS_CMS = (20.0, 300.0)      # small | medium | large, drives the animation speed
NAMED_RIVERS = ("Godavari", "Krishna", "Bhima", "Tungabhadra", "Indravati", "Wainganga")
NAME_MATCH_M = 4000.0               # both reach ends this close to the Natural Earth line
MAIN_STEM_MIN_ORDER = 6             # Strahler order; keeps short tributary mouths unnamed
PROFILE_FLOW_MATCH_M = 6000.0


# --- terrain tiles ----------------------------------------------------------

def tile_index(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_bounds_mercator(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    size = EARTH_CIRCUMFERENCE_M / 2 ** zoom
    half = EARTH_CIRCUMFERENCE_M / 2.0
    west, north = -half + x * size, half - y * size
    return west, north - size, west + size, north


def terrarium(elevation: np.ndarray) -> np.ndarray:
    value = np.clip(elevation, -32768.0, 32767.0) + 32768.0
    red = np.floor(value / 256.0)
    green = np.floor(value - red * 256.0)
    blue = np.floor((value - np.floor(value)) * 256.0)
    return np.dstack([red, green, blue]).astype(np.uint8)


def load_source_dem() -> tuple[np.ndarray, dict]:
    sources = [rasterio.open(p) for p in sorted((RAW / "dem").glob("*.tif"))]
    try:
        mosaic, transform = merge(sources)
        crs = sources[0].crs
    finally:
        for src in sources:
            src.close()
    dem = np.maximum(np.nan_to_num(mosaic[0], nan=0.0), 0.0)
    dem = gaussian_filter(dem, sigma=SOURCE_SMOOTH_SIGMA_PX).astype(np.float32)
    profile = {"driver": "GTiff", "dtype": "float32", "count": 1, "width": dem.shape[1],
               "height": dem.shape[0], "crs": crs, "transform": transform}
    return dem, profile


def write_tiles(dem: np.ndarray, profile: dict) -> int:
    if TILES.exists():
        shutil.rmtree(TILES)
    west, south, east, north = rasterio.transform.array_bounds(profile["height"], profile["width"], profile["transform"])
    count = 0
    with MemoryFile() as memory, memory.open(**profile) as src:
        src.write(dem, 1)
        for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
            x0, y0 = (int(v) for v in tile_index(west, north, zoom))
            x1, y1 = (int(v) for v in tile_index(east, south, zoom))
            resampling = Resampling.average if zoom < 10 else Resampling.bilinear
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    tile = np.zeros((TILE_PX, TILE_PX), dtype=np.float32)
                    reproject(rasterio.band(src, 1), tile,
                              dst_transform=from_bounds(*tile_bounds_mercator(x, y, zoom), TILE_PX, TILE_PX),
                              dst_crs=MERCATOR, dst_nodata=0.0, resampling=resampling)
                    target = TILES / str(zoom) / str(x) / f"{y}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(terrarium(tile), "RGB").save(target, compress_level=6)
                    count += 1
            print(f"zoom {zoom}: {(x1 - x0 + 1) * (y1 - y0 + 1)} tiles")
    return count


# --- vectors ----------------------------------------------------------------

def read_projected(name: str) -> gpd.GeoDataFrame:
    """data/*.geojson hold TARGET_CRS metres, but GeoJSON readers label them EPSG:4326."""
    return gpd.read_file(DATA / f"{name}.geojson").set_crs(TARGET_CRS, allow_override=True)


def write_geojson(gdf: gpd.GeoDataFrame, name: str) -> None:
    gdf.to_crs(WGS84).to_file(WEB_DATA / f"{name}.geojson", driver="GeoJSON")


def write_vectors(state: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> None:
    write_geojson(state, "state")
    write_geojson(districts, "districts")
    points = districts.copy()
    points["geometry"] = points.representative_point()
    write_geojson(points, "district_points")
    write_geojson(read_projected("rivers"), "rivers")
    world = box(-180.0, -85.0, 180.0, 85.0)
    mask = world.difference(state.to_crs(WGS84).geometry.iloc[0])
    gpd.GeoDataFrame({"geometry": [mask]}, crs=WGS84).to_file(WEB_DATA / "mask.geojson", driver="GeoJSON")


# --- elevation sampling -----------------------------------------------------

class DemSampler:
    """Window statistics on the projected 200 m DEM (metres above sea level)."""

    def __init__(self, path: Path) -> None:
        with rasterio.open(path) as src:
            self.heights = src.read(1)
            self.inverse = ~src.transform
            self.crs = src.crs
        self.to_dem = Transformer.from_crs(WGS84, self.crs, always_xy=True)

    def window(self, lon: float, lat: float, radius_px: int) -> np.ndarray | None:
        x, y = self.to_dem.transform(lon, lat)
        col, row = (int(v) for v in self.inverse * (x, y))
        rows, cols = self.heights.shape
        if not (radius_px <= row < rows - radius_px and radius_px <= col < cols - radius_px):
            return None
        return self.heights[row - radius_px:row + radius_px + 1, col - radius_px:col + radius_px + 1]

    def median(self, lon: float, lat: float, radius_px: int) -> float | None:
        window = self.window(lon, lat, radius_px)
        return None if window is None else float(np.median(window))

    def percentile(self, lon: float, lat: float, radius_px: int, percentile: float) -> float | None:
        window = self.window(lon, lat, radius_px)
        return None if window is None else float(np.percentile(window, percentile))


def parse_population(tags: dict) -> int:
    match = re.match(r"\d+", (tags.get("population") or "").replace(",", ""))
    return int(match.group()) if match else 0


def build_cities(sampler: DemSampler, districts: gpd.GeoDataFrame) -> list[dict]:
    elements = json.loads((RAW / "osm_places.json").read_text(encoding="utf-8"))["elements"]
    districts_wgs = districts.to_crs(WGS84)
    cities = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        population = parse_population(tags)
        if not name or name in EXCLUDED_PLACES:
            continue
        if tags["place"] != "city" and population < CITY_MIN_POPULATION:
            continue
        elevation = sampler.median(element["lon"], element["lat"], CITY_RADIUS_PX)
        if elevation is None:
            continue
        inside = districts_wgs[districts_wgs.contains(Point(element["lon"], element["lat"]))]
        cities.append({
            "name": name, "lon": round(element["lon"], 5), "lat": round(element["lat"], 5),
            "population": population, "place": tags["place"], "elev": round(elevation),
            "district": inside["shapeName"].iloc[0] if len(inside) else None,
        })
    cities.sort(key=lambda c: -c["elev"])
    return cities


# --- river profiles ---------------------------------------------------------

def river_centreline(name: str, corridor) -> LineString:
    """Merge Natural Earth segments of one river inside the corridor, ordered west to east."""
    rivers = gpd.read_file(f"zip://{(RAW / 'rivers.zip').as_posix()}!ne_10m_rivers_lake_centerlines.shp")
    parts = rivers[rivers["name_en"] == name].to_crs(TARGET_CRS).geometry
    merged = linemerge(unary_union(list(parts))).intersection(corridor)
    lines = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
    lines = [line for line in lines if not line.is_empty]
    # Both rivers run west to east through Telangana; orient every part that way.
    lines.sort(key=lambda line: line.bounds[0])
    coords: list[tuple[float, float]] = []
    for line in lines:
        points = list(line.coords)
        if points[0][0] > points[-1][0]:
            points.reverse()
        coords.extend(points)
    return LineString(coords)


def build_profiles(sampler: DemSampler, state: gpd.GeoDataFrame, cities: list[dict]) -> dict:
    corridor = state.to_crs(TARGET_CRS).geometry.iloc[0].buffer(RIVER_CORRIDOR_M)
    to_wgs = Transformer.from_crs(TARGET_CRS, WGS84, always_xy=True)
    profiles = {}
    for name in PROFILE_RIVERS:
        line = river_centreline(name, corridor)
        points = []
        for distance in np.arange(0.0, line.length, PROFILE_STEP_M):
            point = line.interpolate(distance)
            lon, lat = to_wgs.transform(point.x, point.y)
            elevation = sampler.percentile(lon, lat, RIVERBED_RADIUS_PX, RIVERBED_PERCENTILE)
            if elevation is not None:
                points.append({"d": round(distance / 1000.0, 1), "lon": round(lon, 5),
                               "lat": round(lat, 5), "elev": round(elevation)})
        elevations = median_filter([p["elev"] for p in points], size=PROFILE_MEDIAN_SAMPLES, mode="nearest")
        for point, elevation in zip(points, elevations):
            point["elev"] = int(elevation)
        # The filter cannot clean the ends; both lie in the corridor outside the state anyway.
        trim = PROFILE_MEDIAN_SAMPLES // 2
        points = points[trim:-trim]
        # Water only flows downhill: where the coarse centreline strays onto the valley
        # sides (the Krishna's Nallamala gorge) the bed is capped at the upstream level.
        for point, elevation in zip(points, np.minimum.accumulate([p["elev"] for p in points])):
            point["elev"] = int(elevation)
            point["d"] = round(point["d"] - points[0]["d"], 1)
        landmarks = []
        for city in cities:
            x, y = sampler.to_dem.transform(city["lon"], city["lat"])
            if line.distance(Point(x, y)) <= CITY_NEAR_RIVER_M:
                landmarks.append({"name": city["name"],
                                  "d": round(line.project(Point(x, y)) / 1000.0 - trim * PROFILE_STEP_M / 1000.0, 1)})
        elevations = [p["elev"] for p in points]
        profiles[name] = {
            "length_km": points[-1]["d"], "points": points,
            "min_elev": min(elevations), "max_elev": max(elevations),
            "landmarks": sorted(landmarks, key=lambda item: item["d"]),
        }
        print(f"{name}: {len(points)} samples over {line.length / 1000:.0f} km, "
              f"{max(elevations)} -> {min(elevations)} m, landmarks {[l['name'] for l in landmarks]}")
    return profiles


# --- river flow (HydroRIVERS) -----------------------------------------------

def load_reaches() -> gpd.GeoDataFrame:
    with zipfile.ZipFile(HYDRORIVERS_ZIP) as archive:
        shp = next(n for n in archive.namelist() if n.endswith(".shp"))
    reaches = gpd.read_file(f"zip://{HYDRORIVERS_ZIP.as_posix()}!{shp}", bbox=FLOW_BBOX)
    reaches = reaches[reaches["DIS_AV_CMS"] >= FLOW_MIN_CMS]
    return reaches[["HYRIV_ID", "DIS_AV_CMS", "UPLAND_SKM", "ORD_STRA", "DIST_DN_KM", "geometry"]].copy()


def name_reaches(reaches: gpd.GeoDataFrame) -> None:
    """Label reaches that follow a Natural Earth named river (HydroRIVERS has no names)."""
    named = read_zipped("rivers.zip")
    named = named[named["name_en"].isin(NAMED_RIVERS)].to_crs(TARGET_CRS)
    projected = reaches.to_crs(TARGET_CRS).geometry
    starts = projected.apply(lambda line: Point(line.coords[0]))
    ends = projected.apply(lambda line: Point(line.coords[-1]))
    reaches["name"] = None
    for river, group in named.groupby("name_en"):
        line = unary_union(list(group.geometry))
        close = (starts.distance(line) <= NAME_MATCH_M) & (ends.distance(line) <= NAME_MATCH_M)
        if river in PROFILE_RIVERS:
            close &= reaches["ORD_STRA"] >= MAIN_STEM_MIN_ORDER
        reaches.loc[close & reaches["name"].isna(), "name"] = river


def flow_class(discharge: float) -> int:
    return 1 if discharge < FLOW_CLASS_CMS[0] else 2 if discharge < FLOW_CLASS_CMS[1] else 3


def write_flow(reaches: gpd.GeoDataFrame) -> None:
    out = gpd.GeoDataFrame({
        "q": reaches["DIS_AV_CMS"].round(1), "up": reaches["UPLAND_SKM"].round().astype(int),
        "ord": reaches["ORD_STRA"], "cls": reaches["DIS_AV_CMS"].apply(flow_class), "name": reaches["name"],
        "geometry": reaches.geometry.simplify(0.0004),
    }, crs=reaches.crs)
    out.to_file(WEB_DATA / "flow.geojson", driver="GeoJSON")


def attach_flow_to_profiles(profiles: dict, reaches: gpd.GeoDataFrame) -> None:
    projected = reaches.to_crs(TARGET_CRS)
    to_dem = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    for river, profile in profiles.items():
        stem = projected[projected["name"] == river]
        points = gpd.GeoSeries([Point(to_dem.transform(p["lon"], p["lat"])) for p in profile["points"]], crs=TARGET_CRS)
        flows = np.full(len(points), np.nan)
        point_idx, reach_idx = stem.sindex.nearest(points, return_all=False, max_distance=PROFILE_FLOW_MATCH_M)
        flows[point_idx] = stem["DIS_AV_CMS"].to_numpy()[reach_idx]
        # Interpolate gaps, then enforce the physics: flow never shrinks downstream.
        flows = np.array(pd_interpolate(flows))
        flows = np.maximum.accumulate(flows)
        for point, flow in zip(profile["points"], flows):
            point["q"] = round(float(flow))
        profile["min_q"], profile["max_q"] = int(flows.min()), int(flows.max())


def pd_interpolate(values: np.ndarray) -> np.ndarray:
    index = np.arange(len(values))
    known = ~np.isnan(values)
    return np.interp(index, index[known], values[known])


def flow_summary(reaches: gpd.GeoDataFrame, districts: gpd.GeoDataFrame, state: gpd.GeoDataFrame) -> dict:
    projected = reaches.to_crs(TARGET_CRS)
    districts = districts.to_crs(TARGET_CRS)
    corridor = state.to_crs(TARGET_CRS).geometry.iloc[0].buffer(RIVER_CORRIDOR_M)
    to_wgs = Transformer.from_crs(TARGET_CRS, WGS84, always_xy=True)
    summary = {"peaks": {}, "districts": []}
    for river in PROFILE_RIVERS:
        stem = projected[(projected["name"] == river) & projected.intersects(corridor)]
        peak = stem.loc[stem["DIS_AV_CMS"].idxmax()]
        lon, lat = to_wgs.transform(*peak.geometry.coords[-1])
        summary["peaks"][river] = {"q": round(peak["DIS_AV_CMS"]), "up": round(peak["UPLAND_SKM"]),
                                   "entry_q": round(stem["DIS_AV_CMS"].min()), "lon": round(lon, 5), "lat": round(lat, 5)}
        for _, district in districts.iterrows():
            inside = stem[stem.intersects(district.geometry)]
            if inside.empty:
                continue
            clipped = inside.geometry.intersection(district.geometry)
            lengths = clipped.length
            if lengths.sum() < 1000.0:
                continue
            mid = unary_union(list(clipped)).representative_point()
            lon, lat = to_wgs.transform(mid.x, mid.y)
            summary["districts"].append({
                "district": district["shapeName"], "river": river,
                "mean_q": round(float((inside["DIS_AV_CMS"] * lengths).sum() / lengths.sum())),
                "max_q": round(float(inside["DIS_AV_CMS"].max())), "length_km": round(float(lengths.sum() / 1000.0)),
                "dist_dn_km": float(inside["DIST_DN_KM"].min()), "lon": round(lon, 5), "lat": round(lat, 5),
            })
    summary["districts"].sort(key=lambda row: (row["river"], -row["dist_dn_km"]))
    return summary


# --- contours ---------------------------------------------------------------

def build_contours() -> gpd.GeoDataFrame:
    with rasterio.open(PROFILE_DEM) as src:
        dem = gaussian_filter(src.read(1), sigma=CONTOUR_SMOOTH_SIGMA_PX)
        a, b, c, d, e, f = src.transform.a, src.transform.b, src.transform.c, src.transform.d, src.transform.e, src.transform.f
        crs = src.crs
    generator = contourpy.contour_generator(z=dem)
    records = []
    for level in range(CONTOUR_INTERVAL_M, int(dem.max()), CONTOUR_INTERVAL_M):
        for segment in generator.lines(level):
            cols, rows = segment[:, 0] + 0.5, segment[:, 1] + 0.5
            line = LineString(np.column_stack([a * cols + b * rows + c, d * cols + e * rows + f]))
            if line.length >= CONTOUR_MIN_LENGTH_M:
                records.append({"elev": level, "geometry": line.simplify(CONTOUR_SIMPLIFY_M)})
    return gpd.GeoDataFrame(records, crs=crs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-tiles", action="store_true", help="rebuild vectors, cities, profiles and contours only")
    args = parser.parse_args()
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    state = read_projected("state")
    districts = read_projected("districts")
    sampler = DemSampler(PROFILE_DEM)

    write_vectors(state, districts)
    cities = build_cities(sampler, districts)
    (WEB_DATA / "cities.json").write_text(json.dumps(cities, indent=1), encoding="utf-8")
    print(f"cities {len(cities)}: " + ", ".join(f"{c['name']} {c['elev']} m" for c in cities))
    profiles = build_profiles(sampler, state, cities)
    reaches = load_reaches()
    name_reaches(reaches)
    write_flow(reaches)
    attach_flow_to_profiles(profiles, reaches)
    (WEB_DATA / "rivers.json").write_text(json.dumps(profiles), encoding="utf-8")
    summary = flow_summary(reaches, districts, state)
    (WEB_DATA / "flow_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    named = reaches["name"].value_counts().to_dict()
    print(f"flow: {len(reaches)} reaches >= {FLOW_MIN_CMS:g} m3/s, named {named}")
    for river, peak in summary["peaks"].items():
        print(f"{river}: {peak['entry_q']} -> {peak['q']} m3/s, catchment {peak['up']:,} km2 at peak; "
              f"profile flow {profiles[river]['min_q']} -> {profiles[river]['max_q']}")
    for row in summary["districts"]:
        print(f"  {row['river']:9} {row['district']:18} mean {row['mean_q']:5} max {row['max_q']:5} m3/s over {row['length_km']} km")
    contours = build_contours()
    write_geojson(contours, "contours")
    print(f"contours: {len(contours)} lines, {(WEB_DATA / 'contours.geojson').stat().st_size / 1e6:.1f} MB")

    if args.skip_tiles:
        return
    dem, profile = load_source_dem()
    print(f"source DEM {dem.shape[1]}x{dem.shape[0]} px, writing tiles...")
    print(f"tiles: {write_tiles(dem, profile)}")


if __name__ == "__main__":
    main()

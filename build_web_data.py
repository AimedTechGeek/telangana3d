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
- web/data/dams.json          dams and barrages from Wikipedia infoboxes (height, river)
- web/data/dam_lines.geojson  OSM dam crest lines of the dams above, with height, for the 3D walls
- web/data/links.geojson      schematic Kaleshwaram water links between those structures
- web/data/pumphouses.json    Kaleshwaram pump houses from OpenStreetMap
- web/data/cropland_*.png     GLAD percent-cropland rasters (before/after 2014) and their change
- web/data/cropland.json      state and district cropland statistics plus official irrigation figures
- web/data/canals.geojson     OpenStreetMap canals oriented in flow direction, with an era class
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import shutil
import zipfile
from pathlib import Path

import contourpy
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import gaussian_filter, median_filter
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, mapping
from shapely.ops import linemerge, polygonize, unary_union

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


# --- dams and barrages (Wikipedia infoboxes) --------------------------------

DAM_WALL_DEFAULT_M = 15            # wall height drawn for a dam whose height no source gives (flagged height_known false)
DAM_CORRIDOR_M = 15000.0            # border dams (Srisailam, Nagarjuna Sagar) sit just outside the state
EXCLUDED_TITLE_WORDS = ("lift irrigation", "scheme", "wildlife", "district")
# Infobox dam_type codes are inconsistent ("B" marks Osman Sagar, a masonry dam), so only
# names decide the kind, plus this list of barrages whose names do not say so.
BARRAGE_TITLES = ("Sripada Yellampalli Project",)
# Kaleshwaram reservoirs without a Wikipedia page: dams come from OSM (osm_reservoirs.json),
# the dates were checked by hand (sources in DATA_SOURCES.md). 2016 is the project's
# construction start; Ranganayaka Sagar's 2020 is its first filling.
OSM_RESERVOIRS = {
    "Mallanna Sagar": {"began": 2016, "opened": 2022, "capacity_tmc": 50},
    "Konda Pochamma Sagar": {"began": 2016, "opened": 2020, "capacity_tmc": 15},
    "Ranganayaka Sagar": {"began": 2016, "opened": 2020, "capacity_tmc": 3.5},
}
KALESHWARAM_URL = "https://en.wikipedia.org/wiki/Kaleshwaram_Lift_Irrigation_Project"
WIKI = "https://en.wikipedia.org/wiki/"
# Power stations with a dam infobox but no storage or diversion role.
EXCLUDED_TITLES = ("Lower Jurala Hydro Electric Project",)

# --- works still under construction or only proposed (see DATA_SOURCES.md 6h) ------------
# Status words used everywhere: "operational", "under construction", "proposed".
# Wikipedia pages whose infobox status is P (proposed) or UC (under construction) stay in
# the data with that status; these hand-checked facts add the scheme, years and context.
# `target` is the completion year the government last announced, not a prediction.
PENDING_FACTS = {
    "Icchampally Project": {"scheme": "Godavari–Cauvery link (NWDA)", "note":
        "Multi-purpose dam proposed jointly with Maharashtra and Chhattisgarh; Telangana wants it as the source of the "
        "Godavari–Cauvery link (NWDA meeting, August 2025), Andhra Pradesh objects; no agreement yet"},
    "Tummidihetti Barrage": {"scheme": "Pranahita–Chevella", "planned": 2008, "note":
        "Pranahita barrage of the Pranahita–Chevella scheme; FRL 148 m agreed with Maharashtra in 2016, Telangana asked "
        "the Centre in September 2026 to expedite an agreement for 152 m; the 2026-27 budget speaks of reviving the scheme"},
    "Sitamma Sagar Barrage": {"name": "Sitamma Sagar Barrage", "scheme": "Sitarama lift scheme", "planned": 2016, "target": 2026, "note":
        "Barrage 200 m below the Dummugudem anicut, built by L&T, with 320 MW of hydro power; three pump houses and the "
        "canals (shown from OpenStreetMap) are under construction; NGT clearance and R&R bills still pending in mid-2026"},
    "Janampet Barrage": {"scheme": "Dummugudem link (shelved)", "status": "proposed", "note":
        "Proposed for the Dummugudem to Nagarjuna Sagar tail pond link; shelved when the Sitarama scheme and the "
        "Sitamma Sagar barrage replaced it"},
    "Sadarmat Barrage": {"status": "operational", "note": "Water impounded since 2021; the Wikipedia infobox still says under construction"},
    "Sammakka Sagar Barrage": {"status": "operational", "note": "Impounding since June 2021, not formally inaugurated; the 240 MW hydro plant is still to be built"},
}
# Structures with no usable Wikipedia infobox. `approx` names the place whose OpenStreetMap
# coordinates stand in for the structure (village or tank centre), so the marker is roughly
# right but not surveyed; `url` is the source for the facts. Capacities are only given where
# a source states them.
NEWS = {
    "prlis": "https://thesouthfirst.com/news/palamuru-rangareddy-lift-irrigation-scheme-in-telangana-gets-new-deadline-december-2027",
    "slbc": "https://indianinfrastructure.com/2026/07/03/regaining-momentum-srisailam-left-bank-canal-tunnel-project-makes-progress-after-setbacks/",
    "devadula": "https://thesouthfirst.com/news/devadula-lift-irrigation-project-in-telangana-to-become-fully-operational-by-2027",
    "chanaka": "https://www.deccanchronicle.com/southern-states/telangana/floods-due-to-incomplete-korata-chanaka-project-damage-crops-in-adilabad-district-1976070",
    "gouravelli": "https://www.deccanchronicle.com/southern-states/telangana/congress-initiated-project-works-nearly-98-complete-uttam-1992803",
    "baswapur": "https://cwc.gov.in/sites/default/files/reply-rti-shri-srinivas-rao-cwcnd-00108-2.pdf",
    "cag": "https://cag.gov.in/uploads/download_audit_report/2024/08_Chapter-V_Execution-of-Kaleshwaram-Project-065cdab5633b085.36569039.pdf",
    "dindi": "https://www.uniindia.com/south-india/politics-telangana-cpi-19ms50/219572",
    "palamuru_targets": "https://www.siasat.com/telangana-uttam-sets-20-month-target-for-palamuru-project-3426924/",
    "mukteshwar": "https://rsdebate.nic.in/bitstream/123456789/749427/1/PQ_265_22072024_U95_p356_p356.pdf",
}
EXTRA_STRUCTURES = [
    {"name": "Baswapur reservoir", "kind": "dam", "scheme": "Kaleshwaram", "status": "under construction",
     "lon": 78.8817, "lat": 17.5728, "approx": "Baswapur tank, Bhongir mandal", "capacity_tmcft": 11.39, "planned": 2016,
     "note": "Link V storage to be fed from Konda Pochamma Sagar by gravity canals and a 1.2 km tunnel; the CAG found in 2024 "
             "that resettlement had not started in the affected villages", "url": NEWS["baswapur"]},
    {"name": "Annapurna reservoir (Anantha Sagar)", "kind": "dam", "scheme": "Kaleshwaram", "status": "operational",
     "lon": 78.9881, "lat": 18.2058, "approx": "Ananthasagar village, Siddipet", "capacity_tmcft": 3.5, "planned": 2016, "began": 2016,
     "note": "Link IV balancing reservoir between Mid Manair and Ranganayaka Sagar", "url": KALESHWARAM_URL},
    {"name": "Veeranjaneya reservoir (Yedula)", "kind": "dam", "scheme": "Palamuru-Rangareddy", "status": "under construction",
     "lon": 78.1740, "lat": 16.3575, "approx": "Yedula village, Gopalpet mandal", "capacity_tmcft": 6.5, "planned": 2015, "began": 2015, "target": 2027,
     "note": "Stage II: the pump house is an underground cavern 415 m long and 90 m high with ten 145 MW pumps; the reservoir is "
             "first in line for filling (minister's review, May 2025)", "url": NEWS["prlis"]},
    {"name": "Venkatadri reservoir (Vattem)", "kind": "dam", "scheme": "Palamuru-Rangareddy", "status": "under construction",
     "lon": 78.2168, "lat": 16.5823, "approx": "Vattem village, Bijinapalle mandal", "planned": 2015, "began": 2015, "target": 2027,
     "note": "Stage III pump house with ten pumps, fed by a 10 km tunnel from Yedula", "url": NEWS["prlis"]},
    {"name": "Kurumurthy Raya reservoir (Karvena)", "kind": "dam", "scheme": "Palamuru-Rangareddy", "status": "under construction",
     "lon": 78.1101, "lat": 16.6686, "approx": "Karivena village, Bhoothpur mandal", "planned": 2015, "began": 2015, "target": 2027,
     "note": "Stage IV; Udandapur and KP Laxmidevipalli follow but have no published coordinates", "url": NEWS["prlis"]},
    {"name": "Dindi reservoir", "kind": "dam", "scheme": "Dindi lift scheme", "status": "operational",
     "lon": 78.67944, "lat": 16.54056, "capacity_tmcft": 2.08,
     "note": "Existing medium reservoir on the Dindi river that the lift scheme will feed; 59 million m³ gross storage (Wikipedia)",
     "url": "https://www.wikidata.org/wiki/Q62033240"},
    {"name": "Dharmasagar reservoir", "kind": "dam", "scheme": "Devadula lift scheme", "status": "operational",
     "lon": 79.4418, "lat": 17.9926, "approx": "Dharmasagar village, Hanumakonda",
     "note": "Existing tank that receives Devadula Phase III water from the Devannapet pump house (pump 02 since May 2025)", "url": NEWS["devadula"]},
    {"name": "Chanaka–Korata barrage", "kind": "barrage", "scheme": "Lower Penganga", "status": "under construction",
     "lon": 78.5188, "lat": 19.8112, "approx": "Korta village, Jainad mandal", "began": 2016, "river": "Penganga River",
     "note": "Barrage on the Penganga at the Maharashtra border, wet run September 2023; canals and the pump house still unfinished, "
             "so it stored no flood water in 2026 (about 50,000 acres planned)", "url": NEWS["chanaka"]},
    {"name": "Gouravelli reservoir", "kind": "dam", "scheme": "Indiramma flood flow canal (SRSP)", "status": "under construction",
     "lon": 79.1823, "lat": 18.0728, "approx": "Gouravelli village, Akkannapet mandal", "capacity_tmcft": 8.23,
     "note": "Capacity raised from 1.41 to 8.23 TMC; works reported about 98 % complete in 2026, held up by approvals and clearances",
     "url": NEWS["gouravelli"]},
]
# Pending works whose location no source publishes: listed in the panel only, no marker.
PENDING_NOTES = [
    {"scheme": "Kaleshwaram", "item": "Gandhamalla reservoir", "kind": "reservoir", "status": "under construction",
     "note": "Link V storage near Gandhamalla, M. Turkapally mandal (Yadadri); 9.87 TMC in the DPR, 1.41 TMC per the contractor; resettlement not started (CAG 2024)", "url": NEWS["cag"]},
    {"scheme": "Kaleshwaram", "item": "Distributary network", "kind": "canals", "status": "under construction",
     "note": "690 of 9,564 km of distributaries built by March 2022; only 40,288 acres of new irrigation created against 18.26 lakh planned (CAG 2024)", "url": NEWS["cag"]},
    {"scheme": "Palamuru-Rangareddy", "item": "Udandapur reservoir", "kind": "reservoir", "status": "under construction",
     "note": "Fifth reservoir of the chain; headworks to Udandapur to be completed by June 2027 (CM, 2026)", "url": NEWS["prlis"]},
    {"scheme": "Palamuru-Rangareddy", "item": "KP Laxmidevipalli reservoir", "kind": "reservoir", "status": "proposed",
     "note": "End reservoir in Kodangal; construction to be taken up under the 2025-26 budget, six months after Udandapur", "url": NEWS["palamuru_targets"]},
    {"scheme": "Palamuru-Rangareddy", "item": "Main canal and distributaries", "kind": "canals", "status": "under construction",
     "note": "240 km main canal and 95 km of tunnels in all; completion target December 2027", "url": NEWS["prlis"]},
    {"scheme": "Dindi lift scheme", "item": "Nakkalagandi, Shivannagudem and the other reservoirs", "kind": "reservoirs", "status": "under construction",
     "note": "Nine reservoirs including Nakkalagandi (Dindi balancing reservoir, 7.5 TMC) along a 66 km canal with a 5.5 km tunnel; works since 2015, no water yet (October 2026)", "url": NEWS["dindi"]},
    {"scheme": "Sitarama lift scheme", "item": "Main canals and distributaries", "kind": "canals", "status": "under construction",
     "note": "The Dummugudem–Sagar tail pond canals for 9.36 lakh acres; the canals tagged under construction in OpenStreetMap are these", "url": WIKI + "Sitamma_Sagar_Barrage"},
    {"scheme": "Mukteshwar (Chinna Kaleshwaram)", "item": "Lift from the Godavari at Kannepalli, Nizamabad", "kind": "lift scheme", "status": "proposed",
     "note": "Techno-economic viability accepted by the Centre's advisory committee in 2024; ₹545 crore estimate", "url": NEWS["mukteshwar"]},
    {"scheme": "Kalwakurthy, Nettempadu, Bhima, Koilsagar", "item": "Remaining canals and distributaries", "kind": "canals", "status": "under construction",
     "note": "Palamuru-region lift schemes operating since 2017-19 whose last reaches are unfinished; target March 2027", "url": NEWS["palamuru_targets"]},
]

# Intakes, pump houses, tunnel portals and reservoirs that are nodes of a water link but not
# in dams.json. Coordinates come from the article named in `source` (see DATA_SOURCES.md);
# `approx` marks OpenStreetMap village positions standing in for the structure.
EXTRA_NODES = {
    "Puttamgandi pump house": {"lon": 79.11694, "lat": 16.61028, "kind": "pump",
                               "source": WIKI + "Srisailam_Left_Bank_Canal"},
    "Kalwakurthy intake (Yellur)": {"lon": 78.39972, "lat": 16.10139, "kind": "pump",
                                    "source": WIKI + "Mahatma_Gandhi_Kalwakurthy_lift_irrigation_scheme"},
    # The Wikipedia infobox puts this pump house at 15.96 N 78.15 E, which is in Andhra Pradesh;
    # it stands at Yellur-Narlapur on the Srisailam foreshore, so OSM's Narlapur substation is used.
    "Narlapur pump house": {"lon": 78.3760, "lat": 16.1167, "kind": "pump", "approx": "Narlapur substation, Kollapur mandal",
                            "source": NEWS["prlis"]},
    "SLBC tunnel inlet (Domalapenta)": {"lon": 78.8969, "lat": 16.1051, "kind": "tunnel", "status": "under construction",
                                        "approx": "Domalapenta village, Amrabad mandal", "source": NEWS["slbc"]},
    "SLBC tunnel outlet (Mannevaripalle)": {"lon": 78.8987, "lat": 16.5337, "kind": "tunnel", "status": "under construction",
                                            "approx": "Mannevaripalle village, Achampet mandal", "source": NEWS["slbc"]},
    "Devadula intake (Gangaram)": {"lon": 80.3703, "lat": 18.5682, "kind": "pump", "approx": "Devadula village, Kannaigudem mandal",
                                   "source": NEWS["devadula"]},
}
WIKIDATA_NODES = {"Singotam reservoir": "Singotam Dam"}     # node name -> Wikidata label

# Water links between the structures. Years: planned (scheme sanctioned or redesigned),
# began (construction start), water (first water delivered), done (link complete), all
# from the sources listed in DATA_SOURCES.md; None where no source gives one. Lines are
# schematic: canal and tunnel alignments are not published as open data.
LINKS = [
    # scheme, link, from, to, via, kind, status, years {planned, began, water, done}, note
    ("Kaleshwaram", "Link I", "Medigadda Barrage", "Saraswati Barrage", "Medigadda pump house", "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2019, "done": 2019}, "Lakshmi pump house lifts Godavari water from Medigadda into the Annaram pool"),
    ("Kaleshwaram", "Link I", "Saraswati Barrage", "Parvati Barrage", "Annaram pump house", "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2019, "done": 2019}, "Saraswathi pump house lifts into the Sundilla pool"),
    ("Kaleshwaram", "Link I", "Parvati Barrage", "Sripada Yellampalli Project", "Sundilla pump house", "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2019, "done": 2019}, "Parvathi pump house lifts into the Yellampalli reservoir"),
    ("Kaleshwaram", "Link II", "Sripada Yellampalli Project", "Mid Manair Dam", None, "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2019, "done": None}, "Nandi and Gayatri pump houses with two tunnels of about 25 km; Godavari water reached Mid Manair in November 2019"),
    ("Kaleshwaram", "Link III", "Mid Manair Dam", "Upper Manair Dam", None, "lift", "in progress",
     {"planned": 2016, "began": 2016, "water": None, "done": None}, "86,150 acres planned"),
    ("Kaleshwaram", "Link IV", "Mid Manair Dam", "Ranganayaka Sagar", None, "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2020, "done": 2020}, "via the Annapurna (Anantha Sagar) reservoir, which has no published coordinates; first filled April 2020"),
    ("Kaleshwaram", "Link IV", "Ranganayaka Sagar", "Mallanna Sagar", None, "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2020, "done": 2022}, "water first let out in May 2020; Mallanna Sagar inaugurated February 2022"),
    ("Kaleshwaram", "Link IV", "Mallanna Sagar", "Konda Pochamma Sagar", None, "lift", "operational",
     {"planned": 2016, "began": 2016, "water": 2020, "done": 2020}, "Markook pump house, opened May 2020"),
    ("Kaleshwaram", "Link VI", "Mallanna Sagar", "Singur Dam", None, "canal", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None}, "gravity canals, tunnels and lifts towards Singur"),
    ("Kaleshwaram", "Link VII", "Sriram Sagar Project", "Nizam Sagar", None, "lift", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None}, "from the SRSP foreshore to the Nizam Sagar canals"),
    ("Sriram Sagar canals", "SRSP flood-flow canal", "Sriram Sagar Project", "Mid Manair Dam", None, "canal", "operational",
     {"planned": None, "began": None, "water": None, "done": None}, "gravity canal from the SRSP spillway that also fills Mid Manair"),
    ("Sriram Sagar canals", "Kakatiya canal", "Sriram Sagar Project", "Lower Manair Dam", None, "canal", "operational",
     {"planned": 1963, "began": 1963, "water": 1977, "done": 1985}, "SRSP's right-bank Kakatiya canal; Lower Manair Dam is its balancing reservoir"),
    ("Srisailam Left Bank Canal", "Puttamgandi lift", "Nagarjuna Sagar Dam", "Puttamgandi pump house", None, "lift", "operational",
     {"planned": None, "began": None, "water": 2004, "done": 2004}, "pumps from the Nagarjuna Sagar foreshore into Puttamgandi tank, then by gravity to the Akkampalli reservoir (no published coordinates)"),
    ("Kalwakurthy", "Stage I", "Srisailam Dam", "Kalwakurthy intake (Yellur)", None, "lift", "operational",
     {"planned": 1984, "began": 1984, "water": 2017, "done": 2017}, "lift from the Srisailam backwaters near Kollapur"),
    ("Kalwakurthy", "Stage I", "Kalwakurthy intake (Yellur)", "Singotam reservoir", None, "lift", "operational",
     {"planned": 1984, "began": 1984, "water": 2017, "done": 2017}, "Stage II continues from Singotam to the Jonnalaboguda and Gudipally reservoirs, which have no published coordinates"),
    ("Palamuru-Rangareddy", "Stage I", "Srisailam Dam", "Narlapur pump house", None, "lift", "operational",
     {"planned": 2015, "began": 2015, "water": 2023, "done": None}, "Yellur-Narlapur pump house lifts 104 m from the Srisailam backwaters at Yellur (Kollapur) into the Anjanagiri reservoir at Narlapur (6.4 TMC); pumping since September 2023"),
    ("Palamuru-Rangareddy", "Stage II", "Narlapur pump house", "Veeranjaneya reservoir (Yedula)", None, "tunnel", "in progress",
     {"planned": 2015, "began": 2015, "water": None, "done": None, "target": 2027}, "twin tunnels of 3.7 km and an open canal (Package 3, due late 2025) to the Yedula pump house, an underground cavern with ten 145 MW pumps"),
    ("Palamuru-Rangareddy", "Stage III", "Veeranjaneya reservoir (Yedula)", "Venkatadri reservoir (Vattem)", None, "tunnel", "in progress",
     {"planned": 2015, "began": 2015, "water": None, "done": None, "target": 2027}, "10 km tunnel of 11.5 m diameter to Vattem, then the Stage III pump house with ten pumps"),
    ("Palamuru-Rangareddy", "Stage IV", "Venkatadri reservoir (Vattem)", "Kurumurthy Raya reservoir (Karvena)", None, "lift", "in progress",
     {"planned": 2015, "began": 2015, "water": None, "done": None, "target": 2027}, "on to Udandapur (by June 2027) and KP Laxmidevipalli (six months later), which have no published coordinates; the scheme is to lift 90 TMC in 60 days for 12.3 lakh acres"),
    ("Dindi lift scheme", "Head reach", "Veeranjaneya reservoir (Yedula)", "Dindi reservoir", None, "lift", "in progress",
     {"planned": 2015, "began": 2015, "water": None, "done": None}, "lift from the Yedula foreshore into a 66 km canal with a 5.5 km tunnel feeding nine reservoirs, among them Nakkalagandi (7.5 TMC); 0.5 TMC allotted in the Palamuru DPR, no water yet (October 2026)"),
    ("Srisailam Left Bank Canal", "SLBC tunnel", "SLBC tunnel inlet (Domalapenta)", "SLBC tunnel outlet (Mannevaripalle)", None, "tunnel", "in progress",
     {"planned": 2005, "began": 2006, "water": None, "done": None, "target": 2028}, "43.9 km gravity tunnel from the Srisailam reservoir to replace the Puttamgandi pumping: 13.95 km dug from the inlet and 20.43 km from the outlet, 9.8 km left (July 2026); the roof collapse of February 2025 killed eight workers; target June 2028"),
    ("Devadula lift scheme", "Phase III", "Devadula intake (Gangaram)", "Dharmasagar reservoir", None, "tunnel", "in progress",
     {"planned": None, "began": None, "water": 2025, "done": None, "target": 2027}, "49 km tunnel (Package III) with leakage repairs and the Devannapet pump house, seven of ten pumps running (July 2026); phases I and II irrigate since the 2000s; full operation targeted for 2027"),
    ("Kaleshwaram", "Link V", "Konda Pochamma Sagar", "Baswapur reservoir", None, "canal", "planned",
     {"planned": 2016, "began": None, "water": None, "done": None}, "gravity canals and a 1.2 km tunnel from the Link IV anicut to the Gandhamalla (no published coordinates) and Baswapur reservoirs, 2.4 lakh acres towards Chityala"),
    ("Sitarama lift scheme", "Lift chain", "Sitamma Sagar Barrage", "Sitarama pump house 1", None, "canal", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None, "target": 2026}, "gravity canal from the barrage pool to the first pump house (positions from OpenStreetMap); the scheme merges the Rajiv Dummugudem and Indira Sagar Rudramkota lifts for 9.36 lakh acres"),
    ("Sitarama lift scheme", "Lift chain", "Sitarama pump house 1", "Sitarama pump house 2", None, "lift", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None, "target": 2026}, "second lift towards the Khammam plains"),
    ("Sitarama lift scheme", "Lift chain", "Sitarama pump house 2", "Sitarama pump house 3", None, "lift", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None, "target": 2026}, "third lift"),
    ("Sitarama lift scheme", "Lift chain", "Sitarama pump house 3", "Sitarama pump house 4", None, "lift", "in progress",
     {"planned": 2016, "began": None, "water": None, "done": None, "target": 2026}, "fourth pump house (Package 11), tagged under construction in OpenStreetMap; the canals continue towards the Nagarjuna Sagar tail pond"),
]
LINK_SOURCES = {
    "Kaleshwaram": KALESHWARAM_URL, "Sriram Sagar canals": WIKI + "Sriram_Sagar_Project",
    "Srisailam Left Bank Canal": WIKI + "Srisailam_Left_Bank_Canal",
    "Kalwakurthy": WIKI + "Mahatma_Gandhi_Kalwakurthy_lift_irrigation_scheme",
    "Palamuru-Rangareddy": WIKI + "Palamuru-Rangareddy_Lift_Irrigation_Scheme",
    "Dindi lift scheme": WIKI + "R._Vidyasagar_Rao_Dindi_Lift_Irrigation_Scheme",
    "Devadula lift scheme": WIKI + "J._Chokka_Rao_Devadula_Lift_Irrigation_Scheme",
    "Sitarama lift scheme": WIKI + "Sitamma_Sagar_Barrage",
}
LINK_BULGE = 0.12                   # schematic arc height as a fraction of the straight distance
NODE_ELEV_RADIUS_PX = 2             # 400 m window for a structure's elevation


def arc(start: tuple[float, float], end: tuple[float, float], bulge: float, steps: int = 24) -> list[list[float]]:
    """Quadratic curve from start to end, bowed to the left of travel so edges never overlap the river."""
    (x0, y0), (x1, y1) = start, end
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    cx, cy = mx - dy * bulge, my + dx * bulge
    points = []
    for i in range(steps + 1):
        t = i / steps
        points.append([round((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1, 5),
                       round((1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1, 5)])
    return points


def load_pumphouses() -> list[dict]:
    """Kaleshwaram pump houses from OSM plus the intakes listed in EXTRA_NODES."""
    elements = json.loads((RAW / "osm_pumphouses.json").read_text(encoding="utf-8"))["elements"]
    houses = []
    for element in elements:
        tags, centre = element["tags"], element.get("center", element)
        houses.append({"name": tags.get("alt_name") or tags["name"], "osm_name": tags["name"], "scheme": "Kaleshwaram",
                       "power": tags.get("power:input"), "since": (tags.get("start_date") or "")[:4] or None,
                       "lon": round(centre["lon"], 5), "lat": round(centre["lat"], 5), "source": "OpenStreetMap",
                       "kind": "pump", "status": "operational", "approx": None})
    for name, node in EXTRA_NODES.items():
        houses.append({"name": name, "osm_name": name, "scheme": None, "power": None, "since": None,
                       "lon": node["lon"], "lat": node["lat"], "source": node["source"], "kind": node["kind"],
                       "status": node.get("status", "operational"), "approx": node.get("approx")})
    # Sitarama's pump houses are mapped as "Pump house - N" (one tagged landuse=construction, Package 11);
    # the scheme has delivered no water yet, so all four count as under construction.
    for element in osm_construction():
        tags = element.get("tags", {})
        match = re.fullmatch(r"pump house - (\d)", (tags.get("name") or "").lower())
        if match and tags.get("man_made") == "pumping_station" and element.get("center", element)["lon"] > 80.5:
            centre = element.get("center", element)
            houses.append({"name": f"Sitarama pump house {match.group(1)}", "osm_name": f"Sitarama pump house {match.group(1)}",
                           "scheme": "Sitarama lift scheme", "power": None, "since": None, "lon": round(centre["lon"], 5),
                           "lat": round(centre["lat"], 5), "source": "OpenStreetMap", "kind": "pump", "status": "under construction", "approx": None})
    return houses


def osm_construction() -> list[dict]:
    """Water works tagged under construction and pumping stations around the state (osm_construction.json)."""
    path = RAW / "osm_construction.json"
    if not path.exists():
        print("  warning: data/raw/osm_construction.json missing (fetch_data.py); Sitarama pump houses not built")
        return []
    return json.loads(path.read_text(encoding="utf-8"))["elements"]


def wikidata_nodes() -> list[dict]:
    """Reservoirs with a Wikidata item but no Wikipedia page (Singotam)."""
    import csv
    rows = list(csv.DictReader((RAW / "wikidata_dams.csv").open(encoding="utf-8")))
    nodes = []
    for name, label in WIKIDATA_NODES.items():
        row = next((r for r in rows if r["itemLabel"] == label), None)
        if not row:
            print(f"  warning: {label} not in wikidata_dams.csv")
            continue
        lon, lat = (float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", row["coord"]))
        nodes.append({"name": name, "kind": "dam", "lon": round(lon, 5), "lat": round(lat, 5),
                      "height": float(row["height"]) if row["height"] else None, "river": "Kalwakurthy lift scheme (off-river)",
                      "began": None, "opened": None, "capacity_tmcft": None,
                      "url": row["item"].replace("http://www.wikidata.org/entity/", "https://www.wikidata.org/wiki/")})
    return nodes


def geodesic_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = (a[1] + b[1]) / 2 * math.pi / 180
    return math.hypot((b[0] - a[0]) * EARTH_M_PER_DEG * math.cos(lat), (b[1] - a[1]) * EARTH_M_PER_DEG) / 1000


EARTH_M_PER_DEG = 111_320


def build_links(nodes_by_name: dict[str, dict]) -> dict:
    features = []
    for index, (scheme, link, source, target, via, kind, status, years, note) in enumerate(LINKS):
        missing = [n for n in (source, target, via) if n and n not in nodes_by_name]
        if missing:
            print(f"  warning: {scheme} {link} skipped, unknown node(s) {missing}")
            continue
        stop_names = [source] + ([via] if via else []) + [target]
        stops = [(nodes_by_name[n]["lon"], nodes_by_name[n]["lat"]) for n in stop_names]
        coords = []
        for a, b in zip(stops, stops[1:]):
            coords.extend(arc(a, b, LINK_BULGE if not via else LINK_BULGE / 2)[: -1])
        coords.append([round(stops[-1][0], 5), round(stops[-1][1], 5)])
        # A village standing in for a structure can sit far above the water, so approximate nodes give no terrain height.
        elev_from, elev_to = (None if nodes_by_name[n].get("approx") else nodes_by_name[n].get("elev_m") for n in (source, target))
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                         "properties": {"id": index, "scheme": scheme, "link": link, "from": source, "to": target, "via": via,
                                        "kind": kind, "status": status, "note": note, "source": LINK_SOURCES[scheme],
                                        "straight_km": round(sum(geodesic_km(a, b) for a, b in zip(stops, stops[1:])), 1),
                                        "elev_from": elev_from, "elev_to": elev_to,
                                        "lift_m": (elev_to - elev_from) if elev_from is not None and elev_to is not None else None,
                                        **years}})
    return {"type": "FeatureCollection", "features": features}
FOOT_M = 0.3048


def infobox_field(text: str, name: str) -> str | None:
    # [ \t]* rather than \s*: an empty value must not run on into the next line.
    match = re.search(r"^\|[ \t]*" + name + r"[ \t]*=[ \t]*(.*?)[ \t]*$", text, re.M)
    return match.group(1) if match and match.group(1) else None


def strip_markup(value: str) -> str:
    value = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", value, flags=re.S)
    value = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    return re.sub(r"\s+", " ", value).strip(" ,;")


def parse_height_m(value: str | None) -> int | None:
    """'{{convert|124|m|ft}} from river bed' -> 124; feet are converted."""
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*\|?\s*(m|ft|metre|meter|feet)?\b", value)
    if not match:
        return None
    metres = float(match.group(1))
    if match.group(2) in ("ft", "feet"):
        metres *= FOOT_M
    return round(metres) if 3 <= metres <= 400 else None


TMCFT_M3 = 28_316_846.6             # one thousand million cubic feet in cubic metres
DAM_INFLOW_MATCH_M = 3000.0         # a dam's river reach must lie this close to its coordinates


def parse_capacity_tmcft(value: str | None) -> float | None:
    """Gross storage from the infobox, in tmcft (the unit Indian projects quote)."""
    if not value:
        return None
    text = value.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)[\s|]*(?:\[\[)?\s*tmc", text, re.I)   # "216|tmcft", "20 [[tmcft]]", "29.72 tmc ft"
    if match:
        return round(float(match.group(1)), 2)
    match = re.search(r"\{\{convert\|(\d+(?:\.\d+)?)\|(km3|e9m3|e6m3|Mm3|m3)", text, re.I) or \
        re.search(r"(\d+(?:\.\d+)?)\s*(km3|Mm3|cubic met)", text, re.I)
    if not match:
        return None
    amount, unit = float(match.group(1)), match.group(2).lower()
    cubic_metres = amount * {"km3": 1e9, "e9m3": 1e9, "e6m3": 1e6, "mm3": 1e6}.get(unit, 1.0)
    tmcft = cubic_metres / TMCFT_M3
    return round(tmcft, 2) if tmcft >= 0.1 else None   # smaller values are tagging errors


def parse_year(value: str | None) -> int | None:
    match = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value or "")
    return int(match.group(1)) if match else None


def parse_coord(text: str) -> tuple[float, float] | None:
    match = re.search(r"\{\{coord\|([^}]+)\}\}", text, re.I)
    if not match:
        return None
    parts = [p.strip() for p in match.group(1).split("|") if p.strip() and "=" not in p and ":" not in p]
    numbers, hemis = [], []
    for part in parts:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", part):
            numbers.append(float(part))
        elif part.upper() in ("N", "S", "E", "W"):
            hemis.append(part.upper())
    if hemis and len(numbers) % 2 == 0 and numbers:
        half = len(numbers) // 2
        first = sum(v / 60 ** i for i, v in enumerate(numbers[:half]))
        second = sum(v / 60 ** i for i, v in enumerate(numbers[half:]))
        # A few pages write longitude first ("78|8|47|E|15|57|49|N"); the hemisphere letters say which is which.
        lat, lon = (second, first) if hemis[0] in ("E", "W") else (first, second)
        if "S" in hemis:
            lat = -lat
        if "W" in hemis:
            lon = -lon
        return lon, lat
    if len(numbers) >= 2:
        return numbers[1], numbers[0]
    return None


def build_dams(state: gpd.GeoDataFrame, reaches: gpd.GeoDataFrame) -> list[dict]:
    pages = json.loads((RAW / "wikipedia_dams.json").read_text(encoding="utf-8"))
    corridor = state.to_crs(TARGET_CRS).geometry.iloc[0].buffer(DAM_CORRIDOR_M)
    to_dem = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    dams = []
    for title, text in pages.items():
        if not text or not re.search(r"\{\{\s*infobox dam", text, re.I):
            continue
        if any(word in title.lower() for word in EXCLUDED_TITLE_WORDS) or title in EXCLUDED_TITLES:
            continue
        coord = parse_coord(text)
        if not coord or not corridor.contains(Point(to_dem.transform(*coord))):
            continue
        name = strip_markup(infobox_field(text, "name") or infobox_field(text, "dam_name") or title)
        kind_text = f"{title} {name} {infobox_field(text, 'dam_type') or ''}".lower()
        barrage = title in BARRAGE_TITLES or re.search(r"barrage|anicut", kind_text) is not None
        opened = parse_year(infobox_field(text, "opening") or infobox_field(text, "dam_opening") or infobox_field(text, "completion"))
        facts = PENDING_FACTS.get(title, {})
        dams.append({
            "name": name, "kind": "barrage" if barrage else "dam",
            "lon": round(coord[0], 5), "lat": round(coord[1], 5),
            # dam_height is above the river bed; a few pages only give height above the foundation.
            "height": parse_height_m(infobox_field(text, "dam_height")) or parse_height_m(infobox_field(text, "dam_height_foundation")),
            "river": strip_markup(infobox_field(text, "dam_crosses") or infobox_field(text, "crosses") or "") or None,
            # Infoboxes record when building started and when the dam opened; no page states a proposal year.
            "began": parse_year(infobox_field(text, "construction_began")),
            "opened": opened,
            "capacity_tmcft": parse_capacity_tmcft(infobox_field(text, "res_capacity_total")),
            "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
            "status": facts.get("status") or infobox_status(infobox_field(text, "status"), opened),
            **{k: v for k, v in facts.items() if k != "status"},
        })
    dams.extend(osm_reservoir_dams())
    dams.extend(wikidata_nodes())
    dams.extend(copy.deepcopy(EXTRA_STRUCTURES))
    # Named reservoirs OSM tags as under construction (landuse=construction + construction=reservoir) inside the state.
    for element in osm_construction():
        tags, centre = element.get("tags", {}), element.get("center", element)
        if tags.get("construction") == "reservoir" and tags.get("name") and corridor.contains(Point(to_dem.transform(centre["lon"], centre["lat"]))):
            dams.append({"name": tags["name"], "kind": "dam", "lon": round(centre["lon"], 5), "lat": round(centre["lat"], 5),
                         "status": "under construction", "river": "scheme not identified (off-river)",
                         "note": "Tagged in OpenStreetMap as a reservoir under construction; no source names its scheme or capacity",
                         "url": f"https://www.openstreetmap.org/{element['type']}/{element['id']}"})
    for dam in dams:
        for key, default in (("status", "operational"), ("scheme", None), ("planned", None), ("target", None),
                             ("note", None), ("approx", None), ("height", None), ("river", None), ("began", None),
                             ("opened", None), ("capacity_tmcft", None)):
            dam.setdefault(key, default)
        if dam["river"] is None and dam["scheme"]:
            dam["river"] = f"{dam['scheme']} (off-river)"
    attach_inflow(dams, reaches)
    dams.sort(key=lambda d: (d["height"] is None, -(d["height"] or 0)))
    return dams


def infobox_status(value: str | None, opened: int | None) -> str:
    """Map the infobox status (NRLD codes P / UC, or words) to the three status words."""
    status = (value or "").lower()
    if re.search(r"^(p|pl)$|proposed|planned", status):
        return "proposed"
    if re.search(r"^uc$|construction", status) and not opened:
        return "under construction"
    return "operational"


def attach_inflow(dams: list[dict], reaches: gpd.GeoDataFrame) -> None:
    """Average flow of the HydroRIVERS reach at each dam; off-river reservoirs get none."""
    projected = reaches.to_crs(TARGET_CRS)
    to_dem = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    for dam in dams:
        dam["inflow_q"] = dam["inflow_name"] = None
        if "off-river" in (dam["river"] or ""):
            continue
        point = gpd.GeoSeries([Point(to_dem.transform(dam["lon"], dam["lat"]))], crs=TARGET_CRS)
        _, reach_idx = projected.sindex.nearest(point, return_all=False, max_distance=DAM_INFLOW_MATCH_M)
        if len(reach_idx):
            reach = projected.iloc[reach_idx[0]]
            dam["inflow_q"] = round(float(reach["DIS_AV_CMS"]))
            dam["inflow_name"] = reach["name"]


def dam_key(name: str) -> str:
    """'Sriram Sagar Project (Pochampad) Dam' -> 'sriramsagar': the words that differ between OSM and Wikipedia names are dropped."""
    name = re.sub(r"\(.*?\)", " ", name.lower())
    return re.sub(r"[^a-z]", "", re.sub(r"\b(dam|project|reservoir|barrage|weir|lake|the)\b", " ", name))


# OSM names of dam ways that differ from the map's dam names beyond the words dam_key drops (checked by eye against the 42 dams).
DAM_LINE_ALIASES = {"priyadarshinijurala": "jurala", "nagarjunsagar": "nagarjunasagar", "sriranganayakasagar": "ranganayakasagar",
                    "sammakka": "sammakkasagar",
                    # OSM way 801963324 "Baswapuram Dam" lies 0.8 km from the map's Baswapur position. The other 26 dams without a line
                    # have only unnamed waterway=dam ways near them (Lower Manair, Kaddam, Komaram Bheem, Sarala Sagar within 0.1 km),
                    # which a name alias cannot reach; Medigadda's nearest OSM dam way is 22 km away.
                    "baswapuram": "baswapur"}


def build_dam_lines(dams: list[dict]) -> dict:
    """OSM waterway=dam ways (data/raw/osm_dam_lines.json) joined by name to the dams on the map; dams without a line are skipped."""
    elements = json.loads((RAW / "osm_dam_lines.json").read_text(encoding="utf-8"))["elements"]
    by_key = {}
    for i, dam in enumerate(dams):
        by_key.setdefault(dam_key(dam["name"]), i)
    features, used = [], set()
    for e in elements:
        tags = e.get("tags", {})
        keys = [DAM_LINE_ALIASES.get(k, k) for k in (dam_key(tags[t]) for t in ("name", "alt_name", "name:en") if t in tags)]
        i = next((by_key[k] for k in keys if k in by_key), None)
        if i is None or len(e.get("geometry", [])) < 2:
            continue
        dam = dams[i]
        height = dam["height"] if dam["height"] is not None else parse_height_m(tags.get("height"))
        coords = [[round(p["lon"], 5), round(p["lat"], 5)] for p in e["geometry"]]
        properties = {"i": i, "name": dam["name"], "status": dam["status"], "height": height if height is not None else DAM_WALL_DEFAULT_M,
                      "height_known": height is not None}
        year = dam["opened"] or dam["began"]
        if year is not None:
            properties["year"] = year
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": properties})
        used.add(i)
    print(f"dam lines: {len(features)} OSM dam ways joined to {len(used)} of {len(dams)} dams")
    return {"type": "FeatureCollection", "features": features}


def osm_reservoir_dams() -> list[dict]:
    elements = json.loads((RAW / "osm_reservoirs.json").read_text(encoding="utf-8"))["elements"]
    dams = []
    for key, facts in OSM_RESERVOIRS.items():
        matches = [e for e in elements if key.lower() in e["tags"].get("name", "").lower()]
        if not matches:
            print(f"  warning: {key} not found in OSM data")
            continue
        element = sorted(matches, key=lambda e: e["tags"].get("waterway") != "dam")[0]   # the dam line over the lake
        centre = element.get("center", element)
        dams.append({
            "name": key, "kind": "dam", "lon": round(centre["lon"], 5), "lat": round(centre["lat"], 5),
            "height": parse_height_m(element["tags"].get("height")), "river": "Kaleshwaram lift scheme (off-river)",
            "began": facts["began"], "opened": facts["opened"], "capacity_tmcft": facts["capacity_tmc"],
            "url": KALESHWARAM_URL,
        })
    return dams


# --- canals (OpenStreetMap) -------------------------------------------------
# OSM carries no construction dates for Telangana's canals, so the era comes from
# the project a canal belongs to (see DATA_SOURCES.md 6f):
# - construction=yes ways are the Sitarama lift scheme's canal works in Khammam and
#   Bhadradri (2016-), including its extensions of older canals -> "after";
# - real tunnels (not road culverts) within CANAL_CORRIDOR_M of a Kaleshwaram link
#   are Kaleshwaram's (2016-) -> "after"; names of post-2014 projects -> "after";
# - names of older projects -> "before"; everything else -> "unknown".
CANAL_CORRIDOR_M = 20000.0
CANAL_POST2014_NAMES = ("kaleshwaram", "link-i", "link i", "palamuru", "sitarama", "sita rama", "mallanna", "kondapochamma",
                        "konda pochamma", "ranganayaka", "anantha", "annapurna", "medigadda", "sundilla", "annaram")
CANAL_PRE2014_NAMES = ("nagarjun", "nagarjuna", "kakatiya", "srsp", "nizam", "jurala", "manair", "mula vagu", "palavagu",
                       "ali sagar", "sathupally", "kurnool", "ntr canal", "flood flow", "devadula", "koil", "dindi", "kalwakurthy",
                       "bhima", "nettempadu", "rajolibanda", "rds")
SITARAMA_WEST_LON = 79.5            # the construction-tagged canals east of this are Sitarama's
CANAL_SIMPLIFY_DEG = 0.00005


def canal_era(tags: dict, near_kaleshwaram: bool, lon: float) -> tuple[str, str | None]:
    """Return (era, scheme) for one OSM canal way."""
    name = (tags.get("name") or "").lower()
    real_tunnel = way_kind(tags) == "tunnel"
    if tags.get("construction") == "yes":
        return "after", "Sitarama lift scheme (under construction)" if lon >= SITARAMA_WEST_LON else "under construction"
    if any(k in name for k in CANAL_POST2014_NAMES):
        return "after", "Kaleshwaram" if "link" in name or "kaleshwaram" in name else "post-2014 project (by name)"
    if near_kaleshwaram and real_tunnel:
        return "after", "Kaleshwaram tunnel"
    if any(k in name for k in CANAL_PRE2014_NAMES):
        return "before", "older project (by name)"
    return "unknown", None


# Official scale of the Kaleshwaram canal network, quoted in the panel next to what OSM has mapped.
KALESHWARAM_NETWORK = {
    "planned": [("Gravity canals", 1531), ("Tunnels", 203), ("Pressure / delivery mains", 98)],
    "planned_source": "https://irrigation.telangana.gov.in/",
    "cag": [("Main canals", 1566.04, 897.0), ("Distributary canals", 9564.35, 690.18)],   # planned km, completed km
    "cag_asof": "March 2022",
    "cag_source": "https://cag.gov.in/en/audit-report/details/119583",
}


def way_kind(tags: dict) -> str:
    if tags.get("waterway") == "pressurised" or tags.get("man_made") == "pipeline":
        return "main"                      # pressure / delivery main
    if tags.get("tunnel") in ("yes", "flooded") or tags.get("location") == "underground":
        return "tunnel"
    return "canal"


def build_canals(links: dict) -> tuple[dict, dict]:
    """Canals, tunnels and pressure mains from OSM, plus a summary for the panel."""
    elements = json.loads((RAW / "osm_canals.json").read_text(encoding="utf-8"))["elements"]
    extra = RAW / "osm_waterpipes.json"
    if extra.exists():
        seen = {w["id"] for w in elements}
        elements += [w for w in json.loads(extra.read_text(encoding="utf-8"))["elements"] if w["id"] not in seen]
    to_m = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    kaleshwaram = unary_union([LineString([to_m.transform(x, y) for x, y in f["geometry"]["coordinates"]])
                               for f in links["features"] if f["properties"]["scheme"] == "Kaleshwaram"]).buffer(CANAL_CORRIDOR_M)
    features, km = [], {}
    for way in elements:
        points = [(p["lon"], p["lat"]) for p in way.get("geometry", [])]
        if len(points) < 2:
            continue
        tags = way.get("tags", {})
        # OSM draws waterways in the direction of flow unless flow_direction says otherwise.
        direction = tags.get("flow_direction", "forward")
        if direction == "backward":
            points.reverse()
        line = LineString(points)
        projected = LineString([to_m.transform(x, y) for x, y in points])
        near = projected.intersects(kaleshwaram)
        kind = way_kind(tags)
        era, scheme = canal_era(tags, near, line.centroid.x)
        if kind == "main" and era == "unknown" and near:
            era, scheme = "after", "Kaleshwaram pressure main"
        length = projected.length / 1000
        km[(era, kind)] = km.get((era, kind), 0.0) + length
        features.append({"type": "Feature", "geometry": mapping(line.simplify(CANAL_SIMPLIFY_DEG)), "properties": {
            "id": way["id"], "name": tags.get("name"), "era": era, "scheme": scheme, "kind": kind,
            "tunnel": kind == "tunnel", "construction": tags.get("construction") == "yes",
            "directed": direction != "both", "km": round(length, 2)}})
    summary = {
        "osm_km": {f"{era}_{kind}": round(v) for (era, kind), v in km.items()},
        "osm_ways": len(features), "network": KALESHWARAM_NETWORK,
    }
    print(f"canals: {len(features)} ways; km " + ", ".join(f"{k} {v}" for k, v in sorted(summary["osm_km"].items())))
    return {"type": "FeatureCollection", "features": features}, summary


CONDUIT_SCHEME_PREFIX = "Sitarama"      # the scheme's open canals get 3D troughs; elsewhere only pressure mains and tunnels are drawn


def build_conduits(canals: dict) -> dict:
    """The canal ways that get a 3D body (three3d.js): post-2014 pressure mains and tunnels, plus every Sitarama way.

    The year follows the web map's canal rule (dug after 2014 counts as 2015, older as 1970) so the timeline can filter the bodies.
    """
    features = []
    for feature in canals["features"]:
        p = feature["properties"]
        scheme = p["scheme"] or ""
        if not ((p["era"] == "after" and p["kind"] in ("main", "tunnel")) or scheme.startswith(CONDUIT_SCHEME_PREFIX)):
            continue
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
            "id": p["id"], "kind": p["kind"], "scheme": p["scheme"], "construction": p["construction"], "km": p["km"],
            "year": 2015 if p["era"] == "after" else 1970}})
    by_kind = {}
    for f in features:
        kind = f["properties"]["kind"]
        by_kind[kind] = (by_kind.get(kind, (0, 0.0))[0] + 1, by_kind.get(kind, (0, 0.0))[1] + f["properties"]["km"])
    print(f"conduits: {len(features)} ways for 3D; " + ", ".join(f"{k} {n} ways {km:.0f} km" for k, (n, km) in sorted(by_kind.items())))
    return {"type": "FeatureCollection", "features": features}


# --- tanks (OSM water bodies) and Mission Kakatiya ---------------------------

TANK_MIN_HA = 0.5                                 # smaller ponds are mostly farm pits and village puddles
TANK_SIMPLIFY_DEG = 0.0001                        # ~11 m, invisible at the zooms the polygons show
TANK_NAME_WORDS = ("cheruvu", "kunta", "tank", "sagar", "lake", "reservoir", "pond", "samudram")
# Tanks taken up for restoration under Mission Kakatiya by district (2016 districts) and phase,
# from the Government of India "Report on Best Practices being followed in Water Resources /
# Irrigation - Mission Kakatiya, Telangana" (Ministry of Water Resources, PMKSY, file dated
# 29 Aug 2018). Phase I 2015-16, II 2016-17, III 2017-18, IV sanctioned 2018-19. The report's
# district names are mapped to geoBoundaries names; Mulugu (carved out of Jayashankar
# Bhupalpally in 2019) and Narayanpet (out of Mahabubnagar) are inside their parents' counts.
MISSION_KAKATIYA_URL = "https://pmksy.mowr.gov.in/aibp-mis/Manual/Mission%20Kakatiya,%20Telangana.pdf"
MISSION_KAKATIYA = {                              # district: (phase I, II, III, IV)
    "Sangareddy": (359, 426, 450, 496), "Siddipet": (858, 682, 338, 221), "Medak": (560, 665, 393, 182),
    "Rangareddy": (310, 384, 217, 96), "Medchal": (88, 67, 23, 23), "Vikarabad": (243, 267, 129, 98),
    "Mahabubnagar": (406, 523, 431, 167), "Wanaparthy": (163, 296, 249, 241), "Jogulamba": (111, 93, 99, 42),
    "Nagarkurnool": (277, 428, 515, 255), "Nalgonda": (377, 499, 330, 165), "Yadadri Bhongiri": (195, 273, 316, 136),
    "Suryapet": (236, 297, 220, 130), "Adilabad": (103, 70, 22, 38), "Komaram Bheem": (184, 123, 54, 66),
    "Mancherial": (150, 155, 113, 51), "Nirmal": (121, 120, 63, 100), "Karimnagar": (223, 290, 299, 148),
    "Peddapalli": (118, 235, 134, 174), "Jagtial": (199, 218, 162, 133), "Rajanna Sircilla": (103, 120, 69, 45),
    "Warangal (U)": (126, 137, 70, 58), "Warangal (R)": (224, 200, 162, 159), "Jayashankar": (415, 434, 191, 90),
    "Jangaon": (180, 159, 147, 100), "Mahabubabad": (335, 388, 188, 158), "Khammam": (292, 304, 172, 119),
    "Bhadradri": (431, 516, 219, 164), "Nizamabad": (275, 279, 192, 95), "Kamareddy": (381, 367, 185, 158),
}
MISSION_KAKATIYA_PARENT = {"Mulugu": "Jayashankar", "Narayanpet": "Mahabubnagar"}   # 2019 districts, counted in the parent
MISSION_KAKATIYA_PHASES = [                       # taken up, completed by the report date, Rs crore, lakh acres stabilised
    {"phase": "I", "years": "2015-16", "taken_up": 8043, "completed": 8003, "crore": 1568.40, "ayacut_lakh_acres": 6.71},
    {"phase": "II", "years": "2016-17", "taken_up": 9015, "completed": 7060, "crore": 1152.20, "ayacut_lakh_acres": 3.80},
    {"phase": "III", "years": "2017-18", "taken_up": 6152, "completed": 1521, "crore": 224.57, "ayacut_lakh_acres": 1.1},
    {"phase": "IV", "years": "2018-19", "taken_up": 4108, "completed": None, "crore": None, "ayacut_lakh_acres": None},
]
MISSION_KAKATIYA_TOTALS = {"tanks_enumerated": 46531, "target_crore": 20000, "asof": "August 2018",
                           "launched": "12 March 2015", "wikipedia_completed": 27713, "wikipedia_crore": 8700,
                           "wikipedia_url": "https://en.wikipedia.org/wiki/Mission_Kakatiya"}


def osm_polygon(element: dict):
    """Shapely polygon for an OSM way or multipolygon relation returned with `out geom`."""
    if element["type"] == "way":
        points = [(p["lon"], p["lat"]) for p in element.get("geometry", [])]
        return Polygon(points) if len(points) >= 4 and points[0] == points[-1] else None
    outers, inners = [], []
    for member in element.get("members", []):
        points = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
        if len(points) >= 2:
            (inners if member.get("role") == "inner" else outers).append(LineString(points))
    if not outers:
        return None
    shape = unary_union([ring for ring in polygonize(unary_union(outers)) if ring.is_valid])
    if inners:
        shape = shape.difference(unary_union(list(polygonize(unary_union(inners)))))
    return shape if not shape.is_empty else None


def tank_kind(tags: dict, name: str) -> str | None:
    """'tank' for ponds, lakes and reservoirs, None for river channels and the like."""
    water = tags.get("water") or ("reservoir" if tags.get("landuse") == "reservoir" else "")
    if water in ("river", "stream", "canal", "oxbow", "wastewater", "moat", "lock", "ditch") or tags.get("waterway") == "riverbank":
        return None
    if water in ("reservoir", "pond", "lake", "basin", "") or any(w in name.lower() for w in TANK_NAME_WORDS):
        return "tank"
    return None


def build_tanks(state: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> tuple[dict, dict, dict]:
    """OSM water bodies inside the state as polygons and centroids, plus a per-district summary."""
    elements = json.loads((RAW / "osm_water.json").read_text(encoding="utf-8"))["elements"]
    rows = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name:en") or tags.get("name") or ""
        kind = tank_kind(tags, name)
        if kind is None:
            continue
        shape = osm_polygon(element)
        if shape is None:
            continue
        rows.append({"osm_id": f"{element['type'][0]}{element['id']}", "name": name or None,
                     "water": tags.get("water") or ("reservoir" if tags.get("landuse") == "reservoir" else None), "geometry": shape})
    tanks = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    tanks["geometry"] = tanks.geometry.buffer(0)               # heals self-touching rings
    projected = tanks.to_crs(TARGET_CRS)
    tanks["area_ha"] = (projected.area / 10_000).round(1)
    tanks["centroid"] = projected.representative_point().to_crs(WGS84)
    centroids = gpd.GeoDataFrame(tanks.drop(columns="geometry"), geometry="centroid", crs=WGS84)
    inside = gpd.sjoin(centroids, districts.to_crs(WGS84)[["shapeName", "geometry"]], how="inner", predicate="within")
    inside = inside[~inside.index.duplicated()]
    tanks = tanks.loc[inside.index].copy()
    tanks["district"] = inside["shapeName"]
    tanks = tanks[tanks["area_ha"] >= TANK_MIN_HA].sort_values("area_ha", ascending=False)
    tanks["lon"] = tanks["centroid"].x.round(5)
    tanks["lat"] = tanks["centroid"].y.round(5)
    # The same reservoir is sometimes drawn twice (a way and a relation, or natural=water over landuse=reservoir).
    key = tanks["area_ha"].round(0).astype(str) + "|" + tanks["lon"].round(3).astype(str) + "|" + tanks["lat"].round(3).astype(str)
    tanks = tanks[~key.duplicated()]
    columns = ["osm_id", "name", "water", "area_ha", "district"]
    polygons = gpd.GeoDataFrame(tanks[columns], geometry=tanks.geometry.simplify(TANK_SIMPLIFY_DEG), crs=WGS84)
    points = gpd.GeoDataFrame(tanks[columns + ["lon", "lat"]], geometry=tanks["centroid"], crs=WGS84)
    per_district = []
    for name in sorted(districts["shapeName"]):
        subset = tanks[tanks["district"] == name]
        phases = MISSION_KAKATIYA.get(name)
        per_district.append({"district": name, "osm_tanks": int(len(subset)), "osm_area_ha": round(float(subset["area_ha"].sum())),
                             "osm_named": int(subset["name"].notna().sum()),
                             "mk_phases": list(phases) if phases else None, "mk_total": sum(phases) if phases else None,
                             "mk_counted_in": MISSION_KAKATIYA_PARENT.get(name)})
    summary = {
        "osm_tanks": int(len(tanks)), "osm_area_ha": round(float(tanks["area_ha"].sum())), "osm_named": int(tanks["name"].notna().sum()),
        "osm_min_ha": TANK_MIN_HA, "osm_asof": "October 2026",
        "mission_kakatiya": {"url": MISSION_KAKATIYA_URL, "phases": MISSION_KAKATIYA_PHASES,
                             "taken_up": sum(p["taken_up"] for p in MISSION_KAKATIYA_PHASES),
                             "completed_by_report": sum(p["completed"] or 0 for p in MISSION_KAKATIYA_PHASES), **MISSION_KAKATIYA_TOTALS},
        "districts": per_district,
    }
    print(f"tanks: {len(tanks)} OSM water bodies >= {TANK_MIN_HA} ha inside the state ({summary['osm_named']} named, "
          f"{summary['osm_area_ha']:,} ha); Mission Kakatiya {summary['mission_kakatiya']['taken_up']:,} tanks taken up in 4 phases")
    return json.loads(polygons.to_json(drop_id=True)), json.loads(points.to_json(drop_id=True)), summary


RESERVOIR_SEARCH_M = 3000.0                       # a dam's reservoir touches this buffer of its point or crest line
RESERVOIR_MIN_HA = 50.0
RESERVOIR_SIMPLIFY_M = 30.0
RESERVOIR_LEVEL_MIN_SAMPLES = 16                  # outline points sampled for the water level (interpolated when the ring has fewer)
RESERVOIR_LEVEL_STEP_M = 200.0


def build_reservoirs(dams: list[dict], sampler: DemSampler) -> dict:
    """One OSM water polygon per dam for the 3D reservoir surfaces (three3d.js).

    Works on the raw OSM elements (through osm_polygon and tank_kind), not build_tanks' state-clipped output, which drops the
    border reservoirs (Srisailam, Nagarjuna Sagar). The largest polygon part >= RESERVOIR_MIN_HA touching a 3 km buffer of the
    dam's crest line (dam_lines.geojson, written just before) or its point wins; level_m is the median Copernicus DEM height
    along the outline, ignoring nodata, or null when fewer than half the samples are valid (the web map then samples Terrain-DEM).
    """
    elements = json.loads((RAW / "osm_water.json").read_text(encoding="utf-8"))["elements"]
    rows = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name:en") or tags.get("name") or ""
        if tank_kind(tags, name) is None:
            continue
        shape = osm_polygon(element)
        if shape is None:
            continue
        for part in (shape.geoms if hasattr(shape, "geoms") else [shape]):
            if isinstance(part, Polygon):
                rows.append({"osm_id": f"{element['type'][0]}{element['id']}", "osm_name": name or None, "geometry": part})
    water = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    water["geometry"] = water.geometry.buffer(0)
    projected = water.to_crs(TARGET_CRS)
    projected["area_ha"] = projected.area / 10_000
    projected = projected[projected["area_ha"] >= RESERVOIR_MIN_HA]
    lines_file = WEB_DATA / "dam_lines.geojson"
    crest = {}
    if lines_file.exists():
        for f in json.loads(lines_file.read_text(encoding="utf-8"))["features"]:
            crest.setdefault(f["properties"]["i"], []).append(LineString(f["geometry"]["coordinates"]))
    to_m = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    to_wgs = Transformer.from_crs(TARGET_CRS, WGS84, always_xy=True)
    candidates, unmatched = {}, []
    for i, dam in enumerate(dams):
        anchor = unary_union([LineString([to_m.transform(x, y) for x, y in line.coords]) for line in crest[i]]) if i in crest \
            else Point(to_m.transform(dam["lon"], dam["lat"]))
        search = anchor.buffer(RESERVOIR_SEARCH_M)
        hits = projected.iloc[list(projected.sindex.query(search, predicate="intersects"))]
        if hits.empty:
            unmatched.append(dam["name"])
            continue
        best = hits.sort_values("area_ha", ascending=False).iloc[0]
        # A polygon that is the largest near two dams (Icchampalli's proposed site on Sammakka Sagar's pool) goes to the built dam
        # at a known position, then to the nearer one.
        candidates[i] = (best, (dam["approx"] is not None, dam["status"] != "operational", anchor.distance(best.geometry)))
    nearest = {}
    for i, (best, rank) in candidates.items():
        if best["osm_id"] not in nearest or rank < candidates[nearest[best["osm_id"]]][1]:
            nearest[best["osm_id"]] = i
    features, used = [], set()
    for i, (best, _) in candidates.items():
        dam = dams[i]
        if nearest[best["osm_id"]] != i:
            unmatched.append(f"{dam['name']} (polygon taken by {dams[nearest[best['osm_id']]]['name']})")
            continue
        shape = best.geometry.simplify(RESERVOIR_SIMPLIFY_M)
        ring = shape.exterior
        count = max(RESERVOIR_LEVEL_MIN_SAMPLES, int(ring.length / RESERVOIR_LEVEL_STEP_M))
        samples = []
        for k in range(count):
            x, y = ring.interpolate(k / count, normalized=True).coords[0]
            lon, lat = to_wgs.transform(x, y)
            value = sampler.median(lon, lat, 0)
            if value is not None and value > 0:          # the DEM holds 0 outside its coverage
                samples.append(value)
        level = round(float(np.median(samples)), 1) if len(samples) * 2 >= count else None
        geometry = mapping(gpd.GeoSeries([shape], crs=TARGET_CRS).to_crs(WGS84).iloc[0])
        geometry["coordinates"] = [[[round(x, 5), round(y, 5)] for x, y in ring] for ring in geometry["coordinates"]]
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "i": i, "name": dam["name"], "status": dam["status"], "area_ha": round(float(best["area_ha"])), "level_m": level}})
        used.add(i)
    largest = sorted(((d["capacity_tmcft"] or 0, k) for k, d in enumerate(dams)), reverse=True)[:6]
    print(f"reservoirs: {len(features)} surfaces for {len(dams)} dams ({sum(1 for f in features if f['properties']['level_m'] is None)} "
          f"without a DEM level); unmatched: {', '.join(unmatched) or 'none'}")
    print("  six largest by capacity: " + ", ".join(f"{dams[k]['name']} {'yes' if k in used else 'NO'}" for _, k in largest))
    return {"type": "FeatureCollection", "features": features}


# --- groundwater (India-WRIS monitoring wells) -------------------------------

GW_BEFORE = (2010, 2014)                          # pre-monsoon (May) seasons up to the last one before the state formed
GW_AFTER = (2015, 2023)                           # the public export ends in 2019 for the state network and 2023 for CGWB
GW_MIN_SEASONS = 2                                # May readings a window mean needs (the state network left two thirds blank before 2015)
GW_MAX_DEPTH_M = 100.0                            # two readings above this are typos; the deepest CGWB level is 97 m
GW_CHART_MIN_SEASONS = 10                         # wells that carry the year-by-year state curve
GW_CHART_MIN_WELLS = 50                           # a year needs this many of them to be plotted
GW_CHART_FROM = 2005
GW_AGENCY = {"CGWB": "CGWB", "Telangana GW": "Telangana GWD"}
GW_SOURCE = {"name": "India-WRIS, Groundwater Level Collected Manually (India Data Portal mirror of the May 2025 export)",
             "url": "https://ckandev.indiadataportal.com/dataset/groundwater-level/resource/06d6e79c-61ac-46bb-9e03-c7138911c619",
             "wris_url": "https://indiawris.gov.in/wris/#/groundWater"}


def build_groundwater(districts: gpd.GeoDataFrame) -> tuple[dict, dict]:
    """Monitoring wells with their mean May depth to water before and after 2014, plus district and state summaries."""
    readings = pd.read_csv(RAW / "gw_levels.csv.gz", parse_dates=["date"])
    # The state network's export writes 0 for a missing reading (two thirds of its rows before 2015); the few
    # negative values are flowing wells. Depth is metres below ground, so smaller means more water.
    readings = readings[(readings["data_value"] > 0) & (readings["data_value"] < GW_MAX_DEPTH_M)].copy()
    readings["year"] = readings["date"].dt.year
    may = readings[readings["date"].dt.month == 5]
    by_year = may.groupby(["station_code", "year"])["data_value"].mean().unstack("year")     # one value per well and season
    stations = readings.groupby("station_code").agg(
        name=("station_name", "first"), agency=("agency_name", "first"), well=("well_type", "first"),
        well_depth=("well_depth", "first"), lat=("latitude", "first"), lon=("longitude", "first"), last=("year", "max"))
    points = gpd.GeoDataFrame(stations, geometry=gpd.points_from_xy(stations["lon"], stations["lat"]), crs=WGS84)
    inside = gpd.sjoin(points, districts.to_crs(WGS84)[["shapeName", "geometry"]], how="inner", predicate="within")
    inside = inside[~inside.index.duplicated()]
    stations = stations.loc[inside.index].copy()
    stations["district"] = inside["shapeName"]
    by_year = by_year.reindex(stations.index)

    def window_mean(first: int, last: int) -> tuple[pd.Series, pd.Series]:
        block = by_year.loc[:, [year for year in by_year.columns if first <= year <= last]]
        count = block.notna().sum(axis=1)
        return block.mean(axis=1).where(count >= GW_MIN_SEASONS), count

    stations["before"], stations["n_before"] = window_mean(*GW_BEFORE)
    stations["after"], stations["n_after"] = window_mean(*GW_AFTER)
    stations["change"] = stations["before"] - stations["after"]          # positive: the water table rose (is shallower)
    stations["latest_year"] = by_year.apply(lambda row: row.last_valid_index(), axis=1)
    stations["latest"] = [by_year.at[code, year] if pd.notna(year) else np.nan for code, year in stations["latest_year"].items()]
    stations["well_depth"] = stations["well_depth"].where(stations["well_depth"].between(2, 1000))   # 1 m is the export's blank
    stations = stations[(stations["n_before"] >= GW_MIN_SEASONS) | (stations["n_after"] >= GW_MIN_SEASONS)]

    def number(value, digits=2):
        return None if pd.isna(value) else round(float(value), digits)

    features = []
    for code, s in stations.iterrows():
        series = [[int(year), round(float(value), 2)] for year, value in by_year.loc[code].dropna().items() if year >= GW_CHART_FROM]
        props = {"code": code, "name": s["name"], "agency": GW_AGENCY.get(s["agency"], s["agency"]),
                 "well": s["well"] if isinstance(s["well"], str) else None, "well_depth": number(s["well_depth"], 1),
                 "district": s["district"], "before": number(s["before"]), "n_before": int(s["n_before"]),
                 "after": number(s["after"]), "n_after": int(s["n_after"]), "change": number(s["change"]),
                 "latest_year": None if pd.isna(s["latest_year"]) else int(s["latest_year"]), "latest": number(s["latest"]), "series": series}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(float(s["lon"]), 5), round(float(s["lat"]), 5)]},
                         "properties": {k: v for k, v in props.items() if v is not None}})     # a missing window is a missing key

    both = stations.dropna(subset=["change"])

    def summarise(subset: pd.DataFrame, paired: pd.DataFrame) -> dict:
        return {"wells": int(len(subset)), "wells_both": int(len(paired)), "cgwb": int((subset["agency"] == "CGWB").sum()),
                "before": number(paired["before"].mean()), "after": number(paired["after"].mean()),
                "change": number(paired["change"].median()), "rising": int((paired["change"] > 0).sum())}

    per_district = [{"district": name, **summarise(stations[stations["district"] == name], both[both["district"] == name])}
                    for name in sorted(districts["shapeName"])]
    # Year-by-year state curve: each long-running well measured against its own mean, so the growth of the
    # network (about 500 CGWB wells in 2010, 1,000 from 2014) does not masquerade as a change in level.
    chart_wells = by_year.loc[by_year.notna().sum(axis=1) >= GW_CHART_MIN_SEASONS]
    anomalies = chart_wells.sub(chart_wells.mean(axis=1), axis=0)
    grand_mean = float(chart_wells.mean(axis=1).mean())
    chart = [{"year": int(year), "depth": round(grand_mean + float(anomalies[year].mean()), 2), "wells": int(anomalies[year].notna().sum())}
             for year in anomalies.columns if year >= GW_CHART_FROM and anomalies[year].notna().sum() >= GW_CHART_MIN_WELLS]
    summary = {
        "source": GW_SOURCE, "before": {"years": list(GW_BEFORE)}, "after": {"years": list(GW_AFTER)}, "min_seasons": GW_MIN_SEASONS,
        "state": summarise(stations, both) | {
            "tgwd_last_year": int(stations.loc[stations["agency"] == "Telangana GW", "last"].max()),
            "cgwb_last_year": int(stations.loc[stations["agency"] == "CGWB", "last"].max())},
        "chart": chart, "chart_wells": int(len(chart_wells)), "chart_min_seasons": GW_CHART_MIN_SEASONS,
        "districts": per_district,
    }
    state = summary["state"]
    print(f"groundwater: {state['wells']} wells inside the state ({state['cgwb']} CGWB), {state['wells_both']} with May readings in both "
          f"windows: {state['before']} m -> {state['after']} m below ground, median change {state['change']:+} m, {state['rising']} rose; "
          f"curve from {summary['chart_wells']} wells over {len(chart)} years")
    return {"type": "FeatureCollection", "features": features}, summary


# --- cropland (GLAD) --------------------------------------------------------

CROPLAND_DIR = RAW / "cropland"
CROPLAND_EPOCHS = {2003: "2000–2003", 2007: "2004–2007", 2011: "2008–2011", 2015: "2012–2015", 2019: "2016–2019"}
CROPLAND_BEFORE, CROPLAND_AFTER = 2011, 2019      # last epoch fully before 2014; first fully after it
CROPLAND_BBOX = (77.0, 15.0, 82.0, 20.0)          # the map's DEM extent
CROPLAND_PIXEL_M = 1000.0                         # Web Mercator grid the PNGs are drawn on (source cells are ~3 km)
CROPLAND_MIN_SHOWN = 5                            # percent below which a cell stays transparent
CHANGE_MIN_SHOWN = 5                              # percentage points below which change stays transparent
CHANGE_FULL = 40                                  # percentage points at full colour
CROPLAND_RAMP = [(0, (236, 245, 210)), (50, (104, 174, 92)), (100, (18, 94, 46))]   # one green hue, light -> dark
CHANGE_LOSS, CHANGE_GAIN = (196, 60, 57), (43, 108, 176)                             # red <-> blue, neutral transparent
# Official figures quoted in the panel (Telangana Socio Economic Outlook 2023 and a 2023 government
# presentation, as reported by NITI Aayog and The News Minute; see DATA_SOURCES.md).
OFFICIAL_IRRIGATION = [
    {"label": "Gross irrigated area", "before": "62.5 lakh acres (2014-15)", "after": "135 lakh acres (2021-22)",
     "source": "https://www.nitiforstates.gov.in/public-assets/Policy/policy_files/RSSNAM000500.pdf"},
    {"label": "Paddy sown, kharif", "before": "22.7 lakh acres (2014)", "after": "65.0 lakh acres (2022)",
     "source": "https://thenewsminute.com/telangana/telanganas-irrigated-area-has-increased-what-role-have-irrigation-projects-played"},
    {"label": "Gross cropped area", "before": "129 lakh acres (2014-15)", "after": "233 lakh acres (2022-23)",
     "source": "https://thenewsminute.com/telangana/telanganas-irrigated-area-has-increased-what-role-have-irrigation-projects-played"},
]


def cropland_grid() -> tuple[rasterio.Affine, int, int]:
    """Web Mercator grid covering CROPLAND_BBOX at CROPLAND_PIXEL_M."""
    with rasterio.open(CROPLAND_DIR / f"Global_cropland_3km_{CROPLAND_AFTER}.tif") as src:
        window = rasterio.windows.from_bounds(*CROPLAND_BBOX, src.transform)
        transform, width, height = calculate_default_transform(
            src.crs, MERCATOR, int(window.width), int(window.height), *CROPLAND_BBOX, resolution=CROPLAND_PIXEL_M)
    return transform, width, height


def cropland_epoch(year: int, transform: rasterio.Affine, width: int, height: int) -> np.ndarray:
    """Percent cropland for one epoch on the Mercator grid (float32, 0-100)."""
    out = np.zeros((height, width), dtype=np.float32)
    with rasterio.open(CROPLAND_DIR / f"Global_cropland_3km_{year}.tif") as src:
        reproject(rasterio.band(src, 1), out, dst_transform=transform, dst_crs=MERCATOR,
                  dst_nodata=0.0, resampling=Resampling.bilinear)
    return np.clip(out, 0, 100)


def ramp_rgba(values: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]], alpha_from: float, alpha_to: float,
              min_shown: float, full: float) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=np.float32)
    rgb = np.stack([np.interp(values, xs, [s[1][c] for s in stops]) for c in range(3)], axis=-1)
    alpha = np.interp(values, [min_shown, full], [alpha_from, alpha_to]) * 255
    alpha = np.where(values < min_shown, 0, alpha)
    return np.dstack([rgb, alpha]).astype(np.uint8)


def change_rgba(delta: np.ndarray) -> np.ndarray:
    magnitude = np.clip(np.abs(delta), 0, CHANGE_FULL)
    colour = np.where((delta > 0)[..., None], CHANGE_GAIN, CHANGE_LOSS).astype(np.float32)
    alpha = np.interp(magnitude, [CHANGE_MIN_SHOWN, CHANGE_FULL], [0.35, 0.92]) * 255
    alpha = np.where(magnitude < CHANGE_MIN_SHOWN, 0, alpha)
    return np.dstack([colour, alpha]).astype(np.uint8)


def zonal_mean(values: np.ndarray, geometry, transform: rasterio.Affine) -> tuple[float, int]:
    inside = ~geometry_mask([geometry], out_shape=values.shape, transform=transform)
    return float(values[inside].mean()) if inside.any() else float("nan"), int(inside.sum())


def build_cropland(state: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> dict:
    transform, width, height = cropland_grid()
    epochs = {year: cropland_epoch(year, transform, width, height) for year in CROPLAND_EPOCHS}
    before, after = epochs[CROPLAND_BEFORE], epochs[CROPLAND_AFTER]
    Image.fromarray(ramp_rgba(before, CROPLAND_RAMP, 0.25, 0.9, CROPLAND_MIN_SHOWN, 100), "RGBA").save(WEB_DATA / "cropland_before.png")
    Image.fromarray(ramp_rgba(after, CROPLAND_RAMP, 0.25, 0.9, CROPLAND_MIN_SHOWN, 100), "RGBA").save(WEB_DATA / "cropland_after.png")
    Image.fromarray(change_rgba(after - before), "RGBA").save(WEB_DATA / "cropland_change.png")

    to_wgs = Transformer.from_crs(MERCATOR, WGS84, always_xy=True)
    west, north = to_wgs.transform(transform.c, transform.f)
    east, south = to_wgs.transform(transform.c + width * transform.a, transform.f + height * transform.e)
    pixel_km2 = (CROPLAND_PIXEL_M / 1000) ** 2    # Mercator pixels; true area differs by <6 % across 15-20 °N

    state_m = state.to_crs(MERCATOR).geometry.iloc[0]
    state_rows = {}
    for year, values in epochs.items():
        mean, cells = zonal_mean(values, state_m, transform)
        state_rows[str(year)] = {"epoch": CROPLAND_EPOCHS[year], "pct": round(mean, 1), "km2": round(mean / 100 * cells * pixel_km2)}

    rows = []
    for _, district in districts.to_crs(MERCATOR).iterrows():
        pct_before, cells = zonal_mean(before, district.geometry, transform)
        pct_after, _ = zonal_mean(after, district.geometry, transform)
        point = district.geometry.representative_point()
        lon, lat = to_wgs.transform(point.x, point.y)
        rows.append({"district": district["shapeName"], "pct_before": round(pct_before, 1), "pct_after": round(pct_after, 1),
                     "change_pp": round(pct_after - pct_before, 1), "km2_before": round(pct_before / 100 * cells * pixel_km2),
                     "km2_after": round(pct_after / 100 * cells * pixel_km2), "lon": round(lon, 4), "lat": round(lat, 4)})
    rows.sort(key=lambda r: -r["change_pp"])
    return {"bounds": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
            "before": {"year": CROPLAND_BEFORE, "epoch": CROPLAND_EPOCHS[CROPLAND_BEFORE]},
            "after": {"year": CROPLAND_AFTER, "epoch": CROPLAND_EPOCHS[CROPLAND_AFTER]},
            "state": state_rows, "districts": rows, "official": OFFICIAL_IRRIGATION,
            "legend": {"ramp": CROPLAND_RAMP, "loss": CHANGE_LOSS, "gain": CHANGE_GAIN, "change_full": CHANGE_FULL}}


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
    dams = build_dams(state, reaches)
    print(f"dams: {len(dams)} ({sum(1 for d in dams if d['kind'] == 'barrage')} barrages, "
          f"{sum(1 for d in dams if d['height'] is None)} without height, "
          f"{sum(1 for d in dams if d['capacity_tmcft'] is None)} without capacity)")
    for dam in dams:
        print(f"  {dam['kind']:7} {dam['name'][:30]:30} {str(dam['height'] or '-'):>4} m  "
              f"{dam['began'] or '----'}-{dam['opened'] or '----'}  cap {str(dam['capacity_tmcft'] or '-'):>7} tmcft  "
              f"inflow {str(dam['inflow_q'] or '-'):>5} m3/s {dam['inflow_name'] or ''}")
    if (RAW / "osm_dam_lines.json").exists():
        (WEB_DATA / "dam_lines.geojson").write_text(json.dumps(build_dam_lines(dams)), encoding="utf-8")
    else:
        print("  warning: data/raw/osm_dam_lines.json missing (fetch_data.py); dam_lines.geojson not built")
    pumphouses = load_pumphouses()
    for node in [*dams, *pumphouses]:
        elevation = sampler.median(node["lon"], node["lat"], NODE_ELEV_RADIUS_PX)
        node["elev_m"] = round(elevation) if elevation is not None else None
    (WEB_DATA / "dams.json").write_text(json.dumps(dams, indent=1, ensure_ascii=False), encoding="utf-8")
    (WEB_DATA / "pumphouses.json").write_text(json.dumps(pumphouses, indent=1, ensure_ascii=False), encoding="utf-8")
    (WEB_DATA / "pending.json").write_text(json.dumps(PENDING_NOTES, indent=1, ensure_ascii=False), encoding="utf-8")
    pending = [d for d in dams if d["status"] != "operational"]
    print(f"pending: {len(pending)} structures ({sum(1 for d in pending if d['status'] == 'proposed')} proposed, "
          f"{sum(1 for d in pending if d['approx'])} at approximate positions), {len(PENDING_NOTES)} without coordinates")
    for dam in pending:
        print(f"  {dam['status']:18} {dam['kind']:7} {dam['name'][:38]:38} {dam['scheme'] or ''}")
    links = build_links({node["name"]: node for node in dams} | {node["osm_name"]: node for node in pumphouses})
    (WEB_DATA / "links.geojson").write_text(json.dumps(links), encoding="utf-8")
    if (RAW / "osm_canals.json").exists():
        canals, canal_summary = build_canals(links)
        (WEB_DATA / "canals.geojson").write_text(json.dumps(canals), encoding="utf-8")
        (WEB_DATA / "canals_summary.json").write_text(json.dumps(canal_summary, indent=1), encoding="utf-8")
    else:
        print("  warning: data/raw/osm_canals.json missing (fetch_data.py); canals.geojson not built")
    if (RAW / "osm_canals.json").exists():
        (WEB_DATA / "conduits.geojson").write_text(json.dumps(build_conduits(canals)), encoding="utf-8")
    if (RAW / "osm_water.json").exists():
        tank_polygons, tank_points, tank_summary = build_tanks(state, districts)
        (WEB_DATA / "tanks.geojson").write_text(json.dumps(tank_polygons), encoding="utf-8")
        (WEB_DATA / "tank_points.geojson").write_text(json.dumps(tank_points), encoding="utf-8")
        (WEB_DATA / "tanks_summary.json").write_text(json.dumps(tank_summary, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  tanks.geojson {(WEB_DATA / 'tanks.geojson').stat().st_size / 1e6:.1f} MB, "
              f"tank_points.geojson {(WEB_DATA / 'tank_points.geojson').stat().st_size / 1e6:.1f} MB")
    else:
        print("  warning: data/raw/osm_water.json missing (fetch_data.py); tanks not built")
    if (RAW / "osm_water.json").exists():
        (WEB_DATA / "reservoirs.geojson").write_text(json.dumps(build_reservoirs(dams, sampler)), encoding="utf-8")
    if (RAW / "gw_levels.csv.gz").exists():
        gw_points, gw_summary = build_groundwater(districts)
        (WEB_DATA / "groundwater.geojson").write_text(json.dumps(gw_points), encoding="utf-8")
        (WEB_DATA / "groundwater_summary.json").write_text(json.dumps(gw_summary, indent=1, ensure_ascii=False), encoding="utf-8")
        for row in sorted(gw_summary["districts"], key=lambda r: r["change"] or 0, reverse=True)[:4] + [gw_summary["districts"][-1]]:
            print(f"  {row['district']:22} {row['wells_both']:3} wells  {row['before']} -> {row['after']} m  ({row['change']:+} m)")
    else:
        print("  warning: data/raw/gw_levels.csv.gz missing (fetch_data.py); groundwater not built")
    cropland = build_cropland(state, districts)
    (WEB_DATA / "cropland.json").write_text(json.dumps(cropland, indent=1, ensure_ascii=False), encoding="utf-8")
    print("cropland (GLAD, % of area): " + ", ".join(f"{v['epoch']} {v['pct']}%" for v in cropland["state"].values()))
    for row in cropland["districts"][:5] + cropland["districts"][-3:]:
        print(f"  {row['district']:18} {row['pct_before']:5}% -> {row['pct_after']:5}%  ({row['change_pp']:+.1f} pp)")
    print(f"links: {len(pumphouses)} pump houses/intakes, {len(links['features'])} links")
    for f in links["features"]:
        p = f["properties"]
        print(f"  {p['scheme'][:20]:20} {p['link'][:22]:22} {p['from'][:26]:26} -> {p['to'][:28]:28} {p['status']:12} "
              f"{p['straight_km']:6} km  {p['elev_from']} -> {p['elev_to']} m (lift {p['lift_m']})")
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

"""Planning model: river water for most of Telangana's farmland.

Not a design, a reasoned sketch built from the data already on the map, under stated norms:

- ESA WorldCover 2021 (320 m) says what land is cultivable (crop, grass, shrub, bare, not steep) and
  what is already cropland; the target is TARGET_SHARE of cultivable land under crops in every district.
- Water need = new acres / DUTY_NEW + rainfed existing acres / DUTY_STABILISE (TMC a year).
- New reservoirs are sited on the 200 m DEM: every HydroRIVERS reach end of order 4+ is tried with
  dams of 20, 30 and 40 m; the pool is the DEM below crest behind a dam line scanned across the valley,
  priced by storage, dam volume and the farmland and towns it would drown; the cheapest storage per
  district is picked until that district's share of storage is met.
- Each reservoir is fed from the cheapest source (Godavari and Krishna barrages, existing reservoirs
  that lift schemes already fill): straight-line route, lift to full reservoir level, tunnels where
  the ground is above that level, pump stages of at most 120 m like Kaleshwaram's.
- Command = cultivable land within COMMAND_KM below each reservoir's level, served by gravity.
- Costs are indicative unit rates calibrated on Kaleshwaram (Rs 80,190 crore, 225 TMC) and
  Palamuru-Rangareddy (Rs 35,000 crore, 90 TMC).

Writes web/data/proposal.json (budget, works, tables) and web/data/proposal.geojson (pools, routes,
pump houses, command areas). Run after build_web_data.py --skip-tiles; fetch_data.py must have fetched
data/raw/worldcover_320m.tif.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize, shapes
from scipy.ndimage import label
from shapely.geometry import LineString, Point, shape

import build_web_data as b

WGS84 = "EPSG:4326"
WORLDCOVER = b.RAW / "worldcover_320m.tif"

# --- planning norms ----------------------------------------------------------
TARGET_SHARE = 0.90                         # cropland as a share of cultivable land: the upper end of the 80-90 % ask
TARGET_RANGE = (0.80, 0.85)
MAX_SLOPE_PCT = 15.0                        # steeper land is not counted cultivable
DUTY_NEW_ACRES_PER_TMC = 10_000             # ~0.7 m of water a year: between paddy and irrigated-dry crops
DUTY_STABILISE_ACRES_PER_TMC = 20_000       # supplemental water for land already cropped under rain
RAINFED_SHARE = 0.42                        # gross irrigated 135 of 233 lakh acres gross cropped (2021-22, official)
ACRES_PER_KM2 = 247.105
TMC_M3 = 28.317e6
STORAGE_PER_ANNUAL = 0.6                    # Kaleshwaram: 147 TMC of storage for 225 TMC a year
# Legal envelopes (TMC a year). Godavari: 967.94 share, of which 758.76 cleared by CWC, 148.82 cleared for
# availability, 60.26 reserve (CM's letter, Sept 2021). Krishna: 299 interim share, fully committed. In June
# 2025 the state asked the Centre for 1,000 + 500.
ENVELOPES = {
    "Godavari": {"award": 967.94, "committed": 758.76 + 148.82, "requested": 1000.0,
                 "mean_flow_tmc": None},    # filled from HydroRIVERS at the state exit
    "Krishna": {"award": 299.0, "committed": 299.0, "requested": 500.0, "mean_flow_tmc": None},
}
# --- siting --------------------------------------------------------------------
CREST_OPTIONS_M = (20, 30, 40)
MIN_ORDER = 4
MIN_FLOW_CMS = 3.0
MIN_SITE_ELEV_M = 100                       # the Godavari trough below this has little land above it to serve
MIN_STORAGE_TMC = 3.0
MAX_DAM_KM = 16.0                           # total embankment length (Sriram Sagar 15.6 km, Mallanna Sagar 22 km)
MAX_CROPLAND_KM2_PER_TMC = 2.5              # Mallanna Sagar drowned about 1.4 km2 of farmland per TMC
POOL_WINDOW_CELLS = 150                     # 30 km at 200 m
SITE_SAMPLE_M = 5_000                       # try a dam every 5 km along each reach, not only at its end
EXISTING_CLEARANCE_M = 12_000
SITE_SPACING_M = 15_000
DISTRICT_MARGIN_M = 20_000                  # a district's storage may sit this far outside its boundary
MAX_BUILTUP_SHARE = 0.03
MAX_RESERVOIRS = 60
MIN_ANNUAL_TMC = 2.0
# --- conveyance ------------------------------------------------------------------
PUMP_STAGE_M = 120                          # Kaleshwaram lifts in stages of about 100-120 m
FRICTION_M = 15
TUNNEL_ABOVE_M = 25                         # ground this far above the water level is tunnelled
CANAL_SINUOSITY = 1.4                       # contour canals are longer than the straight line
PUMP_DAYS = 120                             # monsoon pumping season
COMMAND_KM = 45
COMMAND_HEAD_M = 10
# --- unit costs, Rs crore ---------------------------------------------------------
COST_STORAGE_PER_TMC = 100                  # spillway, outlets and works that scale with volume
COST_EMBANKMENT_PER_KM_M = 1.2              # earthen bund, per km of length and metre of height
COST_LAND_PER_HA = 0.6                      # land, rehabilitation and resettlement of the pool (Mallanna Sagar class)
COST_DISTRIBUTION_PER_TMC = 150             # distributaries and field channels for the 10,000 acres a TMC serves, Rs 1.5 lakh an acre
BALANCING_STORAGE_SHARE = 0.1               # a lift delivery without its own reservoir still needs balancing tanks
COST_PUMP_PER_MW = 8
COST_TUNNEL_PER_KM = 110                    # SLBC class
COST_CANAL_PER_KM = 20                      # lined main canal
POWER_RS_PER_KWH = 6.0
PUMP_EFFICIENCY = 0.75
ENERGY_YEARS = 10                           # energy counted in the source choice
COST_SOURCES = {
    "Kaleshwaram Lift Irrigation Project": ("Rs 80,190 crore, 225 TMC a year, 147 TMC storage, lifts to 618 m", "https://en.wikipedia.org/wiki/Kaleshwaram_Lift_Irrigation_Project"),
    "Palamuru-Rangareddy Lift Irrigation Scheme": ("Rs 35,000 crore, 90 TMC a year, 67.5 TMC storage", "https://en.wikipedia.org/wiki/Palamuru-Rangareddy_Lift_Irrigation_Scheme"),
    "Sammakka Sagar Barrage": ("Rs 2,121 crore, 6.94 TMC barrage", "https://en.wikipedia.org/wiki/Sammakka_Sagar_Barrage"),
    "Kalwakurthy lift scheme": ("Rs 2,100 crore, 25 TMC a year", "https://en.wikipedia.org/wiki/Mahatma_Gandhi_Kalwakurthy_lift_irrigation_scheme"),
}
# Where new water can be taken from (name as in dams.json: basin, river intake). River intakes draw on the
# flow passing them; a reservoir named with an intake is a hub that the intake's lift scheme fills (built or
# under construction), so water routed through it is debited to the intake and pays the intake's lift too.
# Reservoirs living on their own catchments (Singur, Nizam Sagar, Lower Manair) are hubs of the Kaleshwaram
# links that feed them, not sources: their own water is already committed.
SOURCES = {
    "Medigadda Barrage": ("Godavari", None), "Sammakka Sagar Barrage": ("Godavari", None), "Sitamma Sagar Barrage": ("Godavari", None),
    "Sripada Yellampalli Project": ("Godavari", None), "Sriram Sagar Project": ("Godavari", None),
    "Parvati Barrage": ("Godavari", "Medigadda Barrage"), "Saraswati Barrage": ("Godavari", "Medigadda Barrage"),
    "Mid Manair Dam": ("Godavari", "Medigadda Barrage"), "Lower Manair Dam": ("Godavari", "Medigadda Barrage"),
    "Mallanna Sagar": ("Godavari", "Medigadda Barrage"), "Konda Pochamma Sagar": ("Godavari", "Medigadda Barrage"),
    "Ranganayaka Sagar": ("Godavari", "Medigadda Barrage"), "Baswapur reservoir": ("Godavari", "Medigadda Barrage"),
    "Annapurna reservoir (Anantha Sagar)": ("Godavari", "Medigadda Barrage"), "Singur Dam": ("Godavari", "Medigadda Barrage"),
    "Nizam Sagar": ("Godavari", "Medigadda Barrage"), "Gouravelli reservoir": ("Godavari", "Sriram Sagar Project"),
    "Jurala Project": ("Krishna", None), "Srisailam Dam": ("Krishna", None), "Nagarjuna Sagar Dam": ("Krishna", None), "Pulichintala Project": ("Krishna", None),
    "Veeranjaneya reservoir (Yedula)": ("Krishna", "Srisailam Dam"), "Venkatadri reservoir (Vattem)": ("Krishna", "Srisailam Dam"),
    "Kurumurthy Raya reservoir (Karvena)": ("Krishna", "Srisailam Dam"), "Dindi reservoir": ("Krishna", "Srisailam Dam"),
}
RIVER_SURPLUS_SHARE = 0.25                  # of the mean flow passing an intake may be taken in the monsoon (Kaleshwaram takes ~11 % at Medigadda)
WC_CULTIVABLE = (20, 30, 40, 60)            # shrub, grass, crop, bare
WC_CROP = 40
WC_BUILT = 50
WC_TREE = 10


def tmc_per_year(cms: float) -> float:
    return cms * 365.25 * 86400 / TMC_M3


class Grids:
    """DEM (200 m, Lambert) and WorldCover (320 m, WGS84) with the lookups the model needs."""

    def __init__(self) -> None:
        self.dem_ds = rasterio.open(b.PROFILE_DEM)
        self.dem = self.dem_ds.read(1).astype(np.float32)
        self.dem[self.dem <= -1000] = np.nan
        self.to_dem = Transformer.from_crs(WGS84, self.dem_ds.crs, always_xy=True)
        self.to_wgs = Transformer.from_crs(self.dem_ds.crs, WGS84, always_xy=True)
        gy, gx = np.gradient(np.nan_to_num(self.dem, nan=0.0), 200.0)
        self.slope_pct = np.hypot(gx, gy) * 100
        self.wc_ds = rasterio.open(WORLDCOVER)
        self.wc = self.wc_ds.read(1)
        self.wc_transform = self.wc_ds.transform
        rows, cols = np.indices(self.wc.shape)
        lon, lat = rasterio.transform.xy(self.wc_transform, rows.ravel(), cols.ravel(), offset="center")
        self.wc_lon = np.asarray(lon).reshape(self.wc.shape)
        self.wc_lat = np.asarray(lat).reshape(self.wc.shape)
        self.wc_x, self.wc_y = self.to_dem.transform(self.wc_lon, self.wc_lat)
        dem_row, dem_col = self.dem_rc(self.wc_x, self.wc_y)
        inside = (dem_row >= 0) & (dem_row < self.dem.shape[0]) & (dem_col >= 0) & (dem_col < self.dem.shape[1])
        self.wc_elev = np.full(self.wc.shape, np.nan, dtype=np.float32)
        self.wc_slope = np.full(self.wc.shape, np.nan, dtype=np.float32)
        self.wc_elev[inside] = self.dem[dem_row[inside], dem_col[inside]]
        self.wc_slope[inside] = self.slope_pct[dem_row[inside], dem_col[inside]]
        cell_deg = abs(self.wc_transform.a)
        self.wc_km2 = (cell_deg * 111.32) * (cell_deg * 111.32 * np.cos(np.radians(self.wc_lat)))
        self.cultivable = np.isin(self.wc, WC_CULTIVABLE) & (self.wc_slope <= MAX_SLOPE_PCT)

    def dem_rc(self, x, y):
        t = ~self.dem_ds.transform
        col, row = t * (np.asarray(x), np.asarray(y))
        return np.floor(row).astype(int), np.floor(col).astype(int)

    def elev_at(self, lon: float, lat: float) -> float:
        x, y = self.to_dem.transform(lon, lat)
        r, c = self.dem_rc(x, y)
        return float(self.dem[r, c]) if 0 <= r < self.dem.shape[0] and 0 <= c < self.dem.shape[1] else float("nan")

    def wc_rc(self, lon, lat):
        t = ~self.wc_transform
        col, row = t * (np.asarray(lon), np.asarray(lat))
        return np.floor(row).astype(int), np.floor(col).astype(int)


def district_raster(grids: Grids, districts: gpd.GeoDataFrame) -> np.ndarray:
    """WorldCover-grid array of district index + 1 (0 outside the state)."""
    shapes_ = [(geom, i + 1) for i, geom in enumerate(districts.to_crs(WGS84).geometry)]
    return rasterize(shapes_, out_shape=grids.wc.shape, transform=grids.wc_transform, fill=0, dtype=np.int32)


def demand_table(grids: Grids, districts: gpd.GeoDataFrame, district_ix: np.ndarray) -> tuple[list[dict], dict]:
    rows = []
    for i, name in enumerate(districts["shapeName"]):
        m = district_ix == i + 1
        area = float(grids.wc_km2[m].sum())
        cult = float(grids.wc_km2[m & grids.cultivable].sum())
        crop = float(grids.wc_km2[m & (grids.wc == WC_CROP)].sum())
        tree = float(grids.wc_km2[m & (grids.wc == WC_TREE)].sum())
        built = float(grids.wc_km2[m & (grids.wc == WC_BUILT)].sum())
        water = float(grids.wc_km2[m & np.isin(grids.wc, (80, 90, 95))].sum())
        target = TARGET_SHARE * cult
        new_km2 = max(0.0, target - crop)
        rainfed_acres = RAINFED_SHARE * crop * ACRES_PER_KM2
        tmc = new_km2 * ACRES_PER_KM2 / DUTY_NEW_ACRES_PER_TMC + rainfed_acres / DUTY_STABILISE_ACRES_PER_TMC
        rows.append({"district": name, "area_km2": round(area), "cultivable_km2": round(cult), "cropland_km2": round(crop),
                     "tree_km2": round(tree), "builtup_km2": round(built), "water_km2": round(water),
                     "cultivable_pct": round(100 * cult / area, 1), "cropland_pct": round(100 * crop / area, 1),
                     "cropland_of_cultivable_pct": round(100 * crop / cult, 1) if cult else None,
                     "target_km2": round(target), "new_km2": round(new_km2), "new_lakh_acres": round(new_km2 * ACRES_PER_KM2 / 1e5, 2),
                     "tmc_new": round(new_km2 * ACRES_PER_KM2 / DUTY_NEW_ACRES_PER_TMC, 1),
                     "tmc_stabilise": round(rainfed_acres / DUTY_STABILISE_ACRES_PER_TMC, 1), "tmc": round(tmc, 1)})
    total = {k: round(sum(r[k] for r in rows), 1 if k.startswith("tmc") or k.endswith("acres") else 0)
             for k in ("area_km2", "cultivable_km2", "cropland_km2", "tree_km2", "builtup_km2", "water_km2", "target_km2", "new_km2", "new_lakh_acres", "tmc_new", "tmc_stabilise", "tmc")}
    total["cultivable_pct"] = round(100 * total["cultivable_km2"] / total["area_km2"], 1)
    total["cropland_pct"] = round(100 * total["cropland_km2"] / total["area_km2"], 1)
    total["cropland_of_cultivable_pct"] = round(100 * total["cropland_km2"] / total["cultivable_km2"], 1)
    for share in TARGET_RANGE:
        new = sum(max(0.0, share * r["cultivable_km2"] - r["cropland_km2"]) for r in rows)
        total[f"new_lakh_acres_at_{int(share * 100)}"] = round(new * ACRES_PER_KM2 / 1e5, 1)
        total[f"tmc_at_{int(share * 100)}"] = round(new * ACRES_PER_KM2 / DUTY_NEW_ACRES_PER_TMC + total["tmc_stabilise"], 0)
    return rows, total


def load_existing(grids: Grids) -> tuple[list[dict], list[dict]]:
    dams = json.loads((b.WEB_DATA / "dams.json").read_text(encoding="utf-8"))
    for d in dams:
        d["x"], d["y"] = grids.to_dem.transform(d["lon"], d["lat"])
    by_name = {d["name"]: d for d in dams}
    sources = []
    for d in dams:
        if d["name"] not in SOURCES or d["status"] == "proposed":
            continue
        basin, intake = SOURCES[d["name"]]
        d["basin"] = basin
        d["intake"] = intake or d["name"]
        d["base_lift_m"] = max(0.0, (d["elev_m"] or 0) - (by_name[intake]["elev_m"] or 0)) if intake else 0.0
        sources.append(d)
    return dams, sources


def intake_caps(sources: list[dict]) -> dict[str, float]:
    """TMC a year each river intake may newly supply: a share of the mean flow HydroRIVERS puts past it."""
    caps = {}
    for s in sources:
        if s["intake"] == s["name"]:
            caps[s["name"]] = RIVER_SURPLUS_SHARE * tmc_per_year(s["inflow_q"]) if s.get("inflow_q") else 0.0
    return caps


def candidate_sites(grids: Grids, state: gpd.GeoDataFrame, dams: list[dict]) -> list[dict]:
    reaches = b.load_reaches()
    reaches = reaches[(reaches["ORD_STRA"] >= MIN_ORDER) & (reaches["DIS_AV_CMS"] >= MIN_FLOW_CMS)]
    reaches = reaches.to_crs(grids.dem_ds.crs)
    state_geom = state.to_crs(grids.dem_ds.crs).geometry.iloc[0]
    dam_xy = np.array([(d["x"], d["y"]) for d in dams])
    out = []
    for _, reach in reaches.iterrows():
        line = reach.geometry
        distances = list(np.arange(SITE_SAMPLE_M, line.length, SITE_SAMPLE_M)) + [line.length]
        for along in distances:
            point = line.interpolate(along)
            if not state_geom.contains(point):
                continue
            if np.min(np.hypot(dam_xy[:, 0] - point.x, dam_xy[:, 1] - point.y)) < EXISTING_CLEARANCE_M:
                continue
            back = line.interpolate(max(0.0, along - 600))
            dx, dy = point.x - back.x, point.y - back.y
            norm = math.hypot(dx, dy) or 1.0
            out.append({"x": point.x, "y": point.y, "flow": (dx / norm, dy / norm), "cms": float(reach["DIS_AV_CMS"]),
                        "upland_km2": float(reach["UPLAND_SKM"]), "order": int(reach["ORD_STRA"])})
    return out


REJECTED: dict[str, int] = {}


def reject(reason: str) -> None:
    REJECTED[reason] = REJECTED.get(reason, 0) + 1


def pool_for(grids: Grids, site: dict, crest_m: float, towns_rc: np.ndarray) -> dict | None:
    """Flood the DEM behind a dam line at the site; None when the valley is too wide, leaks or drowns a town."""
    r0, c0 = grids.dem_rc(site["x"], site["y"])
    base = grids.dem[r0, c0]
    if not np.isfinite(base) or base < MIN_SITE_ELEV_M:
        return reject("below the plateau")
    crest = base + crest_m
    w = POOL_WINDOW_CELLS
    r_lo, r_hi, c_lo, c_hi = r0 - w, r0 + w + 1, c0 - w, c0 + w + 1
    if r_lo < 0 or c_lo < 0 or r_hi > grids.dem.shape[0] or c_hi > grids.dem.shape[1]:
        return reject("at the DEM edge")
    window = grids.dem[r_lo:r_hi, c_lo:c_hi]
    flooded = window < crest
    # dam line across the valley, perpendicular to the flow, until the ground reaches the crest
    fx, fy = site["flow"]
    px, py = -fy, fx                                     # perpendicular (x east, y north); rows grow southwards
    dam_cells = []
    max_cells = int(MAX_DAM_KM * 1000 / 200)
    for sign in (1, -1):
        for step in range(1, max_cells + 1):
            rr = w + int(round(-sign * py * step))
            cc = w + int(round(sign * px * step))
            if not (0 <= rr < window.shape[0] and 0 <= cc < window.shape[1]):
                return reject("valley too wide")
            if window[rr, cc] >= crest:
                break
            dam_cells.append((rr, cc))
        else:
            return reject("valley too wide")
    dam_len_km = (len(dam_cells) + 1) * 0.2
    if dam_len_km > MAX_DAM_KM:
        return reject("valley too wide")
    blocked = flooded.copy()
    blocked[w, w] = False
    for rr, cc in dam_cells:
        blocked[rr, cc] = False
    labels, _ = label(blocked, structure=np.ones((3, 3)))
    ur = w - int(round(-fy * 2))                           # two cells upstream of the dam
    uc = w - int(round(fx * 2))
    pool_id = labels[ur, uc]
    if pool_id == 0:
        return reject("no pool upstream")
    pool = labels == pool_id
    if pool[0, :].any() or pool[-1, :].any() or pool[:, 0].any() or pool[:, -1].any():
        return reject("leaks past 30 km")
    depth = crest - window[pool]
    volume_tmc = float(depth.sum()) * 200 * 200 / TMC_M3
    if volume_tmc < MIN_STORAGE_TMC:
        return reject("too small")
    rows, cols = np.nonzero(pool)
    pool_rows, pool_cols = rows + r_lo, cols + c_lo
    if towns_rc.size and np.any((towns_rc[:, 0][:, None] == pool_rows[None, :]) & (towns_rc[:, 1][:, None] == pool_cols[None, :])):
        return reject("drowns a town")
    xs, ys = grids.dem_ds.transform * (pool_cols + 0.5, pool_rows + 0.5)
    lon, lat = grids.to_wgs.transform(xs, ys)
    wr, wcix = grids.wc_rc(lon, lat)
    classes = grids.wc[np.clip(wr, 0, grids.wc.shape[0] - 1), np.clip(wcix, 0, grids.wc.shape[1] - 1)]
    area_km2 = pool.sum() * 0.04
    crop_km2 = float((classes == WC_CROP).mean()) * area_km2
    built_share = float((classes == WC_BUILT).mean())
    if built_share > MAX_BUILTUP_SHARE:
        return reject("drowns built-up land")
    if crop_km2 / volume_tmc > MAX_CROPLAND_KM2_PER_TMC:
        return reject("drowns too much farmland")
    cost = COST_STORAGE_PER_TMC * volume_tmc + COST_EMBANKMENT_PER_KM_M * dam_len_km * crest_m + COST_LAND_PER_HA * area_km2 * 100
    return {"crest_m": crest_m, "frl_m": round(float(crest), 1), "bed_m": round(float(base), 1), "storage_tmc": round(volume_tmc, 2),
            "area_km2": round(area_km2, 1), "cropland_km2": round(crop_km2, 1), "tree_km2": round(float((classes == WC_TREE).mean()) * area_km2, 1),
            "dam_km": round(dam_len_km, 1), "cost_cr": round(cost), "cost_per_tmc": round(cost / volume_tmc),
            "pool_rows": pool_rows, "pool_cols": pool_cols, "centre_lon": float(lon.mean()), "centre_lat": float(lat.mean())}


def pool_polygon(grids: Grids, pool_rows: np.ndarray, pool_cols: np.ndarray):
    r_lo, c_lo = pool_rows.min() - 1, pool_cols.min() - 1
    mask = np.zeros((pool_rows.max() - r_lo + 2, pool_cols.max() - c_lo + 2), dtype=np.uint8)
    mask[pool_rows - r_lo, pool_cols - c_lo] = 1
    transform = grids.dem_ds.transform * grids.dem_ds.transform.translation(c_lo, r_lo)
    geoms = [shape(g) for g, v in shapes(mask, mask=mask.astype(bool), transform=transform) if v == 1]
    geom = max(geoms, key=lambda g: g.area)
    return gpd.GeoSeries([geom], crs=grids.dem_ds.crs).to_crs(WGS84).iloc[0].simplify(0.0008)


def choose_reservoirs(grids: Grids, sites: list[dict], districts: gpd.GeoDataFrame, demand: list[dict], towns: list[dict]) -> list[dict]:
    """Cheapest storage per district until its share of storage is met, with spacing between dams."""
    towns_rc = np.array([grids.dem_rc(*grids.to_dem.transform(t["lon"], t["lat"])) for t in towns]) if towns else np.empty((0, 2), int)
    options = []                                           # every (site, crest) that works
    for i, site in enumerate(sites):
        for crest in CREST_OPTIONS_M:
            pool = pool_for(grids, site, crest, towns_rc)
            if pool:
                options.append({**site, **pool, "site": i})
    print(f"  {len(sites)} candidate sites x {len(CREST_OPTIONS_M)} dam heights: {len(options)} workable pools; rejected "
          + ", ".join(f"{v} {k}" for k, v in sorted(REJECTED.items(), key=lambda kv: -kv[1])))
    districts_dem = districts.to_crs(grids.dem_ds.crs)
    for cand in options:
        hits = districts_dem[districts_dem.contains(Point(cand["x"], cand["y"]))]
        cand["district"] = hits["shapeName"].iloc[0] if len(hits) else None
    chosen: list[dict] = []
    for row in sorted(demand, key=lambda r: -r["tmc"]):
        target_storage = STORAGE_PER_ANNUAL * row["tmc"]
        geom = districts_dem.loc[districts_dem["shapeName"] == row["district"], "geometry"].iloc[0]
        nearby = [c for c in options if geom.distance(Point(c["x"], c["y"])) <= DISTRICT_MARGIN_M]
        have = 0.0
        while have < target_storage and len(chosen) < MAX_RESERVOIRS:
            remaining_storage = target_storage - have
            if remaining_storage / STORAGE_PER_ANNUAL < MIN_ANNUAL_TMC:
                break
            fits = [c for c in nearby if c["storage_tmc"] <= max(1.5 * remaining_storage, MIN_STORAGE_TMC)
                    and not any(c["site"] == k["site"] or math.hypot(c["x"] - k["x"], c["y"] - k["y"]) < SITE_SPACING_M for k in chosen)]
            if not fits:
                break
            cand = min(fits, key=lambda c: c["cost_per_tmc"])
            cand["annual_tmc"] = min(cand["storage_tmc"], remaining_storage) / STORAGE_PER_ANNUAL
            cand["serves"] = row["district"]
            chosen.append(cand)
            have += cand["storage_tmc"]
        row["storage_target_tmc"] = round(target_storage, 1)
        row["storage_sited_tmc"] = round(have, 1)
    return chosen


def route_profile(grids: Grids, x0, y0, x1, y1, step_m=500.0):
    n = max(2, int(math.hypot(x1 - x0, y1 - y0) / step_m))
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    r, c = grids.dem_rc(xs, ys)
    ok = (r >= 0) & (r < grids.dem.shape[0]) & (c >= 0) & (c < grids.dem.shape[1])
    elev = np.full(n, np.nan)
    elev[ok] = grids.dem[r[ok], c[ok]]
    return xs, ys, np.nan_to_num(elev, nan=0.0)


def plan_conveyance(grids: Grids, reservoir: dict, sources: list[dict], caps: dict[str, float], basin_caps: dict[str, float]) -> dict:
    """Cheapest feeder with water to spare: lift + tunnels + canal + ten years of power. Debits the intake and basin caps."""
    best = None
    need = reservoir["annual_tmc"]
    usable = [s for s in sources if caps.get(s["intake"], 0.0) >= need and basin_caps.get(s["basin"], float("inf")) >= need]
    over_cap = not usable
    for src in usable or sources:
        src_level = (src["elev_m"] or 0) + 5
        lift = max(0.0, reservoir["frl_m"] - src_level) + FRICTION_M          # new lift from this source
        total_lift = lift + src["base_lift_m"]                                # plus the existing lift into a hub, which needs more pumps
        xs, ys, prof = route_profile(grids, src["x"], src["y"], reservoir["x"], reservoir["y"])
        km = math.hypot(reservoir["x"] - src["x"], reservoir["y"] - src["y"]) / 1000
        tunnel_mask = prof > reservoir["frl_m"] + TUNNEL_ABOVE_M
        tunnel_km = float(tunnel_mask.mean()) * km
        canal_km = (km - tunnel_km) * CANAL_SINUOSITY
        q = reservoir["annual_tmc"] * TMC_M3 / (PUMP_DAYS * 86400)
        mw = q * total_lift * 9.81 / PUMP_EFFICIENCY / 1000
        energy_cr = reservoir["annual_tmc"] * TMC_M3 * 1000 * 9.81 * total_lift / PUMP_EFFICIENCY / 3.6e6 * POWER_RS_PER_KWH / 1e7
        capex = COST_PUMP_PER_MW * mw + COST_TUNNEL_PER_KM * tunnel_km + COST_CANAL_PER_KM * canal_km
        score = capex + ENERGY_YEARS * energy_cr
        if best is None or score < best["score"]:
            stages = max(1, math.ceil(lift / PUMP_STAGE_M)) if lift > FRICTION_M + 1 else 0
            pumps = []
            if stages:
                level = src_level
                idx = 0
                for k in range(stages):
                    pumps.append({"stage": k + 1, "x": float(xs[idx]), "y": float(ys[idx]), "lift_m": round(lift / stages), "mw": round(mw / stages, 1)})
                    level += lift / stages
                    ahead = np.nonzero(prof[idx + 1:] > level - 10)[0]        # next place the ground rises above this stage's level
                    idx = idx + 1 + int(ahead[0]) - 1 if ahead.size else len(prof) - 1
                    idx = max(idx, int(len(prof) * (k + 1) / (stages + 1)))
                    idx = min(idx, len(prof) - 2)
            segments = []
            kind = None
            for i in range(len(xs) - 1):
                seg_kind = "tunnel" if tunnel_mask[i] or tunnel_mask[i + 1] else "canal"
                if seg_kind != kind:
                    segments.append({"kind": seg_kind, "xy": [(float(xs[i]), float(ys[i]))]})
                    kind = seg_kind
                segments[-1]["xy"].append((float(xs[i + 1]), float(ys[i + 1])))
            best = {"score": score, "source": src["name"], "basin": src["basin"], "intake": src["intake"], "source_elev_m": src["elev_m"],
                    "lift_m": round(lift), "base_lift_m": round(src["base_lift_m"]), "total_lift_m": round(total_lift),
                    "route_km": round(km, 1), "tunnel_km": round(tunnel_km, 1), "canal_km": round(canal_km, 1), "design_cms": round(q, 1),
                    "mw": round(mw), "stages": stages, "capex_conveyance_cr": round(capex), "energy_cr_per_year": round(energy_cr, 1),
                    "over_cap": over_cap, "pumps": pumps, "segments": segments}
    caps[best["intake"]] = caps.get(best["intake"], 0.0) - need
    if best["basin"] in basin_caps:
        basin_caps[best["basin"]] -= need
    return best


def lift_deliveries(grids: Grids, districts: gpd.GeoDataFrame, district_ix: np.ndarray, demand: list[dict], reservoirs: list[dict]) -> list[dict]:
    """Districts whose need is not met by new storage get water lifted to a delivery point on their high ground."""
    out = []
    for i, row in enumerate(demand):
        sited = sum(r["annual_tmc"] for r in reservoirs if r.get("serves") == row["district"])
        shortfall = row["tmc"] - sited
        row["annual_sited_tmc"] = round(sited, 1)
        if shortfall < MIN_ANNUAL_TMC:
            continue
        m = (district_ix == districts.index.get_loc(districts.index[i]) + 1) & grids.cultivable & np.isfinite(grids.wc_elev)
        if not m.any():
            continue
        x, y = float(grids.wc_x[m].mean()), float(grids.wc_y[m].mean())
        level = float(np.percentile(grids.wc_elev[m], 80)) + COMMAND_HEAD_M
        out.append({"id": f"L{len(out) + 1:02d}", "kind": "delivery", "name": f"{row['district']} lift delivery", "district": row["district"],
                    "serves": row["district"], "x": x, "y": y, "frl_m": round(level, 1), "annual_tmc": shortfall, "storage_tmc": 0.0,
                    "area_km2": 0.0, "cropland_km2": 0.0, "tree_km2": 0.0, "dam_km": 0.0, "crest_m": 0,
                    "cost_cr": round(BALANCING_STORAGE_SHARE * shortfall * COST_STORAGE_PER_TMC)})
    return out


def command_masks(grids: Grids, reservoirs: list[dict], existing: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    def served_by(level_m: float, x: float, y: float) -> np.ndarray:
        near = np.hypot(grids.wc_x - x, grids.wc_y - y) <= COMMAND_KM * 1000
        return near & grids.cultivable & (grids.wc_elev < level_m - COMMAND_HEAD_M)

    by_existing = np.zeros(grids.wc.shape, dtype=bool)
    for d in existing:
        if d["status"] == "proposed" or (d["capacity_tmcft"] or 0) < 2 or d["elev_m"] is None:
            continue
        by_existing |= served_by(d["elev_m"] + 10, d["x"], d["y"])
    by_new = np.zeros(grids.wc.shape, dtype=bool)
    for r in reservoirs:
        by_new |= served_by(r["frl_m"], r["x"], r["y"])
    return by_existing, by_new & ~by_existing


def mask_features(grids: Grids, mask: np.ndarray, kind: str, min_km2: float = 25.0) -> list[dict]:
    feats = []
    for geom, value in shapes(mask.astype(np.uint8), mask=mask, transform=grids.wc_transform):
        if value != 1:
            continue
        poly = shape(geom)
        area_km2 = poly.area * 111.32 * 111.32 * math.cos(math.radians(poly.centroid.y))
        if area_km2 < min_km2:
            continue
        feats.append({"type": "Feature", "geometry": poly.simplify(0.004).__geo_interface__, "properties": {"kind": kind, "area_km2": round(area_km2)}})
    return feats


def nearest_town(towns: list[dict], lon: float, lat: float) -> str:
    return min(towns, key=lambda t: (t["lon"] - lon) ** 2 + (t["lat"] - lat) ** 2)["name"]


def main() -> None:
    grids = Grids()
    districts = b.read_projected("districts")
    state = b.read_projected("state")
    district_ix = district_raster(grids, districts)
    demand, total = demand_table(grids, districts, district_ix)
    print(f"land: {total['cultivable_pct']} % of the state cultivable, {total['cropland_pct']} % cropland now "
          f"({total['cropland_of_cultivable_pct']} % of cultivable); target {int(TARGET_SHARE * 100)} % adds {total['new_lakh_acres']} lakh acres "
          f"and needs {total['tmc']} TMC a year ({total['tmc_new']} new + {total['tmc_stabilise']} stabilisation)")
    dams, sources = load_existing(grids)
    places = json.loads((b.RAW / "osm_places.json").read_text(encoding="utf-8"))["elements"]
    towns = [{"name": e["tags"].get("name:en") or e["tags"]["name"], "lon": e["lon"], "lat": e["lat"]} for e in places if "name" in e["tags"]]
    sites = candidate_sites(grids, state, dams)
    reservoirs = choose_reservoirs(grids, sites, districts, demand, towns)
    for i, r in enumerate(reservoirs):
        r["id"] = f"R{i + 1:02d}"
        r["kind"] = "reservoir"
        r["lon"], r["lat"] = grids.to_wgs.transform(r["x"], r["y"])
        r["name"] = f"{nearest_town(towns, r['lon'], r['lat'])} reservoir"
    for r in reservoirs:
        if sum(1 for k in reservoirs if k["name"] == r["name"]) > 1:
            r["name"] = f"{r['name']} ({r['serves']})"
    deliveries = lift_deliveries(grids, districts, district_ix, demand, reservoirs)
    for d in deliveries:
        d["lon"], d["lat"] = grids.to_wgs.transform(d["x"], d["y"])
    works = reservoirs + deliveries
    caps = intake_caps(sources)
    basin_caps = {"Krishna": max(0.0, ENVELOPES["Krishna"]["requested"] - ENVELOPES["Krishna"]["committed"])}   # the Godavari overdraw is reported, not forbidden
    cap_table = {k: round(v) for k, v in caps.items()}
    for r in sorted(works, key=lambda w: -w["annual_tmc"]):
        r.update(plan_conveyance(grids, r, sources, caps, basin_caps))
        r["capex_distribution_cr"] = round(COST_DISTRIBUTION_PER_TMC * r["annual_tmc"])
        r["capex_cr"] = r["cost_cr"] + r["capex_conveyance_cr"] + r["capex_distribution_cr"]
        r["annual_tmc"] = round(r["annual_tmc"], 1)
    print(f"  {len(reservoirs)} reservoirs sited, {len(deliveries)} districts need water lifted in without a new reservoir; "
          f"intake caps (TMC a year, {int(RIVER_SURPLUS_SHARE * 100)} % of mean flow): {cap_table}; over cap: {[w['id'] for w in works if w['over_cap']]}")
    # water balance per basin
    flow = json.loads((b.WEB_DATA / "flow_summary.json").read_text(encoding="utf-8"))
    for river, peak in flow["peaks"].items():
        if river in ENVELOPES:
            ENVELOPES[river]["mean_flow_tmc"] = round(tmc_per_year(peak["q"]))
    basins = {}
    for r in works:
        basins[r["basin"]] = basins.get(r["basin"], 0.0) + r["annual_tmc"]
    envelope_rows = []
    for river, e in ENVELOPES.items():
        free_award = max(0.0, e["award"] - e["committed"])
        free_requested = max(0.0, e["requested"] - e["committed"])
        drawn = round(basins.get(river, 0.0), 1)
        envelope_rows.append({"river": river, **e, "free_within_award": round(free_award, 1), "free_if_requested": round(free_requested, 1),
                              "proposal_draws": drawn, "beyond_request": round(max(0.0, drawn - free_requested), 1)})
    by_existing, by_new = command_masks(grids, works, dams)
    coverage = []
    for i, name in enumerate(districts["shapeName"]):
        m = district_ix == i + 1
        cult = float(grids.wc_km2[m & grids.cultivable].sum())
        ex = float(grids.wc_km2[m & by_existing].sum())
        new = float(grids.wc_km2[m & by_new].sum())
        coverage.append({"district": name, "gravity_existing_pct": round(100 * ex / cult, 1) if cult else None,
                         "gravity_new_pct": round(100 * new / cult, 1) if cult else None,
                         "needs_lift_pct": round(100 * max(0.0, cult - ex - new) / cult, 1) if cult else None,
                         "works": [r["id"] for r in works if r["serves"] == name]})
    totals = {"reservoirs": len(reservoirs), "deliveries": len(deliveries), "storage_tmc": round(sum(r["storage_tmc"] for r in reservoirs), 1),
              "annual_tmc": round(sum(r["annual_tmc"] for r in works), 1), "annual_from_reservoirs_tmc": round(sum(r["annual_tmc"] for r in reservoirs), 1),
              "submerged_km2": round(sum(r["area_km2"] for r in reservoirs)),
              "cropland_submerged_km2": round(sum(r["cropland_km2"] for r in reservoirs)), "pump_houses": sum(r["stages"] for r in works),
              "mw": round(sum(r["mw"] for r in works)), "tunnel_km": round(sum(r["tunnel_km"] for r in works)),
              "canal_km": round(sum(r["canal_km"] for r in works)), "capex_cr": round(sum(r["capex_cr"] for r in works)),
              "capex_storage_cr": round(sum(r["cost_cr"] for r in works)), "capex_conveyance_cr": round(sum(r["capex_conveyance_cr"] for r in works)),
              "capex_distribution_cr": round(sum(r["capex_distribution_cr"] for r in works)),
              "energy_cr_per_year": round(sum(r["energy_cr_per_year"] for r in works)),
              "storage_target_tmc": round(STORAGE_PER_ANNUAL * total["tmc"], 1),
              "demand_met_pct": round(100 * sum(r["annual_tmc"] for r in works) / total["tmc"], 1)}
    cult_total = float(grids.wc_km2[(district_ix > 0) & grids.cultivable].sum())
    totals["gravity_existing_pct"] = round(100 * float(grids.wc_km2[(district_ix > 0) & by_existing].sum()) / cult_total, 1)
    totals["gravity_new_pct"] = round(100 * float(grids.wc_km2[(district_ix > 0) & by_new].sum()) / cult_total, 1)
    print(f"works: {totals['reservoirs']} reservoirs ({totals['storage_tmc']} TMC storage) and {totals['deliveries']} lift deliveries for "
          f"{totals['annual_tmc']} TMC a year ({totals['demand_met_pct']} % of need), {totals['pump_houses']} pump houses, {totals['mw']} MW, "
          f"{totals['tunnel_km']} km tunnel, {totals['canal_km']} km canal; capex Rs {totals['capex_cr']:,} crore "
          f"(storage {totals['capex_storage_cr']:,}, conveyance {totals['capex_conveyance_cr']:,}, distribution {totals['capex_distribution_cr']:,}), "
          f"power Rs {totals['energy_cr_per_year']:,} crore a year")
    for e in envelope_rows:
        print(f"  {e['river']}: draws {e['proposal_draws']} TMC; free within award {e['free_within_award']}, if the 2025 request is granted {e['free_if_requested']}; beyond that {e['beyond_request']}")

    features = []
    features += mask_features(grids, by_existing, "command_existing")
    features += mask_features(grids, by_new, "command_new")
    for r in works:
        if r["kind"] == "reservoir":
            features.append({"type": "Feature", "geometry": pool_polygon(grids, r["pool_rows"], r["pool_cols"]).__geo_interface__,
                             "properties": {"kind": "pool", "id": r["id"], "name": r["name"], "storage_tmc": r["storage_tmc"], "frl_m": r["frl_m"]}})
        else:
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r["lon"], 5), round(r["lat"], 5)]},
                             "properties": {"kind": "delivery", "id": r["id"], "name": r["name"], "annual_tmc": r["annual_tmc"], "frl_m": r["frl_m"]}})
        for seg in r["segments"]:
            lon, lat = grids.to_wgs.transform(*zip(*seg["xy"]))
            features.append({"type": "Feature", "geometry": LineString(zip(lon, lat)).__geo_interface__,
                             "properties": {"kind": seg["kind"], "id": r["id"], "name": r["name"], "source": r["source"], "lift_m": r["lift_m"],
                                            "route_km": r["route_km"], "tunnel_km": r["tunnel_km"], "canal_km": r["canal_km"], "annual_tmc": r["annual_tmc"]}})
        for p in r["pumps"]:
            lon, lat = grids.to_wgs.transform(p["x"], p["y"])
            p["lon"], p["lat"] = round(lon, 5), round(lat, 5)
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                             "properties": {"kind": "pump", "id": r["id"], "name": f"{r['name']} · stage {p['stage']}", "stage": p["stage"],
                                            "lift_m": p["lift_m"], "mw": p["mw"], "source": r["source"]}})
    keep = ("id", "kind", "name", "district", "serves", "lon", "lat", "crest_m", "frl_m", "bed_m", "storage_tmc", "annual_tmc", "area_km2", "cropland_km2",
            "tree_km2", "dam_km", "cost_cr", "cost_per_tmc", "cms", "upland_km2", "source", "basin", "intake", "source_elev_m", "lift_m", "base_lift_m",
            "total_lift_m", "route_km", "tunnel_km", "canal_km", "design_cms", "mw", "stages", "capex_conveyance_cr", "capex_distribution_cr",
            "energy_cr_per_year", "capex_cr", "over_cap", "pumps")
    out_works = [{k: (round(r[k], 5) if k in ("lon", "lat") else r[k]) for k in keep if k in r} for r in works]
    for r in out_works:
        r["pumps"] = [{k: p[k] for k in ("stage", "lon", "lat", "lift_m", "mw")} for p in r["pumps"]]
    proposal = {
        "norms": {"target_share": TARGET_SHARE, "target_range": TARGET_RANGE, "max_slope_pct": MAX_SLOPE_PCT, "duty_new_acres_per_tmc": DUTY_NEW_ACRES_PER_TMC,
                  "duty_stabilise_acres_per_tmc": DUTY_STABILISE_ACRES_PER_TMC, "rainfed_share": RAINFED_SHARE, "storage_per_annual": STORAGE_PER_ANNUAL,
                  "crest_options_m": CREST_OPTIONS_M, "pump_stage_m": PUMP_STAGE_M, "command_km": COMMAND_KM, "command_head_m": COMMAND_HEAD_M,
                  "costs": {"storage_per_tmc_cr": COST_STORAGE_PER_TMC, "embankment_per_km_m_cr": COST_EMBANKMENT_PER_KM_M, "land_per_ha_cr": COST_LAND_PER_HA,
                            "distribution_per_tmc_cr": COST_DISTRIBUTION_PER_TMC, "pump_per_mw_cr": COST_PUMP_PER_MW,
                            "tunnel_per_km_cr": COST_TUNNEL_PER_KM, "canal_per_km_cr": COST_CANAL_PER_KM, "power_rs_per_kwh": POWER_RS_PER_KWH,
                            "pump_efficiency": PUMP_EFFICIENCY, "pump_days": PUMP_DAYS, "energy_years_in_choice": ENERGY_YEARS}, "cost_benchmarks": COST_SOURCES,
                  "landcover": "ESA WorldCover 2021 v200 at 320 m (CC BY 4.0)", "dem": "Copernicus GLO-90 resampled to 200 m"},
        "demand": {"state": total, "districts": demand}, "envelopes": envelope_rows, "intake_caps": cap_table, "works": out_works, "totals": totals,
        "coverage": coverage,
    }
    (b.WEB_DATA / "proposal.json").write_text(json.dumps(proposal, indent=1, ensure_ascii=False), encoding="utf-8")
    (b.WEB_DATA / "proposal.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print(f"wrote proposal.json and proposal.geojson ({(b.WEB_DATA / 'proposal.geojson').stat().st_size / 1e6:.1f} MB, {len(features)} features)")


if __name__ == "__main__":
    main()

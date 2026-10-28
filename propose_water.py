"""Planning model: river water for most of Telangana's farmland, lifted in stages.

Not a design, a reasoned sketch built from the data already on the map, under stated norms that were
reviewed by a lift-irrigation engineer (the review's numbers are the defaults below, marked "review"):

- ESA WorldCover 2021 (320 m) says what land is cultivable (crop, grass, shrub, bare, not steep) and
  what is already cropland; the target is TARGET_SHARE of cultivable land under crops in every district.
- Water need = new acres / DUTY_NEW + rainfed existing acres / DUTY_STABILISE (TMC a year, net); the
  intake draws LOSSES more for evaporation and seepage.
- New reservoirs are sited on the 200 m DEM: every HydroRIVERS reach of order 4+ is tried every 5 km with
  dams of 20, 30 and 40 m; the pool is the DEM below crest behind a dam line scanned across the valley,
  must lie inside Telangana, and is priced by storage, embankment (height squared), farmland and forest
  drowned; the cheapest storage per district is picked until that district's share of storage is met.
  Districts without a usable site get a "lift delivery" to a ridge point on their high ground.
- Six multi-stage trunk systems (river intake -> pump -> pool -> canal or tunnel -> pump -> ... up the
  plateau, as Kaleshwaram is built) are encoded from the engineering review, reusing the existing stages
  of Kaleshwaram, Devadula, Palamuru-Rangareddy, Bhima and Nettempadu and adding new stage reservoirs.
- Each work is fed by the cheapest source with water to spare: a river intake, a trunk-stage or other
  reservoir an existing scheme already fills, a tap on an existing canal (within its spare capacity), a
  new trunk stage, or a reservoir proposed here (so lifts cascade). Water taken through an existing
  scheme is debited to its river intake, pays that lift as power, and is listed as pump augmentation.
- Routes stay inside the state (shortest path on a 1 km grid); gravity when the source's operating
  level allows, else stages of 60-130 m; the hydraulic grade line is followed along the route to pick
  pressure mains on rising legs, tunnels under high ground, deep cuts, and aqueducts over low ground.
- Command = cultivable land within COMMAND_KM whose ground is below the work's level minus canal fall.

Writes web/data/proposal.json (budget, works, systems, tables) and web/data/proposal.geojson (pools,
routes, trunk stages, pump houses, delivery points, command areas). Run after build_web_data.py
--skip-tiles; fetch_data.py must have fetched worldcover_320m.tif and nominatim_proposal.json.
"""
from __future__ import annotations

import heapq
import json
import math
import re

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from scipy.ndimage import label
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, unary_union

import build_web_data as b

WGS84 = "EPSG:4326"
WORLDCOVER = b.RAW / "worldcover_320m.tif"
PLACES = b.RAW / "nominatim_proposal.json"

# --- planning norms (review = value recommended by the engineering review) ------------------------------
TARGET_SHARE = 0.85                         # review: WorldCover grass, shrub and bare include commons and fallow; 0.90 shown as a sensitivity
TARGET_RANGE = (0.80, 0.90)
MAX_SLOPE_PCT = 15.0
DUTY_NEW_ACRES_PER_TMC = 9_000              # review: irrigated-dry ~10,000, paddy ~3,500; 9,000 allows about 5 % paddy
DUTY_STABILISE_ACRES_PER_TMC = 20_000       # review: two or three protective waterings plus a light rabi crop
RAINFED_SHARE = 0.30                        # review: the 42 % state figure must be net of ayacut already promised to Kaleshwaram, Palamuru, Sitarama, Devadula; 0.30 is a placeholder
LOSSES = 0.12                               # review: pool evaporation (~1.5 m a year) plus trunk seepage, added at the intake
ACRES_PER_KM2 = 247.105
TMC_M3 = 28.317e6
STORAGE_PER_ANNUAL = 0.5                    # review: ~100 pumping days against ~240 release days
ENVELOPES = {                               # TMC a year; see DATA_SOURCES.md section 8
    "Godavari": {"award": 967.94, "committed": 758.76 + 148.82, "requested": 1000.0, "mean_flow_tmc": None},
    "Krishna": {"award": 299.0, "committed": 299.0, "requested": 500.0, "mean_flow_tmc": None},
}
# --- siting ----------------------------------------------------------------------------------------------
CREST_OPTIONS_M = (20, 30, 40)
MIN_ORDER = 4
MIN_FLOW_CMS = 3.0
MIN_SITE_ELEV_M = 100
MIN_STORAGE_TMC = 3.0
MAX_DAM_KM = 16.0
MAX_CROPLAND_KM2_PER_TMC = 1.5              # review: Mallanna Sagar ~1.4; 2.5 admits shallow, land-hungry pools
MAX_POOL_OUTSIDE_SHARE = 0.01
POOL_WINDOW_CELLS = 150
SITE_SAMPLE_M = 5_000
EXISTING_CLEARANCE_M = 12_000
SITE_SPACING_M = 15_000
DISTRICT_MARGIN_M = 20_000
MAX_BUILTUP_SHARE = 0.03
MAX_RESERVOIRS = 60
MIN_ANNUAL_TMC = 2.0
DELIVERY_PERCENTILE = 75                    # review: a ridge point within 10 m of the 75th-percentile height of the district's cultivable land
DELIVERY_BAND_M = 10
# --- conveyance ------------------------------------------------------------------------------------------
ROUTE_CELL_M = 1_000                        # review: a 2 km grid misses the saddles canals use
ROUTE_SIMPLIFY_M = 800
SOURCE_SNAP_CELLS = 6
STAGE_MAX_M = 120                           # review: large single-stage pumps hold ~90 % efficiency to ~120 m
STAGE_MIN_M = 60                            # review: below this a pump house plus forebay costs more than raising the previous stage
STAGE_LOSS_M = 3                            # review: per stage
CANAL_FALL_M_PER_KM = 0.1                   # review: gravity canal slope about 1:10,000
MAIN_LOSS_M_PER_KM = 1.0                    # review: pressure main
TUNNEL_COVER_M = 30                         # review: tunnel where ground is this far above the local water level for at least 1 km
CUT_COVER_M = 12                            # review: 12-30 m above the water level is deep cut
AQUEDUCT_DEPTH_M = 15                       # review: ground this far below the water level needs an aqueduct or siphon
RISING_LEG_KM = 5                           # review: pressure main where the route rises more than 30 m in 5 km
CANAL_SINUOSITY = 1.3                       # review: contour canals wrap round spurs
PUMP_HOURS = 22                             # review
STANDBY = 1.25                              # review: installed capacity over duty
PUMP_EFFICIENCY = 0.80                      # review: wire-to-water for units above 20 MW
PUMP_DAYS = {"Medigadda Barrage": 100, "Sripada Yellampalli Project": 100, "Sriram Sagar Project": 100, "Tummidihetti Barrage": 100,
             "Sammakka Sagar Barrage": 110, "Sitamma Sagar Barrage": 120, "Jurala Project": 60, "Srisailam Dam": 60,
             "Nagarjuna Sagar Dam": 60, "Pulichintala Project": 60}   # review: dependable surplus months per intake
COMMAND_KM = 60                             # review: along the canal (straight distance used as the proxy)
COMMAND_HEAD_M = 5                          # review: plus 0.15 m per km of canal
COMMAND_FALL_M_PER_KM = 0.15
TAP_MAX_KM = 25
TAP_SHARE = 0.20                            # review: at most 20 % of a canal's design discharge may be tapped
TAP_DESIGN_CMS = {"Sriram Sagar canals": 280, "Nagarjuna Sagar left canal": 311, "Jurala canals": 30, "Nizam Sagar canal (filled by Kaleshwaram Link VI)": 70,
                  "Sitarama canals (under construction)": 100, "Kaleshwaram canals": 100}   # approximate design discharges
RIVER_SURPLUS_SHARE = 0.15                  # review: of the 75 %-dependable monsoon flow ...
DEPENDABLE_MONSOON_OF_MEAN = 0.60           # ... approximated as 60 % of HydroRIVERS' mean annual flow (monsoon share ~0.8 x dependable/mean ~0.75)
MAX_PUMPED_LIFT_M = 350                     # review: flag deliveries lifted further; power alone then costs ~Rs 24,000 an acre a year
# --- unit costs, Rs crore (review values) ---------------------------------------------------------------
COST_STORAGE_PER_TMC = 100
COST_EMBANKMENT_KM_H2 = 0.1                 # per km of bund per m2 of height: earth volume grows with height squared
COST_FARMLAND_PER_HA = 0.5                  # LARR 2013 compensation ~Rs 15-20 lakh an acre
COST_FOREST_PER_HA = 0.2                    # net present value, compensatory afforestation
COST_OTHER_LAND_PER_HA = 0.25               # grass, shrub, water: a judgement value
COST_DISTRIBUTION_PER_TMC = 150             # Rs 1.5 lakh an acre new, 0.75 lakh stabilised
BALANCING_STORAGE_SHARE = 0.1
COST_PUMP_PER_MW = 10                       # installed, with substation, line and standby
COST_TUNNEL_PER_KM = lambda q: 40 + 0.7 * q  # noqa: E731  SLBC class ~110 at 100 cumecs
COST_CANAL_PER_KM = lambda q: 5 + 0.15 * q + 3  # noqa: E731  lined canal with structures plus right of way
COST_MAIN_PER_KM = lambda q: 8 + 1.0 * q    # noqa: E731  steel mains of 2.5-3.5 m in parallel
CUT_FACTOR = 3.0                            # deep cut, times the canal rate
AQUEDUCT_FACTOR = 2.5                       # aqueduct or siphon, times the canal rate
POWER_RS_PER_KWH = 7.0                      # energy plus demand charge
ENERGY_YEARS = 10.7                         # present value of 25 years at 8 %
COST_SOURCES = {
    "Kaleshwaram Lift Irrigation Project": ("Rs 80,190 crore, 225 TMC a year, 147 TMC storage, lifts to 618 m", "https://en.wikipedia.org/wiki/Kaleshwaram_Lift_Irrigation_Project"),
    "Palamuru-Rangareddy Lift Irrigation Scheme": ("Rs 35,000 crore, 90 TMC a year, 67.5 TMC storage", "https://en.wikipedia.org/wiki/Palamuru-Rangareddy_Lift_Irrigation_Scheme"),
    "Sammakka Sagar Barrage": ("Rs 2,121 crore, 6.94 TMC barrage", "https://en.wikipedia.org/wiki/Sammakka_Sagar_Barrage"),
    "Kalwakurthy lift scheme": ("Rs 2,100 crore, 25 TMC a year", "https://en.wikipedia.org/wiki/Mahatma_Gandhi_Kalwakurthy_lift_irrigation_scheme"),
}
# Operating levels (m above sea): approximate full reservoir or minimum drawdown levels recalled in the
# review; dams.json carries the ground height at the structure, 5-55 m lower. Check against each DPR.
OPERATING_LEVEL = {
    "Medigadda Barrage": 100, "Saraswati Barrage": 119, "Parvati Barrage": 130, "Sripada Yellampalli Project": 148, "Mid Manair Dam": 318,
    "Lower Manair Dam": 280, "Annapurna reservoir (Anantha Sagar)": 380, "Ranganayaka Sagar": 490, "Mallanna Sagar": 557, "Konda Pochamma Sagar": 618,
    "Baswapur reservoir": 475, "Singur Dam": 523, "Nizam Sagar": 428, "Maikapet Reservoir": 430, "Upper Manair Dam": 455, "Dharmasagar reservoir": 320,
    "Sammakka Sagar Barrage": 83, "Sitamma Sagar Barrage": 58, "Sriram Sagar Project": 332, "Tummidihetti Barrage": 148, "Wyra Reservoir": 95,
    "Jurala Project": 318, "Srisailam Dam": 245, "Nagarjuna Sagar Dam": 155, "Pulichintala Project": 53, "Dindi reservoir": 395,
    "Veeranjaneya reservoir (Yedula)": 465, "Venkatadri reservoir (Vattem)": 545, "Kurumurthy Raya reservoir (Karvena)": 520,
}
# Where new water can be taken from (name as in dams.json: basin, river intake, scheme that fills it).
SOURCES = {
    "Medigadda Barrage": ("Godavari", None, None), "Sammakka Sagar Barrage": ("Godavari", None, None),
    "Sitamma Sagar Barrage": ("Godavari", None, None), "Sripada Yellampalli Project": ("Godavari", None, None),
    "Sriram Sagar Project": ("Godavari", None, None),
    "Parvati Barrage": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link I"), "Saraswati Barrage": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link I"),
    "Mid Manair Dam": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link II"), "Lower Manair Dam": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link II"),
    "Mallanna Sagar": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link IV"), "Konda Pochamma Sagar": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link IV"),
    "Ranganayaka Sagar": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link IV"), "Baswapur reservoir": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link V"),
    "Annapurna reservoir (Anantha Sagar)": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link IV"),
    "Singur Dam": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link VI"), "Nizam Sagar": ("Godavari", "Medigadda Barrage", "Kaleshwaram Link VI"),
    "Gouravelli reservoir": ("Godavari", "Sriram Sagar Project", "SRSP flood flow canal"),
    "Jurala Project": ("Krishna", None, None), "Srisailam Dam": ("Krishna", None, None), "Nagarjuna Sagar Dam": ("Krishna", None, None),
    "Pulichintala Project": ("Krishna", None, None),
    "Veeranjaneya reservoir (Yedula)": ("Krishna", "Srisailam Dam", "Palamuru-Rangareddy"), "Venkatadri reservoir (Vattem)": ("Krishna", "Srisailam Dam", "Palamuru-Rangareddy"),
    "Kurumurthy Raya reservoir (Karvena)": ("Krishna", "Srisailam Dam", "Palamuru-Rangareddy"), "Dindi reservoir": ("Krishna", "Srisailam Dam", "Dindi lift scheme"),
}
CANAL_SCHEMES = [
    (re.compile(r"Kakatiya|SRSP|Flood Flow|ALI SAGAR", re.I), "Sriram Sagar Project", "Godavari", "Sriram Sagar canals"),
    (re.compile(r"Nagarjun", re.I), "Nagarjuna Sagar Dam", "Krishna", "Nagarjuna Sagar left canal"),
    (re.compile(r"Jurala", re.I), "Jurala Project", "Krishna", "Jurala canals"),
    (re.compile(r"Nizam", re.I), "Medigadda Barrage", "Godavari", "Nizam Sagar canal (filled by Kaleshwaram Link VI)"),
    (re.compile(r"^Sitarama", re.I), "Sitamma Sagar Barrage", "Godavari", "Sitarama canals (under construction)"),
    (re.compile(r"^Kaleshwaram", re.I), "Medigadda Barrage", "Godavari", "Kaleshwaram canals"),
]
# Multi-stage trunk systems from the engineering review: ordered stages, approximate pool levels, lifts
# (pool to pool), conveyance and length. "existing" = built or under construction. Levels and the
# allocation of districts are the reviewer's judgement, to be checked against each project report.
SYSTEMS = [
    {"name": "S1 Pranahita – Adilabad plateau", "basin": "Godavari", "intake": "Tummidihetti Barrage", "tmc_per_year": 71.1, "design_cms": 254, "pump_days": 100,
     "districts": ["Komaram Bheem", "Adilabad", "Nirmal", "Mancherial"],
     "notes": "Take Pranahita water above the confluence so the Godavari trough is never climbed out of; a 12 km tunnel crosses the Peddavagu–Kadam divide, a pressure main climbs the Utnur–Ichoda scarp; keep clear of the Kawal tiger reserve. Tummidihetti is an interstate barrage, proposed.",
     "stages": [("Tummidihetti Barrage", "Asifabad reservoir (new)", 240, 92, False, "canal", 60), ("Asifabad reservoir (new)", "Utnur reservoir (new)", 365, 125, False, "tunnel", 55),
                ("Utnur reservoir (new)", "Ichoda reservoir (new)", 470, 105, False, "pressure main", 40), ("Ichoda reservoir (new)", "Nirmal–Bhainsa contour canal tail", 459, 0, False, "gravity", 110)]},
    {"name": "S2 Kaleshwaram augmentation – Manjira and Zaheerabad–Vikarabad", "basin": "Godavari", "intake": "Medigadda Barrage", "tmc_per_year": 216.6, "design_cms": 774, "pump_days": 100,
     "districts": ["Peddapalli", "Karimnagar", "Jagtial", "Rajanna Sircilla", "Siddipet", "Medak", "Kamareddy", "Nizamabad", "Sangareddy", "Medchal", "Hyderabad", "Vikarabad", "Yadadri Bhongiri"],
     "notes": "Links I, II and IV as built, then a third-TMC augmentation of about 2.4 TMC a day for 100 days. The Manjira valley at Singur cuts the Siddipet plateau off from the 620–660 m Zaheerabad–Vikarabad plateau, so a 127 m re-lift is unavoidable; summit lift 584 m costs about Rs 39 crore of power per TMC. Medigadda's condition after 2023 must be verified; Yellampalli is the fallback intake.",
     "stages": [("Medigadda Barrage", "Saraswati Barrage", 119, 19, True, "canal", 29), ("Saraswati Barrage", "Parvati Barrage", 130, 11, True, "canal", 22),
                ("Parvati Barrage", "Sripada Yellampalli Project", 148, 18, True, "canal", 28), ("Sripada Yellampalli Project", "Nandi Medaram reservoir", 255, 107, True, "pressure main", 25),
                ("Nandi Medaram reservoir", "Mid Manair Dam", 318, 63, True, "tunnel", 45), ("Mid Manair Dam", "Annapurna reservoir (Anantha Sagar)", 380, 62, True, "tunnel", 20),
                ("Annapurna reservoir (Anantha Sagar)", "Ranganayaka Sagar", 490, 110, True, "tunnel", 15), ("Ranganayaka Sagar", "Mallanna Sagar", 557, 67, True, "tunnel", 24),
                ("Mallanna Sagar", "Konda Pochamma Sagar", 618, 61, True, "canal", 25), ("Mid Manair Dam", "Maikapet Reservoir", 430, 112, True, "pressure main", 27),
                ("Maikapet Reservoir", "Upper Manair Dam", 455, 25, True, "canal", 27), ("Konda Pochamma Sagar", "Baswapur reservoir", 475, 0, True, "gravity", 35),
                ("Konda Pochamma Sagar", "Medchal (Keshavapuram) reservoir (new)", 600, 0, False, "gravity", 30), ("Mallanna Sagar", "Singur Dam", 523, 0, False, "gravity", 110),
                ("Singur Dam", "Nizam Sagar", 428, 0, True, "gravity", 60), ("Singur Dam", "Zaheerabad (Kohir) reservoir (new)", 650, 127, False, "pressure main", 35),
                ("Zaheerabad (Kohir) reservoir (new)", "Vikarabad reservoir (new)", 645, 0, False, "gravity", 55)]},
    {"name": "S3 Sammakka Sagar – Devadula – Jangaon ridge to Nalgonda", "basin": "Godavari", "intake": "Sammakka Sagar Barrage", "tmc_per_year": 116.0, "design_cms": 377, "pump_days": 110,
     "districts": ["Mulugu", "Jayashankar", "Warangal (U)", "Warangal (R)", "Jangaon", "Mahabubabad", "Suryapet", "Nalgonda"],
     "notes": "Sammakka Sagar sits below the Indravati confluence and has the most reliable surplus. Devadula's pressure mains would have to become a canal or tunnel at 377 cumecs. Dharmasagar commands Warangal, Mahabubabad, Mulugu and Jayashankar by gravity; a Jangaon pool feeds a ridge canal along the Aler–Motkur–Ramannapet watershed to Chityal and Nalgonda, with a branch to Suryapet, putting Godavari water into Krishna-basin districts so the Krishna share stays free.",
     "stages": [("Sammakka Sagar Barrage", "Bheemghanpur reservoir (Devadula)", 195, 112, True, "pressure main", 50), ("Bheemghanpur reservoir (Devadula)", "Dharmasagar reservoir", 320, 125, True, "pressure main", 60),
                ("Dharmasagar reservoir", "Jangaon reservoir (new)", 405, 85, False, "canal", 35), ("Jangaon reservoir (new)", "Aler–Ramannapet ridge canal tail (Chityal)", 394, 0, False, "gravity", 105)]},
    {"name": "S4 Sitarama – Palvancha – Yellandu", "basin": "Godavari", "intake": "Sitamma Sagar Barrage", "tmc_per_year": 54.1, "design_cms": 161, "pump_days": 120,
     "districts": ["Bhadradri", "Khammam"],
     "notes": "Overlaps the Sitarama lift scheme under construction for the same districts: count only the increment. Yellandu commands Khammam, Wyra and Sathupalli by gravity; Palvancha the Kothagudem lowland.",
     "stages": [("Sitamma Sagar Barrage", "Palvancha reservoir (new)", 125, 67, False, "canal", 45), ("Palvancha reservoir (new)", "Yellandu reservoir (new)", 235, 110, False, "canal", 40),
                ("Yellandu reservoir (new)", "Wyra Reservoir", 95, 0, True, "gravity", 45)]},
    {"name": "S5 Palamuru–Rangareddy extension – Kulkacherla summit and Dindi", "basin": "Krishna", "intake": "Srisailam Dam", "tmc_per_year": 114.9, "design_cms": 685, "pump_days": 60,
     "districts": ["Nagarkurnool", "Mahabubnagar", "Rangareddy", "Wanaparthy"],
     "notes": "Srisailam intake near its minimum drawdown (~245 m). Palamuru pools as designed, levels approximate. A new 70 m stage reaches Kulkacherla, the summit of the Krishna–Godavari divide, commanding Shadnagar, Kothur, Maheshwaram, Chevella and southern Vikarabad. Dindi is fed by gravity from Yedula. Entirely beyond the 299 TMC award: Krishna flood water only.",
     "stages": [("Srisailam Dam", "Anjanagiri reservoir (Narlapur)", 345, 100, True, "pressure main", 15), ("Anjanagiri reservoir (Narlapur)", "Veeranjaneya reservoir (Yedula)", 465, 120, True, "tunnel", 30),
                ("Veeranjaneya reservoir (Yedula)", "Venkatadri reservoir (Vattem)", 545, 80, True, "tunnel", 30), ("Venkatadri reservoir (Vattem)", "Kurumurthy Raya reservoir (Karvena)", 520, 0, True, "gravity", 20),
                ("Kurumurthy Raya reservoir (Karvena)", "Uddandapur reservoir", 600, 80, True, "pressure main", 25), ("Uddandapur reservoir", "Kulkacherla reservoir (new)", 670, 70, False, "pressure main", 20),
                ("Veeranjaneya reservoir (Yedula)", "Dindi reservoir", 395, 0, False, "gravity", 70)]},
    {"name": "S6 Jurala – Bhima – Nettempadu", "basin": "Krishna", "intake": "Jurala Project", "tmc_per_year": 24.9, "design_cms": 148, "pump_days": 60,
     "districts": ["Jogulamba", "Narayanpet"],
     "notes": "Bhima and Nettempadu pools as existing, levels approximate. A new 125 m stage to Kosgi commands Narayanpet and Kodangal. Krishna flood water only.",
     "stages": [("Jurala Project", "Sangambanda reservoir (Bhima LIS)", 400, 82, True, "canal", 30), ("Sangambanda reservoir (Bhima LIS)", "Kosgi reservoir (new)", 525, 125, False, "pressure main", 40),
                ("Jurala Project", "Ryalampad reservoir (Nettempadu)", 410, 92, True, "pressure main", 25)]},
]
# Stage sites that are neither on the map nor on Nominatim: hand-placed, approximate.
APPROX_SITES = {"Nandi Medaram reservoir": (79.37, 18.70), "Bheemghanpur reservoir (Devadula)": (80.05, 18.30),
                "Uddandapur reservoir": (78.22, 16.80), "Medchal (Keshavapuram) reservoir (new)": (78.57, 17.64)}
PLACE_KEYS = {"Anjanagiri reservoir (Narlapur)": "Narlapur", "Sangambanda reservoir (Bhima LIS)": "Sangambanda", "Ryalampad reservoir (Nettempadu)": "Ryalampad",
              "Asifabad reservoir (new)": "Asifabad", "Utnur reservoir (new)": "Utnur", "Ichoda reservoir (new)": "Ichoda", "Nirmal–Bhainsa contour canal tail": "Bhainsa",
              "Zaheerabad (Kohir) reservoir (new)": "Kohir", "Vikarabad reservoir (new)": "Vikarabad", "Jangaon reservoir (new)": "Jangaon",
              "Aler–Ramannapet ridge canal tail (Chityal)": "Chityal", "Palvancha reservoir (new)": "Palvancha", "Yellandu reservoir (new)": "Yellandu",
              "Kulkacherla reservoir (new)": "Kulkacherla", "Kosgi reservoir (new)": "Kosgi"}
CAVEATS = [
    "A planning sketch from a 200 m DEM and 320 m land cover; no survey, geology or hydrology behind any line.",
    "Levels are approximate full-reservoir or drawdown levels recalled by the reviewer; the map's dam heights are ground at the structure, 5–55 m lower.",
    "Water beyond the award: the Godavari draw needs a new interstate allocation; Krishna has no free water within the 299 TMC award, only flood years.",
    "Medigadda, Annaram and Sundilla suffered structural distress in 2023; their availability as intakes is not established.",
    "Demand overlaps ayacut already promised to Kaleshwaram, Palamuru, Sitarama and Devadula; the true increment is smaller than shown.",
    "Energy is the dominant recurring cost: water lifted 450–600 m costs Rs 30,000–40,000 an acre a year in power alone.",
    "Routes may cross the Kawal and Amrabad tiger reserves and reserved forests; real alignments must avoid them.",
    "Evaporation and seepage are a flat 12 % at the intake, not modelled site by site; villages inside pools are not counted, so resettlement is understated.",
    "Groundwater, Mission Kakatiya tanks and treated Musi wastewater (about 25 TMC a year) are not counted as sources.",
    "Tapped canals are assumed to spare 20 % of their design discharge; nothing here checks a head reservoir's dependable yield.",
]
WC_CULTIVABLE = (20, 30, 40, 60)
WC_CROP = 40
WC_BUILT = 50
WC_TREE = 10


def tmc_per_year(cms: float) -> float:
    return cms * 365.25 * 86400 / TMC_M3


def design_cms(gross_tmc: float, days: int) -> float:
    return gross_tmc * TMC_M3 / (days * PUMP_HOURS * 3600)


class Grids:
    """DEM (200 m, Lambert) and WorldCover (320 m, WGS84) with the lookups the model needs."""

    def __init__(self, state_dem) -> None:
        self.dem_ds = rasterio.open(b.PROFILE_DEM)
        self.dem = self.dem_ds.read(1).astype(np.float32)
        self.dem[self.dem <= -1000] = np.nan
        self.to_dem = Transformer.from_crs(WGS84, self.dem_ds.crs, always_xy=True)
        self.to_wgs = Transformer.from_crs(self.dem_ds.crs, WGS84, always_xy=True)
        gy, gx = np.gradient(np.nan_to_num(self.dem, nan=0.0), 200.0)
        self.slope_pct = np.hypot(gx, gy) * 100
        self.state_mask = rasterize([(state_dem, 1)], out_shape=self.dem.shape, transform=self.dem_ds.transform, fill=0, dtype=np.uint8).astype(bool)
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

    def elev_xy(self, x: float, y: float) -> float:
        r, c = self.dem_rc(x, y)
        return float(self.dem[r, c]) if 0 <= r < self.dem.shape[0] and 0 <= c < self.dem.shape[1] else float("nan")

    def wc_rc(self, lon, lat):
        t = ~self.wc_transform
        col, row = t * (np.asarray(lon), np.asarray(lat))
        return np.floor(row).astype(int), np.floor(col).astype(int)


class Router:
    """Shortest paths that stay inside the state, on a grid in the DEM's projection."""

    MOVES = [(-1, -1, math.sqrt(2)), (-1, 0, 1.0), (-1, 1, math.sqrt(2)), (0, -1, 1.0), (0, 1, 1.0), (1, -1, math.sqrt(2)), (1, 0, 1.0), (1, 1, math.sqrt(2))]

    def __init__(self, state_dem, cell_m: float = ROUTE_CELL_M) -> None:
        minx, miny, maxx, maxy = state_dem.bounds
        margin = 4 * cell_m
        self.cell = cell_m
        self.minx, self.maxy = minx - margin, maxy + margin
        self.nx = int((maxx - minx + 2 * margin) / cell_m) + 1
        self.ny = int((maxy - miny + 2 * margin) / cell_m) + 1
        self.transform = from_origin(self.minx, self.maxy, cell_m, cell_m)
        self.inside = rasterize([(state_dem, 1)], out_shape=(self.ny, self.nx), transform=self.transform, fill=0, dtype=np.uint8, all_touched=True).astype(bool)
        self.state = state_dem
        self.trees: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        return int((self.maxy - y) // self.cell), int((x - self.minx) // self.cell)

    def centre(self, row: int, col: int) -> tuple[float, float]:
        return self.minx + (col + 0.5) * self.cell, self.maxy - (row + 0.5) * self.cell

    def snap(self, x: float, y: float) -> tuple[int, int] | None:
        row, col = self.cell_of(x, y)
        best = None
        for dr in range(-SOURCE_SNAP_CELLS, SOURCE_SNAP_CELLS + 1):
            for dc in range(-SOURCE_SNAP_CELLS, SOURCE_SNAP_CELLS + 1):
                r, c = row + dr, col + dc
                if 0 <= r < self.ny and 0 <= c < self.nx and self.inside[r, c]:
                    d = dr * dr + dc * dc
                    if best is None or d < best[0]:
                        best = (d, r, c)
        return (best[1], best[2]) if best else None

    def tree(self, x: float, y: float) -> tuple[np.ndarray, np.ndarray] | None:
        """Dijkstra from the cell nearest (x, y): distance in cells and predecessor index for every reachable cell (cached)."""
        cell = self.snap(x, y)
        if cell is None:
            return None
        if cell in self.trees:
            return self.trees[cell]
        dist = np.full(self.ny * self.nx, np.inf)
        pred = np.full(self.ny * self.nx, -1, dtype=np.int64)
        start = cell[0] * self.nx + cell[1]
        dist[start] = 0.0
        heap = [(0.0, start)]
        inside = self.inside.ravel()
        while heap:
            d, node = heapq.heappop(heap)
            if d > dist[node]:
                continue
            r, c = divmod(node, self.nx)
            for dr, dc, step in self.MOVES:
                rr, cc = r + dr, c + dc
                if 0 <= rr < self.ny and 0 <= cc < self.nx:
                    nxt = rr * self.nx + cc
                    if inside[nxt]:
                        nd = d + step
                        if nd < dist[nxt]:
                            dist[nxt] = nd
                            pred[nxt] = node
                            heapq.heappush(heap, (nd, nxt))
        self.trees[cell] = (dist, pred)
        return self.trees[cell]

    def path(self, tree, root_xy: tuple[float, float], to_xy: tuple[float, float]) -> LineString | None:
        """Polyline from the tree's root to to_xy, inside the state, lightly simplified."""
        dist, pred = tree
        cell = self.snap(*to_xy)
        if cell is None:
            return None
        node = cell[0] * self.nx + cell[1]
        if not np.isfinite(dist[node]):
            return None
        cells = []
        while node != -1:
            cells.append(self.centre(*divmod(node, self.nx)))
            node = pred[node]
        coords = [to_xy] + cells + [root_xy]
        coords.reverse()
        line = LineString(coords)
        simple = line.simplify(ROUTE_SIMPLIFY_M, preserve_topology=False)
        return simple if self.state.buffer(ROUTE_CELL_M).covers(simple) else line

    def route(self, from_xy: tuple[float, float], to_xy: tuple[float, float]) -> LineString | None:
        straight = LineString([from_xy, to_xy])
        if self.state.buffer(200).covers(straight):
            return straight
        tree = self.tree(*from_xy)
        return self.path(tree, from_xy, to_xy) if tree else None


def district_raster(grids: Grids, districts: gpd.GeoDataFrame) -> np.ndarray:
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
                     "tmc_stabilise": round(rainfed_acres / DUTY_STABILISE_ACRES_PER_TMC, 1), "tmc": round(tmc, 1), "tmc_gross": round(tmc * (1 + LOSSES), 1)})
    total = {k: round(sum(r[k] for r in rows), 1 if k.startswith("tmc") or k.endswith("acres") else 0)
             for k in ("area_km2", "cultivable_km2", "cropland_km2", "tree_km2", "builtup_km2", "water_km2", "target_km2", "new_km2", "new_lakh_acres", "tmc_new", "tmc_stabilise", "tmc", "tmc_gross")}
    total["cultivable_pct"] = round(100 * total["cultivable_km2"] / total["area_km2"], 1)
    total["cropland_pct"] = round(100 * total["cropland_km2"] / total["area_km2"], 1)
    total["cropland_of_cultivable_pct"] = round(100 * total["cropland_km2"] / total["cultivable_km2"], 1)
    for share in TARGET_RANGE:
        new = sum(max(0.0, share * r["cultivable_km2"] - r["cropland_km2"]) for r in rows)
        total[f"new_lakh_acres_at_{int(share * 100)}"] = round(new * ACRES_PER_KM2 / 1e5, 1)
        total[f"tmc_at_{int(share * 100)}"] = round(new * ACRES_PER_KM2 / DUTY_NEW_ACRES_PER_TMC + total["tmc_stabilise"], 0)
    return rows, total


def level_of(d: dict) -> float:
    return float(OPERATING_LEVEL.get(d["name"], (d.get("elev_m") or 0) + 5))


def load_existing(grids: Grids) -> tuple[list[dict], list[dict]]:
    dams = json.loads((b.WEB_DATA / "dams.json").read_text(encoding="utf-8"))
    for d in dams:
        d["x"], d["y"] = grids.to_dem.transform(d["lon"], d["lat"])
    by_name = {d["name"]: d for d in dams}
    sources = []
    for d in dams:
        if d["name"] not in SOURCES or d["status"] == "proposed":
            continue
        basin, intake, scheme = SOURCES[d["name"]]
        sources.append({"name": d["name"], "kind": "river intake" if intake is None else "existing reservoir", "basin": basin,
                        "intake": intake or d["name"], "scheme": scheme, "x": d["x"], "y": d["y"], "level_m": level_of(d),
                        "base_lift_m": max(0.0, level_of(d) - level_of(by_name[intake])) if intake else 0.0, "inflow_q": d.get("inflow_q")})
    return dams, sources


def resolve_site(name: str, dams: list[dict], places: dict, grids: Grids) -> tuple[float, float, str] | None:
    """Coordinates (DEM projection) of a trunk-stage site and how they were found."""
    for d in dams:
        if d["name"] == name:
            return d["x"], d["y"], "map"
    key = PLACE_KEYS.get(name)
    if key:
        hit = next((v for k, v in places.items() if k.split(",")[0].strip().lower() == key.lower()), None)
        if hit:
            x, y = grids.to_dem.transform(hit["lon"], hit["lat"])
            return x, y, "OpenStreetMap place (Nominatim)"
    if name in APPROX_SITES:
        x, y = grids.to_dem.transform(*APPROX_SITES[name])
        return x, y, "hand-placed, approximate"
    return None


def build_systems(grids: Grids, router: Router, dams: list[dict], sources: list[dict]) -> tuple[list[dict], list[dict]]:
    """Trunk systems with resolved stage sites, routed stage lines, costs, and the stage pools as sources."""
    places = json.loads(PLACES.read_text(encoding="utf-8")) if PLACES.exists() else {}
    by_name = {s["name"]: s for s in sources}
    systems = []
    stage_sources = []
    for spec in SYSTEMS:
        intake = by_name.get(spec["intake"]) or next((d for d in dams if d["name"] == spec["intake"]), None)
        if intake is None:
            print(f"  system {spec['name']}: intake {spec['intake']} missing, skipped")
            continue
        q = spec["design_cms"]
        stages = []
        cumulative = {spec["intake"]: 0.0}                              # pumped lift from the river to each pool
        sites = {spec["intake"]: (intake["x"], intake["y"], "map")}
        levels = {spec["intake"]: float(intake["level_m"]) if "level_m" in intake else level_of(intake)}   # water level at each pool
        for from_name, to_name, level, lift, existing, conveyance, km in spec["stages"]:
            to_site = resolve_site(to_name, dams, places, grids)
            if to_site is None or from_name not in sites:
                print(f"  system {spec['name']}: stage {from_name} -> {to_name} not placed")
                continue
            sites[to_name] = to_site
            cumulative[to_name] = cumulative[from_name] + lift
            from_level = levels[from_name]
            levels[to_name] = float(level)
            fx, fy, _ = sites[from_name]
            line = router.route((fx, fy), (to_site[0], to_site[1]))
            # water above ground along the stage, sampled evenly: a lifted stage pumps at its start and runs at the upper pool's
            # level, a gravity stage falls from pool to pool; the map lifts the line off the terrain by this much
            height_above_ground = []
            if line is not None:
                _, _, _, ground = profile_along(grids, line, step_m=1000.0)
                water = np.linspace(float(level) if lift else from_level, float(level), len(ground))
                height_above_ground = np.maximum(0.0, water - ground).round(1).tolist()
            mw = q * lift * 9.81 / PUMP_EFFICIENCY / 1000 if lift else 0.0
            rate = {"tunnel": COST_TUNNEL_PER_KM(q), "canal": COST_CANAL_PER_KM(q) * CANAL_SINUOSITY, "gravity": COST_CANAL_PER_KM(q) * CANAL_SINUOSITY, "pressure main": COST_MAIN_PER_KM(q)}[conveyance]
            capex = 0.0 if existing else COST_PUMP_PER_MW * mw * STANDBY + rate * km
            stages.append({"from": from_name, "to": to_name, "to_level_m": level, "from_level_m": round(from_level), "lift_m": lift, "cumulative_lift_m": round(cumulative[to_name]), "existing": existing,
                           "conveyance": conveyance, "km": km, "mw": round(mw), "capex_cr": round(capex), "placed_by": to_site[2],
                           "lon": round(grids.to_wgs.transform(to_site[0], to_site[1])[0], 5), "lat": round(grids.to_wgs.transform(to_site[0], to_site[1])[1], 5),
                           "line": line, "_hg": height_above_ground})
            if lift or not existing:
                stage_sources.append({"name": to_name, "kind": "existing reservoir" if to_site[2] == "map" else "new trunk stage", "basin": spec["basin"], "intake": spec["intake"],
                                      "scheme": spec["name"], "x": to_site[0], "y": to_site[1], "level_m": float(level), "base_lift_m": float(cumulative[to_name]),
                                      "system": spec["name"]})
        summit = max(cumulative.values())
        energy_per_tmc = TMC_M3 * 1000 * 9.81 * summit / PUMP_EFFICIENCY / 3.6e6 * POWER_RS_PER_KWH / 1e7
        systems.append({**{k: v for k, v in spec.items() if k != "stages"}, "stages": stages, "summit_lift_m": round(summit),
                        "new_stages": sum(1 for s in stages if not s["existing"]), "existing_stages": sum(1 for s in stages if s["existing"]),
                        "capex_new_cr": round(sum(s["capex_cr"] for s in stages)), "augment_mw": round(sum(s["mw"] for s in stages if s["existing"])),
                        "new_mw": round(sum(s["mw"] for s in stages if not s["existing"])),
                        "power_cr_per_tmc_at_summit": round(energy_per_tmc, 1),
                        "energy_cr_per_year": round(sum(spec["tmc_per_year"] * TMC_M3 * 1000 * 9.81 * s["lift_m"] / PUMP_EFFICIENCY / 3.6e6 * POWER_RS_PER_KWH / 1e7 for s in stages), 1)})
    # a pool named in several systems or in SOURCES keeps one entry, with the system's cumulative lift
    merged = {s["name"]: s for s in sources}
    for s in stage_sources:
        merged[s["name"]] = {**merged.get(s["name"], {}), **s}
    return systems, list(merged.values())


def canal_taps(grids: Grids) -> list[dict]:
    path = b.WEB_DATA / "canals.geojson"
    if not path.exists():
        return []
    canals = gpd.read_file(path).to_crs(grids.dem_ds.crs)
    groups: dict[str, dict] = {}
    for _, row in canals.iterrows():
        if row.get("kind") == "main":
            continue
        text = f"{row.get('name') or ''} {row.get('scheme') or ''}"
        for pattern, intake, basin, label_ in CANAL_SCHEMES:
            if pattern.search(text):
                groups.setdefault(label_, {"intake": intake, "basin": basin, "geoms": []})["geoms"].append(row.geometry)
                break
    taps = []
    for label_, g in groups.items():
        days = PUMP_DAYS.get(g["intake"], 100)
        cap = TAP_SHARE * TAP_DESIGN_CMS.get(label_, 50) * days * 86400 / TMC_M3
        taps.append({"label": label_, "intake": g["intake"], "basin": g["basin"], "geometry": unary_union(g["geoms"]), "cap_tmc": cap})
    return taps


def intake_caps(sources: list[dict]) -> dict[str, float]:
    """TMC a year each river intake may newly supply: a share of the dependable monsoon flow past it."""
    return {s["name"]: RIVER_SURPLUS_SHARE * DEPENDABLE_MONSOON_OF_MEAN * tmc_per_year(s["inflow_q"]) if s.get("inflow_q") else 0.0
            for s in sources if s["kind"] == "river intake"}


def candidate_sites(grids: Grids, state_dem, dams: list[dict]) -> list[dict]:
    reaches = b.load_reaches()
    reaches = reaches[(reaches["ORD_STRA"] >= MIN_ORDER) & (reaches["DIS_AV_CMS"] >= MIN_FLOW_CMS)].to_crs(grids.dem_ds.crs)
    dam_xy = np.array([(d["x"], d["y"]) for d in dams])
    out = []
    for _, reach in reaches.iterrows():
        line = reach.geometry
        for along in list(np.arange(SITE_SAMPLE_M, line.length, SITE_SAMPLE_M)) + [line.length]:
            point = line.interpolate(along)
            if not state_dem.contains(point) or np.min(np.hypot(dam_xy[:, 0] - point.x, dam_xy[:, 1] - point.y)) < EXISTING_CLEARANCE_M:
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
    fx, fy = site["flow"]
    px, py = -fy, fx
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
    ur = w - int(round(-fy * 2))
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
    if 1.0 - float(grids.state_mask[pool_rows, pool_cols].mean()) > MAX_POOL_OUTSIDE_SHARE:
        return reject("crosses the state border")
    dam_rows = np.array([rr + r_lo for rr, _ in dam_cells] + [r0])
    dam_cols = np.array([cc + c_lo for _, cc in dam_cells] + [c0])
    if not grids.state_mask[dam_rows, dam_cols].all():
        return reject("crosses the state border")
    if towns_rc.size and np.any((towns_rc[:, 0][:, None] == pool_rows[None, :]) & (towns_rc[:, 1][:, None] == pool_cols[None, :])):
        return reject("drowns a town")
    xs, ys = grids.dem_ds.transform * (pool_cols + 0.5, pool_rows + 0.5)
    lon, lat = grids.to_wgs.transform(xs, ys)
    wr, wcix = grids.wc_rc(lon, lat)
    classes = grids.wc[np.clip(wr, 0, grids.wc.shape[0] - 1), np.clip(wcix, 0, grids.wc.shape[1] - 1)]
    area_km2 = pool.sum() * 0.04
    crop_km2 = float((classes == WC_CROP).mean()) * area_km2
    tree_km2 = float((classes == WC_TREE).mean()) * area_km2
    if float((classes == WC_BUILT).mean()) > MAX_BUILTUP_SHARE:
        return reject("drowns built-up land")
    if crop_km2 / volume_tmc > MAX_CROPLAND_KM2_PER_TMC:
        return reject("drowns too much farmland")
    land = 100 * (COST_FARMLAND_PER_HA * crop_km2 + COST_FOREST_PER_HA * tree_km2 + COST_OTHER_LAND_PER_HA * (area_km2 - crop_km2 - tree_km2))
    cost = COST_STORAGE_PER_TMC * volume_tmc + COST_EMBANKMENT_KM_H2 * dam_len_km * crest_m ** 2 + land
    return {"crest_m": crest_m, "frl_m": round(float(crest), 1), "bed_m": round(float(base), 1), "storage_tmc": round(volume_tmc, 2),
            "area_km2": round(area_km2, 1), "cropland_km2": round(crop_km2, 1), "tree_km2": round(tree_km2, 1),
            "dam_km": round(dam_len_km, 1), "cost_cr": round(cost), "cost_per_tmc": round(cost / volume_tmc),
            "dam_xy": dam_line_xy(grids, dam_rows, dam_cols, px, py), "pool_rows": pool_rows, "pool_cols": pool_cols}


def dam_line_xy(grids: Grids, rows: np.ndarray, cols: np.ndarray, px: float, py: float) -> list[tuple[float, float]]:
    """Dam crest as a straight line between the two outermost dam cells (DEM CRS), ordered across the valley."""
    xs, ys = grids.dem_ds.transform * (cols + 0.5, rows + 0.5)
    across = np.asarray(xs) * px + np.asarray(ys) * py
    lo, hi = int(np.argmin(across)), int(np.argmax(across))
    return [(float(xs[lo]), float(ys[lo])), (float(xs[hi]), float(ys[hi]))]


def pool_polygon(grids: Grids, pool_rows: np.ndarray, pool_cols: np.ndarray):
    r_lo, c_lo = pool_rows.min() - 1, pool_cols.min() - 1
    mask = np.zeros((pool_rows.max() - r_lo + 2, pool_cols.max() - c_lo + 2), dtype=np.uint8)
    mask[pool_rows - r_lo, pool_cols - c_lo] = 1
    transform = grids.dem_ds.transform * grids.dem_ds.transform.translation(c_lo, r_lo)
    geoms = [shape(g) for g, v in shapes(mask, mask=mask.astype(bool), transform=transform) if v == 1]
    return gpd.GeoSeries([max(geoms, key=lambda g: g.area)], crs=grids.dem_ds.crs).to_crs(WGS84).iloc[0].simplify(0.0008)


def choose_reservoirs(grids: Grids, sites: list[dict], districts: gpd.GeoDataFrame, demand: list[dict], towns: list[dict]) -> list[dict]:
    towns_rc = np.array([grids.dem_rc(*grids.to_dem.transform(t["lon"], t["lat"])) for t in towns]) if towns else np.empty((0, 2), int)
    options = []
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


def lift_deliveries(grids: Grids, districts: gpd.GeoDataFrame, district_ix: np.ndarray, demand: list[dict], reservoirs: list[dict]) -> list[dict]:
    """Districts whose need is not met by new storage get water lifted to a ridge point on their high ground."""
    out = []
    for i, row in enumerate(demand):
        sited = sum(r["annual_tmc"] for r in reservoirs if r.get("serves") == row["district"])
        shortfall = row["tmc"] - sited
        row["annual_sited_tmc"] = round(sited, 1)
        if shortfall < MIN_ANNUAL_TMC:
            continue
        m = (district_ix == i + 1) & grids.cultivable & np.isfinite(grids.wc_elev)
        if not m.any():
            continue
        cx, cy = float(grids.wc_x[m].mean()), float(grids.wc_y[m].mean())
        target = float(np.percentile(grids.wc_elev[m], DELIVERY_PERCENTILE))
        band = m & (np.abs(grids.wc_elev - target) <= DELIVERY_BAND_M)
        if not band.any():
            band = m
        dist = np.hypot(grids.wc_x - cx, grids.wc_y - cy)
        dist[~band] = np.inf
        r, c = np.unravel_index(int(np.argmin(dist)), dist.shape)
        x, y, ground = float(grids.wc_x[r, c]), float(grids.wc_y[r, c]), float(grids.wc_elev[r, c])
        out.append({"id": f"L{len(out) + 1:02d}", "kind": "delivery", "name": f"{row['district']} lift delivery", "district": row["district"],
                    "serves": row["district"], "x": x, "y": y, "frl_m": round(ground + COMMAND_HEAD_M, 1), "ground_m": round(ground),
                    "annual_tmc": shortfall, "storage_tmc": 0.0, "area_km2": 0.0, "cropland_km2": 0.0, "tree_km2": 0.0, "dam_km": 0.0, "crest_m": 0,
                    "cost_cr": round(BALANCING_STORAGE_SHARE * shortfall * COST_STORAGE_PER_TMC)})
    return out


def profile_along(grids: Grids, line: LineString, step_m: float = 500.0):
    n = max(2, int(line.length / step_m) + 1)
    chainage = np.linspace(0, line.length, n)
    pts = [line.interpolate(d) for d in chainage]
    xs = np.array([p.x for p in pts])
    ys = np.array([p.y for p in pts])
    r, c = grids.dem_rc(xs, ys)
    ok = (r >= 0) & (r < grids.dem.shape[0]) & (c >= 0) & (c < grids.dem.shape[1])
    elev = np.full(n, np.nan)
    elev[ok] = grids.dem[r[ok], c[ok]]
    return xs, ys, chainage, np.nan_to_num(elev, nan=0.0)


def conveyance_for(grids: Grids, work: dict, src: dict, line: LineString) -> dict:
    """Follow the hydraulic grade line along the routed line: gravity or pump stages, and what each reach needs."""
    xs, ys, chainage, ground = profile_along(grids, line)
    km = line.length / 1000
    canal_fall = CANAL_FALL_M_PER_KM * km
    if src["level_m"] >= work["frl_m"] + canal_fall + STAGE_LOSS_M:          # review: gravity when the source level allows
        lift, stages = 0.0, 0
    else:
        lift = work["frl_m"] - src["level_m"] + canal_fall
        stages = max(1, math.ceil(lift / STAGE_MAX_M))
        if stages > 1 and lift / stages < STAGE_MIN_M:
            stages -= 1
        lift += STAGE_LOSS_M * stages
    total_lift = lift + src["base_lift_m"]
    # water level along the route: falls at canal gradient, jumps at each pump house placed at the toe of the next rise
    level = np.empty(len(ground))
    pumps = []
    current = src["level_m"]
    next_pump_at = 0 if stages else None
    stage_lift = lift / stages if stages else 0.0
    main_until = -1
    for i in range(len(ground)):
        if next_pump_at is not None and i == next_pump_at and len(pumps) < stages:
            pumps.append({"stage": len(pumps) + 1, "x": float(xs[i]), "y": float(ys[i]), "lift_m": round(stage_lift), "index": i})
            current += stage_lift
            main_until = i + int(RISING_LEG_KM * 1000 / 500)
            ahead = np.nonzero(ground[i + 1:] > current - 10)[0]
            next_pump_at = i + 1 + int(ahead[0]) if ahead.size and len(pumps) < stages else len(ground) - 2
            next_pump_at = max(next_pump_at, i + int(len(ground) * 1 / (stages + 1)))
            next_pump_at = min(next_pump_at, len(ground) - 2)
        level[i] = current
        if i > 0:
            current -= CANAL_FALL_M_PER_KM * (chainage[i] - chainage[i - 1]) / 1000
    cover = ground - level
    kinds = np.full(len(ground), "canal", dtype=object)
    kinds[(cover >= CUT_COVER_M) & (cover < TUNNEL_COVER_M)] = "cut"
    kinds[cover >= TUNNEL_COVER_M] = "tunnel"
    kinds[cover <= -AQUEDUCT_DEPTH_M] = "aqueduct"
    for p in pumps:                                                            # the rising leg after a pump house is a pressure main
        end = min(len(ground), p["index"] + int(RISING_LEG_KM * 1000 / 500) + 1)
        for i in range(p["index"], end):
            kinds[i] = "pressure main"
            if ground[i] >= level[i] - 5 and i > p["index"]:
                break
    for i in range(1, len(kinds) - 1):                                         # tunnels shorter than 1 km are cut instead
        if kinds[i] == "tunnel" and kinds[i - 1] != "tunnel" and kinds[i + 1] != "tunnel":
            kinds[i] = "cut"
    segments = []
    for i in range(len(xs) - 1):
        seg_kind = kinds[i + 1] if kinds[i + 1] == "pressure main" else kinds[i]
        if not segments or segments[-1]["kind"] != seg_kind:
            segments.append({"kind": seg_kind, "xy": [(float(xs[i]), float(ys[i]))], "hg": [round(max(0.0, float(level[i] - ground[i])), 1)]})
        segments[-1]["xy"].append((float(xs[i + 1]), float(ys[i + 1])))
        segments[-1]["hg"].append(round(max(0.0, float(level[i + 1] - ground[i + 1])), 1))   # water above ground at each vertex: the map lifts the line by it
    lengths = {k: 0.0 for k in ("canal", "cut", "tunnel", "aqueduct", "pressure main")}
    for seg in segments:
        lengths[seg["kind"]] += LineString(seg["xy"]).length / 1000
    return {"source": src["name"], "feed_kind": src["kind"], "feed_scheme": src.get("scheme"), "basin": src["basin"], "intake": src["intake"],
            "source_level_m": round(src["level_m"]), "lift_m": round(lift), "base_lift_m": round(src["base_lift_m"]), "total_lift_m": round(total_lift),
            "route_km": round(km, 1), "canal_km": round(lengths["canal"] * CANAL_SINUOSITY, 1), "cut_km": round(lengths["cut"], 1), "tunnel_km": round(lengths["tunnel"], 1),
            "aqueduct_km": round(lengths["aqueduct"], 1), "main_km": round(lengths["pressure main"], 1), "stages": stages,
            "pumps": [{k: v for k, v in p.items() if k != "index"} for p in pumps], "segments": segments,
            "_lift": lift, "_total_lift": total_lift, "_lengths": lengths}


def size_pumps(work: dict, through_tmc: float, days: int) -> None:
    """Pumps, power and conveyance cost for the water a work passes (its own plus anything cascaded through it)."""
    gross = through_tmc * (1 + LOSSES)
    q = design_cms(gross, days)
    mw_new = q * work["_lift"] * 9.81 / PUMP_EFFICIENCY / 1000
    mw_augment = q * work["base_lift_m"] * 9.81 / PUMP_EFFICIENCY / 1000
    energy_cr = gross * TMC_M3 * 1000 * 9.81 * work["_total_lift"] / PUMP_EFFICIENCY / 3.6e6 * POWER_RS_PER_KWH / 1e7
    energy_new_cr = gross * TMC_M3 * 1000 * 9.81 * work["_lift"] / PUMP_EFFICIENCY / 3.6e6 * POWER_RS_PER_KWH / 1e7   # the trunk systems carry the rest
    ln = work["_lengths"]
    canal_rate = COST_CANAL_PER_KM(q)
    conveyance = (ln["canal"] * CANAL_SINUOSITY * canal_rate + ln["cut"] * CUT_FACTOR * canal_rate + ln["aqueduct"] * AQUEDUCT_FACTOR * canal_rate
                  + ln["tunnel"] * COST_TUNNEL_PER_KM(q) + ln["pressure main"] * COST_MAIN_PER_KM(q))
    work.update({"through_tmc": round(through_tmc, 1), "gross_tmc": round(gross, 1), "pump_days": days, "design_cms": round(q, 1), "mw": round(mw_new * STANDBY),
                 "augment_mw": round(mw_augment * STANDBY), "energy_cr_per_year": round(energy_cr, 1), "energy_new_cr_per_year": round(energy_new_cr, 1),
                 "capex_conveyance_cr": round(COST_PUMP_PER_MW * mw_new * STANDBY + conveyance)})
    for p in work["pumps"]:
        p["mw"] = round(mw_new * STANDBY / max(1, work["stages"]), 1)


def plan_feeds(grids: Grids, router: Router, works: list[dict], sources: list[dict], taps: list[dict], caps: dict[str, float], basin_caps: dict[str, float]) -> None:
    """Cheapest feeder with water to spare for each work, lowest works first so higher ones can cascade from them."""
    planned: list[dict] = []
    for work in sorted(works, key=lambda w: w["frl_m"]):
        tree = router.tree(work["x"], work["y"])
        need = work["annual_tmc"]
        candidates = list(sources) + planned
        here = Point(work["x"], work["y"])
        for tap in taps:
            on_canal, _ = nearest_points(tap["geometry"], here)
            if on_canal.distance(here) <= TAP_MAX_KM * 1000 and tap["cap_tmc"] >= need:
                level = grids.elev_xy(on_canal.x, on_canal.y)
                intake_level = next((s["level_m"] for s in sources if s["name"] == tap["intake"]), level)
                candidates.append({"name": tap["label"], "kind": "existing canal", "basin": tap["basin"], "intake": tap["intake"], "scheme": tap["label"],
                                   "x": on_canal.x, "y": on_canal.y, "level_m": level + 2, "base_lift_m": max(0.0, level - intake_level), "tap": tap})
        best = None
        for src in candidates:
            if src.get("work_id") == work["id"]:
                continue
            within = caps.get(src["intake"], 0.0) >= need and basin_caps.get(src["basin"], float("inf")) >= need
            line = router.path(tree, (work["x"], work["y"]), (src["x"], src["y"]))
            if line is None:
                continue
            line = LineString(list(line.coords)[::-1])
            plan = conveyance_for(grids, work, src, line)
            size_pumps(plan, need, PUMP_DAYS.get(src["intake"], 100))
            score = plan["capex_conveyance_cr"] + ENERGY_YEARS * plan["energy_cr_per_year"] + (0 if within else 1e9)
            if best is None or score < best[0]:
                best = (score, plan, src, within)
        _, plan, src, within = best
        plan["over_cap"] = not within
        plan["feed_work"] = src.get("work_id")
        plan["feed_system"] = src.get("system")
        work.update(plan)
        caps[src["intake"]] = caps.get(src["intake"], 0.0) - need * (1 + LOSSES)
        if src["basin"] in basin_caps:
            basin_caps[src["basin"]] -= need * (1 + LOSSES)
        if "tap" in src:
            src["tap"]["cap_tmc"] -= need
        if work["kind"] == "reservoir":
            planned.append({"name": work["name"], "kind": "proposed reservoir", "basin": src["basin"], "intake": src["intake"], "scheme": f"this proposal, via {src['name']}",
                            "x": work["x"], "y": work["y"], "level_m": work["frl_m"] - 3, "base_lift_m": plan["_total_lift"], "work_id": work["id"]})
    by_id = {w["id"]: w for w in works}
    through = {w["id"]: w["annual_tmc"] for w in works}
    for w in sorted(works, key=lambda w: -w["frl_m"]):
        if w.get("feed_work"):
            through[w["feed_work"]] += through[w["id"]]
    for w in works:
        size_pumps(w, through[w["id"]], w["pump_days"])
        chain = []
        node = w
        while node.get("feed_work"):
            node = by_id[node["feed_work"]]
            chain.append(node["name"])
        w["chain"] = chain
        w["high_lift"] = w["total_lift_m"] > MAX_PUMPED_LIFT_M


def command_masks(grids: Grids, works: list[dict], existing: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    def served_by(level_m: float, x: float, y: float) -> np.ndarray:
        km = np.hypot(grids.wc_x - x, grids.wc_y - y) / 1000
        return (km <= COMMAND_KM) & grids.cultivable & (grids.wc_elev <= level_m - COMMAND_HEAD_M - COMMAND_FALL_M_PER_KM * km)

    by_existing = np.zeros(grids.wc.shape, dtype=bool)
    for d in existing:
        if d["status"] == "proposed" or (d["capacity_tmcft"] or 0) < 2 or d["elev_m"] is None:
            continue
        by_existing |= served_by(level_of(d), d["x"], d["y"])
    by_new = np.zeros(grids.wc.shape, dtype=bool)
    for r in works:
        by_new |= served_by(r["frl_m"], r["x"], r["y"])
    return by_existing, by_new & ~by_existing


def mask_features(grids: Grids, mask: np.ndarray, kind: str, min_km2: float = 25.0) -> list[dict]:
    feats = []
    for geom, value in shapes(mask.astype(np.uint8), mask=mask, transform=grids.wc_transform):
        if value != 1:
            continue
        poly = shape(geom)
        area_km2 = poly.area * 111.32 * 111.32 * math.cos(math.radians(poly.centroid.y))
        if area_km2 >= min_km2:
            feats.append({"type": "Feature", "geometry": poly.simplify(0.004).__geo_interface__, "properties": {"kind": kind, "area_km2": round(area_km2)}})
    return feats


def nearest_town(towns: list[dict], lon: float, lat: float) -> str:
    return min(towns, key=lambda t: (t["lon"] - lon) ** 2 + (t["lat"] - lat) ** 2)["name"]


def main() -> None:
    districts = b.read_projected("districts")
    state = b.read_projected("state")
    dem_crs = rasterio.open(b.PROFILE_DEM).crs
    state_dem = state.to_crs(dem_crs).geometry.iloc[0]
    grids = Grids(state_dem)
    router = Router(state_dem)
    district_ix = district_raster(grids, districts)
    demand, total = demand_table(grids, districts, district_ix)
    print(f"land: {total['cultivable_pct']} % of the state cultivable, {total['cropland_pct']} % cropland now "
          f"({total['cropland_of_cultivable_pct']} % of cultivable); target {int(TARGET_SHARE * 100)} % adds {total['new_lakh_acres']} lakh acres "
          f"and needs {total['tmc']} TMC a year net ({total['tmc_new']} new + {total['tmc_stabilise']} stabilisation), {total['tmc_gross']} gross at the intakes")
    dams, sources = load_existing(grids)
    sources = [s for s in sources if router.snap(s["x"], s["y"]) is not None]
    systems, sources = build_systems(grids, router, dams, sources)
    taps = canal_taps(grids)
    print(f"  sources: {sum(1 for s in sources if s['kind'] == 'river intake')} river intakes, {sum(1 for s in sources if s['kind'] == 'existing reservoir')} reservoirs filled by existing schemes, "
          f"{sum(1 for s in sources if s['kind'] == 'new trunk stage')} new trunk stages, {len(taps)} canal systems that can be tapped "
          f"({', '.join(f'{t['label']} {t['cap_tmc']:.0f} TMC' for t in taps)})")
    places = json.loads((b.RAW / "osm_places.json").read_text(encoding="utf-8"))["elements"]
    towns = [{"name": e["tags"].get("name:en") or e["tags"]["name"], "lon": e["lon"], "lat": e["lat"]} for e in places if "name" in e["tags"]]
    sites = candidate_sites(grids, state_dem, dams)
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
    basin_caps = {"Krishna": max(0.0, ENVELOPES["Krishna"]["requested"] - ENVELOPES["Krishna"]["committed"])}
    cap_table = {k: round(v) for k, v in caps.items()}
    plan_feeds(grids, router, works, sources, taps, caps, basin_caps)
    for r in works:
        r["capex_distribution_cr"] = round(COST_DISTRIBUTION_PER_TMC * r["annual_tmc"])
        r["capex_cr"] = r["cost_cr"] + r["capex_conveyance_cr"] + r["capex_distribution_cr"]
        r["annual_tmc"] = round(r["annual_tmc"], 1)
    feeds = {k: sum(1 for w in works if w["feed_kind"] == k) for k in ("river intake", "existing reservoir", "existing canal", "new trunk stage", "proposed reservoir")}
    print(f"  {len(reservoirs)} reservoirs sited, {len(deliveries)} lift deliveries; feeds {feeds}; intake caps (TMC a year) {cap_table}; "
          f"over cap {[w['id'] for w in works if w['over_cap']]}; lifted over {MAX_PUMPED_LIFT_M} m {[w['id'] for w in works if w['high_lift']]}")
    flow = json.loads((b.WEB_DATA / "flow_summary.json").read_text(encoding="utf-8"))
    for river, peak in flow["peaks"].items():
        if river in ENVELOPES:
            ENVELOPES[river]["mean_flow_tmc"] = round(tmc_per_year(peak["q"]))
    basins = {}
    for r in works:
        basins[r["basin"]] = basins.get(r["basin"], 0.0) + r["gross_tmc"] * r["annual_tmc"] / max(r["through_tmc"], 0.01)
    envelope_rows = []
    for river, e in ENVELOPES.items():
        free_award = max(0.0, e["award"] - e["committed"])
        free_requested = max(0.0, e["requested"] - e["committed"])
        drawn = round(basins.get(river, 0.0), 1)
        systems_draw = round(sum(s["tmc_per_year"] for s in systems if s["basin"] == river), 1)
        envelope_rows.append({"river": river, **e, "free_within_award": round(free_award, 1), "free_if_requested": round(free_requested, 1),
                              "proposal_draws": drawn, "systems_draw": systems_draw, "beyond_request": round(max(0.0, drawn - free_requested), 1)})
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
                         "works": [r["id"] for r in works if r["serves"] == name], "system": next((s["name"] for s in systems if name in s["districts"]), None)})
    totals = {"reservoirs": len(reservoirs), "deliveries": len(deliveries), "storage_tmc": round(sum(r["storage_tmc"] for r in reservoirs), 1),
              "annual_tmc": round(sum(r["annual_tmc"] for r in works), 1), "gross_tmc": round(sum(r["annual_tmc"] for r in works) * (1 + LOSSES), 1),
              "annual_from_reservoirs_tmc": round(sum(r["annual_tmc"] for r in reservoirs), 1), "submerged_km2": round(sum(r["area_km2"] for r in reservoirs)),
              "cropland_submerged_km2": round(sum(r["cropland_km2"] for r in reservoirs)), "pump_houses": sum(r["stages"] for r in works),
              "mw": round(sum(r["mw"] for r in works)), "augment_mw": round(sum(r["augment_mw"] for r in works)),
              "tunnel_km": round(sum(r["tunnel_km"] for r in works)), "canal_km": round(sum(r["canal_km"] for r in works)), "cut_km": round(sum(r["cut_km"] for r in works)),
              "main_km": round(sum(r["main_km"] for r in works)), "aqueduct_km": round(sum(r["aqueduct_km"] for r in works)),
              "capex_cr": round(sum(r["capex_cr"] for r in works)), "capex_storage_cr": round(sum(r["cost_cr"] for r in works)),
              "capex_conveyance_cr": round(sum(r["capex_conveyance_cr"] for r in works)), "capex_distribution_cr": round(sum(r["capex_distribution_cr"] for r in works)),
              "energy_cr_per_year": round(sum(r["energy_cr_per_year"] for r in works)), "energy_new_cr_per_year": round(sum(r["energy_new_cr_per_year"] for r in works)),
              "storage_target_tmc": round(STORAGE_PER_ANNUAL * total["tmc"], 1),
              "demand_met_pct": round(100 * sum(r["annual_tmc"] for r in works) / total["tmc"], 1), "feeds": feeds,
              "cascaded": sum(1 for w in works if w.get("feed_work")), "high_lift": sum(1 for w in works if w["high_lift"]),
              "systems": len(systems), "systems_capex_new_cr": round(sum(s["capex_new_cr"] for s in systems)), "systems_new_mw": round(sum(s["new_mw"] for s in systems)),
              "systems_augment_mw": round(sum(s["augment_mw"] for s in systems)), "systems_tmc": round(sum(s["tmc_per_year"] for s in systems), 1),
              "systems_energy_cr_per_year": round(sum(s["energy_cr_per_year"] for s in systems))}
    cult_total = float(grids.wc_km2[(district_ix > 0) & grids.cultivable].sum())
    totals["gravity_existing_pct"] = round(100 * float(grids.wc_km2[(district_ix > 0) & by_existing].sum()) / cult_total, 1)
    totals["gravity_new_pct"] = round(100 * float(grids.wc_km2[(district_ix > 0) & by_new].sum()) / cult_total, 1)
    print(f"works: {totals['reservoirs']} reservoirs ({totals['storage_tmc']} TMC storage) and {totals['deliveries']} lift deliveries for {totals['annual_tmc']} TMC a year net "
          f"({totals['demand_met_pct']} % of need), {totals['cascaded']} cascaded, {totals['pump_houses']} pump houses, {totals['mw']} MW new + {totals['augment_mw']} MW augmentation, "
          f"{totals['tunnel_km']} km tunnel, {totals['canal_km']} km canal, {totals['main_km']} km pressure main; capex Rs {totals['capex_cr']:,} crore "
          f"(storage {totals['capex_storage_cr']:,}, conveyance {totals['capex_conveyance_cr']:,}, distribution {totals['capex_distribution_cr']:,}), power Rs {totals['energy_cr_per_year']:,} crore a year")
    print(f"trunk systems: {totals['systems']} systems carrying {totals['systems_tmc']} TMC a year gross; new stages Rs {totals['systems_capex_new_cr']:,} crore, "
          f"{totals['systems_new_mw']} MW new + {totals['systems_augment_mw']} MW augmentation of existing stages, power Rs {totals['systems_energy_cr_per_year']:,} crore a year")
    for e in envelope_rows:
        print(f"  {e['river']}: works draw {e['proposal_draws']} TMC gross (systems {e['systems_draw']}); free within award {e['free_within_award']}, if the 2025 request is granted {e['free_if_requested']}; beyond that {e['beyond_request']}")

    features = mask_features(grids, by_existing, "command_existing") + mask_features(grids, by_new, "command_new")
    for s in systems:
        for i, st in enumerate(s["stages"]):
            if st["line"] is not None:
                lon, lat = grids.to_wgs.transform(*zip(*st["line"].coords))
                features.append({"type": "Feature", "geometry": LineString(zip(lon, lat)).__geo_interface__,
                                 "properties": {"kind": "trunk", "system": s["name"], "stage": i + 1, "from": st["from"], "to": st["to"], "lift_m": st["lift_m"], "to_level_m": st["to_level_m"],
                                                "existing": st["existing"], "conveyance": st["conveyance"], "km": st["km"], "mw": st["mw"], "tmc_per_year": s["tmc_per_year"], "design_cms": s["design_cms"],
                                                "hg": st["_hg"]}})
            st.pop("line", None)
            st.pop("_hg", None)
    for r in works:
        if r["kind"] == "reservoir":
            dlon, dlat = grids.to_wgs.transform(*zip(*r["dam_xy"]))
            features.append({"type": "Feature", "geometry": LineString(zip(dlon, dlat)).__geo_interface__,
                             "properties": {"kind": "dam", "id": r["id"], "name": r["name"], "crest_m": r["crest_m"], "dam_km": r["dam_km"]}})
            features.append({"type": "Feature", "geometry": pool_polygon(grids, r["pool_rows"], r["pool_cols"]).__geo_interface__,
                             "properties": {"kind": "pool", "id": r["id"], "name": r["name"], "storage_tmc": r["storage_tmc"], "frl_m": r["frl_m"]}})
        else:
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r["lon"], 5), round(r["lat"], 5)]},
                             "properties": {"kind": "delivery", "id": r["id"], "name": r["name"], "annual_tmc": r["annual_tmc"], "frl_m": r["frl_m"]}})
        for seg in r["segments"]:
            lon, lat = grids.to_wgs.transform(*zip(*seg["xy"]))
            features.append({"type": "Feature", "geometry": LineString(zip(lon, lat)).__geo_interface__,
                             "properties": {"kind": seg["kind"], "id": r["id"], "name": r["name"], "source": r["source"], "lift_m": r["lift_m"], "km": round(LineString(seg["xy"]).length / 1000, 1),
                                            "route_km": r["route_km"], "tunnel_km": r["tunnel_km"], "canal_km": r["canal_km"], "annual_tmc": r["annual_tmc"], "through_tmc": r["through_tmc"],
                                            "hg": seg["hg"]}})
        for p in r["pumps"]:
            lon, lat = grids.to_wgs.transform(p["x"], p["y"])
            p["lon"], p["lat"] = round(lon, 5), round(lat, 5)
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                             "properties": {"kind": "pump", "id": r["id"], "name": f"{r['name']} · stage {p['stage']}", "stage": p["stage"], "lift_m": p["lift_m"], "mw": p["mw"], "source": r["source"]}})
    keep = ("id", "kind", "name", "district", "serves", "lon", "lat", "crest_m", "frl_m", "bed_m", "ground_m", "storage_tmc", "annual_tmc", "through_tmc", "gross_tmc", "area_km2",
            "cropland_km2", "tree_km2", "dam_km", "cost_cr", "cost_per_tmc", "cms", "upland_km2", "source", "feed_kind", "feed_scheme", "feed_work", "feed_system", "chain", "basin",
            "intake", "source_level_m", "lift_m", "base_lift_m", "total_lift_m", "high_lift", "route_km", "canal_km", "cut_km", "tunnel_km", "aqueduct_km", "main_km", "pump_days",
            "design_cms", "mw", "augment_mw", "stages", "capex_conveyance_cr", "capex_distribution_cr", "energy_cr_per_year", "energy_new_cr_per_year", "capex_cr", "over_cap", "pumps")
    out_works = [{k: (round(r[k], 5) if k in ("lon", "lat") else r[k]) for k in keep if k in r} for r in works]
    for r in out_works:
        r["pumps"] = [{k: p[k] for k in ("stage", "lon", "lat", "lift_m", "mw")} for p in r["pumps"]]
    proposal = {
        "norms": {"target_share": TARGET_SHARE, "target_range": TARGET_RANGE, "max_slope_pct": MAX_SLOPE_PCT, "duty_new_acres_per_tmc": DUTY_NEW_ACRES_PER_TMC,
                  "duty_stabilise_acres_per_tmc": DUTY_STABILISE_ACRES_PER_TMC, "rainfed_share": RAINFED_SHARE, "losses": LOSSES, "storage_per_annual": STORAGE_PER_ANNUAL,
                  "crest_options_m": CREST_OPTIONS_M, "stage_min_m": STAGE_MIN_M, "stage_max_m": STAGE_MAX_M, "stage_loss_m": STAGE_LOSS_M, "canal_fall_m_per_km": CANAL_FALL_M_PER_KM,
                  "tunnel_cover_m": TUNNEL_COVER_M, "cut_cover_m": CUT_COVER_M, "aqueduct_depth_m": AQUEDUCT_DEPTH_M, "rising_leg_km": RISING_LEG_KM, "canal_sinuosity": CANAL_SINUOSITY,
                  "pump_days": PUMP_DAYS, "pump_hours": PUMP_HOURS, "standby": STANDBY, "pump_efficiency": PUMP_EFFICIENCY, "command_km": COMMAND_KM, "command_head_m": COMMAND_HEAD_M,
                  "command_fall_m_per_km": COMMAND_FALL_M_PER_KM, "tap_max_km": TAP_MAX_KM, "tap_share": TAP_SHARE, "tap_design_cms": TAP_DESIGN_CMS, "route_cell_m": ROUTE_CELL_M,
                  "river_surplus_share": RIVER_SURPLUS_SHARE, "dependable_monsoon_of_mean": DEPENDABLE_MONSOON_OF_MEAN, "max_pumped_lift_m": MAX_PUMPED_LIFT_M,
                  "delivery_percentile": DELIVERY_PERCENTILE, "max_cropland_km2_per_tmc": MAX_CROPLAND_KM2_PER_TMC, "operating_levels": OPERATING_LEVEL,
                  "costs": {"storage_per_tmc_cr": COST_STORAGE_PER_TMC, "embankment_km_h2_cr": COST_EMBANKMENT_KM_H2, "farmland_per_ha_cr": COST_FARMLAND_PER_HA,
                            "forest_per_ha_cr": COST_FOREST_PER_HA, "other_land_per_ha_cr": COST_OTHER_LAND_PER_HA, "distribution_per_tmc_cr": COST_DISTRIBUTION_PER_TMC,
                            "pump_per_mw_cr": COST_PUMP_PER_MW, "tunnel_per_km_cr": "40 + 0.7 Q", "canal_per_km_cr": "5 + 0.15 Q + 3", "pressure_main_per_km_cr": "8 + 1.0 Q",
                            "cut_factor": CUT_FACTOR, "aqueduct_factor": AQUEDUCT_FACTOR, "power_rs_per_kwh": POWER_RS_PER_KWH, "energy_years": ENERGY_YEARS},
                  "cost_benchmarks": COST_SOURCES, "landcover": "ESA WorldCover 2021 v200 at 320 m (CC BY 4.0)", "dem": "Copernicus GLO-90 resampled to 200 m",
                  "review": "Norms, operating levels, the six trunk systems and the caveats follow a lift-irrigation engineering review of the model (24 October 2026); levels are recalled, not verified."},
        "caveats": CAVEATS, "demand": {"state": total, "districts": demand}, "envelopes": envelope_rows, "intake_caps": cap_table, "works": out_works, "systems": systems,
        "totals": totals, "coverage": coverage,
    }
    (b.WEB_DATA / "proposal.json").write_text(json.dumps(proposal, indent=1, ensure_ascii=False), encoding="utf-8")
    (b.WEB_DATA / "proposal.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print(f"wrote proposal.json and proposal.geojson ({(b.WEB_DATA / 'proposal.geojson').stat().st_size / 1e6:.1f} MB, {len(features)} features)")


if __name__ == "__main__":
    main()

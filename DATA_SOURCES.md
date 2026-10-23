# Data sources

Every dataset behind the Telangana terrain map and 3D block, where it comes
from, its terms, what it is used for and how it is processed. All sources are
public and were downloaded by `fetch_data.py` into `data/raw/` (not committed);
`prepare_data.py` and `build_web_data.py` derive everything else from them.

| # | Dataset | Provider | Downloaded | Terms |
|---|---|---|---|---|
| 1 | Copernicus DEM GLO-90 | ESA / Copernicus, via AWS Open Data | 2026-10-20 | Copernicus DEM licence, free with attribution |
| 2 | geoBoundaries gbOpen IND ADM1 / ADM2 | geoBoundaries (William & Mary geoLab) | 2026-10-20 | CC BY 4.0 |
| 3 | Natural Earth 10m rivers + lake centerlines, populated places | Natural Earth | 2026-10-20 | Public domain |
| 4 | OpenStreetMap places (Overpass API) | OpenStreetMap contributors | 2026-10-22 | ODbL 1.0 |
| 5 | HydroRIVERS v1.0, Asia | HydroSHEDS | 2026-10-22 | HydroSHEDS licence, free with attribution |
| 6 | Wikipedia dam articles | Wikimedia Foundation / Wikipedia editors | 2026-10-22 | CC BY-SA 4.0 |
| 7 | Landmark heights (4 values) | Wikipedia, World History Encyclopedia | 2026-10-22 | CC BY-SA 4.0 / CC BY-NC-SA |

## 1. Copernicus DEM GLO-90 (elevation)

- **What:** global digital *surface* model at 3 arc-seconds (~90 m), derived
  from TanDEM-X. Heights are orthometric (EGM2008), i.e. metres above sea
  level. Being a surface model it includes tree canopy and buildings.
- **Files:** 25 one-degree COG tiles `Copernicus_DSM_COG_30_N{15..19}_00_E{77..81}_00_DEM.tif`
  from `https://copernicus-dem-90m.s3.amazonaws.com/` (≈130 MB).
- **Pages:** https://registry.opendata.aws/copernicus-dem/ ·
  https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model
- **Terms:** free for any use including commercial, attribution required.
  Required credit: *“© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH
  2014-2018 provided under COPERNICUS by the European Union and ESA; all
  rights reserved.”*
- **Used for:** terrain tiles of the web map (`web/tiles`, Terrarium PNG,
  zoom 5–11), the elevation under the cursor, city elevations, river-bed
  profiles, 100 m contours, the forge3d viewer DEM and the 3D block.
- **Processing:** mosaicked; values below 0 m (a few dozen reservoir
  artefacts) clamped to 0; Gaussian smoothing σ = 1 px to tame canopy and
  building noise; reprojected to Web Mercator for tiles and to a Lambert
  Conformal Conic grid at 200 m for the forge3d outputs (`prepare_data.py`,
  `build_web_data.py`).

## 2. geoBoundaries gbOpen, India ADM1 and ADM2 (state and districts)

- **What:** open administrative boundaries; ADM1 = states, ADM2 = districts.
  Telangana is `shapeISO IN-TG`; 33 districts fall inside it.
- **Files:** `india_adm1.geojson`, `india_adm2.geojson` via
  `https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/` and `/ADM2/`.
- **Pages:** https://www.geoboundaries.org
- **Terms:** CC BY 4.0. Cite: Runfola D. et al. (2020) *geoBoundaries: A
  global database of political administrative boundaries.* PLoS ONE 15(4):
  e0231866.
- **Used for:** the state outline and mask, district lines and labels, the
  per-district river-flow table, the city → district lookup.
- **Known issues:** the file still has `Warangal (R)` and `Warangal (U)`; in
  August 2021 these became Warangal and Hanumakonda and some mandals moved
  between them, so that boundary may predate the change. The source's
  `Hydrabad` spelling is corrected to Hyderabad.

## 3. Natural Earth 10m (river names, forge3d cities)

- **What:** `ne_10m_rivers_lake_centerlines` (named river centrelines) and
  `ne_10m_populated_places`.
- **Files:** `rivers.zip`, `places.zip` from `https://naciscdn.org/naturalearth/10m/`.
- **Pages:** https://www.naturalearthdata.com ·
  terms https://www.naturalearthdata.com/about/terms-of-use/
- **Terms:** public domain.
- **Used for:** naming HydroRIVERS reaches (Godavari, Krishna, Bhima,
  Tungabhadra, Indravati, Wainganga) and as the centreline along which the
  river-bed and flow profiles are sampled; the five populated places feed the
  forge3d viewer's city labels. The web map's cities come from OpenStreetMap
  instead (source 4).
- **Caveat:** 1:10 m centrelines are coarse (hundreds of metres off the
  channel in places), which is why profile sampling takes the 10th-percentile
  elevation within 1.4 km and caps the bed so it never rises downstream.

## 4. OpenStreetMap places via the Overpass API (cities and towns)

- **What:** nodes tagged `place=city` or `place=town` inside the Telangana
  relation (`admin_level=4`), with name and population tags.
- **Query:** `[out:json]; area["name"="Telangana"]["admin_level"="4"]->.a;
  (node["place"~"^(city|town)$"](area.a);); out body;` against
  `https://overpass-api.de/api/interpreter`, cached as `osm_places.json`.
- **Pages:** https://www.openstreetmap.org/copyright ·
  https://wiki.openstreetmap.org/wiki/Overpass_API
- **Terms:** ODbL 1.0; credit “© OpenStreetMap contributors”.
- **Used for:** the 27 web-map cities (all `place=city` nodes except
  Secunderabad, which is part of Hyderabad, and a mistagged node, plus towns
  with population ≥ 40 000). Each city's elevation is the median DSM value
  within 1 km of the node.

## 5. HydroRIVERS v1.0 (river network and average flow)

- **What:** global vectorised river network derived from HydroSHEDS, one
  record per reach with `DIS_AV_CMS` (long-term average *naturalised*
  discharge in m³/s from the WaterGAP model, i.e. before dams and
  withdrawals), `UPLAND_SKM` (upstream catchment area), `ORD_STRA` (Strahler
  order), `DIST_DN_KM` and the reach topology. Lines run upstream → downstream.
- **File:** `HydroRIVERS_v10_as_shp.zip` (Asia, 86 MB) from
  `https://data.hydrosheds.org/file/HydroRIVERS/`, cached as `hydrorivers_as.zip`.
- **Pages:** https://www.hydrosheds.org/products/hydrorivers ·
  licence https://www.hydrosheds.org/page/license
- **Terms:** HydroSHEDS licence, free for scientific, educational and
  commercial use with attribution. Cite: Lehner B., Grill G. (2013) *Global
  river hydrography and network routing: baseline data and new approaches to
  study the world's large river systems.* Hydrological Processes 27(15):
  2171–2186.
- **Used for:** the animated flow network (6 912 reaches ≥ 1 m³/s around
  Telangana), stream hover popups, peak-flow markers, the per-district average
  flow of the Godavari and Krishna, the flow profile chart and the bubbles.
- **Processing:** reaches are named by matching both ends to a Natural Earth
  named river within 4 km (main stems also need Strahler order ≥ 6); district
  averages are length-weighted means of the named main stem inside each
  district; profile flow is the nearest named reach within 6 km, forced
  non-decreasing downstream.

## 6. Wikipedia (dams and barrages)

- **What:** wikitext of
  https://en.wikipedia.org/wiki/List_of_dams_and_reservoirs_in_Telangana and
  of every page it links to, plus the border dams and Kaleshwaram barrages the
  list does not link (Srisailam Dam, Pulichinthala Project, Nagarjuna Sagar
  Dam, Jurala Project, Nizam Sagar Dam, Lakshmi Barrage, Saraswati Barrage,
  Sammakka Sagar Barrage, Mid Manair Dam, Koil Sagar, Taliperu Project,
  Sripada Yellampalli Project, Sitamma Sagar Barrage). Fetched through the
  MediaWiki API (`action=query&prop=revisions`), cached as `wikipedia_dams.json`.
- **Terms:** text under CC BY-SA 4.0 (https://en.wikipedia.org/wiki/Wikipedia:Copyrights);
  facts and figures are reused with a link to each article.
- **Used for:** the 22 dam and barrage markers: coordinates (`{{coord}}`),
  name, river (`dam_crosses`), height (`dam_height`, or
  `dam_height_foundation` when that is all the page gives) and kind.
- **Rules:** only pages with an `Infobox dam` and coordinates within 15 km of
  the state; pages whose infobox status is proposed or under construction
  (NRLD codes `P`, `UC`) are dropped; kind is “barrage” when the name says
  barrage or anicut, plus Sripada Yellampalli by explicit override, because
  the infobox type codes proved unreliable.
- **Caveats:** heights are as stated by each article and are not all measured
  the same way; Nizam Sagar's 95.72 m could not be confirmed from an official
  source. Medigadda, Saraswati (Annaram) and Parvati (Sundilla) barrages have
  no height on Wikipedia.

## 7. Landmark heights (elevation comparison)

Hard-coded in `web/app.js` (`LANDMARKS`), checked on 2026-10-22:

| Landmark | Height | Source |
|---|---|---|
| Gateway of India, Mumbai | 26 m | https://en.wikipedia.org/wiki/Gateway_of_India |
| Charminar, Hyderabad | 56 m | https://en.wikipedia.org/wiki/Charminar |
| Qutub Minar, Delhi | 72.5 m (shown as 73) | https://www.worldhistory.org/image/22160/the-qutb-minar/ |
| Statue of Unity, Gujarat | 182 m, statue without base | https://en.wikipedia.org/wiki/Statue_of_Unity |

## Derived files

| Output | Built by | From |
|---|---|---|
| `data/telangana_dem.tif`, `telangana_dem_clipped.tif`, `telangana_viewer_dem.tif` | `prepare_data.py` | 1, 2 |
| `data/state.geojson`, `districts.geojson`, `rivers.geojson`, `cities.geojson` | `prepare_data.py` | 2, 3 |
| `data/overlay.png` (forge3d map colours and lines) | `make_overlay.py` | 1, 2, 3 |
| `web/tiles/{z}/{x}/{y}.png` (1 251 Terrarium tiles) | `build_web_data.py` | 1 |
| `web/data/state.geojson`, `districts.geojson`, `district_points.geojson`, `mask.geojson` | `build_web_data.py` | 2 |
| `web/data/rivers.geojson`, `contours.geojson` | `build_web_data.py` | 3, 1 |
| `web/data/cities.json` | `build_web_data.py` | 4, 1, 2 |
| `web/data/rivers.json` (bed and flow profiles) | `build_web_data.py` | 3, 1, 5 |
| `web/data/flow.geojson`, `flow_summary.json` | `build_web_data.py` | 5, 3, 2 |
| `web/data/dams.json` | `build_web_data.py` | 6 |
| `out/telangana_block.png` | `block.py` | 1, 2 |

## Software

| Component | Version | Licence | Role |
|---|---|---|---|
| MapLibre GL JS | 5.12.0 (unpkg CDN) | BSD-3-Clause | web map rendering, 3D terrain |
| forge3d | 1.44.0 | Apache-2.0 OR MIT | native viewer and path-traced block |
| rasterio / GDAL | 1.5.2 | BSD-3 / MIT | raster mosaic, reprojection, tiles |
| geopandas, shapely, pyogrio, pyproj | 1.2.0, 2.2.0, 0.13.0, 3.8.0 | BSD / MIT | vector processing |
| numpy, scipy, contourpy, matplotlib, Pillow | 2.5.4, 1.18.1, 1.4.0, 3.11.2, 13.0.0 | BSD / HPND | arrays, smoothing, contours, images |
| requests | 2.34.2 | Apache-2.0 | downloads |
| Playwright (dev) | 1.64.1 | Apache-2.0 | headless smoke test |
| Inter, JetBrains Mono (Google Fonts CDN) | — | SIL OFL 1.1 | web typography |

Exact versions of every Python dependency are pinned in `uv.lock`.

## Attribution line used in the web map

“Copernicus DEM (ESA) · HydroRIVERS (HydroSHEDS, Lehner & Grill 2013) ·
geoBoundaries · Natural Earth · © OpenStreetMap contributors”, plus a link to
Wikipedia on each dam marker.

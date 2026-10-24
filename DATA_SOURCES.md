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
- **Used for:** the dam and barrage markers: coordinates (`{{coord}}`),
  name, river (`dam_crosses`), height (`dam_height`, or
  `dam_height_foundation` when that is all the page gives), years
  (`construction_began`, `opening`), gross capacity (`res_capacity_total`,
  converted to tmcft from m³, Mm³ or km³ where needed) and kind. The popup's
  "average inflow" is the HydroRIVERS reach (source 5) within 3 km of the dam.
- **Rules:** only pages with an `Infobox dam` and coordinates within 15 km of
  the state; pages whose infobox status is proposed or under construction
  (NRLD codes `P`, `UC`) are dropped; kind is “barrage” when the name says
  barrage or anicut, plus Sripada Yellampalli by explicit override, because
  the infobox type codes proved unreliable.
- **Caveats:** heights are as stated by each article and are not all measured
  the same way; Nizam Sagar's 95.72 m could not be confirmed from an official
  source. Medigadda, Saraswati (Annaram) and Parvati (Sundilla) barrages have
  no height on Wikipedia.

## 6b. OpenStreetMap dams of the Kaleshwaram reservoirs

- **What:** `waterway=dam` / `water=reservoir` features named Mallanna Sagar,
  Konda Pochamma Sagar and Ranganayaka Sagar, which have no Wikipedia page
  of their own. Fetched through Overpass (query in `fetch_data.py`), cached as
  `osm_reservoirs.json`. Terms as in source 4 (ODbL).
- **Hand-checked facts** (`OSM_RESERVOIRS` in `build_web_data.py`):
  construction start 2016 = start of the Kaleshwaram project
  (https://en.wikipedia.org/wiki/Kaleshwaram_Lift_Irrigation_Project);
  Mallanna Sagar inaugurated February 2022 (same article; 50 tmcft);
  Konda Pochamma Sagar inaugurated 29 May 2020
  (https://www.thenewsminute.com/telangana/kondapochamma-reservoir-under-kaleshwaram-project-inaugurated-telangana-125526;
  15 tmcft); Ranganayaka Sagar first filled April 2020
  (https://etvbharat.com/english/state/telangana/godavari-project-brings-cheer-to-telangana-amid-gloom/na20200425191409541;
  about 3.5 tmcft), no formal inauguration date found. Capacities are from the
  Kaleshwaram article's reservoir table.
- **Not included:** the smaller Kaleshwaram "online storages" (Medaram,
  Ananthagiri, Malkapet, Amarlabanda, Katchapur, Thimmakka Palli, Issaipet,
  Bhoompally, Gujjal, Katewadi, Mothe, Kondem Cheruvu, Gandamalla, Baswapuram)
  have no coordinates in Wikipedia, Wikidata or OSM at the time of writing.

## 6c. Water links, pump houses and intakes

- **Edges** (`LINKS` in `build_web_data.py`), each with years *planned /
  construction began / first water / complete* where a source gives them:
  - *Kaleshwaram* — the "Links" section of
    https://en.wikipedia.org/wiki/Kaleshwaram_Lift_Irrigation_Project (Link I
    Medigadda → Annaram → Sundilla → Yellampalli with three lifts, 2016–2019;
    Link II Yellampalli → Mid Manair, water reached Mid Manair in November
    2019 per https://www.pressreader.com/india/deccan-chronicle/20191113/281749861177429;
    Link III; Link VI; Link VII). Link IV is taken as Mid Manair → Annapurna →
    Ranganayaka Sagar → Mallanna Sagar → Konda Pochamma Sagar after the Union
    government's reply to Parliament (https://cwc.gov.in/sites/default/files/reply_70.pdf)
    and Deccan Chronicle's pumping sequence
    (https://www.deccanchronicle.com/amp/southern-states/telangana/intermittent-power-hits-pumping-irrigation-department-1898970);
    the Wikipedia list's "upper Manair" start is treated as an error. "Planned
    2016" is the year the Pranahita–Chevella scheme was redesigned as
    Kaleshwaram; its construction start is the infobox `construction_began`.
  - *Sriram Sagar canals* — the SRSP flood-flow canal (Mid Manair infobox
    `dam_crosses`) and the Kakatiya canal to Lower Manair Dam
    (https://en.wikipedia.org/wiki/Lower_Manair_Dam: "balancing reservoir for
    the Kakatiya Canal"; years from the SRSP and LMD infoboxes).
  - *Srisailam Left Bank Canal* — Nagarjuna Sagar foreshore → Puttamgandi pump
    house (coordinates and "completed by 2004" from
    https://en.wikipedia.org/wiki/Srisailam_Left_Bank_Canal). The Akkampalli
    reservoir it feeds has no published coordinates.
  - *Kalwakurthy* — Srisailam backwaters → Yellur intake (infobox coordinates
    of https://en.wikipedia.org/wiki/Mahatma_Gandhi_Kalwakurthy_lift_irrigation_scheme,
    construction 1984, opened 2017) → Singotam reservoir (Wikidata Q62033088).
    Stage II to Jonnalaboguda and Stage III to Gudipally (National Green
    Tribunal order, https://www.greentribunal.gov.in/sites/default/files/news_updates/3217120_0.pdf)
    have no published coordinates.
  - *Palamuru-Rangareddy* — Jurala foreshore → Yellur-Narlapur pump house
    (infobox coordinates of https://en.wikipedia.org/wiki/Palamuru-Rangareddy_Lift_Irrigation_Scheme,
    foundation 2015, first phase started 16 September 2023; 104 m lift per
    https://thesouthfirst.com/telangana/palamuru-rangareddy-lift-irrigation-scheme-in-telangana-gets-new-deadline-december-2027/).
    Narlapur, Yedula, Vattem, Karvena, Udandapur and KP Laxmidevipally
    reservoirs have no published coordinates.
  - *Not drawn for lack of coordinates:* Devadula (intake, Dharmasagar,
    Ghanpur), Sitarama, Dindi and Koil Sagar lift schemes.
- **Status** (operating / in progress) reflects those sources as of
  2026-10-24 and is not an official schedule.
- **Geometry is schematic:** curves drawn between the structures' coordinates
  (through the pump house where one is known). Real canal, tunnel and
  pressure-main alignments are not available as open data. The popup's
  distance is the straight line between the structures, and its terrain
  heights are the Copernicus DEM (source 1) at each structure, not water
  levels.
- **Pump houses:** OpenStreetMap `man_made=pumping_station` features named
  Medigadda, Annaram and Sundilla (alt names Lakshmi, Saraswathi, Parvathi),
  with their `power:input` and `start_date` tags; cached as
  `osm_pumphouses.json`. Terms as in source 4 (ODbL). Other Kaleshwaram pump
  houses (Nandi, Gayatri, Markook …) are not mapped there yet. The Puttamgandi,
  Yellur and Narlapur intakes come from the Wikipedia pages above.
- **Wikidata** (https://query.wikidata.org, CC0): dams within 76.9–81.6 °E,
  15.4–20.0 °N with coordinates, cached as `wikidata_dams.csv`; used for the
  Singotam reservoir.

## 6f. Canals (OpenStreetMap)

- **What:** every `waterway=canal` way inside the Telangana relation
  (1,582 ways, ≈5,900 km; `osm_canals.json`), plus `waterway=pressurised`
  and water `man_made=pipeline` ways (253 ways, ≈490 km; `osm_waterpipes.json`),
  all with geometry, downloaded 2026-10-24 through Overpass. Terms as in
  source 4 (ODbL). Kinds drawn: *canal*; *canal tunnel* (`tunnel=yes|flooded`
  or `location=underground` on a canal, road culverts excluded); *pressurised
  tunnel or pipe* (`waterway=pressurised`, which is how OSM mappers drew the
  Kaleshwaram tunnels and pressure mains).
- **Direction:** OSM draws waterways in the direction of flow; ways tagged
  `flow_direction=backward` are reversed, `both` would be shown without
  moving dashes (none in this extract).
- **Era:** OSM holds no construction dates for these canals, so the project
  decides: `construction=yes` ways are the Sitarama lift scheme's canal works
  in Khammam and Bhadradri (sanctioned 2016; they include extensions of the
  older Sathupally, Palavagu and NTR canals) → *after 2014*; real tunnels
  (`tunnel=yes|flooded`, `location=underground`, not road culverts) within
  20 km of a Kaleshwaram link → *after 2014* (Kaleshwaram, 2016–);
  pressurised ways within that corridor → *after 2014* (Kaleshwaram pressure
  mains and tunnels, ≈300 km mapped); names mentioning Kaleshwaram, Link-I,
  Palamuru, Sitarama or the new reservoirs → *after 2014*; names of older
  projects (Nagarjuna Sagar, SRSP Kakatiya and flood-flow canals, Nizam
  Sagar, Jurala, Manair, Mula Vagu, Ali Sagar, Kurnool–Cuddapah …) →
  *before 2014*; the remaining mostly unnamed distributaries, the Jurala-area
  tunnels and the pressurised ways near Devadula (a 2004– project) →
  *unknown*.
- **Caveats:** OSM coverage of canals is incomplete and uneven (the
  Kaleshwaram gravity canals in particular are only partly mapped), so the
  layer shows what volunteers have drawn, not the full network; the
  `construction` tags reflect the state of the map, not today's progress.

## 6g. Kaleshwaram canal network figures (Water links panel table)

- **Planned lengths** 1,531 km gravity canals, 203 km tunnels, 98 km
  pressure/delivery mains (1,832 km): Telangana Irrigation Department
  project description, https://irrigation.telangana.gov.in/ (also quoted on
  the Wikipedia project page).
- **Completed lengths as of March 2022** — main canals 897 km of 1,566.04 km
  (57 %), distributary canals 690.18 km of 9,564.35 km (7 %): CAG Performance
  Audit of the Kaleshwaram Lift Irrigation Project, Report No. 1 of 2024
  (tabled 15 February 2024), Chapter V "Execution",
  https://cag.gov.in/en/audit-report/details/119583 (chapter PDF:
  https://cag.gov.in/uploads/download_audit_report/2024/08_Chapter-V_Execution-of-Kaleshwaram-Project-065cdab5633b085.36569039.pdf).
  The chapter PDF could not be re-downloaded on 2026-10-24 (HTTP 404 from the
  CAG site), so these two rows were taken from the user's transcription of
  the audit and should be re-checked against the report.
- **Caveats:** an audited historical snapshot, not a 2026 completion total;
  "completed" excavation does not mean a canal is lined, operational or
  connected to fields; the CAG planned total (1,566 km of main canals) differs
  slightly from the department's 1,531 km because the two documents cut the
  network differently.

## 6d. Cropland cover (GLAD global cropland extent)

- **What:** percent of each 3 km (0.025°) cell under crops, one layer per
  four-year epoch (2000–03, 2004–07, 2008–11, 2012–15, 2016–19), summarised by
  the University of Maryland GLAD lab from their 30 m Landsat cropland maps.
  Cropland here means land used for annual and perennial herbaceous crops
  (not plantations, pasture or fallow for more than four years).
- **Files:** `Global_cropland_3km_{2003,2007,2011,2015,2019}.tif` from
  `https://glad.umd.edu/users/Potapov/Global_Crop/Data/` (≈7 MB each), cached
  in `data/raw/cropland/`.
- **Pages:** https://glad.umd.edu/dataset/croplands
- **Terms:** Creative Commons Attribution 4.0. Cite: Potapov P. et al. (2021)
  *Global maps of cropland extent and change show accelerated cropland
  expansion in the twenty-first century.* Nature Food 3, 19–28.
  https://doi.org/10.1038/s43016-021-00429-z
- **Used for:** the "Before 2014" (2008–2011 epoch), "After 2014"
  (2016–2019 epoch) and "Change" rasters, the state and per-district
  statistics in the Cropland panel.
- **Processing:** each epoch is resampled (bilinear) onto a 1 km Web Mercator
  grid over the map extent and drawn as a PNG image source; district and
  state values are the mean cell percentage inside each polygon, and the km²
  figures multiply that by the polygon's Mercator pixel area (true areas are
  within ~6 % at these latitudes). Cells below 5 % and changes below 5
  percentage points are left transparent.
- **Caveats:** the 2012–2015 epoch straddles the 2014 state formation, so the
  comparison uses the epochs either side of it. Cropland extent is not the
  same as irrigated area, and the increase has several causes (irrigation
  projects, groundwater recovery, rainfall, tank restoration), which the data
  cannot separate.

## 6e. Official irrigation and cropping figures (Cropland panel table)

- Gross irrigated area 62.48 lakh acres (2014-15) → 135 lakh acres (2021-22):
  Telangana Socio Economic Outlook 2023, as hosted by NITI Aayog,
  https://www.nitiforstates.gov.in/public-assets/Policy/policy_files/RSSNAM000500.pdf
- Paddy sown in kharif 22.74 lakh acres (2014) → 64.99 lakh acres (2022), and
  gross cropped area 129.04 → 232.58 lakh acres (2014-15 → 2022-23): Telangana
  government presentation reported by The News Minute,
  https://thenewsminute.com/telangana/telanganas-irrigated-area-has-increased-what-role-have-irrigation-projects-played
- These are state statistics quoted as published; they were not re-derived.

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

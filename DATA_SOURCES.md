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
  - *Palamuru-Rangareddy* — Srisailam backwaters → Yellur-Narlapur pump house
    (foundation 2015, first phase started 16 September 2023; 104 m lift per
    https://thesouthfirst.com/telangana/palamuru-rangareddy-lift-irrigation-scheme-in-telangana-gets-new-deadline-december-2027/).
    The infobox coordinates of https://en.wikipedia.org/wiki/Palamuru-Rangareddy_Lift_Irrigation_Scheme
    (15.96 °N 78.15 °E) fall in Andhra Pradesh, south of the Krishna, so the
    pump house is placed at OpenStreetMap's Narlapur substation in Kollapur
    mandal (flagged approximate). The later stages are in section 6h.
  - *Sitarama, Dindi, Devadula and the SLBC tunnel* — see section 6h; Koil
    Sagar still has no coordinates.
- **Status** (operating / under construction / planned) reflects those sources
  as of 2026-10-24 and is not an official schedule.
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

## 6h. Works still under construction or only proposed ("Still to be built")

Every structure and link carries a `status`: *operational*, *under
construction* or *proposed* (links: *operational*, *in progress*, *planned*).
The Status filter and the "Still to be built" list use it. Statuses are what
the sources below reported up to 2026-10-24; they change often and are not an
official schedule. A `target` is the completion year the government last
announced, not a forecast.

- **Wikipedia dam infoboxes** (section 6): pages whose `status` is `P`
  (proposed) or `UC` (under construction) are no longer dropped. `P` →
  proposed; `UC` without an opening year → under construction; `UC` with an
  opening year → operational (Sadarmat Barrage, impounded 2021; Sammakka
  Sagar, impounding since June 2021). Lower Jurala Hydro Electric Project is
  excluded (a power station, all units commissioned 2013–2016). Janampet
  Barrage is kept as *proposed (shelved)*: its own article says the barrage
  "was proposed" for the Dummugudem link that the Sitarama scheme replaced.
  Scheme names, planned years and notes for these pages are hand-entered
  (`PENDING_FACTS`) from the article text and:
  - Tummidihetti: https://en.wikipedia.org/wiki/Pranahita_Chevella_Lift_Irrigation_Project
    (2008 start of the scheme, 148 m FRL agreement of 2016);
    https://www.newkerala.com/news/a/telangana-cm-revanth-reddy-urges-centre-expedite-approvals-590.htm
    (September 2026 request for a 152 m agreement).
  - Icchampally: https://thesouthfirst.com/news/telangana-proposes-inchampalli-godavari-link-as-fair-alternative-to-andhras-polavaram-banakacherla-project
    and https://www.etvbharat.com/en/!state/andhra-pradesh-objects-to-godavari-cauvery-link-flags-use-of-chhattisgarhs-share-enn25082302273
    (August 2025 NWDA meeting; Andhra Pradesh's objection).
  - Sitamma Sagar: https://uniindia.com/t-gana-govt-working-to-resolve-ngt-hurdles-for-seethamma-sagar-barrage-bhatti-vikramarka/south/news/3873771.html
    (NGT clearance and R&R bills pending, June 2026);
    https://deccanchronicle.com/southern-states/telangana/dont-lag-on-sitarama-project-uttam-tells-officials-1826520
    (target of 2026); the L&T contract from the article's infobox.
- **Structures without a usable infobox** (`EXTRA_STRUCTURES`): facts from
  the source given per entry (`url`); coordinates are *approximate* where the
  entry names a place (`approx`): the OpenStreetMap village or tank centre
  from Nominatim (https://nominatim.openstreetmap.org, ODbL) stands in for
  the structure, which is why those markers carry a dotted ring and their
  links omit terrain heights. Overpass area queries timed out all day
  (2026-10-24), so no outlines of these reservoirs could be taken from OSM.
- **OpenStreetMap works under construction** (`osm_construction.json`,
  `OVERPASS_CONSTRUCTION_QUERY` in `fetch_data.py`, ODbL as in source 4): a
  bounding-box query for `construction=dam|reservoir|weir|pumping_station`,
  `waterway=dam|weir` with `construction`, and every
  `man_made=pumping_station` around the state (36 features, fetched
  2026-10-24). It supplies, at surveyed positions: the four Sitarama pump
  houses ("Pump house - 1" … "Pump House - 4", the last tagged
  `landuse=construction`, note "SRLIP - Package no. 11"), drawn as a lift
  chain from the Sitamma Sagar barrage and all marked under construction
  because the scheme has delivered no water; and the *Maikapet Reservoir*
  (`construction=reservoir`, Kamareddy district), whose scheme and capacity no
  source names. Nettempadu and Koilsagar stage pump houses are in the file but
  not drawn (operating schemes without links); the unnamed Kaleshwaram pump
  houses in it cannot be matched to names.
  - *Baswapur reservoir* (11.39 TMC per the Kaleshwaram DPR as quoted in a
    CWC RTI reply, https://cwc.gov.in/sites/default/files/reply-rti-shri-srinivas-rao-cwcnd-00108-2.pdf;
    R&R not started per the CAG's 2024 report,
    https://cag.gov.in/uploads/download_audit_report/2024/08_Chapter-V_Execution-of-Kaleshwaram-Project-065cdab5633b085.36569039.pdf).
    Position: Baswapur tank, Bhongir mandal.
  - *Annapurna (Anantha Sagar) reservoir*, 3.5 TMC, Link IV, operating
    (Kaleshwaram article). Position: Ananthasagar village, from the
    coordinates of https://en.wikipedia.org/wiki/Saraswathi_Kshetramu,_Ananthasagar.
  - *Palamuru-Rangareddy stages* — Veeranjaneya (Yedula, 6.5 TMC, Stage II
    cavern pump house with 10 × 145 MW), Venkatadri (Vattem, Stage III),
    Kurumurthy Raya (Karvena, Stage IV), the 3.7 km twin tunnel Narlapur →
    Yedula and the 10 km tunnel Yedula → Vattem, the December 2027 target,
    the Udandapur (June 2027) and KP Laxmidevipalli timing:
    https://thesouthfirst.com/news/palamuru-rangareddy-lift-irrigation-scheme-in-telangana-gets-new-deadline-december-2027
    (2 May 2025), https://www.varksengineers.com/projects/palamuru-rangareddy-package-7,
    https://telanganatoday.com/ground-reality-contradicts-telangana-governments-prlis-completion-claims
    (2026) and https://www.siasat.com/telangana-uttam-sets-20-month-target-for-palamuru-project-3426924/.
    Positions: the Yedula, Vattem and Karivena villages.
  - *Dindi reservoir* (existing, 59 million m³ ≈ 2.08 TMC,
    https://en.wikipedia.org/wiki/R._Vidyasagar_Rao_Dindi_Lift_Irrigation_Scheme;
    coordinates Wikidata Q62033240) and the *Dindi head reach* from Yedula
    (66 km canal, 5.5 km tunnel, nine reservoirs including Nakkalagandi
    7.5 TMC: the Wikipedia list of dams, https://www.varksengineers.com/projects/dindi-lift-irrigation-scheme,
    and https://www.uniindia.com/south-india/politics-telangana-cpi-19ms50/219572
    for "no water yet", 19 October 2026).
  - *SLBC tunnel* (43.9 km, 13.95 km from the inlet and 20.43 km from the
    outlet dug, 9.8 km left, start 2006, February 2025 collapse):
    https://indianinfrastructure.com/2026/07/03/regaining-momentum-srisailam-left-bank-canal-tunnel-project-makes-progress-after-setbacks/
    (3 July 2026); June 2028 target per
    https://www.siasat.com/slbc-tunnel-work-clears-major-hurdle-to-be-complete-by-june-28-3552421/.
    Portals placed at the Domalapenta (Amrabad) and Mannevaripalle (Achampet)
    villages; the 2005 "planned" year is the tunnel contract year quoted in
    https://en.wikipedia.org/wiki/Srisailam_Left_Bank_Canal ("taken up in
    2004 … scheduled for completion in 2010").
  - *Devadula Phase III* (49.06 km tunnel, Devannapet pump house, 7 of 10
    pumps, 2027 target, water to Dharmasagar since May 2025):
    https://thesouthfirst.com/news/devadula-lift-irrigation-project-in-telangana-to-become-fully-operational-by-2027
    and https://www.telangana360.com/2026/07/devadula-lift-irrigation.html
    (secondary). Positions: Devadula village (Kannaigudem mandal) for the
    Gangaram intake and Dharmasagar village for the tank.
  - *Chanaka–Korata barrage* (construction March 2016 per
    https://en.wikipedia.org/wiki/Chanaka-Korata_Barrage; wet run September
    2023 and the unfinished canals per
    https://www.deccanchronicle.com/southern-states/telangana/floods-due-to-incomplete-korata-chanaka-project-damage-crops-in-adilabad-district-1976070,
    August 2026). Position: Korta village, Jainad mandal (the barrage is on
    the Penganga just north of it).
  - *Gouravelli reservoir* (8.23 TMC, raised from 1.41; about 98 % complete):
    https://www.deccanchronicle.com/southern-states/telangana/congress-initiated-project-works-nearly-98-complete-uttam-1992803.
    Position: Gouravelli village, Akkannapet mandal.
- **Works without any published location** (`PENDING_NOTES`, listed in grey
  with no marker): Gandhamalla reservoir (9.87 TMC in the DPR per the CAG,
  1.41 TMC per the contractor https://www.varksengineers.com/projects/kaleshwaram-project-gandhamalla-reservoir),
  the Kaleshwaram distributary network (CAG 2024), Udandapur and KP
  Laxmidevipalli, the Palamuru main canal, the Dindi reservoirs, the Sitarama
  pump houses, the Mukteshwar (Chinna Kaleshwaram) lift
  (https://rsdebate.nic.in/bitstream/123456789/749427/1/PQ_265_22072024_U95_p356_p356.pdf,
  July 2024) and the remaining Kalwakurthy, Nettempadu, Bhima and Koilsagar
  works (March 2027 target, siasat.com above).
- **Canals and tunnels:** OSM's `construction=yes` ways (section 6f, the
  Sitarama canals) are the only canals with a pending status; every other
  mapped canal counts as built. Kaleshwaram's unfinished canal kilometres are
  in the network table (section 6g), not on the map.
- **Not covered:** Modikuntavagu, Nakkalagandi's exact site, the Sammakka
  Sagar and Sitamma Sagar hydro plants, the Lower Penganga dam itself, and
  the Godavari–Cauvery link canal: no coordinates or no reliable status found.

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

## 6i. Tanks (OpenStreetMap) and Mission Kakatiya (Tanks card, "Tanks" control)

- **Tanks on the map:** every `natural=water` way or multipolygon relation and
  every `landuse=reservoir` way in the box 15.8–19.95 N, 77.2–81.4 E, with
  geometry, downloaded 2026-10-24 through Overpass in four bbox tiles (an
  area query for the whole state timed out all day; 17,423 elements,
  `osm_water.json`, kept in the repo because the public servers were at
  capacity for most of the day). Terms as in source 4 (ODbL). River
  channels (`water=river|stream|canal|oxbow|…`, `waterway=riverbank`) are
  dropped; what remains are ponds, lakes, reservoirs and untagged water
  bodies — in Telangana overwhelmingly village tanks (cheruvu, kunta).
  Only those whose representative point lies in a district and whose water
  spread is at least 0.5 ha are kept (about 6,800 bodies lie inside the
  state, some 2,000 of them under 0.5 ha: farm pits, village puddles,
  mapping noise), leaving 4,835;
  a body drawn twice (way and relation, or `natural=water` over
  `landuse=reservoir`, e.g. Yellampalli) is counted once. Water spread =
  polygon area in the map's metric projection. Below zoom 9 each tank is a
  dot whose radius grows with the square root of its area; from zoom 9 the
  real outline is drawn (simplified by ~11 m).
- **Caveat:** OpenStreetMap has mapped only a fraction of Telangana's
  46,531 minor irrigation tanks (4,835 of 0.5 ha or more), unevenly
  across districts, and records neither a construction nor a restoration
  date for them. The layer shows what volunteers have drawn.
- **Mission Kakatiya figures:** Government of India, Ministry of Water
  Resources (PMKSY / AIBP MIS), *Report on Best Practices being followed in
  Water Resources/Irrigation – Mission Kakatiya, Telangana*,
  <https://pmksy.mowr.gov.in/aibp-mis/Manual/Mission%20Kakatiya,%20Telangana.pdf>
  (PDF dated 29 Aug 2018, accessed 2026-10-24; the server presents a
  certificate browsers reject, so it was fetched with verification off).
  It gives the programme's aim (restore all 46,531 minor irrigation sources
  in five years, 20 % a year, ≈₹20,000 crore), the district-wise × phase-wise
  tanks taken up (Phase I 8,043, II 9,015, III 6,152, IV 4,108 sanctioned;
  total 27,318 across 30 districts as of 2016 boundaries), the works
  completed by the report date (Phase I 8,003 for ₹1,568.40 crore, Phase II
  7,060 for ₹1,152.20 crore, Phase III 1,521 for ₹224.57 crore) and the
  ayacut stabilised (6.71 + 3.80 + 1.1 = 11.61 lakh acres). The restoration
  components listed there are desilting, feeder-channel restoration (chain
  of tanks), bund/weir/sluice repair and channel re-sectioning — tanks were
  not connected to rivers or project canals under the programme. The
  programme's launch date (12 March 2015) and the end-state figures quoted
  as such (27,713 tanks completed, ₹8,700 crore) come from Wikipedia,
  <https://en.wikipedia.org/wiki/Mission_Kakatiya> (accessed 2026-10-24);
  the official portal (missionkakatiya.cgg.gov.in), which held the
  tank-level list, no longer resolves.
- **District mapping:** the report uses the 31 districts of 2016 (no
  Hyderabad row). Names are mapped to geoBoundaries: *Badrachalam* →
  Bhadradri, *Jayashankar Bhupalpally* → Jayashankar, *Yadhadhri Bhongir* →
  Yadadri Bhongiri, *Sircilla* → Rajanna Sircilla, *Medchal (Malkajgiri)* →
  Medchal, *Warangal Urban/Rural* → Warangal (U)/(R), *Komaram Bheem* →
  Komaram Bheem. Mulugu (split from Jayashankar Bhupalpally in 2019) and
  Narayanpet (from Mahabubnagar) have no row; the map shows the parent's
  figure for them and says so.
- **Why no per-tank before/after 2014:** no public dataset lists the
  restored tanks with coordinates (the portal is offline; data.telangana.gov.in
  publishes no such file; the Minor Irrigation Census is not geolocated), so
  the "Restored 2015–18" view shades districts by tanks taken up and labels
  each with its count. It is a district total, not a statement about any
  individual tank.

## 6j. Groundwater levels (India-WRIS) (Groundwater card, "Groundwater" control)

- **What:** depth to water in metres below ground level from the manual monitoring networks of the Central Ground Water Board (CGWB: January, May, August and November readings, 1976–2024) and the Telangana Ground Water Department (monthly piezometer readings, 2007–2023). Source: the India-WRIS "Ground Water Level" export as mirrored by the India Data Portal (CKAN resource `06d6e79c-61ac-46bb-9e03-c7138911c619`, May 2025 export, https://ckandev.indiadataportal.com/dataset/groundwater-level). The WRIS portal itself (https://indiawris.gov.in/wris/#/groundWater) only serves a browser app and could not be reached from the build machine; the Telangana department's own site (gwd.telangana.gov.in) could not be reached either. `fetch_data.py` pulls every reading of the two agencies inside the box 15.8–19.95 N / 77.2–81.4 E through the mirror's SQL endpoint, 30,000 rows a page: 188,132 readings from 2,793 stations into `data/raw/gw_levels.csv.gz` (1 MB, committed).
- **Processing** (`build_groundwater` in `build_web_data.py`): readings of exactly 0 are dropped, because the state network writes 0 for a missing reading (two thirds of its rows before 2015), as are the two readings above 100 m; stations are assigned to geoBoundaries districts by location; readings dated May are the pre-monsoon season. "Before 2014" is the mean of a well's May readings of 2010–14, "After 2014" the mean of May 2015–23, each needing at least two seasons; change = before − after, so a positive number means the water table rose. 1,605 wells inside the state have at least one window (945 CGWB, 660 state department), 748 have both. The year-by-year state curve averages each well's deviation from its own long-run mean over the 563 wells with ten or more May readings, so the growth of the network (about 500 CGWB wells in 2010, 1,000 from 2014) does not masquerade as a change in level. The export has no statewide May survey in 2020 and 2021, and the state network's readings end in 2019.
- **Result:** the 748 paired wells stood 11.0 m below ground in May 2010–14 and 12.5 m in May 2015–23, a median change of −0.9 m, with 217 wells rising. The curve shows why: pre-monsoon levels were deepest in May 2016 (14.9 m) and May 2019 (14.6 m), in and after the 2015–18 drought years, and recovered to about 9.0 m in May 2022 and 2023 after the very wet 2020–22 monsoons, close to the May 2014 level (9.6 m). The government's reported rise of "more than 4 metres" (Dynamic Ground Water Resources of Telangana 2023, Deccan Chronicle, 1 October 2023) compares 2013 with 2023 and uses the state's 1,771-piezometer network, which is not in the public export after 2019; it is quoted in the card as a claim, not reproduced.
- **Limits:** a well mean over two to nine seasons is noisy, and a district figure is the mean of its paired wells, from 7 in Narayanpet and Wanaparthy to 52 in Rangareddy. CGWB dug wells and state-department bore wells tap different depths, so levels differ between agencies and districts for reasons other than recharge. Levels follow the monsoon far more than any project; the map shows change, not cause. The CGWB Ground Water Year Books for Telangana (2014-15, 2020-21, 2023-24, https://cgwb.gov.in/cgwbpnm/publications) were used to check magnitudes; they publish district ranges and percentages, not means.

## 6k. Land cover (ESA WorldCover 2021)

- **What:** ESA WorldCover 2021 v200, 10 m global land cover in eleven classes (tree cover, shrubland, grassland, cropland, built-up, bare, snow, water, wetland, mangrove, moss), CC BY 4.0, Zanaga et al. 2022, https://esa-worldcover.org/. `fetch_data.py` reads the 1/32 overview (320 m) of the six 3° cloud-optimised tiles around Telangana straight from the public bucket (`https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/`) and writes one small mosaic, `data/raw/worldcover_320m.tif` (0.9 MB, committed).
- **Used for:** the proposal model's definition of cultivable land and of land already cropped (section 8). It is not used for the Cropland card, which keeps the GLAD epochs so that "before and after 2014" is like-for-like.
- **Note:** WorldCover 2021 puts 64.4 % of Telangana under cropland against GLAD's 54.8 % for 2016–19; the two products define cropland differently (WorldCover maps any cultivated field, GLAD the share of a 3 km cell under annual crops) and the years differ. The Proposal card uses WorldCover throughout, so its percentages are internally consistent but not comparable with the Cropland card's.

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

## 8. Proposal model (Proposal card, "Show proposal" control)

- **What it is:** a planning sketch, not a design. `propose_water.py` computes, from the data already on the map, what it would take to put 90 % of the state's cultivable land under assured irrigation from river water: where new reservoirs could be built, where districts have no usable dam site and need water lifted in, which river intake or existing reservoir should feed each, how many pump stages, how much tunnel and canal, what land gravity could then serve, and an indicative cost. It is turned on with the "Show proposal" control in the Filters card and explained in the Proposal card. Every number comes out of the norms below; none has been checked by a survey or a hydrological study.
- **Inputs:** the 200 m terrain model (section 1), HydroRIVERS mean flows (section 5), WorldCover land cover (6k), the dams, barrages and reservoirs on the map (6, 6g) with their terrain heights, OSM towns (4), and the geoBoundaries districts (2).
- **Land and water need:** cultivable = WorldCover crop, grass, shrub and bare classes on slopes up to 15 % (76.6 % of the state); cropland now = WorldCover cropland (64.4 %, i.e. 84.1 % of cultivable, so 80 % is already met). Target 90 % of cultivable adds 14.8 lakh acres. Water need = new acres / 10,000 per TMC + 42 % of existing cropland (the rainfed share: gross irrigated 135 of 233 lakh acres gross cropped, official) / 20,000 per TMC → 534 TMC a year (148 new, 385 stabilisation). At 85 % the need would be 455 TMC.
- **Reservoir siting:** every HydroRIVERS reach of Strahler order 4 or more with 3 m³/s or more inside the state is tried at 5 km intervals with dams of 20, 30 and 40 m; a dam line is scanned across the valley until the ground reaches the crest, the pool is the connected DEM area below crest behind it. A site is rejected when the dam would exceed 16 km, the pool leaks past a 30 km window, the river bed is below 100 m (the Godavari trough), the pool drowns a town or more than 3 % built-up land, or takes more than 2.5 km² of farmland per TMC. Of 788 sites × 3 heights, 94 pools pass. Each district gets the cheapest storage within 20 km of its boundary, at least 15 km apart, until storage reaches 0.6 × its annual need; 10 reservoirs (146 TMC) result. Districts that still lack water (25) get a "lift delivery": water pumped to a point at the 80th-percentile elevation of their cultivable land, with balancing storage priced in.
- **Sources of water:** Godavari and Krishna barrages and dams on the map (Medigadda, Sammakka Sagar, Sitamma Sagar, Yellampalli, Sriram Sagar; Jurala, Srisailam, Nagarjuna Sagar, Pulichintala) and reservoirs that built or under-construction lift schemes fill (Kaleshwaram's Parvati and Saraswati barrages, Mid Manair, Lower Manair, Mallanna Sagar, Konda Pochamma, Ranganayaka Sagar, Baswapur, Annapurna, Singur and Nizam Sagar; Palamuru's Yedula, Vattem and Karvena; Dindi). Water routed through such a hub is debited to its river intake and pays that scheme's lift as extra pumping. An intake may newly give up to 25 % of the mean flow HydroRIVERS puts past it (Kaleshwaram takes about 11 % at Medigadda); the Krishna total is capped at the headroom of the state's 2025 request.
- **Conveyance:** straight-line route from source to work; lift = full level − source level + 15 m friction; ground more than 25 m above the water level is tunnelled, the rest is canal at 1.4 × the straight length; pump stages of at most 120 m (Kaleshwaram's stages are 100–120 m), each placed where the ground next rises above the previous stage's level; pumps sized for a 120-day monsoon season at 75 % efficiency. Gravity command = cultivable land within 45 km and at least 10 m below a reservoir's or delivery point's level; the rest of a district needs pressurised or lift distribution.
- **Costs (₹ crore, indicative):** 100 per TMC of storage + 1.2 per km·m of embankment + 0.6 per hectare submerged; pumps 8 per MW; tunnel 110 per km; canal 20 per km; distribution 150 per TMC a year (₹1.5 lakh an acre); power ₹6 a unit. Calibration: Kaleshwaram ₹80,190 crore for 225 TMC a year (Wikipedia infobox; the 2017 EIA summary at https://mpcb.gov.in/sites/default/files/public_hearing/exe_summary/2019-07/Kaleshwaram_Project_Executive_Summary_English18092017.pdf gives 225 TMC, 180 from the Godavari), Palamuru-Rangareddy ₹35,000 crore for 90 TMC, Sammakka Sagar barrage ₹2,121 crore, Kalwakurthy ₹2,100 crore for 25 TMC (all Wikipedia infoboxes, cached in `data/raw/wikipedia_dams.json`). The model comes out at about ₹420 crore per TMC a year, in Kaleshwaram's range.
- **Result of the 24 October 2026 run:** 10 reservoirs and 25 lift deliveries supplying 531 TMC a year (99.5 % of the need), 53 pump houses, 3,347 MW, 216 km of tunnel, 2,608 km of canal, about ₹2.22 lakh crore to build (storage 0.40, conveyance 1.03, distribution 0.80 lakh crore) and ₹5,800 crore of power a year. Godavari draw 342 TMC, Krishna 189 TMC.
- **Water budget it is set against:** Godavari share 967.94 TMC, of which 758.76 cleared by the CWC, 148.82 cleared for availability and 60.26 reserve (Chief Minister's letter, September 2021, https://www.etvbharat.com/english/state/telangana/drop-telangana-irrigation-projects-from-unapproved-list-kcr/na20210907073309773); Krishna 299 TMC interim share against Andhra Pradesh's 512, pending the second tribunal (https://www.theweek.in/wire-updates/national/2025/07/14/mes38-tl-govt-river-waters.html); the state's June 2025 request to the Centre for 1,000 + 500 TMC (https://www.siasat.com/telangana-seeks-centres-nod-for-1500-tmc-of-godavari-krishna-water-3235979/). The Godavari draw exceeds even the 1,000 TMC asked for by 249 TMC: HydroRIVERS puts the mean flow leaving the state at about 3,670 TMC a year, so the water exists in the monsoon, but using it needs a new inter-state award and flood-season capture.
- **Not modelled:** evaporation and seepage, sediment, environmental flows and downstream rights, real canal alignments and land acquisition along them, land that pressurised networks could serve above the gravity command, groundwater as a conjunctive source, crop choice, phasing, and the operating cost of anything but power. The 200 m DEM smooths valleys, so pool volumes are rough and small dams are missed; towns come from OSM's city/town nodes only, so villages in a pool are not counted.
- **Outputs:** `web/data/proposal.json` (norms, demand per district, water budget, works with their pumps, totals, gravity coverage per district) and `web/data/proposal.geojson` (pools, canal and tunnel segments, pump houses, delivery points, gravity command areas). Rebuild with `uv run python propose_water.py` after `build_web_data.py`.

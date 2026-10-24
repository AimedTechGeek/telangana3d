# Sources tried and failed

Every legitimate website or API this project tried to reach between 22 and
24 October 2026 that answered with an error or no connection at all, grouped
by topic. Each entry says what the source should have supplied, what came
back, and what the map uses instead. Sources that worked are documented in
`DATA_SOURCES.md`.

How to read the error column:

- **HTTP 000** – `curl` on the build machine (Windows PC on a corporate
  network) never got a connection: DNS or TCP blocked, no HTTP answer.
- **EAI_AGAIN** – temporary DNS failure; **ENOTFOUND** – the host name no
  longer exists in DNS. Both came from the fetch service (Claude Code's
  WebFetch, which runs outside the build machine), so they are not a
  local-network problem.
- **502 / 504** – the server answered but was overloaded (bad gateway /
  gateway time-out); **401 / 403 / 404** – answered but refused or missing.
- **certificate rejected** – the server's TLS certificate is not trusted by
  browsers or Python; data could be pulled only with verification switched
  off (`curl -k`) and is marked as such.

Status: **open** = never obtained, the map says so; **worked around** =
obtained from another source or by another route; **resolved** = a retry or
different URL worked.

---

## 1. Telangana state government portals

All `*.telangana.gov.in` hosts failed from both the build machine (HTTP 000)
and the fetch service (DNS EAI_AGAIN), on every attempt over three days.

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://irrigation.telangana.gov.in/ | 24 Oct, fetch service | EAI_AGAIN | Irrigation & CAD department pages on Kaleshwaram, Palamuru-Rangareddy, Sitarama and the pending reservoirs (official project descriptions and status) | **worked around**: Wikipedia infoboxes, CAG audit landing page, CWC replies, news reports; status per work cited in `DATA_SOURCES.md` 6g |
| https://www.telangana.gov.in/mission-kakatiya/ | 24 Oct, fetch service (4 attempts) | EAI_AGAIN | State page on Mission Kakatiya: phase counts, spending, completion | **worked around**: Government of India PMKSY report (section 6 below) and Wikipedia |
| https://tweb.telangana.gov.in/initiatives/mission-kakatiya/ | 24 Oct, fetch service | EAI_AGAIN | Same, newer state site | **worked around** as above |
| https://gwd.telangana.gov.in/ and https://gwd.telangana.gov.in/Document/Document_20250814155952025_4889.pdf | 24 Oct, build machine and fetch service | HTTP 000 / EAI_AGAIN | Telangana Ground Water Department: *Status of Ground Water Level Scenario, July 2025* with the district-wise average depth table, and the department's May 2014 vs recent-year comparisons from its 1,771 piezometers | **open**: the state network's own averages are not in the map; the Groundwater card uses the India-WRIS export instead (section 3) and quotes the department's figures only where a news report carries them |
| https://groundwater.telangana.gov.in/ | 24 Oct, build machine | HTTP 000 | Older address of the same department | **open** (same as above) |
| https://data.telangana.gov.in/ | 24 Oct, search only | reachable, but publishes no Mission Kakatiya tank list or groundwater file | Per-tank restoration list with coordinates | **open**: no such public dataset exists; noted in `DATA_SOURCES.md` 6i |

## 2. Mission Kakatiya (tank restoration programme)

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://missionkakatiya.cgg.gov.in/homemission | 24 Oct, fetch service (3 attempts) | ENOTFOUND (domain gone) | The programme's own portal: tank-wise lists by district and phase, progress dashboards | **open**: portal is dead; district × phase counts come from the Government of India report below |
| https://web.archive.org/web/20180413130121/http://missionkakatiya.cgg.gov.in/homemission | 24 Oct, fetch service | "unable to fetch from web.archive.org" (the fetch tool does not serve the Wayback Machine) | Archived copy of the dead portal | **open** |
| https://web.archive.org/web/20180412211814/https://telanganatoday.com/central-team-to-recommend-mission-kakatiya-in-other-states | 24 Oct, fetch service | same | Archived news item on the central team's review | **worked around**: the live Telangana Today page and the PMKSY report |

## 3. Groundwater: India-WRIS and national open-data portals

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://indiawris.gov.in/wris/ (also `#/groundWater`, `#/timeseriesdata`) | 24 Oct, build machine | HTTP 000 | India Water Resources Information System: well-wise groundwater level time series with coordinates (CGWB and state networks); the portal is a browser app and its data API is POST-only, so the fetch service cannot use it either | **worked around**: the India Data Portal's CKAN mirror of the WRIS export (`ckandev.indiadataportal.com`, SQL datastore) supplied 188,132 readings; see `DATA_SOURCES.md` 6j |
| https://arc.indiawris.gov.in/server/rest/services | 24 Oct, build machine | HTTP 000 | WRIS ArcGIS map services (same data as layers) | **worked around** as above |
| https://data.gov.in/ | 24 Oct, build machine | HTTP 000 | Open Government Data platform: CGWB groundwater level datasets | **worked around** as above |
| https://ckandev.indiadataportal.com/api/3/action/datastore_search_sql (telemetric dataset `f78f7b15-f325-4c39-a291-f44ad4e95334`) | 24 Oct, build machine | "Query took too long" on a GROUP BY over the whole table | Daily telemetric (DWLR) piezometer readings, which might extend the state network past 2019 | **open**: only the manual-reading dataset was pulled; bounding-box queries on it worked |

## 4. Groundwater: Central Ground Water Board

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://www.cgwb.gov.in/ and https://www.cgwb.gov.in/cgwbpnm/download/1729 | 24 Oct, build machine | HTTP 000 (the `www.` host) | Ground Water Year Book of Telangana 2023-24 | **resolved**: the same paths without `www.` (https://cgwb.gov.in/cgwbpnm/download/1729) answered 200 and the PDF was downloaded; year books 2014-15 and 2020-21 likewise |

## 5. Irrigation audits and dam registers (CAG, CWC)

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://cag.gov.in/uploads/download_audit_report/2024/08_Chapter-V_Execution-of-Kaleshwaram-Project-065cdab5633b085.36569039.pdf | 24 Oct, fetch service | HTTP 404 Not Found | CAG Performance Audit of Kaleshwaram, Report 1 of 2024, Chapter V: completed canal lengths (897 of 1,566 km main, 690 of 9,564 km distributaries, March 2022) | **open**: the landing page https://cag.gov.in/en/audit-report/details/119583 is reachable and cited, but the two completion rows rest on the user's transcription of the report and should be re-checked when the PDF is back |
| https://cwc.gov.in/sites/default/files/nrld06042019.pdf | 22 Oct, build machine | HTTP 401 (39-byte body) | Central Water Commission, National Register of Large Dams 2019: official dam heights, years and capacities for Telangana | **worked around**: Wikipedia infoboxes and Wikidata for dam heights and years; the CWC's Parliament reply (`reply_70.pdf`) and RTI reply (`reply-rti-shri-srinivas-rao-cwcnd-00108-2.pdf`) on the same host did download |
| https://cwc.gov.in/sites/default/files/nrld-2023.pdf | 22 Oct, build machine | HTTP 401 (39-byte body) | National Register of Large Dams 2023 | **worked around** as above |
| https://web.archive.org/web/20160920223122/http://www.cwc.nic.in/main/downloads/new%20nrld.pdf | 24 Oct, fetch service | "unable to fetch from web.archive.org" | Archived 2016 register | **open** |

## 6. Government of India report server (PMKSY / Ministry of Water Resources)

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://pmksy.mowr.gov.in/aibp-mis/Manual/Mission%20Kakatiya,%20Telangana.pdf | 24 Oct, fetch service and Python `requests` | certificate rejected / `CERTIFICATE_VERIFY_FAILED` | *Report on Best Practices – Mission Kakatiya, Telangana* (29 Aug 2018): district × phase tank counts, phase costs and ayacut | **worked around**: downloaded with `curl -k` (TLS verification off) and read with pypdf; the provenance note in `DATA_SOURCES.md` 6i records this |

## 7. Cropland (GLAD, University of Maryland)

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://glad.umd.edu/dataset/croplands | 24 Oct, fetch service | certificate rejected | Dataset description page for the global cropland extent layers | **resolved** for the data: the GeoTIFFs under https://glad.umd.edu/users/Potapov/Global_Crop/Data/ downloaded normally with Python `requests`; only the description page could not be read through the fetch service, and the method is cited from Potapov et al. 2021 instead |

## 8. OpenStreetMap Overpass API

The public Overpass servers were overloaded for most of 23 and 24 October.
Area queries (`area["name"="Telangana"]`) for the whole state never
completed; bounding-box queries did, after retries.

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://overpass-api.de/api/interpreter | 22–24 Oct, build machine, many attempts | HTTP 502 "at capacity", HTTP 000, `ReadTimeout` after 120 s on area queries, and `CERTIFICATE_VERIFY_FAILED` on three attempts | Canals, water bodies (tanks), reservoirs, pump houses, works under construction | **worked around**: bounding-box queries in up to four tiles with 5 retries and back-off (`fetch_data.py`); the resulting snapshots (`osm_canals.json`, `osm_water.json` 22 MB, `osm_construction.json`, …) are committed so the build does not depend on the server |
| https://overpass.kumi.systems/api/interpreter | 23–24 Oct, build machine | HTTP 000, then HTTP 504 | Mirror of the above | **worked around** as above |
| https://overpass.private.coffee/api/interpreter | 24 Oct, build machine | HTTP 504, `ReadTimeout` after 400 s | Mirror | **worked around** as above |
| https://maps.mail.ru/osm/tools/overpass/api/interpreter | 24 Oct, build machine | HTTP 504 Gateway Time-out | Mirror | **worked around** as above |

## 9. Wikidata SPARQL

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://query.wikidata.org/sparql | 24 Oct, build machine | HTTP 504 Gateway Timeout, then HTTP 500, on one heavy query (UNION over several dam/reservoir classes with coordinates, heights and inception) | Dams and reservoirs around Telangana that have no Wikipedia page | **resolved**: split into three lighter queries (dams, reservoirs, irrigation works), all answered; none of the pending Palamuru or Kaleshwaram reservoirs exist in Wikidata, which is a data gap, not an error |

## 10. GitHub (repository hosting, not a data source)

| URL | Tried | Error | Needed for | Status |
|---|---|---|---|---|
| https://api.github.com/repos/AimedTechGeek/telangana3d/branches/main/protection, `/rulesets`, `/rules/branches/main` | 22 Oct, build machine | HTTP 403: "Resource not accessible by personal access token" and "Upgrade to GitHub Pro or make this repository public to enable this feature" | Checking branch protection on the private repository | **resolved**: branch protection is a paid feature for private repositories on the free plan; nothing to protect against, pushes go to `web-map` |
| `git push` to https://github.com/AimedTechGeek/telangana3d | 22 Oct, build machine | HTTP 403 | Pushing commits | **resolved**: the personal access token lacked repository write permission; the user updated it and pushes have worked since |

---

## Summary of what the map therefore cannot show from primary sources

- Which individual tanks Mission Kakatiya restored (portal dead, no archived
  copy, no state dataset): the map shades districts by counts from a
  Government of India report instead.
- The Telangana Ground Water Department's own district averages and its
  May 2014 versus recent-year comparison (department site unreachable): the
  map uses the India-WRIS well readings mirrored by the India Data Portal,
  which stop in 2019 for the state network and 2023 for CGWB wells.
- The CAG's canal-completion rows re-checked against the chapter PDF (404):
  they are marked as user-transcribed.
- Official dam heights and years from the CWC National Register of Large
  Dams (401): Wikipedia and Wikidata stand in.

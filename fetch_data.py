"""Download raw inputs for the Telangana terrain map into data/raw/.

Sources (all public, no auth):
- Copernicus GLO-90 DEM, 1x1 degree COG tiles on AWS
- geoBoundaries gbOpen India ADM1 (states) and ADM2 (districts)
- Natural Earth 10m rivers, populated places
- OpenStreetMap place=city/town nodes in Telangana (Overpass API)
- HydroRIVERS v1.0 (HydroSHEDS) Asia river network with modelled average discharge
- Wikipedia wikitext of "List of dams and reservoirs in Telangana" and every
  page it links to (dam infoboxes carry height and coordinates)
- OpenStreetMap dams of the Kaleshwaram reservoirs that have no Wikipedia page
- GLAD global cropland extent, 3 km percent-cropland summaries for 2003-2019
- OpenStreetMap canals (waterway=canal) in Telangana with geometry
- OpenStreetMap water bodies (tanks, lakes, reservoirs) in a box around the state, as polygons
- India-WRIS groundwater level readings of the CGWB and Telangana Ground Water Department
  monitoring wells (manual network), via the India Data Portal datastore mirror
- ESA WorldCover 2021 land cover (10 m), read at 320 m from the cloud-optimised tiles
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import time
from pathlib import Path

import requests

RAW = Path(__file__).parent / "data" / "raw"
DEM_DIR = RAW / "dem"
# Tile grid covering Telangana (~15.8-19.95 N, 77.2-81.4 E) with a margin.
LATS = range(15, 20)
LONS = range(77, 82)
DEM_URL = (
    "https://copernicus-dem-90m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM.tif"
)
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/IND/{level}/"
NATURAL_EARTH = {
    "rivers.zip": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_lake_centerlines.zip",
    "places.zip": "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip",
}
HYDRORIVERS_URL = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip"  # ~86 MB
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_HEADERS = {"User-Agent": "telangana3d/1.0 (terrain map)"}
DAM_LIST_PAGE = "List of dams and reservoirs in Telangana"
# Border dams and Kaleshwaram barrages the list page links under other names or not at all.
EXTRA_DAM_PAGES = ["Srisailam Dam", "Pulichinthala Project", "Nagarjuna Sagar Dam", "Jurala Project", "Nizam Sagar Dam",
                   "Lakshmi Barrage", "Saraswati Barrage", "Sammakka Sagar Barrage", "Mid Manair Dam", "Koil Sagar",
                   "Taliperu Project", "Sripada Yellampalli Project", "Sitamma Sagar Barrage"]
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = (
    '[out:json][timeout:90];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(node["place"~"^(city|town)$"](area.a););'
    'out body;'
)
# Kaleshwaram reservoirs that have no Wikipedia page of their own: OSM has their dams.
OVERPASS_RESERVOIRS_QUERY = (
    '[out:json][timeout:90];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(nwr["waterway"="dam"]["name"~"Mallanna Sagar|Konda Pochamma Sagar|Ranganayaka Sagar",i](area.a);'
    'nwr["water"="reservoir"]["name"~"Mallanna Sagar|Konda Pochamma Sagar|Ranganayaka Sagar",i](area.a););'
    'out center tags;'
)
OVERPASS_CANALS_QUERY = (
    '[out:json][timeout:300];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(way["waterway"="canal"](area.a););'
    'out tags geom;'
)
OVERPASS_WATERPIPES_QUERY = (       # pressure mains and tunnels that are not tagged as canals
    '[out:json][timeout:240];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(way["waterway"="pressurised"](area.a);way["man_made"="pipeline"]["substance"="water"](area.a););'
    'out tags geom;'
)
OVERPASS_PUMPHOUSES_QUERY = (
    '[out:json][timeout:90];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(nwr["man_made"="pumping_station"]["name"~"Medigadda|Annaram|Sundilla",i](area.a););'
    'out center tags;'
)
# Water works tagged as under construction, and every pumping station, in a box around the
# state (an area filter made Overpass time out); the Sitarama pump houses come from here.
OVERPASS_CONSTRUCTION_QUERY = (
    '[out:json][timeout:90];'
    '(nwr["construction"~"^(dam|reservoir|weir|pumping_station|water_works)$"](15.6,77.0,19.95,81.6);'
    'nwr["waterway"~"^(dam|weir)$"]["construction"](15.6,77.0,19.95,81.6);'
    'nwr["man_made"="pumping_station"](15.6,77.0,19.95,81.6);'
    'nwr["landuse"="construction"]["construction:landuse"~"reservoir|basin"](15.6,77.0,19.95,81.6););'
    'out center tags;'
)
# Every mapped water body as a polygon. One query for the whole state times out, so the box is
# fetched in four tiles; the public server is often at capacity, hence the retries.
OVERPASS_WATER_TILES = [(15.8, 77.2, 17.9, 79.3), (15.8, 79.3, 17.9, 81.4), (17.9, 77.2, 19.95, 79.3), (17.9, 79.3, 19.95, 81.4)]
OVERPASS_WATER_QUERY = (
    '[out:json][timeout:240];'
    '(way["natural"="water"]({bbox});relation["natural"="water"]({bbox});way["landuse"="reservoir"]({bbox}););'
    'out tags geom;'
)
# Overpass rejects requests without a descriptive User-Agent.
OVERPASS_HEADERS = {"User-Agent": "telangana3d/1.0 (terrain map)", "Accept": "application/json"}
TIMEOUT_S = 120


def download(url: str, target: Path, params: dict | None = None, headers: dict | None = None) -> None:
    if target.exists():
        print(f"cached  {target.name}")
        return
    response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_S)
    response.raise_for_status()
    target.write_bytes(response.content)
    print(f"fetched {target.name} ({len(response.content) / 1e6:.1f} MB)")


def fetch_dem_tiles() -> None:
    DEM_DIR.mkdir(parents=True, exist_ok=True)
    for lat in LATS:
        for lon in LONS:
            download(DEM_URL.format(lat=lat, lon=lon), DEM_DIR / f"N{lat}_E{lon}.tif")


def fetch_boundaries() -> None:
    for level in ("ADM1", "ADM2"):
        meta = requests.get(GEOBOUNDARIES_API.format(level=level), timeout=TIMEOUT_S)
        meta.raise_for_status()
        download(meta.json()["gjDownloadURL"], RAW / f"india_{level.lower()}.geojson")


def fetch_natural_earth() -> None:
    for name, url in NATURAL_EARTH.items():
        download(url, RAW / name)


def fetch_osm_places() -> None:
    download(OVERPASS_URL, RAW / "osm_places.json", params={"data": OVERPASS_QUERY}, headers=OVERPASS_HEADERS)


def fetch_hydrorivers() -> None:
    download(HYDRORIVERS_URL, RAW / "hydrorivers_as.zip")


def wikitext(titles: list[str]) -> dict[str, str | None]:
    """Current wikitext per page title (None when missing); 25 titles per request."""
    pages: dict[str, str | None] = {}
    for start in range(0, len(titles), 25):
        response = requests.get(WIKIPEDIA_API, headers=WIKIPEDIA_HEADERS, timeout=TIMEOUT_S, params={
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "redirects": 1,
            "titles": "|".join(titles[start:start + 25]), "format": "json", "formatversion": 2})
        response.raise_for_status()
        for page in response.json()["query"]["pages"]:
            pages[page["title"]] = None if page.get("missing") else page["revisions"][0]["slots"]["main"]["content"]
    return pages


def fetch_osm_reservoirs() -> None:
    download(OVERPASS_URL, RAW / "osm_reservoirs.json", params={"data": OVERPASS_RESERVOIRS_QUERY}, headers=OVERPASS_HEADERS)
    download(OVERPASS_URL, RAW / "osm_pumphouses.json", params={"data": OVERPASS_PUMPHOUSES_QUERY}, headers=OVERPASS_HEADERS)
    download(OVERPASS_URL, RAW / "osm_construction.json", params={"data": OVERPASS_CONSTRUCTION_QUERY}, headers=OVERPASS_HEADERS)
    # ~1,600 ways with geometry; the public Overpass servers are often busy, so retry on failure.
    download(OVERPASS_URL, RAW / "osm_canals.json", params={"data": OVERPASS_CANALS_QUERY}, headers=OVERPASS_HEADERS)
    download(OVERPASS_URL, RAW / "osm_waterpipes.json", params={"data": OVERPASS_WATERPIPES_QUERY}, headers=OVERPASS_HEADERS)


def fetch_osm_water() -> None:
    target = RAW / "osm_water.json"
    if target.exists():
        print(f"cached  {target.name}")
        return
    elements = []
    for tile in OVERPASS_WATER_TILES:
        query = OVERPASS_WATER_QUERY.format(bbox=",".join(str(v) for v in tile))
        for attempt in range(5):
            response = requests.post(OVERPASS_URL, data={"data": query}, headers=OVERPASS_HEADERS, timeout=300)
            if response.ok:
                break
            print(f"  overpass {response.status_code} for tile {tile}, retrying")
            time.sleep(30 * (attempt + 1))
        response.raise_for_status()
        elements += response.json()["elements"]
        print(f"  tile {tile}: {len(elements)} water bodies so far")
    target.write_text(json.dumps({"version": 0.6, "generator": "Overpass API, four bbox tiles", "elements": elements}), encoding="utf-8")
    print(f"fetched {target.name} ({target.stat().st_size / 1e6:.1f} MB)")


# India-WRIS groundwater levels (metres below ground level) of the manual monitoring network. The WRIS
# portal only serves a browser app, so the readings come from the India Data Portal's CKAN mirror of the
# WRIS export (data to mid-2023 for the state department, 2024 for CGWB), which has an SQL datastore.
IDP_SQL_URL = "https://ckandev.indiadataportal.com/api/3/action/datastore_search_sql"
IDP_GW_MANUAL = "06d6e79c-61ac-46bb-9e03-c7138911c619"       # resource "Groundwater Level Collected Manually"
GW_BBOX = (15.8, 19.95, 77.2, 81.4)                           # south, north, west, east: the state with a margin
GW_AGENCIES = ("CGWB", "Telangana GW")                        # the box also clips Andhra Pradesh and Chhattisgarh wells
GW_COLUMNS = ("station_code", "station_name", "agency_name", "well_type", "well_aquifer_type",
              "latitude", "longitude", "well_depth", "date", "data_value")
GW_PAGE = 30000                                               # the datastore returns at most 32,000 rows per query


def fetch_groundwater_levels() -> None:
    """Every reading of the CGWB and Telangana GW wells in the box, as a gzipped CSV (~190,000 rows)."""
    target = RAW / "gw_levels.csv.gz"
    if target.exists():
        print(f"cached  {target.name}")
        return
    south, north, west, east = GW_BBOX
    where = (f"latitude BETWEEN {south} AND {north} AND longitude BETWEEN {west} AND {east} "
             f"AND agency_name IN ({', '.join(repr(a) for a in GW_AGENCIES)})")
    rows: list[dict] = []
    last_id = 0
    while True:                                               # keyset pagination on the row id
        sql = (f'SELECT _id, {", ".join(GW_COLUMNS)} FROM "{IDP_GW_MANUAL}" WHERE {where} AND _id > {last_id} '
               f"ORDER BY _id LIMIT {GW_PAGE}")
        for attempt in range(5):
            response = requests.get(IDP_SQL_URL, params={"sql": sql}, timeout=300)
            if response.ok and response.json().get("success"):
                break
            print(f"  datastore {response.status_code} ({response.text[:80]!r}), retrying")
            time.sleep(20 * (attempt + 1))
        response.raise_for_status()
        records = response.json()["result"]["records"]
        rows += records
        print(f"  {len(rows):,} readings so far")
        if len(records) < GW_PAGE:
            break
        last_id = records[-1]["_id"]
    with gzip.open(target, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"fetched {target.name} ({target.stat().st_size / 1e6:.1f} MB, {len(rows):,} readings)")


# ESA WorldCover 2021 (v200, CC BY 4.0): 10 m land cover in 3-degree COG tiles on AWS. Only the 1/32
# overview (320 m) is read, straight from the cloud files, and written as one small mosaic.
WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
WORLDCOVER_TILES = ("N15E075", "N15E078", "N15E081", "N18E075", "N18E078", "N18E081")
WORLDCOVER_FACTOR = 32


def fetch_worldcover() -> None:
    """Land-cover classes around Telangana at 320 m (tree, shrub, grass, crop, built-up, bare, water, wetland)."""
    target = RAW / "worldcover_320m.tif"
    if target.exists():
        print(f"cached  {target.name}")
        return
    import numpy as np
    import rasterio
    from rasterio.merge import merge
    from rasterio.io import MemoryFile
    sources = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for tile in WORLDCOVER_TILES:
            with rasterio.open(WORLDCOVER_URL.format(tile=tile)) as src:
                shape = (src.height // WORLDCOVER_FACTOR, src.width // WORLDCOVER_FACTOR)
                data = src.read(1, out_shape=shape)
                transform = src.transform * src.transform.scale(src.width / shape[1], src.height / shape[0])
                memory = MemoryFile()
                with memory.open(driver="GTiff", height=shape[0], width=shape[1], count=1, dtype=data.dtype,
                                 crs=src.crs, transform=transform, nodata=0) as dst:
                    dst.write(data, 1)
                sources.append(memory.open())
                print(f"  {tile}: {np.count_nonzero(data):,} land-cover cells")
    mosaic, transform = merge(sources)
    profile = sources[0].profile | {"height": mosaic.shape[1], "width": mosaic.shape[2], "transform": transform, "compress": "lzw"}
    with rasterio.open(target, "w", **profile) as dst:
        dst.write(mosaic)
    print(f"fetched {target.name} ({target.stat().st_size / 1e6:.1f} MB)")


# Places named by the proposal's multi-stage trunk systems that are not on the map yet: stage reservoirs
# of existing schemes that have no Wikipedia page and towns that would name new balancing reservoirs.
# Nominatim (OpenStreetMap, ODbL) gives a village or town centre, which stands in for the site.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "telangana3d/1.0 (terrain map; proposal sketch)"}
PROPOSAL_PLACES = [
    "Nandi Medaram, Peddapalli", "Bheemghanpur, Mulugu", "Dharmasagar, Hanamkonda", "Narlapur, Nagarkurnool", "Uddandapur, Nagarkurnool",
    "Sangambanda, Narayanpet", "Ryalampad, Jogulamba Gadwal", "Asifabad, Komaram Bheem", "Utnur, Adilabad", "Ichoda, Adilabad",
    "Kohir, Sangareddy", "Vikarabad", "Jangaon", "Palvancha, Bhadradri Kothagudem", "Yellandu, Bhadradri Kothagudem",
    "Kulkacherla, Vikarabad", "Kosgi, Narayanpet", "Keshavapuram, Medchal", "Chityal, Nalgonda", "Bhainsa, Nirmal",
]


def fetch_proposal_places() -> None:
    target = RAW / "nominatim_proposal.json"
    if target.exists():
        print(f"cached  {target.name}")
        return
    found = {}
    for place in PROPOSAL_PLACES:
        response = requests.get(NOMINATIM_URL, headers=NOMINATIM_HEADERS, timeout=TIMEOUT_S,
                                params={"q": f"{place}, Telangana, India", "format": "json", "limit": 1})
        response.raise_for_status()
        hits = response.json()
        if hits:
            found[place] = {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "display": hits[0]["display_name"], "type": hits[0].get("type")}
            print(f"  {place}: {hits[0]['display_name'][:70]}")
        else:
            print(f"  {place}: not found")
        time.sleep(1.1)                                       # Nominatim usage policy: one request a second
    target.write_text(json.dumps(found, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"fetched {target.name} ({len(found)} of {len(PROPOSAL_PLACES)} places)")


# Potapov et al. 2021: percent cropland per 3 km cell, one layer per four-year epoch (named by its last year).
GLAD_CROPLAND_URL = "https://glad.umd.edu/users/Potapov/Global_Crop/Data/Global_cropland_3km_{year}.tif"
GLAD_CROPLAND_YEARS = (2003, 2007, 2011, 2015, 2019)
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_DAMS_QUERY = """SELECT ?item ?itemLabel ?typeLabel ?coord ?height ?riverLabel ?inception WHERE {
  SERVICE wikibase:box { ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point(76.9 15.4)"^^geo:wktLiteral ;
                    wikibase:cornerNorthEast "Point(81.6 20.0)"^^geo:wktLiteral . }
  ?item wdt:P31 ?type . ?type wdt:P279* wd:Q12323 .
  OPTIONAL { ?item wdt:P2048 ?height } OPTIONAL { ?item wdt:P206 ?river } OPTIONAL { ?item wdt:P571 ?inception }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def fetch_wikidata_dams() -> None:
    """Dams around Telangana from Wikidata (CSV); supplies reservoirs with no Wikipedia page."""
    download(WIKIDATA_SPARQL, RAW / "wikidata_dams.csv", params={"query": WIKIDATA_DAMS_QUERY},
             headers={**WIKIPEDIA_HEADERS, "Accept": "text/csv"})


def fetch_cropland() -> None:
    (RAW / "cropland").mkdir(exist_ok=True)
    for year in GLAD_CROPLAND_YEARS:
        download(GLAD_CROPLAND_URL.format(year=year), RAW / "cropland" / f"Global_cropland_3km_{year}.tif")


def fetch_wikipedia_dams() -> None:
    target = RAW / "wikipedia_dams.json"
    if target.exists():
        print(f"cached  {target.name}")
        return
    listing = wikitext([DAM_LIST_PAGE])[DAM_LIST_PAGE]
    linked = re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", listing)
    titles = list(dict.fromkeys(t.strip() for t in linked if not t.startswith(("File:", "Category:"))))
    pages = wikitext(titles + EXTRA_DAM_PAGES)
    target.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    print(f"fetched {target.name} ({sum(1 for v in pages.values() if v)} pages)")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    fetch_dem_tiles()
    fetch_boundaries()
    fetch_natural_earth()
    fetch_osm_places()
    fetch_hydrorivers()
    fetch_wikipedia_dams()
    fetch_wikidata_dams()
    fetch_osm_reservoirs()
    fetch_osm_water()
    fetch_groundwater_levels()
    fetch_worldcover()
    fetch_proposal_places()
    fetch_cropland()

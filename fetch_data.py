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
"""
from __future__ import annotations

import json
import re
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
    fetch_cropland()

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
OVERPASS_PUMPHOUSES_QUERY = (
    '[out:json][timeout:90];'
    'area["name"="Telangana"]["admin_level"="4"]->.a;'
    '(nwr["man_made"="pumping_station"]["name"~"Medigadda|Annaram|Sundilla",i](area.a););'
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
    fetch_osm_reservoirs()

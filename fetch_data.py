"""Download raw inputs for the Telangana terrain map into data/raw/.

Sources (all public, no auth):
- Copernicus GLO-90 DEM, 1x1 degree COG tiles on AWS
- geoBoundaries gbOpen India ADM1 (states) and ADM2 (districts)
- Natural Earth 10m rivers, populated places
"""
from __future__ import annotations

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
TIMEOUT_S = 120


def download(url: str, target: Path) -> None:
    if target.exists():
        print(f"cached  {target.name}")
        return
    response = requests.get(url, timeout=TIMEOUT_S)
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


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    fetch_dem_tiles()
    fetch_boundaries()
    fetch_natural_earth()

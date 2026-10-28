"""Publish the atlas's static layers as Mapbox-hosted vector tilesets (Mapbox Tiling Service).

    export MAPBOX_SECRET_TOKEN=sk....        # needs tilesets:read, tilesets:write and tilesets:list
                                             # (MAPBOX_ALL_ACCESS_TOKEN is used when MAPBOX_SECRET_TOKEN is not set)
    uv run python publish_tilesets.py                  # all layers
    uv run python publish_tilesets.py flow tanks       # some layers
    uv run python publish_tilesets.py --username me    # instead of the user decoded from the public token

For each layer in web/data it uploads a tileset source, creates (or updates) the tileset <username>.tg-<layer>,
publishes it, waits for the job, and finally writes web/data/tilesets.json. The map reads that file at boot:
present -> these layers load as vector tiles; absent -> the GeoJSON files, as before.
`links` and `proposal` stay GeoJSON (they need lineMetrics and change often). The mapbox-tilesets CLI is run
through `uv run --with mapbox-tilesets tilesets ...`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
TOKEN_FILE = ROOT / "web" / "mapbox-token.js"
MIN_ZOOM = 5
POLL_SECONDS = 10
POLL_LIMIT = 90                     # 15 minutes per tileset

# layer -> (GeoJSON file, max zoom). Every tile at the max zoom keeps full detail; lower zooms are simplified harder.
LAYERS = {
    "flow": ("flow.geojson", 12),
    "tanks": ("tanks.geojson", 12),
    "tank_points": ("tank_points.geojson", 12),
    "canals": ("canals.geojson", 12),
    "contours": ("contours.geojson", 12),
    "districts": ("districts.geojson", 12),
    "mask": ("mask.geojson", 12),
    "state": ("state.geojson", 12),
    "groundwater": ("groundwater.geojson", 12),
}
MISSING_TOKEN_TEXT = """MAPBOX_SECRET_TOKEN is not set.

Publishing tilesets needs a Mapbox *secret* token (it starts with sk.) with the scopes
tilesets:read, tilesets:write and tilesets:list. Create one at https://account.mapbox.com/access-tokens/
and export it for this shell only:

    export MAPBOX_SECRET_TOKEN=sk....

The public token used by the map cannot publish and is not used here for anything but the user name."""


def username_from_public_token() -> str | None:
    """The public token is a JWT; its payload field "u" is the account name."""
    token = os.environ.get("MAPBOX_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        found = re.search(r'"(pk\.[^"]+)"', TOKEN_FILE.read_text(encoding="utf-8"))
        token = found.group(1) if found else ""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload.get("u")


def recipe(username: str, layer: str, max_zoom: int) -> dict:
    return {
        "version": 1,
        "layers": {
            layer: {
                "source": f"mapbox://tileset-source/{username}/tg-{layer}",
                "minzoom": MIN_ZOOM,
                "maxzoom": max_zoom,
                "features": {"simplification": ["case", ["==", ["zoom"], max_zoom], 1, 4]},
            }
        },
    }


def tilesets(*args: str) -> str:
    """Run the mapbox-tilesets CLI (reads MAPBOX_SECRET_TOKEN as its access token); returns stdout."""
    env = {**os.environ, "MAPBOX_ACCESS_TOKEN": os.environ["MAPBOX_SECRET_TOKEN"]}
    result = subprocess.run(["uv", "run", "--with", "mapbox-tilesets", "tilesets", *args],
                            capture_output=True, text=True, env=env, cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"tilesets {args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


CANAL_YEAR = {"after": 2015, "before": 1970}    # the years slider treats canals by era; keep in step with CANAL_YEAR in web/app.js


def line_delimited(source: Path, target: Path, layer: str = "") -> int:
    """Tileset sources are line-delimited GeoJSON: one feature per line."""
    features = json.loads(source.read_text(encoding="utf-8"))["features"]
    if layer == "canals":                      # the map's years filter reads a numeric year property
        for feature in features:
            year = CANAL_YEAR.get(feature["properties"].get("era"))
            if year is not None:
                feature["properties"]["year"] = year
    with target.open("w", encoding="utf-8") as out:
        for feature in features:
            out.write(json.dumps(feature, separators=(",", ":")) + "\n")
    return len(features)


def tileset_exists(tileset_id: str, username: str) -> bool:
    return tileset_id in tilesets("list", username)


def publish_layer(username: str, layer: str, workdir: Path) -> dict:
    file_name, max_zoom = LAYERS[layer]
    tileset_id = f"{username}.tg-{layer}"
    count = line_delimited(DATA / file_name, workdir / f"{layer}.ndjson", layer)
    print(f"[{layer}] {count} features")
    tilesets("upload-source", username, f"tg-{layer}", str(workdir / f"{layer}.ndjson"), "--replace", "--no-validation")
    recipe_path = workdir / f"{layer}.recipe.json"
    recipe_path.write_text(json.dumps(recipe(username, layer, max_zoom), indent=1), encoding="utf-8")
    if tileset_exists(tileset_id, username):
        tilesets("update-recipe", tileset_id, str(recipe_path))
    else:
        tilesets("create", tileset_id, "--recipe", str(recipe_path), "--name", f"Telangana atlas {layer}")
    tilesets("publish", tileset_id)
    for _ in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        status = json.loads(tilesets("status", tileset_id))
        print(f"[{layer}] {status.get('status')}")
        if status.get("status") == "success":
            return {"url": f"mapbox://{tileset_id}", "sourceLayer": layer}
        if status.get("status") == "failed":
            raise RuntimeError(f"[{layer}] tileset job failed: {json.dumps(status)[:500]}")
    raise RuntimeError(f"[{layer}] still processing after {POLL_LIMIT * POLL_SECONDS} s; run again later")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("layers", nargs="*", choices=list(LAYERS), metavar="LAYER",
                        help=f"layers to publish (default: all of {', '.join(LAYERS)})")
    parser.add_argument("--username", help="Mapbox account name (default: the public token's JWT field u)")
    args = parser.parse_args()

    if not os.environ.get("MAPBOX_SECRET_TOKEN", "").strip() and os.environ.get("MAPBOX_ALL_ACCESS_TOKEN", "").strip():
        os.environ["MAPBOX_SECRET_TOKEN"] = os.environ["MAPBOX_ALL_ACCESS_TOKEN"].strip()    # fallback name
    if not os.environ.get("MAPBOX_SECRET_TOKEN", "").strip():
        print(MISSING_TOKEN_TEXT, file=sys.stderr)
        return 2
    username = args.username or username_from_public_token()
    if not username:
        print("Cannot tell the Mapbox user name: pass --username, or set MAPBOX_TOKEN to the public token.", file=sys.stderr)
        return 2
    layers = args.layers or list(LAYERS)
    out_path = DATA / "tilesets.json"
    mapping = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        for layer in layers:
            mapping[layer] = publish_layer(username, layer, Path(tmp))
            out_path.write_text(json.dumps(mapping, indent=1) + "\n", encoding="utf-8")   # keep progress if a later layer fails
    print(f"wrote {out_path.relative_to(ROOT)} for {', '.join(mapping)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        sys.exit(1)

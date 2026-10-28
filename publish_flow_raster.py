"""Publish the river-velocity GeoTIFF as a Mapbox raster-array tileset for the particle layer.

    uv run python build_flow_raster.py       # first: data/flow_velocity.tif
    uv run python publish_flow_raster.py     # uploads, creates and publishes <username>.tg-flow-particles

Needs the Mapbox tilesets CLI (`pip install mapbox-tilesets`) and a SECRET token with the
tilesets:write, tilesets:read and tilesets:list scopes in MAPBOX_SECRET_TOKEN. The username
is read from the token (override with MAPBOX_USERNAME). Tokens are never printed.
Afterwards the tileset URL is written to web/data/tilesets.json under "flow_particles";
the map then draws particles instead of the canvas bubbles.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
GEOTIFF = ROOT / "data" / "flow_velocity.tif"
RECIPE = ROOT / "recipes" / "flow_particles.json"
TILESETS_JSON = ROOT / "web" / "data" / "tilesets.json"
SOURCE_ID = "tg-flow-velocity"
TILESET_NAME = "tg-flow-particles"


def username_from_token(token: str) -> str | None:
    """A Mapbox token is a JWT whose payload carries the account name in `u`."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("u")
    except (IndexError, ValueError):
        return None


def run_cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["tilesets", *args], env=env, capture_output=True, text=True)
    print(f"tilesets {args[0]}: exit {result.returncode}")
    return result


def main() -> int:
    token = os.environ.get("MAPBOX_SECRET_TOKEN", "").strip()
    if not token:
        print("MAPBOX_SECRET_TOKEN is not set. Publishing a tileset needs a secret Mapbox token (sk.…) with the\n"
              "tilesets:write, tilesets:read and tilesets:list scopes; the public token in MAPBOX_TOKEN cannot do it.\n"
              "Create one at https://account.mapbox.com/access-tokens/, set it in your environment and run again.")
        return 2
    if not shutil.which("tilesets"):
        print("The Mapbox tilesets CLI was not found on PATH. Install it with: pip install mapbox-tilesets")
        return 2
    if not GEOTIFF.exists():
        print(f"{GEOTIFF} is missing: run build_flow_raster.py first.")
        return 2
    username = os.environ.get("MAPBOX_USERNAME") or username_from_token(token)
    if not username:
        print("Could not read the account name from the token: set MAPBOX_USERNAME.")
        return 2

    env = {**os.environ, "MAPBOX_ACCESS_TOKEN": token}
    tileset_id = f"{username}.{TILESET_NAME}"
    recipe = RECIPE.read_text(encoding="utf-8").replace("{username}", username)
    with tempfile.TemporaryDirectory() as folder:
        recipe_path = Path(folder) / "recipe.json"
        recipe_path.write_text(recipe, encoding="utf-8")
        steps = [
            ["upload-raster-source", "--replace", "--quiet", username, SOURCE_ID, str(GEOTIFF)],
            ["create", tileset_id, "--recipe", str(recipe_path), "--name", "Telangana river flow particles"],
        ]
        for args in steps:
            result = run_cli(args, env)
            if result.returncode != 0 and args[0] == "create":
                # The tileset already exists from an earlier run: update its recipe instead.
                result = run_cli(["update-recipe", tileset_id, str(recipe_path)], env)
            if result.returncode != 0:
                print(result.stdout.replace(token, "***")[-600:], result.stderr.replace(token, "***")[-600:])
                return 1
        result = run_cli(["publish", tileset_id], env)
        if result.returncode != 0:
            print(result.stdout.replace(token, "***")[-600:], result.stderr.replace(token, "***")[-600:])
            return 1
    print(result.stdout.replace(token, "***").strip())

    entries = json.loads(TILESETS_JSON.read_text(encoding="utf-8")) if TILESETS_JSON.exists() else {}
    entries["flow_particles"] = f"mapbox://{tileset_id}"
    TILESETS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TILESETS_JSON.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote flow_particles to {TILESETS_JSON}. The tileset is processed in the background: check its status in Mapbox Studio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

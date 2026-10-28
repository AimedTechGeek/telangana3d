"""Publish the river-velocity GeoTIFF as a Mapbox raster-array tileset for the particle layer.

    uv run python build_flow_raster.py       # first: data/flow_velocity.tif
    uv run python publish_flow_raster.py     # uploads, creates and publishes <username>.tg-flow-particles

Needs uv (it runs the Mapbox tilesets CLI as `uv run --with mapbox-tilesets tilesets ...`, as publish_tilesets.py does) and a SECRET token with the
tilesets:write, tilesets:read and tilesets:list scopes in MAPBOX_SECRET_TOKEN (MAPBOX_ALL_ACCESS_TOKEN is used when it is not set). The username
is read from the token (override with MAPBOX_USERNAME). Tokens are never printed.
It waits for the tileset job to succeed, then the tileset URL is written to web/data/tilesets.json under "flow_particles";
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
import time
from pathlib import Path

ROOT = Path(__file__).parent
GEOTIFF = ROOT / "data" / "flow_velocity.tif"
RECIPE = ROOT / "recipes" / "flow_particles.json"
TILESETS_JSON = ROOT / "web" / "data" / "tilesets.json"
SOURCE_ID = "tg-flow-velocity"
TILESET_NAME = "tg-flow-particles"
POLL_SECONDS = 10
POLL_LIMIT = 90                     # 15 minutes, as in publish_tilesets.py


def username_from_token(token: str) -> str | None:
    """A Mapbox token is a JWT whose payload carries the account name in `u`."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("u")
    except (IndexError, ValueError):
        return None


def run_cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    # Same invocation as publish_tilesets.py, so neither script needs the CLI installed beforehand.
    result = subprocess.run(["uv", "run", "--with", "mapbox-tilesets", "tilesets", *args], env=env, capture_output=True, text=True, cwd=ROOT)
    print(f"tilesets {args[0]}: exit {result.returncode}")
    return result


def main() -> int:
    token = (os.environ.get("MAPBOX_SECRET_TOKEN") or os.environ.get("MAPBOX_ALL_ACCESS_TOKEN") or "").strip()
    if not token:
        print("MAPBOX_SECRET_TOKEN (or MAPBOX_ALL_ACCESS_TOKEN) is not set. Publishing a tileset needs a secret Mapbox token (sk.…) with the\n"
              "tilesets:write, tilesets:read and tilesets:list scopes; the public token in MAPBOX_TOKEN cannot do it.\n"
              "Create one at https://account.mapbox.com/access-tokens/, set it in your environment and run again.")
        return 2
    if not shutil.which("uv"):
        print("uv was not found on PATH; it runs the Mapbox tilesets CLI (uv run --with mapbox-tilesets tilesets ...). Install it from https://docs.astral.sh/uv/")
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
        result = run_cli(["upload-raster-source", "--replace", "--quiet", username, SOURCE_ID, str(GEOTIFF)], env)
        if result.returncode == 0:
            # `create` on an existing tileset exits 0 without changing its recipe, so ask the account first (as publish_tilesets.py does).
            exists = tileset_id in run_cli(["list", username], env).stdout
            result = run_cli(["update-recipe", tileset_id, str(recipe_path)] if exists
                             else ["create", tileset_id, "--recipe", str(recipe_path), "--name", "Telangana river flow particles"], env)
        if result.returncode != 0:
            print(result.stdout.replace(token, "***")[-600:], result.stderr.replace(token, "***")[-600:])
            return 1
        result = run_cli(["publish", tileset_id], env)
        if result.returncode != 0:
            print(result.stdout.replace(token, "***")[-600:], result.stderr.replace(token, "***")[-600:])
            return 1
    print(result.stdout.replace(token, "***").strip())
    for _ in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        result = run_cli(["status", tileset_id], env)
        try:
            status = json.loads(result.stdout).get("status")
        except ValueError:
            status = None
        print(f"[flow_particles] {status}")
        if status == "success":
            break
        if status == "failed":
            print(result.stdout.replace(token, "***")[-600:])
            return 1
    else:
        print(f"Still processing after {POLL_LIMIT * POLL_SECONDS} s; tilesets.json was not written. Run again later.")
        return 1

    entries = json.loads(TILESETS_JSON.read_text(encoding="utf-8")) if TILESETS_JSON.exists() else {}
    entries["flow_particles"] = f"mapbox://{tileset_id}"
    TILESETS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TILESETS_JSON.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote flow_particles to {TILESETS_JSON}. The tileset job finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

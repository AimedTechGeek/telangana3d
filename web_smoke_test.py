"""Load the web map in headless Edge and check it renders without errors.

    uv run python web_smoke_test.py      # writes out/web_home.png

Needs the Playwright dev dependency (uv sync) and Microsoft Edge.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
OUT = ROOT / "out"
URL = "http://127.0.0.1:8765/?debug"
ELEVATION_TOLERANCE_M = 15      # listed city value is a Copernicus 1 km median; decoded is Mapbox Terrain-DEM under the map's surface


def main() -> int:
    OUT.mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, str(ROOT / "serve.py"), "--no-browser"], cwd=ROOT)
    time.sleep(2)
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge", headless=True,
                args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(URL)
            page.wait_for_function("document.title.startsWith('READY')", timeout=120000)
            page.wait_for_timeout(1500)
            report = json.loads(page.locator("#debug").text_content())
            page.screenshot(path=str(OUT / "web_home.png"))
            browser.close()
    finally:
        server.terminate()

    errors.extend(report["errors"])
    hyderabad = report["notes"]["hyderabad"]
    if abs(hyderabad["listed"] - hyderabad["decoded"]) > ELEVATION_TOLERANCE_M:
        errors.append(f"Hyderabad elevation mismatch: {hyderabad}")
    if not report["notes"]["terrain"]:
        errors.append("terrain is not enabled")
    print(json.dumps(report["notes"], indent=1))
    if errors:
        print("FAILED:\n  " + "\n  ".join(errors))
        return 1
    print(f"OK: {report['notes']['cities']} cities, screenshot {OUT / 'web_home.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check the Sketch-a-canal tool in headless Edge: draw a line with clicks, read the card, edit, clear, switch the tool off.

    uv run python web_sketch_test.py      # writes out/web_sketch.png

Needs the Playwright dev dependency (uv sync), Microsoft Edge and MAPBOX_TOKEN. ATLAS_PORT picks the port.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
OUT = ROOT / "out"
PORT = int(os.environ.get("ATLAS_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/?debug"

DRAW_LAYERS = "map.getStyle().layers.filter((l) => l.id.startsWith('gl-draw')).length"
DRAW_SOURCES = "Object.keys(map.getStyle().sources).filter((s) => s.startsWith('mapbox-gl-draw')).length"
# Made-up ground against the proposal norms: a falling line, and the same line with a 60 m ridge in it.
ASSESS = """(() => {
  const norms = proposalData.norms;
  const line = (elevs) => elevs.map((elev, i) => ({ d: i * 0.5, elev }));
  const falling = sketchAssess(line([100, 99, 98, 97, 96, 95]), norms);
  const ridge = sketchAssess(line([100, 99, 160, 97, 96, 95]), norms);
  const flat = sketchAssess(line([100, 100, 100, 100]), norms);
  return { falling, ridge, flat };
})()"""


def check(condition: bool, message: str, problems: list[str]) -> None:
    print(("ok    " if condition else "FAIL  ") + message)
    if not condition:
        problems.append(message)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    problems: list[str] = []
    server = subprocess.Popen([sys.executable, str(ROOT / "serve.py"), "--no-browser"], cwd=ROOT)
    time.sleep(2)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge", headless=True,
                args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(URL)
            page.wait_for_function("document.title.startsWith('READY')", timeout=120000)
            page.wait_for_timeout(6000)   # the intro flight

            check(page.evaluate(DRAW_LAYERS) == 0 and page.evaluate(DRAW_SOURCES) == 0, "Sketch off: no draw layers or sources", problems)
            check(not page.is_visible("#sketch-card"), "Sketch off: the card is hidden", problems)

            page.click('.chip[data-toggle="sketch"]')
            page.wait_for_function(f"{DRAW_LAYERS} > 0 && sketchDraw.getMode() === 'draw_line_string'", timeout=20000)
            check(page.locator("#sketch-tools .mapbox-gl-draw_ctrl-draw-btn").count() == 2, "Only the line and bin buttons are offered", problems)
            check(page.is_visible("#sketch-card"), "Sketch on: the card shows", problems)

            # Pure verdict logic on made-up ground
            result = page.evaluate(ASSESS)
            check(result["falling"]["gravity"] is True, "A line falling 5 m over 2.5 km is gravity-feasible", problems)
            check(result["ridge"]["gravity"] is False and result["ridge"]["stretches"][0]["kind"] == "tunnel",
                  "A 60 m ridge across the line is not gravity-feasible and needs a tunnel", problems)
            check(result["flat"]["gravity"] is False and result["flat"]["lift"] > 0, "A flat line needs a lift", problems)

            # Draw by clicks: three vertices, double-click on the last to finish
            page.mouse.click(620, 520)
            page.mouse.click(760, 560)
            page.mouse.dblclick(900, 500)
            page.wait_for_function("!document.getElementById('sketch-verdict').hidden", timeout=90000)
            summary = page.inner_text("#sketch-summary")
            verdict = page.inner_text("#sketch-verdict")
            print("summary:", summary, "\nverdict:", verdict, "\ncrossings:", page.inner_text("#sketch-crossings"))
            check(bool(re.search(r"Line of [\d.]+ km", summary)), "The card shows the line's length in km", problems)
            check(bool(re.search(r"Gravity is feasible|Needs a lift", verdict)), "The card shows a verdict", problems)
            check(page.is_visible("#sketch-profile"), "The elevation profile is drawn", problems)
            before = page.inner_text("#sketch-facts")
            page.screenshot(path=str(OUT / "web_sketch.png"))

            # Editing through the API fires no event, so refresh as the draw.update handler would
            moved = page.evaluate("""(() => {
              const f = sketchDraw.getAll().features[0];
              f.geometry.coordinates[2] = [f.geometry.coordinates[2][0] + 0.15, f.geometry.coordinates[2][1] + 0.1];
              sketchDraw.add(f); refreshSketch(); return 0; })()""")
            page.wait_for_function("!document.getElementById('sketch-verdict').hidden", timeout=90000)
            page.wait_for_timeout(1500)
            check(page.inner_text("#sketch-facts") != before, "Moving a vertex changes the card", problems)

            # A theme change and a basemap switch keep the line and its layers
            page.evaluate("sketchDraw.deleteAll(); 0")
            page.evaluate("""(() => { sketchDraw.add({ type: 'Feature', properties: {}, geometry: { type: 'LineString',
              coordinates: [[79.0, 18.0], [79.1, 18.05]] } }); return 0; })()""")
            page.click("#theme")
            page.wait_for_timeout(3000)
            check(page.evaluate("sketchDraw.getAll().features.length") == 1 and page.evaluate(DRAW_LAYERS) > 0, "A theme change keeps the sketch", problems)
            page.click('[data-scene="satellite"]')   # the first copy: the top bar's scene segment
            page.wait_for_timeout(6000)
            check(page.evaluate("sketchDraw.getAll().features.length") == 1 and page.evaluate(DRAW_LAYERS) > 0, "A basemap switch keeps the sketch", problems)

            page.click("#sketch-clear")
            page.wait_for_timeout(500)
            check(page.evaluate("sketchLine() === null") and page.is_hidden("#sketch-verdict"), "Clear removes the line and the verdict", problems)

            page.click('.chip[data-toggle="sketch"]')
            page.wait_for_timeout(1000)
            check(page.evaluate(DRAW_LAYERS) == 0 and page.evaluate(DRAW_SOURCES) == 0, "Sketch off again: no draw layers or sources left", problems)
            check(not page.is_visible("#sketch-card"), "Sketch off again: the card is hidden", problems)

            real = [e for e in errors if "Failed to load resource" not in e]
            check(not real, f"No page or console errors {real}", problems)
            browser.close()
    finally:
        server.terminate()
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems))
        return 1
    print("OK: sketch tool")
    return 0


if __name__ == "__main__":
    sys.exit(main())

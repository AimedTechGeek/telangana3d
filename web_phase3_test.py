"""Phase 3 checks in headless Edge: lazy proposal, bubble data diet, fly-to a work, the Follow-the-water tour.

    uv run python web_phase3_test.py      # writes out/d_*.png

Needs the Playwright dev dependency (uv sync) and Microsoft Edge. tour.js and tour.css are injected when index.html
does not load them yet, so the test runs both before and after the shell merge.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
OUT = ROOT / "out"
PORT = int(os.environ.get("ATLAS_PORT", "8765"))   # serve.py reads the same variable
URL = f"http://127.0.0.1:{PORT}/?debug"
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
STOP_COUNT = 7
failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}{'' if condition else f': {detail}'}")
    if not condition:
        failures.append(name)


def open_page(browser, viewport: dict, requests: list[str] | None = None, errors: list[str] | None = None):
    page = browser.new_page(viewport=viewport)
    if errors is not None:
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
    if requests is not None:
        page.on("request", lambda request: requests.append(request.url))
    page.goto(URL)
    page.wait_for_function("document.title.startsWith('READY')", timeout=120000)
    if not page.evaluate("Boolean(window.AtlasTour)"):
        page.add_style_tag(path=str(ROOT / "web" / "tour.css"))
        page.add_script_tag(path=str(ROOT / "web" / "tour.js"))
    page.wait_for_timeout(1500)
    return page


def count(requests: list[str], name: str) -> int:
    return sum(1 for url in requests if url.split("?")[0].endswith(f"/data/{name}"))


def wait_idle(page, timeout: int = 20000) -> None:
    page.evaluate("new Promise((resolve) => { if (!map.isMoving()) resolve(); else map.once('moveend', () => resolve()); }).then(() => 0)")
    page.wait_for_timeout(1500)


def test_map(browser) -> None:
    requests: list[str] = []
    errors: list[str] = []
    page = open_page(browser, {"width": 1600, "height": 1000}, requests, errors)

    # Data diet: bubbles come from the small file, flow.geojson is not fetched.
    tilesets = page.evaluate("fetch('data/tilesets.json').then((r) => r.json()).then((t) => Object.keys(t))")
    check("tilesets.json lists flow", "flow" in tilesets, tilesets)
    check("flow.geojson is not requested", count(requests, "flow.geojson") == 0, count(requests, "flow.geojson"))
    check("flow_bubbles.geojson is requested once", count(requests, "flow_bubbles.geojson") == 1, count(requests, "flow_bubbles.geojson"))
    check("bubbles are prepared", page.evaluate("debug.notes.bubbles") > 0, page.evaluate("debug.notes.bubbles"))
    check("bubble classes start at 300 m3/s", page.evaluate("Math.min(...BUBBLE_CLASSES.map((c) => c[0]))") >= 300)

    # Proposal: geojson only on first use.
    check("proposal.geojson is not requested before use", count(requests, "proposal.geojson") == 0)
    page.evaluate("setProposalMode('on'); 0")
    page.wait_for_function("map.getSource('proposal') && map.getLayer('prop-labels-far')", timeout=60000)
    page.wait_for_timeout(3000)
    check("proposal.geojson is requested once after showing", count(requests, "proposal.geojson") == 1, count(requests, "proposal.geojson"))
    check("proposal source and label layer exist", page.evaluate("Boolean(map.getSource('proposal') && map.getLayer('prop-labels-far') && map.getLayer('prop-labels-near'))"))
    page.evaluate("setProposalMode('off'); setProposalMode('on'); 0")
    page.wait_for_timeout(1000)
    check("showing the proposal again does not fetch again", count(requests, "proposal.geojson") == 1, count(requests, "proposal.geojson"))
    check("proposal layers are visible when on", page.evaluate("map.getLayoutProperty('prop-labels-far', 'visibility')") == "visible")
    page.evaluate("map.jumpTo({ center: [78.9, 17.6], zoom: 7.6, pitch: 45, bearing: 0 }); 0")
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT / "d_proposal_state.png"))

    # Headline numbers (the ids belong to the new shell; dummies stand in until it is merged).
    page.evaluate("""
      for (const id of ['hl-proposal-1', 'hl-proposal-2', 'hl-proposal-3']) {
        if (!document.getElementById(id)) { const dd = document.createElement('dd'); dd.id = id; document.body.append(dd); }
      }
      renderProposal(proposalData); 0""")
    texts = page.evaluate("['hl-proposal-1', 'hl-proposal-2', 'hl-proposal-3'].map((id) => document.getElementById(id).textContent)")
    check("proposal headline numbers", texts == ["₹1.09 lakh crore", "+ ₹1.84 lakh crore", "352 TMC"], texts)

    # Fly to a work: raised zoom limit, restored after leaving.
    # Read the view on the flight's own moveend: terrain tiles arriving later nudge the zoom by a fraction.
    view = page.evaluate("""new Promise((resolve) => {
      map.once('moveend', () => resolve({ zoom: map.getZoom(), pitch: map.getPitch(), max: map.getMaxZoom() }));
      flyToWork(78.90, 16.09);
    })""")
    page.wait_for_timeout(2500)
    check("flyToWork reaches zoom 15", abs(view["zoom"] - 15) <= 0.1, view)
    check("flyToWork pitch 65", abs(view["pitch"] - 65) <= 1, view)
    check("flyToWork raises the zoom limit to 16", view["max"] == 16, view)
    page.screenshot(path=str(OUT / "d_flytowork_srisailam.png"))
    page.evaluate("map.flyTo({ center: [79.3, 18.3], zoom: 9, duration: 1500, essential: true }); 0")
    page.wait_for_timeout(1500)
    page.wait_for_function("!map.isMoving()", timeout=60000)
    page.wait_for_timeout(1500)
    check("zoom limit is back to 13.5 after leaving the work", page.evaluate("map.getMaxZoom()") == 13.5, page.evaluate("map.getMaxZoom()"))

    # Tour.
    page.evaluate("map.jumpTo({ center: [79.3, 18.3], zoom: 7.5, pitch: 40, bearing: 0 }); 0")
    page.evaluate("AtlasTour.start(); 0")
    page.wait_for_selector("#tour-panel", state="visible", timeout=30000)
    caption = page.locator("#tour-panel").inner_text()
    check("tour caption names the first stop", "Medigadda" in caption, caption)
    check("tour has 7 stops", page.locator("#tour-panel .tour-profile .tour-dot").count() == STOP_COUNT, page.locator("#tour-panel .tour-profile .tour-dot").count())
    check("tour is running", page.evaluate("AtlasTour.isRunning()"))
    page.wait_for_function("!map.isMoving()", timeout=60000)
    page.wait_for_timeout(2500)                              # inside the 7 s dwell, before autoplay moves on
    page.screenshot(path=str(OUT / "d_tour_stop1.png"))
    page.locator("#tour-panel .tour-play").click()          # autoplay may already have moved on; pause so Next x6 lands on the last stop
    check("Pause stops autoplay", page.locator("#tour-panel .tour-play").inner_text() == "Play")
    while page.locator("#tour-panel .tour-prev").is_enabled():
        page.locator("#tour-panel .tour-prev").click()
    for _ in range(STOP_COUNT - 1):
        page.locator("#tour-panel .tour-next").click()
        page.wait_for_timeout(150)
    caption = page.locator("#tour-panel").inner_text()
    check("last stop states the climb", "about 500 m" in caption and "not the pumped head" in caption, caption)
    page.wait_for_function("!map.isMoving()", timeout=60000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUT / "d_tour_last.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("Escape closes the tour panel", page.locator("#tour-panel").count() == 0)
    check("tour reports not running", not page.evaluate("AtlasTour.isRunning()"))

    check("no console errors", not errors, errors)
    page.close()


def test_phone(browser) -> None:
    page = open_page(browser, {"width": 390, "height": 844})
    page.evaluate("AtlasTour.start(); 0")
    page.wait_for_selector("#tour-panel", state="visible", timeout=30000)
    page.wait_for_function("!map.isMoving()", timeout=60000)
    page.wait_for_timeout(5000)
    box = page.locator("#tour-panel").bounding_box()
    check("phone tour panel is full width", box is not None and box["width"] >= 388, box)
    small = page.evaluate("[...document.querySelectorAll('#tour-panel button')].filter((b) => b.getBoundingClientRect().height < 40).length")
    check("phone tour buttons are at least 40 px", small == 0, small)
    page.screenshot(path=str(OUT / "d_tour_phone.png"))
    page.close()


def main() -> int:
    OUT.mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, str(ROOT / "serve.py"), "--no-browser"], cwd=ROOT)
    time.sleep(2)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True, args=GL_ARGS)
            test_map(browser)
            test_phone(browser)
            browser.close()
    finally:
        server.terminate()
    if failures:
        print("FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("OK: phase 3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

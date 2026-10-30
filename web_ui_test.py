"""Check the atlas shell in headless Edge: lenses, drawer, timeline, settings, About sheet, tap readout, headline numbers and the phone sheet.

    uv run python web_ui_test.py      # writes out/ui_*.png

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
LAUNCH = dict(channel="msedge", headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
FLIGHT_MS = 2800            # a lens flight takes 2.2 s

WORDS = "document.body.innerText.split(/\\s+/).filter(Boolean).length"
VISIBLE_BUTTONS = "[...document.querySelectorAll('button')].filter((b) => b.offsetParent !== null && b.offsetWidth > 0 && b.offsetHeight > 0)"
LAYERS_OF_STATE = "JSON.stringify({ canalMode, tankMode, gwMode, cropMode, proposalMode, yearActive, yearValue, lens: lensState.id })"
ABOUT_WORDS = ["schematic", "planning sketch", "change, not cause", "position approximate", ("no dig dates", "records no"), "3d models", "copernicus dem"]


def check(condition: bool, message: str, problems: list[str]) -> None:
    print(("ok    " if condition else "FAIL  ") + message)
    if not condition:
        problems.append(message)


def state(page) -> dict:
    import json
    return json.loads(page.evaluate(LAYERS_OF_STATE))


def text(page, selector: str) -> str:
    return page.evaluate(f"document.querySelector({selector!r}).textContent")


def open_page(browser, viewport: dict, errors: list[str], **extra):
    page = browser.new_page(viewport=viewport, **extra)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.goto(URL)
    page.wait_for_function("document.title.startsWith('READY')", timeout=120000)
    page.wait_for_function("document.getElementById('hl-height-1').textContent.trim() !== ''", timeout=30000)   # atlas:data handled
    page.wait_for_timeout(2500)
    return page


def desktop(browser, problems: list[str], errors: list[str]) -> None:
    page = open_page(browser, {"width": 1600, "height": 1000}, errors)

    # ---- layout after READY: the map dominates, the drawer is closed ----
    box = page.locator("#lens-panel").bounding_box()
    check(page.is_visible("#lens-panel") and box is not None and box["width"] <= 360, f"Lens panel visible and at most 360 px wide ({box and box['width']})", problems)
    check(page.evaluate("document.getElementById('drawer').hasAttribute('inert')") and not page.is_visible("#drawer"), "Drawer closed: inert and not visible", problems)
    words = page.evaluate(WORDS)
    check(words <= 180, f"At most 180 visible words ({words})", problems)
    buttons = page.evaluate(f"{VISIBLE_BUTTONS}.length")
    check(buttons <= 25, f"At most 25 visible buttons ({buttons})", problems)
    for x, y in [(760, 560), (620, 520), (900, 500)]:
        check(page.evaluate(f"document.getElementById('map').contains(document.elementFromPoint({x}, {y}))"), f"Map is the element at ({x}, {y})", problems)
    check(page.is_hidden("#readout") and "— m" not in page.evaluate("document.body.innerText"), "Readout hidden, no '— m' placeholder on the page", problems)

    # ---- headline numbers (filled on atlas:data) ----
    check(bool(re.search(r"\d+ m", text(page, "#hl-height-1"))), f"Hyderabad headline: {text(page, '#hl-height-1')}", problems)
    check(bool(re.search(r"≈ \d+ m", text(page, "#hl-rivers-1"))), f"Kaleshwaram climb headline: {text(page, '#hl-rivers-1')}", problems)
    check(bool(re.search(r"\d", text(page, "#hl-since2014-2"))), f"Mission Kakatiya headline: {text(page, '#hl-since2014-2')}", problems)
    page.screenshot(path=str(OUT / "ui_desktop_height.png"))

    # ---- lenses ----
    def select(lens: str) -> None:
        page.click(f'#lenses [data-lens="{lens}"]')
        page.wait_for_timeout(FLIGHT_MS)
        selected = page.get_attribute(f'#lenses [data-lens="{lens}"]', "aria-selected") == "true"
        cards = page.evaluate("[...document.querySelectorAll('.lens-card')].filter((c) => c.offsetParent !== null).map((c) => c.dataset.lens)")
        check(selected and cards == [lens] and state(page)["lens"] == lens, f"Lens {lens}: tab selected, only its card visible, lensState.id matches ({cards})", problems)

    select("rivers")
    s = state(page)
    check(s["canalMode"] == "after" and page.is_visible("#timeline"), f"Rivers: canals after 2014 and the timeline shows ({s})", problems)
    page.screenshot(path=str(OUT / "ui_desktop_rivers.png"))

    select("since2014")
    s = state(page)
    check(s["yearActive"] and s["yearValue"] == 2014 and s["tankMode"] == "kakatiya", f"Since 2014: year 2014 active, Kakatiya shading ({s})", problems)
    page.screenshot(path=str(OUT / "ui_desktop_since2014.png"))

    select("ground")
    s = state(page)
    check(s["gwMode"] == "change" and page.is_hidden("#timeline"), f"Ground: groundwater change, timeline hidden ({s})", problems)
    page.screenshot(path=str(OUT / "ui_desktop_ground.png"))
    page.click('[data-ground-value] [data-value="depth"]')
    page.wait_for_timeout(300)
    page.evaluate("setYear(2010); 0")
    before = state(page)["gwMode"]
    page.evaluate("setYear(2020); 0")
    after = state(page)["gwMode"]
    check(before == "before" and after == "after" and page.is_visible("#timeline"), f"Ground depth: 2010 -> before, 2020 -> after, timeline shows ({before}, {after})", problems)

    select("proposal")
    s = state(page)
    check(page.is_visible("#plan-badge") and s["proposalMode"] == "on", f"Proposal: plan badge and proposal layers on ({s})", problems)
    page.screenshot(path=str(OUT / "ui_desktop_proposal.png"))

    select("height")
    check(page.is_hidden("#timeline") and page.is_hidden("#plan-badge"), "Height: timeline and badge hidden again", problems)

    # ---- details drawer ----
    page.click("#lens-height .details-btn")
    page.wait_for_timeout(600)
    check(page.is_visible("#drawer") and page.is_visible("#details-height") and not page.evaluate("document.getElementById('drawer').hasAttribute('inert')"),
          "Details opens the drawer on the height details", problems)
    page.wait_for_timeout(1500)          # the 0.35 s slide-in starts late under software rendering; the screenshot should show the drawer in place
    page.screenshot(path=str(OUT / "ui_desktop_drawer.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    check(page.evaluate("document.getElementById('drawer').hasAttribute('inert')") and not page.is_visible("#drawer"), "Escape closes the drawer (inert again)", problems)

    # ---- settings popover ----
    page.click("#settings-btn")
    page.wait_for_timeout(300)
    check(page.is_visible("#settings") and page.is_visible("#settings #exag"), "Settings opens with the exaggeration slider", problems)
    page.screenshot(path=str(OUT / "ui_settings.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(page.is_hidden("#settings") and page.get_attribute("#settings-btn", "aria-expanded") == "false", "Escape closes settings", problems)

    # ---- About & sources ----
    page.click("#about-btn")
    page.wait_for_timeout(300)
    about = page.inner_text("#about").lower()
    missing = [w for w in ABOUT_WORDS if not (any(x in about for x in w) if isinstance(w, tuple) else w in about)]
    check(page.is_visible("#about") and not missing, f"About opens and keeps every caveat (missing: {missing})", problems)
    page.screenshot(path=str(OUT / "ui_about.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(page.is_hidden("#about"), "Escape closes About", problems)

    # ---- tap readout ----
    page.mouse.click(800, 450)
    page.wait_for_timeout(800)
    readout = page.inner_text("#readout") if page.is_visible("#readout") else ""
    check(page.is_visible("#readout") and bool(re.search(r"\d", readout)) and "m above sea level" in readout, f"Click shows the elevation readout ({readout.replace(chr(10), ' ')[:60]})", problems)

    # ---- dark theme ----
    page.click("#theme")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "ui_desktop_dark.png"))
    page.click("#theme")
    page.wait_for_timeout(500)
    page.close()


def phone(browser, problems: list[str], errors: list[str]) -> None:
    page = open_page(browser, {"width": 390, "height": 844}, errors, is_mobile=True, has_touch=True, device_scale_factor=2)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "Phone: no horizontal page scroll", problems)
    height = page.locator("#lens-panel").bounding_box()["height"]
    check(abs(height - 132) <= 8, f"Phone: sheet peeks at 132 px ({height})", problems)
    page.screenshot(path=str(OUT / "ui_phone_peek.png"))
    page.click("#sheet-handle")
    page.wait_for_timeout(500)
    half = page.get_attribute("#lens-panel", "data-sheet")
    page.screenshot(path=str(OUT / "ui_phone_half.png"))
    page.click("#sheet-handle")
    page.wait_for_timeout(500)
    full = page.get_attribute("#lens-panel", "data-sheet")
    check(half == "half" and full == "full", f"Phone: the handle cycles peek -> half -> full ({half}, {full})", problems)
    page.click('#lenses [data-lens="rivers"]')     # the lens with the most controls, and the timeline
    page.wait_for_timeout(FLIGHT_MS)
    short = page.evaluate(f"{VISIBLE_BUTTONS}.filter((b) => b.getBoundingClientRect().height < 40).map((b) => (b.id || b.className || b.textContent.trim()) + ':' + Math.round(b.getBoundingClientRect().height))")
    check(not short, f"Phone: every visible button is at least 40 px tall ({short})", problems)
    small = page.evaluate("""[...document.querySelectorAll('#lens-panel *')].filter((el) => el.offsetParent !== null
      && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(el).fontSize) < 12)
      .map((el) => el.tagName + '.' + el.className + ':' + getComputedStyle(el).fontSize)""")
    check(not small, f"Phone: no text below 12 px in the sheet ({small})", problems)
    page.click("#lens-rivers .details-btn")
    page.wait_for_timeout(600)
    check(page.is_visible("#drawer") and page.is_visible("#details-rivers"), "Phone: Details opens the full-screen drawer", problems)
    page.screenshot(path=str(OUT / "ui_phone_details.png"))
    page.click("#drawer-close")
    page.wait_for_timeout(600)
    check(not page.is_visible("#drawer"), "Phone: the close button returns to the sheet", problems)
    page.close()


def main() -> int:
    sys.stdout.reconfigure(errors="replace")   # the messages quote page text ("≈ 500 m") that a cp1252 console cannot print
    OUT.mkdir(exist_ok=True)
    problems: list[str] = []
    errors: list[str] = []
    server = subprocess.Popen([sys.executable, str(ROOT / "serve.py"), "--no-browser"], cwd=ROOT)
    time.sleep(2)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**LAUNCH)
            desktop(browser, problems, errors)
            phone(browser, problems, errors)
            browser.close()
    finally:
        server.terminate()
    real = [e for e in errors if "Failed to load resource" not in e]   # tour.js, tour.css and three3d.js arrive with other packages
    check(not real, f"No page or console errors {real}", problems)
    if problems:
        print("FAILED:\n  " + "\n  ".join(problems))
        return 1
    print(f"OK: atlas shell, screenshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

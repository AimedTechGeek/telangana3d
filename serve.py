"""Serve the web map from web/ on localhost and open it in the browser.

    uv run python serve.py              # opens http://127.0.0.1:8765/
    uv run python serve.py --no-browser

Browsers block tile and data requests from file:// pages, so the map needs a
local HTTP server. Build web/ first with build_web_data.py.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).parent / "web"
HOST, PORT = "127.0.0.1", 8765
TOKEN_FILE = WEB / "mapbox-token.js"      # git-ignored; the GitHub Pages workflow writes the same file from a repository secret


def write_token_file() -> None:
    """The map needs a Mapbox public token: taken from the MAPBOX_TOKEN environment variable, never from the repo."""
    token = os.environ.get("MAPBOX_TOKEN", "").strip()
    if token:
        TOKEN_FILE.write_text(f"window.MAPBOX_TOKEN = {json.dumps(token)};\n", encoding="utf-8")
    elif not TOKEN_FILE.exists():
        print("MAPBOX_TOKEN is not set: the map will show a token notice instead of the basemap")


class QuietHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args) -> None:
        pass

    def copyfile(self, source, outputfile) -> None:
        try:
            super().copyfile(source, outputfile)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # the browser cancelled a tile request mid-transfer (normal while panning)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not (WEB / "data").is_dir():
        raise SystemExit("web/data is missing: run `uv run python build_web_data.py` first")
    write_token_file()

    server = ThreadingHTTPServer((HOST, PORT), functools.partial(QuietHandler, directory=str(WEB)))
    url = f"http://{HOST}:{PORT}/"
    print(f"Serving {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""Serve the web map from web/ on localhost and open it in the browser.

    uv run python serve.py              # opens http://127.0.0.1:8765/
    uv run python serve.py --no-browser

Browsers block tile and data requests from file:// pages, so the map needs a
local HTTP server. Build web/ first with build_web_data.py.
"""
from __future__ import annotations

import argparse
import functools
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).parent / "web"
HOST, PORT = "127.0.0.1", 8765


class QuietHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not (WEB / "tiles").is_dir():
        raise SystemExit("web/tiles is missing: run `uv run python build_web_data.py` first")

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

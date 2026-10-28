"""Upload Inter (Regular, Medium, Bold) to the Mapbox account so the map's labels can use it.

Downloads the official rsms/inter release zip from GitHub, posts the three TTFs to the
Mapbox Fonts API (POST https://api.mapbox.com/fonts/v1/{username}) and writes
web/data/fonts.json, which tells web/app.js that 'Inter Medium' exists as a glyph font.

Needs the environment variable MAPBOX_SECRET_TOKEN (MAPBOX_ALL_ACCESS_TOKEN is used when it is
not set), a secret token with the fonts:write scope (account.mapbox.com). The username is read from the public MAPBOX_TOKEN (its JWT
"u" field). Neither token is printed. Inter is licensed under the SIL OFL 1.1.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import requests

RELEASE_API = "https://api.github.com/repos/rsms/inter/releases/latest"
WANTED = ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-Bold.ttf"]
OUT = Path(__file__).parent / "web" / "data" / "fonts.json"
TIMEOUT = 120


def username_from_public_token(token: str) -> str:
    """A Mapbox public token is a JWT whose payload carries the account name in "u"."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["u"]


def download_inter_ttfs() -> dict[str, bytes]:
    release = requests.get(RELEASE_API, timeout=TIMEOUT).json()
    asset = next(a for a in release["assets"] if a["name"].startswith("Inter-") and a["name"].endswith(".zip"))
    print(f"Downloading {asset['name']} ({release['tag_name']})")
    archive = zipfile.ZipFile(io.BytesIO(requests.get(asset["browser_download_url"], timeout=TIMEOUT).content))
    found = {Path(n).name: n for n in archive.namelist() if "/ttf/" in n}
    return {name: archive.read(found[name]) for name in WANTED}


def main() -> int:
    secret = (os.environ.get("MAPBOX_SECRET_TOKEN") or os.environ.get("MAPBOX_ALL_ACCESS_TOKEN") or "").strip()
    public = os.environ.get("MAPBOX_TOKEN", "").strip()
    if not secret or not public:
        print("Nothing uploaded: set MAPBOX_SECRET_TOKEN or MAPBOX_ALL_ACCESS_TOKEN (a secret token with the fonts:write scope) and "
              "MAPBOX_TOKEN (the public token, for the account name), then run this again.")
        return 2
    username = username_from_public_token(public)
    names = []
    for filename, data in download_inter_ttfs().items():
        # The Fonts API takes the font file as the raw request body (as curl --data-binary would), not a multipart form:
        # a multipart upload is answered with 422 "not supported or may be corrupt".
        response = requests.post(f"https://api.mapbox.com/fonts/v1/{username}", params={"access_token": secret},
                                 data=data, headers={"Content-Type": "application/octet-stream"}, timeout=TIMEOUT)
        if not response.ok:
            print(f"{filename}: Fonts API answered {response.status_code}: {response.text[:300]}")
            return 1
        names.append(filename.removesuffix(".ttf").replace("-", " "))   # 'Inter-Medium.ttf' -> 'Inter Medium', the glyph font name
        print(f"Uploaded {filename}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"inter": True, "names": names}), encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

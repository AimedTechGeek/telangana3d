"""Interactive 3D terrain map of Telangana in forge3d's viewer.

    uv run python view.py                 # open the window, then type place names
    uv run python view.py --snapshots out # save verification stills and exit

In the window: left-drag orbits, mouse wheel zooms, W/A/S/D tilt and rotate.
forge3d's terrain viewer has no mouse pan, so the console prompt moves the
camera: type a city or district name (e.g. "Hyderabad", "Adilabad"),
"all" for the whole state, "x 60" to set the vertical exaggeration
("x auto" to follow the zoom level again), or "q" to quit.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import forge3d as f3d
import geopandas as gpd
import numpy as np
import rasterio

DATA = Path(__file__).parent / "data"
VIEWER_DEM = DATA / "telangana_viewer_dem.tif"
SOURCE_DEM = DATA / "telangana_dem.tif"
OVERLAY = DATA / "overlay.png"
UNITS_PER_PIXEL = 10.0      # must match prepare_data.VIEWER_UNITS_PER_PIXEL
METRES_PER_UNIT = 20.0      # 200 m pixels / 10 units; z_scale 1.0 = 20x relief
WINDOW = (1600, 1000)
SUN = {"azimuth_deg": 315.0, "elevation_deg": 35.0}
NORTH_UP_PHI = 90.0         # eye due south of the target, looking north
# (theta_deg, radius in viewer units, vertical exaggeration). The plateau's
# ~860 m of relief over ~470 km needs strong exaggeration to read at state
# scale; up close the same factor turns hills into spikes, so it eases off.
VIEWS = {
    "state": (35.0, 38000.0, 50.0),
    "district": (45.0, 9000.0, 30.0),
    "city": (50.0, 3500.0, 20.0),
}
EXAGGERATION_RANGE = (1.0, 150.0)
LABEL_LIFT = 40.0           # world units above the terrain surface
CITY_LABEL = {"size": 22.0, "color": (0.08, 0.08, 0.08, 1.0), "priority": 10}
DISTRICT_LABEL = {"size": 15.0, "color": (0.25, 0.22, 0.20, 1.0), "priority": 1}
HALO = {"halo_color": (1.0, 1.0, 1.0, 0.9), "halo_width": 2.0}


class TerrainFrame:
    """Converts map coordinates (LCC metres) to viewer-world (X, metres above min, Z)."""

    def __init__(self) -> None:
        with rasterio.open(SOURCE_DEM) as src:
            self.heights = src.read(1)
            self.inverse = ~src.transform
        self.min_height = float(self.heights.min())

    def world(self, x: float, y: float) -> tuple[float, float, float]:
        col, row = self.inverse * (x, y)
        r = int(np.clip(row, 0, self.heights.shape[0] - 1))
        c = int(np.clip(col, 0, self.heights.shape[1] - 1))
        return (col * UNITS_PER_PIXEL, float(self.heights[r, c]) - self.min_height, row * UNITS_PER_PIXEL)

    def center(self) -> tuple[float, float, float]:
        rows, cols = self.heights.shape
        return (cols * UNITS_PER_PIXEL / 2, 0.0, rows * UNITS_PER_PIXEL / 2)


def load_places(frame: TerrainFrame) -> tuple[dict, list, list]:
    cities = gpd.read_file(DATA / "cities.geojson")
    districts = gpd.read_file(DATA / "districts.geojson")
    city_labels = [(row["name"], frame.world(row.geometry.x, row.geometry.y)) for _, row in cities.iterrows()]
    district_labels = []
    for _, row in districts.iterrows():
        point = row.geometry.representative_point()
        district_labels.append((row["shapeName"], frame.world(point.x, point.y)))
    places = {name.lower(): (pos, "city") for name, pos in city_labels}
    for name, pos in district_labels:
        places.setdefault(name.lower(), (pos, "district"))
    return places, city_labels, district_labels


class MapSession:
    """Camera, exaggeration and labels for one open viewer."""

    def __init__(self, viewer, frame: TerrainFrame) -> None:
        self.viewer = viewer
        self.frame = frame
        self.places, self.city_labels, self.district_labels = load_places(frame)
        self.override: float | None = None   # user-set exaggeration, None = per view
        self.z_scale: float | None = None

    def show(self, target: tuple[float, float, float], view: str) -> None:
        theta, radius, exaggeration = VIEWS[view]
        self._apply_exaggeration(self.override or exaggeration)
        x, height_m, z = target
        self.viewer.set_orbit_camera(phi_deg=NORTH_UP_PHI, theta_deg=theta, radius=radius,
                                     fov_deg=40.0, target=(x, height_m * self.z_scale, z))
        self.view = (target, view)

    def set_override(self, exaggeration: float | None) -> None:
        self.override = exaggeration
        self.show(*self.view)

    def _apply_exaggeration(self, exaggeration: float) -> None:
        z_scale = exaggeration / METRES_PER_UNIT
        if z_scale == self.z_scale:
            return
        self.z_scale = z_scale
        self.viewer.set_z_scale(z_scale)
        # Label heights depend on the exaggeration, so re-place them.
        self.viewer.clear_labels()
        for labels, style in ((self.district_labels, DISTRICT_LABEL), (self.city_labels, CITY_LABEL)):
            for name, (x, height_m, z) in labels:
                self.viewer.add_label(name, (x, height_m * z_scale + LABEL_LIFT, z), **style, **HALO)


def handle_exaggeration(session: MapSession, argument: str) -> None:
    if argument == "auto":
        session.set_override(None)
        return
    try:
        factor = float(argument)
    except ValueError:
        factor = 0.0
    low, high = EXAGGERATION_RANGE
    if not low <= factor <= high:
        print(f"Use 'x <number>' between {low:g} and {high:g}, or 'x auto'.")
        return
    session.set_override(factor)


def run_prompt(session: MapSession) -> None:
    print("Type a city or district name, 'all' for the whole state, 'list' for names,")
    print("'x 60' to set vertical exaggeration ('x auto' to follow zoom), 'q' to quit.")
    while session.viewer.is_running:
        try:
            command = input("place> ").strip().lower()
        except EOFError:
            return
        if command in ("q", "quit", "exit"):
            return
        if command == "all":
            session.show(session.frame.center(), "state")
        elif command == "list":
            print(", ".join(sorted(name.title() for name in session.places)))
        elif command.startswith("x "):
            handle_exaggeration(session, command[2:].strip())
        elif command in session.places:
            session.show(*session.places[command])
        elif command:
            print(f"Unknown place '{command}'. Type 'list' to see names.")


def save_snapshots(session: MapSession, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = [
        ("1_state.png", session.frame.center(), "state"),
        ("2_district_nalgonda.png", session.places["nalgonda"][0], "district"),
        ("3_city_hyderabad.png", session.places["hyderabad"][0], "city"),
    ]
    for name, target, view in shots:
        session.show(target, view)
        session.viewer.snapshot((out_dir / name).resolve(), width=WINDOW[0], height=WINDOW[1])
        print(f"saved {out_dir / name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", type=Path, help="save verification stills to this folder and exit")
    args = parser.parse_args()

    frame = TerrainFrame()
    with f3d.open_viewer_async(terrain_path=VIEWER_DEM, width=WINDOW[0], height=WINDOW[1]) as viewer:
        viewer.send_ipc({"cmd": "set_terrain_pbr", "enabled": True})
        viewer.set_sun(**SUN)
        # preserve_colors keeps the tint saturated; PBR lighting still shades relief.
        viewer.load_overlay("map", OVERLAY, extent=[0, 0, 1, 1], opacity=1.0, preserve_colors=True)
        viewer.load_label_atlas(*f3d.default_latin_atlas_paths())
        session = MapSession(viewer, frame)
        session.show(frame.center(), "state")
        if args.snapshots:
            save_snapshots(session, args.snapshots)
        else:
            run_prompt(session)


if __name__ == "__main__":
    main()

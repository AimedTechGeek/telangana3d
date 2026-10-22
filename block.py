"""Render Telangana as a 3D terrain block (diorama) standing on a plain floor.

    uv run python block.py                # path-traced PNG -> out/telangana_block.png
    uv run python block.py --interactive  # rotate/zoom the block in forge3d's viewer

The state's terrain is kept; everything outside the boundary drops to a floor
BASE_DEPTH_M below the state's lowest point, so the state stands as a solid
block whose cliff edges form the walls.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import forge3d as f3d
import numpy as np
import rasterio
from forge3d.path_tracing import hybrid_render_terrain_reference
from PIL import Image
from rasterio.enums import Resampling
from scipy.ndimage import binary_dilation

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "out"
CLIPPED_DEM = DATA / "telangana_dem_clipped.tif"
OVERLAY = DATA / "overlay.png"
VIEWER_BLOCK_DEM = DATA / "telangana_block_viewer.tif"
VIEWER_BLOCK_OVERLAY = DATA / "block_overlay.png"
METRES_PER_VIEWER_UNIT = 20.0   # same scale as prepare_data's viewer DEM
DOWNSAMPLE = 2                  # 200 m source grid -> 400 m block grid

EXAGGERATION = 12.0             # 20x (the map's value) leaves black shadow pits on hills
BASE_DEPTH_M = 150.0            # block thickness below the lowest terrain point
FLOOR_JITTER_M = 1.0
FLOOR_JITTER_SEED = 1
WALL_RING_PX = 1                # outside pixels painted as the wall face
FLOOR_RGB = (0.86, 0.85, 0.82)  # linear RGB
WALL_RGB = (0.32, 0.22, 0.14)
RENDER_SIZE = (2400, 1600)
TILE = 800                      # must divide both RENDER_SIZE dimensions
CAMERA_TILT_DEG = 42.0          # from vertical
CAMERA_AZIMUTH_DEG = 200.0      # compass bearing from target to camera (SSW)
CAMERA_DISTANCE_SPANS = 2.0     # times the state's larger extent
FLOOR_PAD_FRACTION = 0.4        # extra floor on each side; more exceeds the 512 MB budget
SUN_ELEVATION_DEG = 60.0
FOV_DEG = 30.0
FRAMES = 256
SATURATION_THRESHOLD = 40       # max-min channel spread that marks block pixels
CROP_MARGIN_PX = 110
BACKGROUND_RGB = (85, 85, 85)   # the path tracer's empty environment colour


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def load_block() -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Return block heights, inside mask, wall-ring mask and pixel size (m)."""
    with rasterio.open(CLIPPED_DEM) as src:
        # The full 200 m grid exceeds the path tracer's 512 MB memory budget.
        shape = (src.height // DOWNSAMPLE, src.width // DOWNSAMPLE)
        dem = src.read(1, out_shape=shape, resampling=Resampling.average)
        pixel_m = float(src.transform.a) * src.width / shape[1]
    inside = np.isfinite(dem)
    floor = float(np.nanmin(dem)) - BASE_DEPTH_M
    # A perfectly flat floor makes the path tracer draw a thin arc across it;
    # sub-metre jitter (invisible at 400 m texels) removes it.
    jitter = np.random.default_rng(FLOOR_JITTER_SEED).random(dem.shape) * FLOOR_JITTER_M
    heights = np.where(inside, dem, floor + jitter).astype(np.float32)
    ring = binary_dilation(inside, iterations=WALL_RING_PX) & ~inside
    return heights, inside, ring, pixel_m


def block_albedo(inside: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Overlay colours on the state, wall colour on the edge ring, floor elsewhere."""
    height, width = inside.shape
    overlay = Image.open(OVERLAY).convert("RGB").resize((width, height), Image.Resampling.BOX)
    rgb = srgb_to_linear(np.asarray(overlay, dtype=np.float32) / 255.0)
    rgb[~inside] = FLOOR_RGB
    rgb[ring] = WALL_RGB
    alpha = np.ones((height, width, 1), dtype=np.float32)  # 1 = use this texel's colour
    return np.ascontiguousarray(np.concatenate([rgb.astype(np.float32), alpha], axis=2))


def extend_floor(heights: np.ndarray, inside: np.ndarray, albedo: np.ndarray) -> tuple:
    """Pad the floor outward so it fills the frame behind the block.

    The border rows are all floor (the DEM rectangle has a margin around the
    state), so edge padding repeats floor height and colour.
    """
    pad = int(FLOOR_PAD_FRACTION * max(heights.shape))
    return (
        np.pad(heights, pad, mode="edge"),
        np.pad(inside, pad, mode="constant", constant_values=False),
        np.ascontiguousarray(np.pad(albedo, ((pad, pad), (pad, pad), (0, 0)), mode="edge")),
    )


def camera(heights: np.ndarray, inside: np.ndarray, pixel_m: float) -> dict:
    """Pinhole camera; world x = east, z = south, y = up (heights * exaggeration)."""
    rows, cols = np.nonzero(inside)
    span = (max(np.ptp(rows), np.ptp(cols)) + 1) * pixel_m
    half_w = 0.5 * (heights.shape[1] - 1) * pixel_m
    half_h = 0.5 * (heights.shape[0] - 1) * pixel_m
    target = (
        cols.mean() * pixel_m - half_w,
        float(np.median(heights[inside])) * EXAGGERATION * 0.5,
        rows.mean() * pixel_m - half_h,
    )
    tilt = math.radians(CAMERA_TILT_DEG)
    bearing = math.radians(CAMERA_AZIMUTH_DEG)
    distance = CAMERA_DISTANCE_SPANS * span
    horizontal = distance * math.sin(tilt)
    origin = (
        target[0] + horizontal * math.sin(bearing),   # east component
        target[1] + distance * math.cos(tilt),
        target[2] - horizontal * math.cos(bearing),   # north is -z
    )
    return {"origin": origin, "look_at": target, "up": (0.0, 1.0, 0.0), "fov_y": FOV_DEG}


def render_png(output: Path) -> None:
    heights, inside, ring, pixel_m = load_block()
    heights, inside, albedo = extend_floor(heights, inside, block_albedo(inside, ring))
    cam = camera(heights, inside, pixel_m)
    width, height = RENDER_SIZE
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    # render_terrain_poster does not forward earth_model, so tile the sensor here:
    # one full frame exceeds the path tracer's 512 MB budget.
    for y in range(0, height, TILE):
        for x in range(0, width, TILE):
            tile = hybrid_render_terrain_reference(
                heights, TILE, TILE, cam,
                full_width=width, full_height=height, pixel_offset=(x, y),
                spacing=(pixel_m, pixel_m), exaggeration=EXAGGERATION,
                albedo_map=albedo, albedo_sampling="nearest",
                sun_azimuth_deg=315.0, sun_elevation_deg=SUN_ELEVATION_DEG, sun_intensity=2.5,
                env_intensity=0.5, min_frames=FRAMES, max_frames=FRAMES, variance_threshold=1e9, seed=7,
                # A diorama is a flat model: no Earth curvature.
                earth_model="flat", refraction_model="none",
            )
            rgb[y:y + TILE, x:x + TILE] = np.asarray(tile["rgba"], dtype=np.uint8)[..., :3]
    output.parent.mkdir(parents=True, exist_ok=True)
    image = crop_to_block(rgb)
    Image.fromarray(image, "RGB").save(output)
    print(f"saved {output} ({image.shape[1]}x{image.shape[0]})")


def crop_to_block(rgb: np.ndarray) -> np.ndarray:
    """Crop to the block plus a margin so the floor's far edge (and the empty
    environment behind it) stays out of frame. The block is the only
    saturated (coloured) content; floor and background are neutral grey."""
    channels = rgb.astype(np.int16)
    saturated = (channels.max(axis=2) - channels.min(axis=2)) > SATURATION_THRESHOLD
    rows, cols = np.nonzero(saturated)
    top = max(rows.min() - CROP_MARGIN_PX, 0)
    bottom = min(rows.max() + CROP_MARGIN_PX, rgb.shape[0])
    left = max(cols.min() - CROP_MARGIN_PX, 0)
    right = min(cols.max() + CROP_MARGIN_PX, rgb.shape[1])
    cropped = np.ascontiguousarray(rgb[top:bottom, left:right])
    background = np.all(np.abs(cropped.astype(np.int16) - BACKGROUND_RGB) <= 2, axis=2).mean()
    if background > 0.001:
        print(f"WARNING: {background:.1%} of the cropped render is empty background; "
              "increase FLOOR_PAD_FRACTION or CAMERA_DISTANCE_SPANS")
    return cropped


def write_viewer_block() -> None:
    """Block heights and colours on the viewer's local grid (see prepare_data)."""
    heights, inside, ring, pixel_m = load_block()
    units = pixel_m / METRES_PER_VIEWER_UNIT
    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1,
        "width": heights.shape[1], "height": heights.shape[0], "compress": "deflate",
        "transform": rasterio.Affine(units, 0, 0, 0, -units, 0),
    }
    with rasterio.open(VIEWER_BLOCK_DEM, "w", **profile) as dst:
        dst.write(heights, 1)
    linear = block_albedo(inside, ring)[..., :3]
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    Image.fromarray((np.clip(srgb, 0, 1) * 255).astype(np.uint8), "RGB").save(VIEWER_BLOCK_OVERLAY)


def open_interactive() -> None:
    write_viewer_block()
    with f3d.open_viewer_async(terrain_path=VIEWER_BLOCK_DEM, width=1600, height=1000) as viewer:
        viewer.send_ipc({"cmd": "set_terrain_pbr", "enabled": True})
        # Heights are metres and 1 viewer unit = 20 m, so z_scale 1.0 = 20x relief.
        viewer.set_z_scale(EXAGGERATION / METRES_PER_VIEWER_UNIT)
        viewer.set_sun(azimuth_deg=315.0, elevation_deg=35.0)
        viewer.load_overlay("block", VIEWER_BLOCK_OVERLAY, extent=[0, 0, 1, 1], opacity=1.0, preserve_colors=True)
        viewer.set_orbit_camera(phi_deg=110.0, theta_deg=55.0, radius=36000.0, fov_deg=40.0)
        print("Left-drag to rotate, mouse wheel to zoom. Press Enter here to close.")
        try:
            input()
        except EOFError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interactive", action="store_true", help="open the block in the viewer instead")
    parser.add_argument("--output", type=Path, default=OUT / "telangana_block.png")
    args = parser.parse_args()
    if args.interactive:
        open_interactive()
    else:
        render_png(args.output)


if __name__ == "__main__":
    main()

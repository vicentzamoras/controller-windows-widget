"""Copies the reference widget's SVG icons into assets/upstream/ and rasterizes
them to the alpha masks the panel tints at runtime (src/sc2tray/assets/*.png).

    git clone https://github.com/jahrekza/steam-controller-plasma-widget <dir>
    python tools/import_icons.py <dir>      # needs resvg-py (dev only)
    python tools/import_icons.py            # re-rasterize the copies already in assets/upstream/

The app itself never parses SVG: it loads the masks with Pillow, so the
runtime and the exe stay free of an SVG renderer.
"""
import io
import shutil
import sys
from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "assets" / "upstream"
MASKS = ROOT / "src" / "sc2tray" / "assets"
UPSTREAM_IMAGES = Path("plasmoid/com.jahrek.steamcontroller/contents/images")
SCALE = 4                   # masks at 4x their SVG size (24 -> 96 px): the panel only ever scales them down

ICONS = ["bluetooth", "bolt", "clock", "hourglass", "locate", "puck", "steam-machine", "usb-c",
         "steam-controller-body", "steam-controller-lines"]


def copy_sources(checkout):
    SOURCES.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        shutil.copyfile(checkout / UPSTREAM_IMAGES / f"{name}.svg", SOURCES / f"{name}.svg")


def rasterize(name):
    png = resvg_py.svg_to_bytes(svg_path=str(SOURCES / f"{name}.svg"), zoom=SCALE)
    mask = Image.open(io.BytesIO(bytes(png))).getchannel("A")
    mask.save(MASKS / f"{name}.png", optimize=True)
    return mask.size


def main():
    if len(sys.argv) > 1:
        copy_sources(Path(sys.argv[1]))
    MASKS.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        print(f"{name}: {rasterize(name)}")


if __name__ == "__main__":
    main()

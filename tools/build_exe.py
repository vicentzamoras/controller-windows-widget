"""Builds dist/SC2Tray.exe: a single windowed executable, no Python needed.

    python tools/build_exe.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

sys.path.insert(0, str(ROOT / "src"))
from sc2tray import icons  # noqa: E402


def app_icon(size):
    """The tray glyph on a dark rounded tile, so it reads on light and dark Explorer backgrounds."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill="#202020")
    glyph = icons.render(icons.NORMAL, 78, False, round(size * 0.84))
    tile.alpha_composite(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2))
    return tile


def write_ico(path):
    images = [app_icon(s) for s in ICO_SIZES]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])


def main():
    BUILD.mkdir(exist_ok=True)
    ico = BUILD / "sc2tray.ico"
    write_ico(ico)
    PyInstaller.__main__.run([
        str(ROOT / "tools" / "sc2tray_entry.py"),
        "--name", "SC2Tray",
        "--onefile",
        "--windowed",
        "--icon", str(ico),
        "--paths", str(ROOT / "src"),
        "--hidden-import", "pystray._win32",     # pystray picks its backend at runtime
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--noconfirm",
    ])


if __name__ == "__main__":
    main()

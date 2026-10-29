"""Rasterise the DEBRIS icons into the favicon set (spec section 10).

The blog mark (icons/debris-mark.svg) and the favicon (icons/debris-favicon.svg)
are independent drawings: the favicon has to read at 16 px, the mark does not.
Rasterised with whatever is already on the machine (qlmanage, then sips); nothing
is installed for this step, and a missing tool degrades to the SVG only.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "icons"
STATIC = ROOT / "app" / "static"
SIZES = {"icon-16.png": 16, "icon-32.png": 32, "icon-48.png": 48, "icon-180.png": 180,
         "icon-192.png": 192, "icon-512.png": 512}


def svg_to_png(svg: Path, out: Path, size: int) -> bool:
    """qlmanage renders an SVG to PNG at a requested box; sips then resizes exactly."""
    if not shutil.which("qlmanage"):
        return False
    tmp = out.parent / "_ql"
    tmp.mkdir(exist_ok=True)
    subprocess.run(["qlmanage", "-t", "-s", str(max(size, 512)), "-o", str(tmp), str(svg)],
                   capture_output=True, check=False)
    rendered = next(iter(tmp.glob("*.png")), None)
    if not rendered:
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    shutil.move(str(rendered), str(out))
    shutil.rmtree(tmp, ignore_errors=True)
    if shutil.which("sips"):
        subprocess.run(["sips", "-z", str(size), str(size), str(out)],
                       capture_output=True, check=False)
    return True


def flatten(png: Path, background: tuple[int, int, int] = (248, 248, 248)) -> None:
    """Composite onto the off-white background: an apple-touch-icon must be opaque."""
    try:
        from PIL import Image  # optional
    except ImportError:
        return
    img = Image.open(png).convert("RGBA")
    flat = Image.new("RGB", img.size, background)
    flat.paste(img, mask=img.split()[3])
    flat.save(png)


def write_ico(pngs: list[Path], out: Path) -> None:
    """A minimal multi-size .ico wrapping PNG payloads (valid since Vista)."""
    entries, payloads, offset = [], [], 6 + 16 * len(pngs)
    for path in pngs:
        data = path.read_bytes()
        width, height = png_size(data)
        entries.append(struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32,
                                   len(data), offset))
        payloads.append(data)
        offset += len(data)
    out.write_bytes(struct.pack("<HHH", 0, 1, len(pngs)) + b"".join(entries) + b"".join(payloads))


def png_size(data: bytes) -> tuple[int, int]:
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def main() -> int:
    STATIC.mkdir(parents=True, exist_ok=True)
    favicon = ICONS / "debris-favicon.svg"
    mark = ICONS / "debris-mark.svg"
    shutil.copy(favicon, STATIC / "favicon.svg")

    made = []
    for name, size in SIZES.items():
        out = STATIC / name
        if svg_to_png(favicon, out, size):
            made.append(out)
            print(f"  {name} {size}x{size}")
    for name in ("icon-180.png", "icon-192.png", "icon-512.png"):
        if (STATIC / name).exists():
            flatten(STATIC / name)
    if (STATIC / "icon-180.png").exists():
        shutil.copy(STATIC / "icon-180.png", STATIC / "apple-touch-icon.png")
    ico_parts = [STATIC / n for n in ("icon-16.png", "icon-32.png", "icon-48.png")
                 if (STATIC / n).exists()]
    if ico_parts:
        write_ico(ico_parts, STATIC / "favicon.ico")
        shutil.copy(STATIC / "favicon.ico", ROOT / "favicon.ico")
        print(f"  favicon.ico ({len(ico_parts)} sizes)")
    # The 300x300 PNG copy of the blog mark lives beside the SVG.
    svg_to_png(mark, ICONS / "debris-mark.png", 300)
    print(f"icons: {len(made)} PNGs written to {STATIC}")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())

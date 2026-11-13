"""Download NASA's CGI Moon Kit (SVS 4720) and build web textures for the 3D viewport.

Source (public domain, NASA/GSFC Scientific Visualization Studio, LRO LROC + LOLA data):
  https://svs.gsfc.nasa.gov/4720/
Raw TIFFs go to data/moon_kit/ (git-ignored, ~46 MB). Web JPEGs go to frontend/public/moon/ (small, committed):
  moon_color.jpg  - LROC colour mosaic, 4096x2048 (equirectangular, lon -180..180, lat +90..-90)
  moon_height.jpg - LOLA elevation (16 px/deg) as an 8-bit height map, 4096x2048, for bump shading

Run from the repo root:  python scripts/fetch_moon_kit.py
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "moon_kit"
OUT = ROOT / "frontend" / "public" / "moon"
BASE = "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/"
FILES = {"color": "lroc_color_poles_4k.tif", "height": "ldem_16_uint.tif"}
SIZE = (4096, 2048)


def download(name: str) -> Path:
    """Fetch one file into data/moon_kit/ unless already present."""
    dest = RAW / name
    if not dest.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(BASE + name, dest)
    return dest


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    color = Image.open(download(FILES["color"])).convert("RGB").resize(SIZE, Image.LANCZOS)
    color.save(OUT / "moon_color.jpg", quality=88, optimize=True)

    h = np.asarray(Image.open(download(FILES["height"])), dtype=np.float64)  # uint16 elevation, 0..65535
    lo, hi = np.percentile(h, [0.2, 99.8])  # clip outliers so relief uses the full 8-bit range
    h8 = (np.clip((h - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    Image.fromarray(h8).resize(SIZE, Image.BICUBIC).save(OUT / "moon_height.jpg", quality=90, optimize=True)
    for f in OUT.glob("*.jpg"):
        print(f"{f.name}: {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

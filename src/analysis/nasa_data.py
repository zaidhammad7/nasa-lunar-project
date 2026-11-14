"""Bundled NASA LOLA rasters: lossless packing for the repository and automatic unpacking on first use.

The raw PDS rasters (int16, little-endian) are larger than GitHub's 100 MB file limit (the LOLA DEM is 116 MB), so the
repository ships them in nasa_data/ as  <name>.xz  =  xz( row-wise delta  ->  split low/high byte planes ).
The transform is exactly reversible; the unpacked file is checked against the SHA-256 of the original PDS file.

    python src/analysis/nasa_data.py pack      (maintainers: data/ -> nasa_data/)
    python src/analysis/nasa_data.py unpack    (anyone: nasa_data/ -> data/; also happens automatically)

Files (all NASA PDS, LRO LOLA):
  data/lola_dem/ldem_75s_120m.img                         LDEM_75S_120M polar DEM, 7624 x 7624 px, 120 m/px (0.5 m DN)
  data/lola_illumination/avgvisib_85s_060m_201608.img     average Sun visibility 2009-2013, 5058 x 5058 px, 60 m/px
  data/lola_illumination/avgvisib_85s_060m_201608_earth.img   average Earth visibility, same grid
"""
from __future__ import annotations

import hashlib
import json
import lzma
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PACKED = ROOT / "nasa_data"
MANIFEST = PACKED / "manifest.json"
RASTERS = {  # relative path under data/ -> square raster side (px)
    "lola_dem/ldem_75s_120m.img": 7624,
    "lola_illumination/avgvisib_85s_060m_201608.img": 5058,
    "lola_illumination/avgvisib_85s_060m_201608_earth.img": 5058,
}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _encode(raw: bytes, n: int) -> bytes:
    a = np.frombuffer(raw, "<i2").reshape(n, n)
    d = np.diff(a.astype(np.int32), axis=1, prepend=0).astype("<i2")  # wraps losslessly in int16
    planes = d.view(np.uint8).reshape(-1, 2)
    return lzma.compress(np.concatenate([planes[:, 0], planes[:, 1]]).tobytes(), preset=6)


def _decode(blob: bytes, n: int) -> bytes:
    planes = np.frombuffer(lzma.decompress(blob), np.uint8)
    d = np.empty((n * n, 2), np.uint8)
    d[:, 0], d[:, 1] = planes[: n * n], planes[n * n:]
    a = np.cumsum(d.view("<i2").reshape(n, n).astype(np.int32), axis=1)
    return ((a + 32768) % 65536 - 32768).astype("<i2").tobytes()


def pack() -> None:
    """data/ -> nasa_data/ (maintainers only; needs the raw PDS files)."""
    PACKED.mkdir(exist_ok=True)
    manifest = {}
    for rel, n in RASTERS.items():
        raw = (ROOT / "data" / rel).read_bytes()
        blob = _encode(raw, n)
        assert _decode(blob, n) == raw, rel
        out = PACKED / (Path(rel).name + ".xz")
        out.write_bytes(blob)
        manifest[rel] = {"packed": out.name, "side_px": n, "bytes": len(raw), "sha256": _sha256(raw)}
        print(f"{rel}: {len(raw) / 2**20:.0f} MB -> {len(blob) / 2**20:.1f} MB")
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def ensure(rel: str) -> bool:
    """Make data/<rel> exist, unpacking it from nasa_data/ if needed. True when the file is present and complete."""
    target = ROOT / "data" / rel
    n = RASTERS.get(rel)
    if n is None:
        return target.exists()
    if target.exists() and target.stat().st_size == n * n * 2:
        return True
    if not MANIFEST.exists():
        return False
    meta = json.loads(MANIFEST.read_text(encoding="utf-8")).get(rel)
    src = PACKED / meta["packed"] if meta else None
    if src is None or not src.exists():
        return False
    print(f"unpacking bundled NASA data {meta['packed']} -> data/{rel} ...", file=sys.stderr)
    raw = _decode(src.read_bytes(), n)
    if _sha256(raw) != meta["sha256"]:
        print(f"checksum mismatch for {rel}; not using it", file=sys.stderr)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(target)
    return True


def unpack_all() -> bool:
    return all([ensure(rel) for rel in RASTERS])


if __name__ == "__main__":
    if sys.argv[1:] == ["pack"]:
        pack()
    else:
        print("all NASA rasters ready" if unpack_all() else "some NASA rasters are missing")

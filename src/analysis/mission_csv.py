"""Parse the dashboard's "Export Full CSV" file into a clean per-site table.

The export is ONE location, written as two stacked sections in a single file::

    MISSION SUMMARY,
    Site_ID,Custom Selected Point        <- Field,Value rows (metadata)
    Latitude_deg,-87.9991
    ...
    <blank line>
    HOURLY TELEMETRY
    Hour_Index,Timestamp_UTC,...         <- real table header
    0,2026-11-20T00:00:00Z,...           <- one row per mission hour

Reading it with a plain ``pd.read_csv`` mixes the two layouts, so it looks like many
locations. :func:`read_mission_csv` splits the sections and stamps the site metadata
(ID, latitude, longitude, ...) onto every hourly row.

Usage::

    python src/analysis/mission_csv.py lunar_mission_telemetry_custom_2026-11-13.csv
    # -> writes <name>_clean.csv next to the input

    from src.analysis.mission_csv import read_mission_csv
    meta, df = read_mission_csv("file.csv")
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

SUMMARY_MARKER = "MISSION SUMMARY"
HOURLY_MARKER = "HOURLY TELEMETRY"
# Summary fields copied onto every hourly row (name in file -> column in output).
SITE_COLUMNS = {
    "Site_ID": "Site_ID",
    "Latitude_deg": "Latitude_deg",
    "Longitude_deg": "Longitude_deg",
    "Priority_Mode": "Priority_Mode",
}


def _read_rows(path: Path) -> list[list[str]]:
    """Read every CSV row as a list of strings (handles quoting; tolerates a UTF-8 BOM)."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


def _find_marker(rows: list[list[str]], marker: str) -> int:
    """Index of the row whose first cell equals ``marker`` (case-insensitive)."""
    for i, row in enumerate(rows):
        if row and row[0].strip().upper() == marker:
            return i
    raise ValueError(f"Section '{marker}' not found - is this a dashboard mission CSV?")


def _to_number(value: str):
    """Convert numeric-looking text to float; keep everything else as text."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def read_mission_csv(path: str | Path) -> tuple[dict, pd.DataFrame]:
    """Split a mission export into ``(metadata, hourly_dataframe)``.

    Args:
        path: CSV exported from the dashboard.

    Returns:
        metadata: dict of the MISSION SUMMARY fields (numbers converted to float).
        hourly: one row per mission hour (Timestamp_UTC parsed to UTC datetimes),
            with Site_ID / Latitude_deg / Longitude_deg / Priority_Mode columns added
            as the first columns, so each row is tied to the single geographic point.
    """
    rows = _read_rows(Path(path))
    s, h = _find_marker(rows, SUMMARY_MARKER), _find_marker(rows, HOURLY_MARKER)

    # 1) Summary: Field,Value rows between the two markers (skip blanks).
    meta = {r[0].strip(): _to_number(r[1].strip()) for r in rows[s + 1:h] if len(r) >= 2 and r[0].strip()}

    # 2) Hourly table: first row after the marker is the header; drop blank/ragged rows.
    header = [c.strip() for c in rows[h + 1]]
    body = [r for r in rows[h + 2:] if r and any(c.strip() for c in r)]
    hourly = pd.DataFrame(body, columns=header).replace("", pd.NA)
    for col in hourly.columns:
        if col != "Timestamp_UTC":
            converted = pd.to_numeric(hourly[col], errors="coerce")
            # keep text columns (status strings) untouched; convert only fully numeric ones
            if converted.notna().sum() == hourly[col].notna().sum():
                hourly[col] = converted
    hourly["Timestamp_UTC"] = pd.to_datetime(hourly["Timestamp_UTC"], utc=True)

    # 3) Tie every hourly row to the one site.
    for k, (src, dst) in enumerate(SITE_COLUMNS.items()):
        hourly.insert(k, dst, meta.get(src))
    return meta, hourly


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    src = Path(argv[1])
    meta, df = read_mission_csv(src)
    out = src.with_name(src.stem + "_clean.csv")
    df.to_csv(out, index=False)
    print(f"Site: {meta.get('Site_ID')}  ({meta.get('Latitude_deg')}, {meta.get('Longitude_deg')})")
    print(f"Unique locations in output: {df[['Latitude_deg', 'Longitude_deg']].drop_duplicates().shape[0]}")
    print(f"{len(df)} hourly rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

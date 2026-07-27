#!/usr/bin/env python3
"""
Migrate legacy LIMASSOL and TEPAK history files into the equal station folders.

This is safe to run multiple times because duplicate station/time rows are
ignored.
"""

from __future__ import annotations

import csv
from pathlib import Path

from github_collector import (
    CSV_COLUMNS,
    STATIONS_DIR,
    append_new_rows,
    safe_folder_name,
)

SCRIPT_DIR = Path(__file__).resolve().parent
LEGACY_FILES = {
    "LIMASSOL": SCRIPT_DIR / "data" / "history" / "LIMASSOL_history_wide.csv",
    "TEPAK": SCRIPT_DIR / "data" / "history" / "TEPAK_history_wide.csv",
}


def main() -> int:
    total = 0

    for station_code, source in LEGACY_FILES.items():
        if not source.exists():
            print(f"Skipped missing legacy file: {source}")
            continue

        with source.open("r", newline="", encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file))

        destination = (
            STATIONS_DIR
            / safe_folder_name(station_code)
            / "history_wide.csv"
        )
        inserted = append_new_rows(destination, rows)
        total += inserted
        print(f"{station_code}: migrated {inserted} rows.")

    print(f"Total migrated rows: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

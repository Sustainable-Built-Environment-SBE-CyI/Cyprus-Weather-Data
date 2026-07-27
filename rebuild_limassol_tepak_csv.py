#!/usr/bin/env python3
"""Rebuild LIMASSOL and TEPAK CSV histories from the SQLite database."""

from pathlib import Path

from selected_station_exports import rebuild_exports

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = SCRIPT_DIR / "cyprus_weather_archive"
DB_PATH = ARCHIVE_DIR / "cyprus_weather_history.sqlite"
EXPORT_DIR = ARCHIVE_DIR / "exports"


def main() -> int:
    try:
        paths = rebuild_exports(DB_PATH, EXPORT_DIR)
    except Exception as exc:
        print(f"Rebuild failed: {exc}")
        return 1

    print("Rebuilt:")
    for path in paths:
        print(f" - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

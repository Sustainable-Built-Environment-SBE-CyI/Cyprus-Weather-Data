#!/usr/bin/env python3
"""
GitHub Actions collector for LIMASSOL and TEPAK.

This script downloads the current Cyprus Department of Meteorology XML feed,
creates one fixed-column row per selected station, prevents duplicate
station/time rows, and updates tracked CSV files under data/.

It deliberately does not use SQLite because GitHub-hosted runners are
temporary. The CSV files committed to the repository are the persistent
cloud history.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from cyprus_weather_logger import (
    API_URL,
    download_xml,
    floor_to_poll_slot,
    parse_xml,
)
from selected_station_exports import (
    CSV_COLUMNS,
    SELECTED_STATIONS,
    build_records,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
MONTHLY_DIR = DATA_DIR / "monthly"
LATEST_DIR = DATA_DIR / "latest"
STATUS_PATH = DATA_DIR / "collection_status.json"

COMBINED_PATH = HISTORY_DIR / "LIMASSOL_TEPAK_history_wide.csv"
STATION_PATHS = {
    "LIMASSOL": HISTORY_DIR / "LIMASSOL_history_wide.csv",
    "TEPAK": HISTORY_DIR / "TEPAK_history_wide.csv",
}
LATEST_PATH = LATEST_DIR / "LIMASSOL_TEPAK_latest_wide.csv"


def read_existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()

    keys: set[tuple[str, str]] = set()
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            slot = (row.get("collection_slot_utc") or "").strip()
            station = (row.get("station_code") or "").strip().upper()
            if slot and station:
                keys.add((slot, station))
    return keys


def append_rows(path: Path, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0

    mode = "w" if new_file else "a"
    encoding = "utf-8-sig" if new_file else "utf-8"

    with path.open(mode, newline="", encoding=encoding) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def write_rows_atomic(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temporary, path)


def monthly_path(slot_utc: datetime) -> Path:
    return MONTHLY_DIR / slot_utc.strftime("%Y") / (
        f"LIMASSOL_TEPAK_{slot_utc.strftime('%Y-%m')}.csv"
    )


def write_status(
    fetched_at_utc: datetime,
    collection_slot_utc: datetime,
    parsed_observation_count: int,
    inserted_rows: int,
    records: list[dict],
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    status = {
        "source_url": API_URL,
        "last_attempt_utc": fetched_at_utc.isoformat(),
        "collection_slot_utc": collection_slot_utc.isoformat(),
        "selected_stations": list(SELECTED_STATIONS),
        "parsed_feed_observation_count": parsed_observation_count,
        "new_rows_added": inserted_rows,
        "station_status": {
            record["station_code"]: {
                "data_available": record["data_available"],
                "observation_count": record["observation_count"],
                "source_time": record["source_time"],
            }
            for record in records
        },
    }

    temporary = STATUS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, STATUS_PATH)


def main() -> int:
    fetched_at_utc = datetime.now(timezone.utc)
    fetched_at_local = fetched_at_utc.astimezone()
    collection_slot_utc = floor_to_poll_slot(fetched_at_utc)

    xml_content = download_xml()
    parsed_rows = parse_xml(xml_content)

    records = build_records(
        rows=parsed_rows,
        collection_slot_utc=collection_slot_utc.isoformat(),
        fetched_at_utc=fetched_at_utc.isoformat(),
        fetched_at_local=fetched_at_local.isoformat(),
    )

    # The combined history is the duplicate-control source of truth.
    existing = read_existing_keys(COMBINED_PATH)
    new_records = [
        record
        for record in records
        if (
            record["collection_slot_utc"],
            str(record["station_code"]).upper(),
        )
        not in existing
    ]

    inserted = append_rows(COMBINED_PATH, new_records)

    for station_code, station_path in STATION_PATHS.items():
        append_rows(
            station_path,
            [
                record
                for record in new_records
                if record["station_code"] == station_code
            ],
        )

    append_rows(monthly_path(collection_slot_utc), new_records)
    write_rows_atomic(LATEST_PATH, records)

    write_status(
        fetched_at_utc=fetched_at_utc,
        collection_slot_utc=collection_slot_utc,
        parsed_observation_count=len(parsed_rows),
        inserted_rows=inserted,
        records=records,
    )

    print(
        f"Feed observations parsed: {len(parsed_rows)}; "
        f"new selected-station rows added: {inserted}; "
        f"slot: {collection_slot_utc.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

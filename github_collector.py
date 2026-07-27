#!/usr/bin/env python3
"""
Collect every Cyprus weather station into an identical folder structure.

Every station is treated equally:

data/stations/<STATION_CODE>/
    history_wide.csv
    latest_wide.csv
    station_metadata.json
    monthly/YYYY/YYYY-MM.csv

National aggregate outputs are stored separately under data/national/.
No individual station receives special output files.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cyprus_weather_logger import (
    API_URL,
    download_xml,
    floor_to_poll_slot,
    parse_xml,
)
from selected_station_exports import CSV_COLUMNS, OBSERVATION_COLUMNS

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
STATIONS_DIR = DATA_DIR / "stations"
NATIONAL_DIR = DATA_DIR / "national"

NATIONAL_HISTORY = NATIONAL_DIR / "history_wide.csv"
NATIONAL_LATEST = NATIONAL_DIR / "latest_wide.csv"
NATIONAL_CATALOG = NATIONAL_DIR / "station_catalog.csv"
STATUS_PATH = NATIONAL_DIR / "collection_status.json"

CATALOG_COLUMNS = [
    "station_code",
    "station_name",
    "latitude",
    "longitude",
    "elevation_m",
    "first_seen_utc",
    "last_seen_utc",
    "latest_source_time",
    "latest_observation_count",
    "latest_data_available",
]


def row_value(row: Mapping, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def numeric_or_text(row: Mapping):
    numeric = row_value(row, "value_numeric")
    return numeric if numeric is not None else row_value(row, "value_text")


def safe_station_code(value: object) -> str:
    code = str(value or "").strip().upper()
    return code or "UNKNOWN"


def safe_folder_name(station_code: str) -> str:
    safe = re.sub(r"[^A-Z0-9._-]+", "_", station_code.upper()).strip("._-")
    return safe or "UNKNOWN"


def station_sort_key(code: str) -> tuple[str, str]:
    return code.casefold(), code


def build_records(
    rows: Sequence[Mapping],
    known_station_codes: Iterable[str],
    collection_slot_utc: str,
    fetched_at_utc: str,
    fetched_at_local: str,
) -> list[dict]:
    grouped: dict[str, list[Mapping]] = {}

    for row in rows:
        code = safe_station_code(row_value(row, "station_code"))
        grouped.setdefault(code, []).append(row)

    station_codes = set(grouped)
    station_codes.update(
        safe_station_code(code)
        for code in known_station_codes
        if str(code or "").strip()
    )

    records: list[dict] = []

    for station_code in sorted(station_codes, key=station_sort_key):
        station_rows = grouped.get(station_code, [])
        first = station_rows[0] if station_rows else {}

        record = {column: None for column in CSV_COLUMNS}
        record.update(
            {
                "collection_slot_utc": collection_slot_utc,
                "fetched_at_utc": fetched_at_utc,
                "fetched_at_local": fetched_at_local,
                "source_time": next(
                    (
                        row_value(row, "source_time")
                        for row in station_rows
                        if row_value(row, "source_time")
                    ),
                    None,
                ),
                "station_code": station_code,
                "station_name": row_value(first, "station_name"),
                "latitude": row_value(first, "latitude"),
                "longitude": row_value(first, "longitude"),
                "elevation_m": row_value(first, "elevation_m"),
                "data_available": 1 if station_rows else 0,
                "observation_count": len(station_rows),
            }
        )

        unknown: dict[str, dict] = {}

        for row in station_rows:
            name = str(row_value(row, "observation_name") or "").strip()
            value = numeric_or_text(row)
            target_column = OBSERVATION_COLUMNS.get(name)

            if target_column:
                record[target_column] = value
            elif name:
                unknown[name] = {
                    "value": value,
                    "unit": row_value(row, "unit"),
                }

            unit = str(row_value(row, "unit") or "").strip().lower()
            numeric = row_value(row, "value_numeric")
            if (
                numeric is not None
                and unit in {"knot", "knots", "kt", "kts"}
                and name in {"Wind Speed (10m)", "Wind Speed (2m)"}
            ):
                record[f"{name} [m/s]"] = round(float(numeric) * 0.514444, 6)

        record["other_observations_json"] = (
            json.dumps(unknown, ensure_ascii=False, sort_keys=True)
            if unknown
            else None
        )
        records.append(record)

    return records


def read_existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()

    keys: set[tuple[str, str]] = set()
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            slot = (row.get("collection_slot_utc") or "").strip()
            station = safe_station_code(row.get("station_code"))
            if slot and station:
                keys.add((slot, station))
    return keys


def only_new_rows(path: Path, rows: Iterable[dict]) -> list[dict]:
    existing = read_existing_keys(path)
    return [
        row
        for row in rows
        if (
            str(row.get("collection_slot_utc") or ""),
            safe_station_code(row.get("station_code")),
        )
        not in existing
    ]


def append_rows(path: Path, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0

    with path.open(
        "w" if is_new else "a",
        newline="",
        encoding="utf-8-sig" if is_new else "utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        if is_new:
            writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def append_new_rows(path: Path, rows: Iterable[dict]) -> int:
    return append_rows(path, only_new_rows(path, rows))


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


def national_monthly_path(slot_utc: datetime) -> Path:
    return (
        NATIONAL_DIR
        / "monthly"
        / slot_utc.strftime("%Y")
        / f"{slot_utc.strftime('%Y-%m')}.csv"
    )


def station_paths(station_code: str, slot_utc: datetime) -> dict[str, Path]:
    station_dir = STATIONS_DIR / safe_folder_name(station_code)
    return {
        "directory": station_dir,
        "history": station_dir / "history_wide.csv",
        "latest": station_dir / "latest_wide.csv",
        "metadata": station_dir / "station_metadata.json",
        "monthly": (
            station_dir
            / "monthly"
            / slot_utc.strftime("%Y")
            / f"{slot_utc.strftime('%Y-%m')}.csv"
        ),
    }


def write_station_metadata(path: Path, record: dict) -> None:
    metadata = {
        "station_code": record.get("station_code"),
        "station_name": record.get("station_name"),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "elevation_m": record.get("elevation_m"),
        "latest_collection_slot_utc": record.get("collection_slot_utc"),
        "latest_source_time": record.get("source_time"),
        "latest_data_available": record.get("data_available"),
        "latest_observation_count": record.get("observation_count"),
        "source_url": API_URL,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def update_station_folders(records: Sequence[dict], slot_utc: datetime) -> int:
    inserted = 0

    for record in records:
        paths = station_paths(
            safe_station_code(record.get("station_code")),
            slot_utc,
        )
        inserted += append_new_rows(paths["history"], [record])
        append_new_rows(paths["monthly"], [record])
        write_rows_atomic(paths["latest"], [record])
        write_station_metadata(paths["metadata"], record)

    return inserted


def read_catalog() -> dict[str, dict]:
    if not NATIONAL_CATALOG.exists() or NATIONAL_CATALOG.stat().st_size == 0:
        return {}

    catalogue: dict[str, dict] = {}
    with NATIONAL_CATALOG.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        for row in csv.DictReader(file):
            code = safe_station_code(row.get("station_code"))
            catalogue[code] = dict(row)
    return catalogue


def update_catalog(records: Sequence[dict], slot_utc: str) -> None:
    catalogue = read_catalog()

    for record in records:
        code = safe_station_code(record["station_code"])
        existing = catalogue.get(code, {})
        available = int(record.get("data_available") or 0) == 1

        catalogue[code] = {
            "station_code": code,
            "station_name": record.get("station_name") or existing.get("station_name"),
            "latitude": (
                record.get("latitude")
                if record.get("latitude") is not None
                else existing.get("latitude")
            ),
            "longitude": (
                record.get("longitude")
                if record.get("longitude") is not None
                else existing.get("longitude")
            ),
            "elevation_m": (
                record.get("elevation_m")
                if record.get("elevation_m") is not None
                else existing.get("elevation_m")
            ),
            "first_seen_utc": existing.get("first_seen_utc") or slot_utc,
            "last_seen_utc": (
                slot_utc if available else existing.get("last_seen_utc")
            ),
            "latest_source_time": record.get("source_time"),
            "latest_observation_count": record.get("observation_count"),
            "latest_data_available": record.get("data_available"),
        }

    NATIONAL_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    temporary = NATIONAL_CATALOG.with_suffix(".csv.tmp")

    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CATALOG_COLUMNS)
        writer.writeheader()
        for code in sorted(catalogue, key=station_sort_key):
            writer.writerow(catalogue[code])

    os.replace(temporary, NATIONAL_CATALOG)


def write_status(
    fetched_at_utc: datetime,
    collection_slot_utc: datetime,
    parsed_observation_count: int,
    records: Sequence[dict],
    national_rows_added: int,
    station_rows_added: int,
) -> None:
    reporting = [
        row for row in records if int(row.get("data_available") or 0) == 1
    ]

    status = {
        "source_url": API_URL,
        "last_attempt_utc": fetched_at_utc.isoformat(),
        "collection_slot_utc": collection_slot_utc.isoformat(),
        "parsed_feed_observation_count": parsed_observation_count,
        "stations_tracked": len(records),
        "stations_reporting": len(reporting),
        "stations_not_reporting": [
            row["station_code"]
            for row in records
            if int(row.get("data_available") or 0) == 0
        ],
        "new_national_rows_added": national_rows_added,
        "new_station_folder_rows_added": station_rows_added,
        "station_folder_template": (
            "data/stations/<STATION_CODE>/"
            "{history_wide.csv,latest_wide.csv,"
            "station_metadata.json,monthly/YYYY/YYYY-MM.csv}"
        ),
    }

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
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

    existing_catalogue = read_catalog()
    records = build_records(
        rows=parsed_rows,
        known_station_codes=existing_catalogue.keys(),
        collection_slot_utc=collection_slot_utc.isoformat(),
        fetched_at_utc=fetched_at_utc.isoformat(),
        fetched_at_local=fetched_at_local.isoformat(),
    )

    national_new = only_new_rows(NATIONAL_HISTORY, records)
    national_inserted = append_rows(NATIONAL_HISTORY, national_new)
    append_new_rows(national_monthly_path(collection_slot_utc), national_new)
    write_rows_atomic(NATIONAL_LATEST, records)

    station_inserted = update_station_folders(records, collection_slot_utc)
    update_catalog(records, collection_slot_utc.isoformat())

    write_status(
        fetched_at_utc=fetched_at_utc,
        collection_slot_utc=collection_slot_utc,
        parsed_observation_count=len(parsed_rows),
        records=records,
        national_rows_added=national_inserted,
        station_rows_added=station_inserted,
    )

    print(
        f"Parsed {len(parsed_rows)} observations; "
        f"treated {len(records)} stations equally; "
        f"added {national_inserted} national rows and "
        f"{station_inserted} station-folder rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Automatic fixed-column CSV exports for LIMASSOL and TEPAK.

The SQLite database remains the authoritative historical archive. These CSV
files are convenience exports that are updated after each new polling slot.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

SELECTED_STATIONS = ("LIMASSOL", "TEPAK")

OBSERVATION_COLUMNS = {
    "Air Temperature (1.2m)": "Air Temperature (1.2m) [C]",
    "Air Temperature (5cm)": "Air Temperature (5cm) [C]",
    "Extreme Day Max. Temp.": "Extreme Day Max. Temp. [C]",
    "Extreme Day Min. Temp.": "Extreme Day Min. Temp. [C]",
    "Wind Speed (10m)": "Wind Speed (10m) [Knots]",
    "Wind Speed (2m)": "Wind Speed (2m) [Knots]",
    "Direct Solar Radiation": "Direct Solar Radiation [W/m2]",
    "Global Radiation": "Global Radiation [W/m2]",
    "Wind Direction (10m)": "Wind Direction (10m) [Deg.]",
    "Rec. Light Work Load": "Rec. Light Work Load [%]",
    "Rec. Medium Work Load": "Rec. Medium Work Load [%]",
    "Rec.Heavy Work Load": "Rec. Heavy Work Load [%]",
    "Relative Humidity (1.2m)": "Relative Humidity (1.2m) [%]",
    "Accumulated Rainfall (10 min.)": "Accumulated Rainfall (10 min.) [mm]",
    "Atmospheric Pressure (Station Level)": (
        "Atmospheric Pressure (Station Level) [hPa]"
    ),
    "24HR Rain Total": "24HR Rain Total [mm]",
}

METADATA_COLUMNS = [
    "collection_slot_utc",
    "fetched_at_utc",
    "fetched_at_local",
    "source_time",
    "station_code",
    "station_name",
    "latitude",
    "longitude",
    "elevation_m",
    "data_available",
    "observation_count",
]

CSV_COLUMNS = (
    METADATA_COLUMNS
    + list(OBSERVATION_COLUMNS.values())
    + [
        "Wind Speed (10m) [m/s]",
        "Wind Speed (2m) [m/s]",
        "other_observations_json",
    ]
)


def _row_value(row: Mapping, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _numeric_or_text(row: Mapping):
    numeric = _row_value(row, "value_numeric")
    return numeric if numeric is not None else _row_value(row, "value_text")


def build_records(
    rows: Sequence[Mapping],
    collection_slot_utc: str,
    fetched_at_utc: str,
    fetched_at_local: str,
) -> list[dict]:
    """Create one fixed-column row for each selected station."""
    grouped: dict[str, list[Mapping]] = defaultdict(list)

    for row in rows:
        station_code = str(_row_value(row, "station_code") or "").upper()
        if station_code in SELECTED_STATIONS:
            grouped[station_code].append(row)

    output: list[dict] = []

    for station_code in SELECTED_STATIONS:
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
                        _row_value(row, "source_time")
                        for row in station_rows
                        if _row_value(row, "source_time")
                    ),
                    None,
                ),
                "station_code": station_code,
                "station_name": _row_value(first, "station_name"),
                "latitude": _row_value(first, "latitude"),
                "longitude": _row_value(first, "longitude"),
                "elevation_m": _row_value(first, "elevation_m"),
                "data_available": 1 if station_rows else 0,
                "observation_count": len(station_rows),
            }
        )

        unknown = {}

        for row in station_rows:
            name = str(_row_value(row, "observation_name") or "").strip()
            value = _numeric_or_text(row)

            target_column = OBSERVATION_COLUMNS.get(name)
            if target_column:
                record[target_column] = value
            elif name:
                unknown[name] = {
                    "value": value,
                    "unit": _row_value(row, "unit"),
                }

            unit = str(_row_value(row, "unit") or "").strip().lower()
            numeric = _row_value(row, "value_numeric")
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
        output.append(record)

    return output


def _append_records(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0

    if is_new:
        file = path.open("w", newline="", encoding="utf-8-sig")
    else:
        file = path.open("a", newline="", encoding="utf-8")

    with file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        if is_new:
            writer.writeheader()
        writer.writerows(records)


def _write_records_atomic(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(records)

    os.replace(temporary, path)


def append_snapshot_exports(
    export_dir: Path,
    rows: Sequence[Mapping],
    collection_slot_utc: str,
    fetched_at_utc: str,
    fetched_at_local: str,
) -> list[Path]:
    """
    Append one row per selected station to persistent historical CSV files.

    This function should only be called after a genuinely new database
    snapshot is inserted, so duplicate CSV rows are not created.
    """
    records = build_records(
        rows=rows,
        collection_slot_utc=collection_slot_utc,
        fetched_at_utc=fetched_at_utc,
        fetched_at_local=fetched_at_local,
    )

    combined = export_dir / "LIMASSOL_TEPAK_history_wide.csv"
    limassol = export_dir / "LIMASSOL_history_wide.csv"
    tepak = export_dir / "TEPAK_history_wide.csv"
    latest = export_dir / "LIMASSOL_TEPAK_latest_wide.csv"

    _append_records(combined, records)
    _append_records(
        limassol,
        [row for row in records if row["station_code"] == "LIMASSOL"],
    )
    _append_records(
        tepak,
        [row for row in records if row["station_code"] == "TEPAK"],
    )
    _write_records_atomic(latest, records)

    return [combined, limassol, tepak, latest]


def rebuild_exports(db_path: Path, export_dir: Path) -> list[Path]:
    """Rebuild all selected-station CSV files from the SQLite database."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        snapshots = connection.execute(
            """
            SELECT
                snapshot_id,
                collection_slot_utc,
                fetched_at_utc,
                fetched_at_local
            FROM snapshots
            ORDER BY collection_slot_utc
            """
        ).fetchall()

        all_records: list[dict] = []

        for snapshot in snapshots:
            rows = connection.execute(
                """
                SELECT
                    station_code,
                    station_name,
                    latitude,
                    longitude,
                    elevation_m,
                    observation_name,
                    value_text,
                    value_numeric,
                    unit,
                    source_time
                FROM observations
                WHERE snapshot_id = ?
                  AND UPPER(COALESCE(station_code, '')) IN ('LIMASSOL', 'TEPAK')
                ORDER BY station_code, observation_name
                """,
                (snapshot["snapshot_id"],),
            ).fetchall()

            all_records.extend(
                build_records(
                    rows=rows,
                    collection_slot_utc=snapshot["collection_slot_utc"],
                    fetched_at_utc=snapshot["fetched_at_utc"],
                    fetched_at_local=snapshot["fetched_at_local"],
                )
            )
    finally:
        connection.close()

    combined = export_dir / "LIMASSOL_TEPAK_history_wide.csv"
    limassol = export_dir / "LIMASSOL_history_wide.csv"
    tepak = export_dir / "TEPAK_history_wide.csv"
    latest = export_dir / "LIMASSOL_TEPAK_latest_wide.csv"

    _write_records_atomic(combined, all_records)
    _write_records_atomic(
        limassol,
        [row for row in all_records if row["station_code"] == "LIMASSOL"],
    )
    _write_records_atomic(
        tepak,
        [row for row in all_records if row["station_code"] == "TEPAK"],
    )

    latest_records = all_records[-2:] if all_records else []
    _write_records_atomic(latest, latest_records)

    return [combined, limassol, tepak, latest]

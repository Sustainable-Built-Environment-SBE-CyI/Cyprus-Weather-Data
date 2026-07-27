#!/usr/bin/env python3
"""
Export the Cyprus weather historical SQLite database to CSV.

Examples:
    py -3 export_weather_history.py --station LIMASSOL --format wide
    py -3 export_weather_history.py --station LIMASSOL --format long
    py -3 export_weather_history.py --station LIMASSOL --start 2026-08-01 --end 2026-08-31
    py -3 export_weather_history.py --format wide
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "cyprus_weather_archive" / "cyprus_weather_history.sqlite"
EXPORT_DIR = SCRIPT_DIR / "cyprus_weather_archive" / "exports"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Cyprus weather history from SQLite to CSV."
    )
    parser.add_argument(
        "--station",
        help="Station code, for example LIMASSOL. Omit to export all stations.",
    )
    parser.add_argument(
        "--start",
        help="Start date/time in ISO format, for example 2026-08-01.",
    )
    parser.add_argument(
        "--end",
        help="End date/time in ISO format, for example 2026-08-31.",
    )
    parser.add_argument(
        "--format",
        choices=("wide", "long"),
        default="wide",
        help="CSV layout. Default: wide.",
    )
    parser.add_argument(
        "--output",
        help="Optional output CSV path.",
    )
    return parser.parse_args()


def normalize_datetime_filter(value: Optional[str], end: bool = False) -> Optional[str]:
    if not value:
        return None

    text = value.strip()
    # A date-only end filter should include that entire date.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text + ("T23:59:59.999999+00:00" if end else "T00:00:00+00:00")

    # Validate common ISO input while preserving it for SQLite lexical comparison.
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def build_query(args: argparse.Namespace) -> tuple[str, list[str]]:
    clauses = []
    parameters: list[str] = []

    if args.station:
        clauses.append("UPPER(COALESCE(o.station_code, '')) = UPPER(?)")
        parameters.append(args.station.strip())

    start = normalize_datetime_filter(args.start, end=False)
    end = normalize_datetime_filter(args.end, end=True)

    if start:
        clauses.append("s.collection_slot_utc >= ?")
        parameters.append(start)
    if end:
        clauses.append("s.collection_slot_utc <= ?")
        parameters.append(end)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    query = f"""
        SELECT
            s.collection_slot_utc,
            s.fetched_at_utc,
            s.fetched_at_local,
            o.source_time,
            o.station_code,
            o.station_name,
            o.latitude,
            o.longitude,
            o.elevation_m,
            o.observation_name,
            o.value_text,
            o.value_numeric,
            o.unit
        FROM observations AS o
        JOIN snapshots AS s
            ON s.snapshot_id = o.snapshot_id
        {where}
        ORDER BY
            s.collection_slot_utc,
            o.station_code,
            o.observation_name
    """
    return query, parameters


def default_output_path(args: argparse.Namespace) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    station = (args.station or "ALL_STATIONS").upper()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_DIR / f"{station}_{args.format}_{stamp}.csv"


def display_column_name(name: str, unit: Optional[str]) -> str:
    name = (name or "Unknown variable").strip()
    unit = (unit or "").strip()
    if unit and f"[{unit}]" not in name:
        return f"{name} [{unit}]"
    return name


def write_long_csv(rows: list[sqlite3.Row], output_path: Path) -> None:
    fields = [
        "collection_slot_utc",
        "fetched_at_utc",
        "fetched_at_local",
        "source_time",
        "station_code",
        "station_name",
        "latitude",
        "longitude",
        "elevation_m",
        "observation_name",
        "value_text",
        "value_numeric",
        "unit",
    ]

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


def write_wide_csv(rows: list[sqlite3.Row], output_path: Path) -> None:
    metadata_fields = [
        "collection_slot_utc",
        "fetched_at_utc",
        "fetched_at_local",
        "source_time",
        "station_code",
        "station_name",
        "latitude",
        "longitude",
        "elevation_m",
    ]

    grouped: "OrderedDict[tuple, dict]" = OrderedDict()
    variable_columns: set[str] = set()

    for row in rows:
        key = (
            row["collection_slot_utc"],
            row["station_code"],
        )
        if key not in grouped:
            grouped[key] = {
                field: row[field]
                for field in metadata_fields
            }

        column = display_column_name(
            row["observation_name"],
            row["unit"],
        )
        variable_columns.add(column)

        value = (
            row["value_numeric"]
            if row["value_numeric"] is not None
            else row["value_text"]
        )
        grouped[key][column] = value

        # Add ENVI-met-friendly wind-speed conversions while retaining knots.
        name_normalized = (row["observation_name"] or "").strip().lower()
        unit_normalized = (row["unit"] or "").strip().lower()
        if (
            row["value_numeric"] is not None
            and name_normalized in {
                "wind speed (10m)",
                "wind speed (2m)",
            }
            and unit_normalized in {"knot", "knots", "kt", "kts"}
        ):
            converted_column = (
                f"{row['observation_name']} [m/s]"
            )
            variable_columns.add(converted_column)
            grouped[key][converted_column] = (
                float(row["value_numeric"]) * 0.514444
            )

    ordered_variables = sorted(variable_columns, key=str.casefold)
    fields = metadata_fields + ordered_variables

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in grouped.values():
            writer.writerow(record)


def main() -> int:
    args = parse_arguments()

    if not DB_PATH.exists():
        print(
            f"Database not found: {DB_PATH}\n"
            "Run cyprus_weather_logger.py first."
        )
        return 1

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else default_output_path(args)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    try:
        query, parameters = build_query(args)
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()

    if not rows:
        print("No records matched the requested filters.")
        return 1

    if args.format == "long":
        write_long_csv(rows, output_path)
    else:
        write_wide_csv(rows, output_path)

    print(f"Exported {len(rows):,} observation records to:")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

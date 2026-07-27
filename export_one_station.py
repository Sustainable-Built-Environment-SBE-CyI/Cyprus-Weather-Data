#!/usr/bin/env python3
"""Extract one station from the national wide history into a separate CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    SCRIPT_DIR
    / "data"
    / "history"
    / "CYPRUS_all_stations_history_wide.csv"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("station_code", help="Station code, e.g. TEPAK")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output")
    args = parser.parse_args()

    station = args.station_code.strip().upper()
    input_path = Path(args.input)
    output_path = (
        Path(args.output)
        if args.output
        else SCRIPT_DIR / "data" / "exports" / f"{station}_history_wide.csv"
    )

    if not input_path.exists():
        print(f"National history not found: {input_path}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    matched = 0

    with input_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            print("The national history has no header.")
            return 1

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as destination:
            writer = csv.DictWriter(destination, fieldnames=reader.fieldnames)
            writer.writeheader()

            for row in reader:
                if (row.get("station_code") or "").strip().upper() == station:
                    writer.writerow(row)
                    matched += 1

    print(f"Exported {matched} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

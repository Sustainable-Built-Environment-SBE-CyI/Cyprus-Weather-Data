#!/usr/bin/env python3
"""
Cyprus Department of Meteorology live-data logger.

Run this script once per scheduled invocation. It:
1. Downloads the current CyDoM XML feed.
2. Archives the raw XML as gzip.
3. Parses all station observations.
4. Saves them in a SQLite historical database.
5. Prevents duplicate inserts within the same 10-minute UTC collection slot.

Uses only the Python standard library.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import sqlite3
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from selected_station_exports import append_snapshot_exports

API_URL = "https://dom.org.cy/AWS/OpenData/CyDoM.xml"
POLL_INTERVAL_MINUTES = 10
REQUEST_TIMEOUT_SECONDS = 60

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = SCRIPT_DIR / "cyprus_weather_archive"
RAW_DIR = ARCHIVE_DIR / "raw_xml"
DB_PATH = ARCHIVE_DIR / "cyprus_weather_history.sqlite"
LOG_PATH = ARCHIVE_DIR / "logger.log"
EXPORT_DIR = ARCHIVE_DIR / "exports"


def setup_logging() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def tag_name(tag: str) -> str:
    """Remove an XML namespace and normalize a tag into snake_case."""
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return re.sub(r"[^a-z0-9]+", "_", tag.strip().lower()).strip("_")


def direct_fields(element: ET.Element) -> Dict[str, str]:
    """
    Return direct leaf-child text and attributes.

    Including attributes makes the parser more tolerant if the API changes
    between element-based and attribute-based XML.
    """
    fields: Dict[str, str] = {}

    for key, value in element.attrib.items():
        fields[tag_name(key)] = str(value).strip()

    for child in list(element):
        if len(list(child)) == 0:
            text = (child.text or "").strip()
            if text:
                fields[tag_name(child.tag)] = text
            for key, value in child.attrib.items():
                fields[f"{tag_name(child.tag)}_{tag_name(key)}"] = str(value).strip()

    return fields


def first_value(fields: Dict[str, str], aliases: Iterable[str]) -> Optional[str]:
    for alias in aliases:
        value = fields.get(alias)
        if value not in (None, ""):
            return value
    return None


def safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    cleaned = value.strip().replace(",", ".")
    # Permit a numeric value followed by a unit or other short text.
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", cleaned)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def floor_to_poll_slot(moment_utc: datetime) -> datetime:
    minute = (moment_utc.minute // POLL_INTERVAL_MINUTES) * POLL_INTERVAL_MINUTES
    return moment_utc.replace(minute=minute, second=0, microsecond=0)


def download_xml() -> bytes:
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "CyprusWeatherHistoricalLogger/1.0",
            "Accept": "application/xml,text/xml,*/*",
            "Cache-Control": "no-cache",
        },
    )

    context = ssl.create_default_context()
    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT_SECONDS,
        context=context,
    ) as response:
        content = response.read()
        status = getattr(response, "status", 200)

    if status != 200:
        raise RuntimeError(f"API returned HTTP status {status}.")
    if not content.strip():
        raise RuntimeError("API returned an empty response.")

    return content


def find_station_elements(root: ET.Element) -> list[ET.Element]:
    candidates: list[ET.Element] = []

    for element in root.iter():
        fields = direct_fields(element)
        station_code = first_value(
            fields,
            (
                "station_code",
                "stationcode",
                "station_id",
                "stationid",
            ),
        )
        if not station_code:
            continue

        has_observation = False
        for descendant in element.iter():
            obs_fields = direct_fields(descendant)
            if (
                first_value(obs_fields, ("observation_name", "observationname"))
                and first_value(
                    obs_fields,
                    ("observation_value", "observationvalue", "value"),
                )
                is not None
            ):
                has_observation = True
                break

        if has_observation:
            candidates.append(element)

    # Remove nested duplicate candidates. Keep the smallest useful station node.
    candidate_ids = {id(element) for element in candidates}
    filtered: list[ET.Element] = []
    for element in candidates:
        nested_candidate = any(
            id(descendant) in candidate_ids
            for descendant in element.iter()
            if descendant is not element
        )
        if not nested_candidate:
            filtered.append(element)

    return filtered


def parse_xml(xml_content: bytes) -> list[dict]:
    root = ET.fromstring(xml_content)
    station_elements = find_station_elements(root)

    rows: list[dict] = []

    for station in station_elements:
        station_fields = direct_fields(station)

        station_code = first_value(
            station_fields,
            ("station_code", "stationcode", "station_id", "stationid"),
        )
        station_name = first_value(
            station_fields,
            ("station_name", "stationname", "name"),
        )
        latitude_text = first_value(
            station_fields,
            ("station_latitude", "latitude", "lat"),
        )
        longitude_text = first_value(
            station_fields,
            ("station_longitude", "longitude", "lon", "lng"),
        )
        elevation_text = first_value(
            station_fields,
            ("station_altitude", "station_elevation", "altitude", "elevation"),
        )

        for observation in station.iter():
            observation_fields = direct_fields(observation)

            observation_name = first_value(
                observation_fields,
                ("observation_name", "observationname"),
            )
            observation_value = first_value(
                observation_fields,
                ("observation_value", "observationvalue", "value"),
            )

            if not observation_name or observation_value is None:
                continue

            unit = first_value(
                observation_fields,
                (
                    "observation_unit",
                    "observationunit",
                    "unit",
                    "units",
                ),
            )
            source_time = first_value(
                observation_fields,
                (
                    "observation_datetime",
                    "observation_date_time",
                    "observation_time",
                    "datetime",
                    "date_time",
                    "timestamp",
                    "time",
                    "date",
                ),
            ) or first_value(
                station_fields,
                (
                    "observation_datetime",
                    "observation_date_time",
                    "observation_time",
                    "datetime",
                    "date_time",
                    "timestamp",
                    "time",
                    "date",
                ),
            )

            rows.append(
                {
                    "station_code": station_code,
                    "station_name": station_name,
                    "latitude": safe_float(latitude_text),
                    "longitude": safe_float(longitude_text),
                    "elevation_m": safe_float(elevation_text),
                    "observation_name": observation_name,
                    "value_text": observation_value,
                    "value_numeric": safe_float(observation_value),
                    "unit": unit,
                    "source_time": source_time,
                    "station_fields_json": json.dumps(
                        station_fields,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "observation_fields_json": json.dumps(
                        observation_fields,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )

    if not rows:
        raise ValueError(
            "No station observations were found in the XML. "
            "The feed may be unavailable or its structure may have changed."
        )

    return rows


def connect_database() -> sqlite3.Connection:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
    connection.execute("PRAGMA foreign_keys=ON;")

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_slot_utc TEXT NOT NULL UNIQUE,
            fetched_at_utc TEXT NOT NULL,
            fetched_at_local TEXT NOT NULL,
            source_url TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            raw_file TEXT NOT NULL,
            observation_count INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            station_code TEXT,
            station_name TEXT,
            latitude REAL,
            longitude REAL,
            elevation_m REAL,
            observation_name TEXT NOT NULL,
            value_text TEXT,
            value_numeric REAL,
            unit TEXT,
            source_time TEXT,
            station_fields_json TEXT,
            observation_fields_json TEXT,
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
                ON DELETE CASCADE,
            UNIQUE(snapshot_id, station_code, observation_name)
        );

        CREATE INDEX IF NOT EXISTS idx_observations_station
            ON observations(station_code);

        CREATE INDEX IF NOT EXISTS idx_observations_name
            ON observations(observation_name);

        CREATE INDEX IF NOT EXISTS idx_snapshots_fetched
            ON snapshots(fetched_at_utc);
        """
    )
    return connection


def archive_raw_xml(
    xml_content: bytes,
    fetched_at_utc: datetime,
    collection_slot_utc: datetime,
) -> Path:
    day_dir = RAW_DIR / collection_slot_utc.strftime("%Y") / collection_slot_utc.strftime("%m") / collection_slot_utc.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    filename = f"CyDoM_{collection_slot_utc.strftime('%Y%m%dT%H%MZ')}_{fetched_at_utc.strftime('%H%M%S')}.xml.gz"
    path = day_dir / filename

    with gzip.open(path, "wb", compresslevel=6) as file:
        file.write(xml_content)

    return path


def save_snapshot(
    connection: sqlite3.Connection,
    rows: list[dict],
    fetched_at_utc: datetime,
    fetched_at_local: datetime,
    collection_slot_utc: datetime,
    content_hash: str,
    raw_file: Path,
) -> Tuple[bool, int]:
    slot_text = collection_slot_utc.isoformat()

    existing = connection.execute(
        "SELECT snapshot_id FROM snapshots WHERE collection_slot_utc = ?",
        (slot_text,),
    ).fetchone()

    if existing:
        return False, 0

    with connection:
        cursor = connection.execute(
            """
            INSERT INTO snapshots (
                collection_slot_utc,
                fetched_at_utc,
                fetched_at_local,
                source_url,
                content_sha256,
                raw_file,
                observation_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot_text,
                fetched_at_utc.isoformat(),
                fetched_at_local.isoformat(),
                API_URL,
                content_hash,
                str(raw_file.relative_to(SCRIPT_DIR)),
                len(rows),
            ),
        )
        snapshot_id = int(cursor.lastrowid)

        inserted = 0
        for row in rows:
            try:
                connection.execute(
                    """
                    INSERT INTO observations (
                        snapshot_id,
                        station_code,
                        station_name,
                        latitude,
                        longitude,
                        elevation_m,
                        observation_name,
                        value_text,
                        value_numeric,
                        unit,
                        source_time,
                        station_fields_json,
                        observation_fields_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        row["station_code"],
                        row["station_name"],
                        row["latitude"],
                        row["longitude"],
                        row["elevation_m"],
                        row["observation_name"],
                        row["value_text"],
                        row["value_numeric"],
                        row["unit"],
                        row["source_time"],
                        row["station_fields_json"],
                        row["observation_fields_json"],
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                # Some feeds can accidentally repeat the same station-variable
                # pair. Retain one value for that polling slot.
                continue

    return True, inserted


def main() -> int:
    setup_logging()

    fetched_at_utc = datetime.now(timezone.utc)
    fetched_at_local = fetched_at_utc.astimezone()
    collection_slot_utc = floor_to_poll_slot(fetched_at_utc)

    logging.info(
        "Starting collection for UTC slot %s",
        collection_slot_utc.isoformat(),
    )

    try:
        xml_content = download_xml()
        rows = parse_xml(xml_content)
        content_hash = hashlib.sha256(xml_content).hexdigest()
        raw_file = archive_raw_xml(
            xml_content,
            fetched_at_utc,
            collection_slot_utc,
        )

        connection = connect_database()
        try:
            saved, inserted = save_snapshot(
                connection,
                rows,
                fetched_at_utc,
                fetched_at_local,
                collection_slot_utc,
                content_hash,
                raw_file,
            )
        finally:
            connection.close()

        if saved:
            station_count = len(
                {
                    row["station_code"]
                    for row in rows
                    if row["station_code"]
                }
            )
            logging.info(
                "Saved %d observations from %d stations. Database: %s",
                inserted,
                station_count,
                DB_PATH,
            )

            exported_paths = append_snapshot_exports(
                export_dir=EXPORT_DIR,
                rows=rows,
                collection_slot_utc=collection_slot_utc.isoformat(),
                fetched_at_utc=fetched_at_utc.isoformat(),
                fetched_at_local=fetched_at_local.isoformat(),
            )
            logging.info(
                "Updated LIMASSOL and TEPAK historical CSV files: %s",
                ", ".join(str(path) for path in exported_paths),
            )
        else:
            logging.info(
                "The current 10-minute slot already exists; no duplicate rows were added."
            )

        return 0

    except urllib.error.HTTPError as exc:
        logging.exception("HTTP error while downloading the API: %s", exc)
    except urllib.error.URLError as exc:
        logging.exception("Network error while downloading the API: %s", exc)
    except ET.ParseError as exc:
        logging.exception("The downloaded response was not valid XML: %s", exc)
    except Exception as exc:
        logging.exception("Collection failed: %s", exc)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

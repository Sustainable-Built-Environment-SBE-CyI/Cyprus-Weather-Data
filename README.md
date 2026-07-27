# Cyprus Weather Station Archive

[![Automated collection](https://img.shields.io/badge/collection-every%2010%20minutes-success)](../../actions/workflows/collect-weather.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://www.python.org/)
[![Software licence](https://img.shields.io/badge/software-MIT-green)](LICENSE)
[![Data licence](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey)](DATA_LICENSE.md)

An automated, continuously updated archive of current meteorological observations from weather stations across Cyprus.

The repository retrieves the live Cyprus Department of Meteorology XML feed, restructures the observations into research-ready CSV files, and maintains an identical folder structure for every reporting station.

## Key features

* Automatic cloud collection through GitHub Actions
* Maintains station-level, monthly and national CSV files
* Records missing-station periods using `data_available = 0`
* Converts wind speed from knots to metres per second while preserving the original values
* Includes station metadata, observation counts and source timestamps
* Provides software licensing, data attribution and citation metadata

## Data source

The observations originate from the Cyprus Department of Meteorology live open-data endpoint:

```text
https://dom.org.cy/AWS/OpenData/CyDoM.xml
```

The feed contains current meteorological-station observations and is normally refreshed approximately every 10 minutes.

Source-data attribution and licensing details are provided in [`DATA_LICENSE.md`](DATA_LICENSE.md).

## Repository structure

```text
data/
├── stations/
│   ├── <STATION_CODE>/
│   │   ├── history_wide.csv
│   │   ├── latest_wide.csv
│   │   ├── station_metadata.json
│   │   └── monthly/
│   │       └── YYYY/
│   │           └── YYYY-MM.csv
│   └── ...
│
└── national/
    ├── history_wide.csv
    ├── latest_wide.csv
    ├── station_catalog.csv
    ├── collection_status.json
    └── monthly/
        └── YYYY/
            └── YYYY-MM.csv
```

Every station is treated equally. No station receives a special file structure or privileged processing pathway.

## Station-level files

Each directory under `data/stations/<STATION_CODE>/` contains the same four components.

### `history_wide.csv`

The accumulated historical record for the station, with one row per collection slot.

### `latest_wide.csv`

The most recent observation row for the station.

### `station_metadata.json`

Station identification and latest-status information, including:

* station code;
* station name, when supplied;
* latitude and longitude, when supplied;
* elevation, when supplied;
* latest source observation time;
* latest collection time;
* number of available variables;
* data-availability status.

### `monthly/YYYY/YYYY-MM.csv`

A monthly station archive for downloading and analysing smaller time periods.

## National files

The `data/national/` folder provides combined outputs across all tracked stations.

### `history_wide.csv`

One row per station per collection slot.

### `latest_wide.csv`

The latest national snapshot containing all tracked stations.

### `station_catalog.csv`

A catalogue of station codes, metadata, first-seen times, last-seen times and latest reporting status.

### `collection_status.json`

A machine-readable status summary containing:

* source endpoint;
* latest workflow attempt;
* current collection slot;
* total observations parsed;
* number of stations tracked;
* number of stations reporting;
* stations not reporting;
* number of new rows added.

### `monthly/YYYY/YYYY-MM.csv`

A monthly combined archive for all stations.

## Available variables

The variables available for each collection depend on the reporting station. Possible fields include:

* air temperature;
* relative humidity;
* wind speed;
* wind direction;
* atmospheric pressure;
* global solar radiation;
* direct solar radiation;
* accumulated rainfall;
* daily rainfall total;
* daily maximum temperature;
* daily minimum temperature;
* heat-workload recommendations.

Blank values do not necessarily indicate a processing error. Individual stations may report only a subset of the variables available in the live feed.

## Time fields

The archive retains several time references.

| Field                 | Meaning                                                  |
| --------------------- | -------------------------------------------------------- |
| `collection_slot_utc` | Normalised 10-minute UTC archive slot                    |
| `fetched_at_utc`      | Actual UTC time at which the workflow retrieved the feed |
| `fetched_at_local`    | Local time reported by the execution environment         |
| `source_time`         | Observation time supplied by the source feed             |

For scientific analysis, `source_time` should be checked against `collection_slot_utc`, particularly during delayed or missed workflow runs.

## Automatic collection

The cloud workflow is defined in:

```text
.github/workflows/collect-weather.yml
```

It is scheduled at:

```text
02, 12, 22, 32, 42 and 52 minutes past each UTC hour
```

The collection runs on GitHub-hosted infrastructure. The user's computer, VS Code and local internet connection do not need to remain active.

A manual collection can be started from the repository's **Actions** tab or with:

```powershell
gh workflow run "Collect Cyprus weather"
```

Recent runs can be checked with:

```powershell
gh run list --workflow="collect-weather.yml" --limit 5
```

## Updating a local copy

To download the latest workflow-generated data and commits:

```powershell
git pull
```

## Exporting one station

An individual station can be extracted from the national archive with:

```powershell
uv run --python 3.14 python export_one_station.py TEPAK
```

Replace `TEPAK` with any station code listed in:

```text
data/national/station_catalog.csv
```

## Historical coverage

This repository creates a historical archive from the first successful collection onward.

The public endpoint supplies current observations only. It does not provide a queryable historical archive at 10-minute resolution. The workflow therefore cannot reconstruct observations from before the repository-based collection began.

The first repository-based collection began on **27 July 2026**. Earlier high-frequency observations must be obtained directly from the Cyprus Department of Meteorology and imported separately.

## Data quality and scientific use

The source observations are preliminary and may later change following quality control.

Before using the archive in research, modelling or publication:

* inspect missing periods;
* check station-specific variable availability;
* verify measurement units;
* review duplicated or delayed timestamps;
* apply appropriate quality-control procedures;
* document any temporal aggregation;
* preserve source attribution.

For ENVI-met or other hourly applications, variables should be aggregated appropriately:

* use means for temperature, relative humidity, pressure and radiation;
* use vector averaging for wind direction together with wind speed;
* use interval-aware totals for rainfall.

## Licensing

### Software

The Python scripts, workflow files and repository utilities are licensed under the [MIT License](LICENSE).

```text
Copyright (c) 2026 Ravi Kumar Pandey
```

### Meteorological observations

The source meteorological observations remain subject to the original data licence and attribution requirements described in [`DATA_LICENSE.md`](DATA_LICENSE.md).

The software licence does not replace or override the source-data licence.

## Citation

GitHub can generate citation formats from [`CITATION.cff`](CITATION.cff).

Suggested software and archive citation:

> Pandey, R. K. (2026). *Cyprus Weather Station Archive: Automated collection and structuring of Cyprus meteorological-station observations* [Software and curated data archive]. GitHub.

Suggested data acknowledgement:

> Meteorological observations were supplied by the Cyprus Department of Meteorology through the National Open Data Portal of Cyprus. Data were collected and structured using the Cyprus Weather Station Archive developed by Ravi Kumar Pandey.

## Author

**Ravi Kumar Pandey**

MSCA Doctoral Candidate
The Cyprus Institute
GitHub: [@exploringravi](https://github.com/exploringravi)

## Disclaimer

This repository is an independent automated archival and restructuring project. It is not an official operational service of the Cyprus Department of Meteorology.

No guarantee is made that every scheduled GitHub Actions run will execute at the exact requested minute. GitHub may delay or skip scheduled workflows during periods of high platform load.

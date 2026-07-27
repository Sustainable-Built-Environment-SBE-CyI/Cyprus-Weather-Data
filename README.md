# Cyprus Weather: LIMASSOL and TEPAK

This repository records current observations for the Cyprus Department of
Meteorology station codes:

- `LIMASSOL`
- `TEPAK`

## Two collection modes

### Cloud collection through GitHub Actions

`.github/workflows/collect-weather.yml` runs in GitHub and therefore does not
depend on the user's laptop being powered on.

It updates:

```text
data/history/LIMASSOL_TEPAK_history_wide.csv
data/history/LIMASSOL_history_wide.csv
data/history/TEPAK_history_wide.csv
data/latest/LIMASSOL_TEPAK_latest_wide.csv
data/monthly/YYYY/LIMASSOL_TEPAK_YYYY-MM.csv
data/collection_status.json
```

The scheduled workflow runs at 2, 12, 22, 32, 42 and 52 minutes past each UTC
hour. GitHub may occasionally delay scheduled jobs, so this is continuous
cloud collection but not a guaranteed real-time scientific acquisition
service.

### Local collection

`cyprus_weather_logger.py` stores all available stations in a local SQLite
database and maintains separate CSV files for LIMASSOL and TEPAK.

Run locally:

```powershell
uv run --python 3.14 python cyprus_weather_logger.py
```

## Publish to your GitHub account

From the VS Code terminal:

```powershell
winget install --id GitHub.cli
```

Close and reopen VS Code, then:

```powershell
gh auth login
```

Choose:

- GitHub.com
- HTTPS
- Login with a web browser

Then publish:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\publish_to_github.ps1
```

The default repository name is:

```text
cyprus-weather-limassol-tepak
```

The script creates it as a private repository. To create a public repository:

```powershell
.\publish_to_github.ps1 -Visibility public
```

## Activate cloud collection

After publishing:

1. Open the repository on GitHub.
2. Open **Actions**.
3. Select **Collect Cyprus weather**.
4. Select **Run workflow**.
5. Confirm that the first run is successful.

If the workflow cannot push its CSV updates:

1. Open **Settings > Actions > General**.
2. Find **Workflow permissions**.
3. Select **Read and write permissions**.
4. Save and run the workflow again.

## Historical boundary

The public live endpoint provides current observations, not a queryable
10-minute archive. This repository can therefore collect exact observations
only from the first successful workflow run onward.

It cannot reconstruct the complete 10-minute LIMASSOL and TEPAK record from
1 January 2026. Official archived observations for the missing period must be
obtained separately and can later be imported into the CSV structure.

## Data quality

The source observations are preliminary. Retain timestamps, inspect missing
periods and perform quality control before using the data in research or
ENVI-met forcing.

# DISA STIGs Library Downloader

> **NOTE:** This downloader targets the single "All SRG-STIGs Public (U)" compilation ZIP. It probes recent months for the current archive name (e.g., `U_SRG-STIG_Library_October_2025.zip`). If DISA changes the naming convention or URL structure, update the probe logic in `disa-stigs-auto-dl.py`.

Fetches the latest SRG-STIG library ZIP from DISA's downloads site without parsing the noisy per-product buttons.

Source page: `https://www.cyber.mil/stigs/downloads`

## What It Does

- Probes `https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/` for `U_SRG-STIG_Library_<Month>_<Year>.zip` across recent months.
- Builds a manifest (`reports/disa-stigs-manifest.csv`) with the discovered URL (or marks as skipped if none found).
- Downloads the ZIP into `source-content/disa-stigs/`.
- Writes a download report (`reports/disa-stigs-download-results.csv`).

## Requirements

Install from the repo root:

```bash
pip install -r requirements.txt
```

Playwright is not required for DISA STIGs.

## How to Run

From the repo root via the main menu:

```bash
python scripts/comply-with-me.py
```

Or run standalone:

```bash
python scripts/disa-stigs-auto-dl/disa-stigs-auto-dl.py
```

Manifest only (no download):

```bash
python scripts/disa-stigs-auto-dl/disa-stigs-auto-dl.py --skip-download
```

Options:
- `--verbose` for debug output

## Outputs

- Manifest: `scripts/disa-stigs-auto-dl/reports/disa-stigs-manifest.csv`
- Download report: `scripts/disa-stigs-auto-dl/reports/disa-stigs-download-results.csv`
- File: `source-content/disa-stigs/`

## Known Notes

- The probe checks a rolling window of recent months. If the archive moves or the naming convention changes, update `probe_library_url` in the script.

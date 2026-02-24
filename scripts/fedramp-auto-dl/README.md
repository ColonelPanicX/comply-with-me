# FedRAMP Rev 5 Documents & Templates Downloader

> **NOTE:** The page contains many non-file links (navigation, blog posts, etc.). The script downloads all detectable files with allowed extensions. Non-downloadable links are marked as skipped in the manifest.

Fetches the FedRAMP Rev 5 documents and templates page and downloads all linked assets with supported extensions (PDF, DOC, DOCX, XLS, XLSX, ZIP).

Source page: `https://www.fedramp.gov/rev5/documents-templates/`

## What It Does

- Fetches the page via `requests`; falls back to Playwright headless if blocked.
- Extracts all `<a href>` links and filters to allowed extensions.
- Writes a manifest (`reports/fedramp-manifest.csv`) listing all links.
- Compares against existing files in `source-content/fedramp/` to detect new items.
- Downloads new files directly into `source-content/fedramp/`.
- Writes a download report (`reports/fedramp-download-results.csv`).

## Requirements

Install from the repo root:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## How to Run

From the repo root via the main menu:

```bash
python scripts/comply-with-me.py
```

Or run standalone:

```bash
python scripts/fedramp-auto-dl/fedramp-auto-dl.py
```

Manifest only (no download):

```bash
python scripts/fedramp-auto-dl/fedramp-auto-dl.py --skip-download
```

Options:
- `--download-workers N` (default 4)
- `--verbose` for debug output

## Outputs

- Manifest: `scripts/fedramp-auto-dl/reports/fedramp-manifest.csv`
- Download report: `scripts/fedramp-auto-dl/reports/fedramp-download-results.csv`
- Files: `source-content/fedramp/`

## Known Notes

- Non-file links are expected and will appear in the manifest/report as `N/A`.
- If the page structure or URLs change, link selectors may need minor updates.

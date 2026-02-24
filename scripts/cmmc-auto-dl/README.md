# CMMC Resources Downloader

> **NOTE:** The DoD portal blocks three PDFs when fetched headlessly. The script downloads 17/20 expected PDFs. The remaining files require manual download:
> - `CMMC-FAQsv3.pdf`
> - `CMMC-101-Nov2025.pdf`
> - `FulcrumAdvStrat.pdf`
>
> Download them manually via a browser and place them in `source-content/cmmc/`.

Uses Playwright (headless Chromium) to scrape and download documents from the CMMC Resources page:
`https://dodcio.defense.gov/cmmc/Resources-Documentation/`

## What It Does

- Loads the resources page in a browser context to bypass basic 403 blocks.
- Scrapes links from "Internal Resources" and "External Resources" (skips "Additional Resources").
- Writes a manifest (`reports/cmmc-manifest.csv`) with all links; marks non-downloadables as `N/A`.
- Downloads allowed file types (PDF/DOC/DOCX) into `source-content/cmmc/`.
- Produces a download report (`reports/cmmc-download-results.csv`) showing successes and failures.

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
python scripts/cmmc-auto-dl/cmmc-auto-dl.py
```

Manifest only (no download):

```bash
python scripts/cmmc-auto-dl/cmmc-auto-dl.py --skip-download
```

## Outputs

- Manifest: `scripts/cmmc-auto-dl/reports/cmmc-manifest.csv`
- Download report: `scripts/cmmc-auto-dl/reports/cmmc-download-results.csv`
- Files: `source-content/cmmc/`

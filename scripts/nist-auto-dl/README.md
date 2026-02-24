# NIST Final & Draft Publications Downloader

> **NOTE:** The crawlers rely on live CSRC pages (`csrc.nist.gov`). If the site structure changes, manifests and downloads may need selector updates. Items without a direct download link are marked `N/A` in the manifest.

Two scripts — one for final publications, one for drafts.

- `nist-finals-auto-dl.py` — crawls `https://csrc.nist.gov/publications/final-pubs`
- `nist-drafts-auto-dl.py` — crawls `https://csrc.nist.gov/publications/draft-pubs`

`nist-final-pubs-urls.xlsx` is a seed URL list used by the finals downloader to resolve individual publication pages.

## What They Do

- Fetch the CSRC listing pages via HTTP (requests + BeautifulSoup).
- Build manifests with detail URLs and download URLs.
- Download PDFs into `source-content/nist/` organized by series (SP, CSWP, AI, etc.).
- Write reports summarizing results.

## Requirements

Install from the repo root:

```bash
pip install -r requirements.txt
```

Playwright is not required for NIST.

## How to Run

From the repo root via the main menu:

```bash
python scripts/comply-with-me.py
```

Or run standalone:

```bash
# Finals
python scripts/nist-auto-dl/nist-finals-auto-dl.py

# Drafts
python scripts/nist-auto-dl/nist-drafts-auto-dl.py
```

Manifest only (no download):

```bash
python scripts/nist-auto-dl/nist-finals-auto-dl.py --skip-download
python scripts/nist-auto-dl/nist-drafts-auto-dl.py --skip-download
```

Options:
- `--max-pages N` — limit listing pages (useful for testing)

## Outputs

Finals:
- Manifest: `scripts/nist-auto-dl/reports/manifest.csv`
- Download report: `scripts/nist-auto-dl/reports/download-results.csv`
- Files: `source-content/nist/final-pubs/<series>/`

Drafts:
- Manifest: `scripts/nist-auto-dl/reports/drafts/draft-manifest.csv`
- Download report: `scripts/nist-auto-dl/reports/drafts/draft-download-results.csv`
- Files: `source-content/nist/draft-pubs/<series>/`

## Known Limitations

- A handful of publications have no direct PDF link on CSRC; those are marked `N/A`.
- If the CSRC listing HTML changes, selectors may need updates.

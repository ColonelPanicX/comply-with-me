# Comply With Me

A CLI tool for downloading and syncing compliance framework documentation from official sources. Supports NIST, FedRAMP, CMMC, and DISA STIGs with smart diff-based sync — only pulls what's new since the last run.

## Supported Frameworks

| Framework | Source | Notes |
|---|---|---|
| NIST Final Publications | csrc.nist.gov | SP, CSWP, AI series |
| NIST Draft Publications | csrc.nist.gov | IPD, 2PD series |
| FedRAMP Rev 5 | fedramp.gov | Documents and templates |
| CMMC | dodcio.defense.gov | 17/20 PDFs automated; 3 require manual download |
| DISA STIGs | dl.dod.cyber.mil | Full SRG-STIG library ZIP |

## Requirements

Python 3.9+

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Quick Start

```bash
python scripts/comply-with-me.py
```

Select a framework from the menu (or download all), confirm the diff, and the tool handles the rest. Downloaded files land in `source-content/<framework>/`.

## Running Individual Downloaders

Each downloader can also be run standalone. See the `README.md` in each subfolder:

- `scripts/cmmc-auto-dl/`
- `scripts/fedramp-auto-dl/`
- `scripts/nist-auto-dl/`
- `scripts/disa-stigs-auto-dl/`

## Known Limitations

- **CMMC:** Three PDFs (`CMMC-FAQsv3.pdf`, `CMMC-101-Nov2025.pdf`, `FulcrumAdvStrat.pdf`) are blocked by the DoD portal in headless mode. Download them manually and place in `source-content/cmmc/`.
- **NIST:** A small number of publications have no direct download link on CSRC; these are marked `N/A` in the manifest.
- **DISA STIGs:** The probe window covers recent months. If DISA changes the archive naming convention, the probe logic in `disa-stigs-auto-dl.py` will need updating.

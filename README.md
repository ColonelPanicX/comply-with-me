# Comply With Me

A self-contained Python tool for downloading and syncing compliance framework documentation from official sources. Tracks what you already have and only pulls what's new — no manual bookmarking, no hunting for PDFs.

## Supported Frameworks

| Framework | Source | Coverage |
|---|---|---|
| FedRAMP Rev 5 | fedramp.gov | Documents and templates |
| NIST Final Publications | csrc.nist.gov | SP, CSWP, AI series |
| NIST Draft Publications | csrc.nist.gov | IPD, 2PD series |
| CMMC | dodcio.defense.gov | Full document library |
| DISA STIGs | dl.dod.cyber.mil | Full SRG/STIG library (ZIP) |
| CISA Binding Operational Directives | cisa.gov | All BODs and implementation guidance (HTML) |

## Requirements

Python 3.9 or later. That's it — the tool handles everything else itself.

## Quick Start

```bash
python3 comply_with_me.py
```

On first run, the tool will:

1. Create a local virtual environment (`.cwm-venv/`) next to the script
2. Install its own dependencies into that environment
3. Launch the menu

Every run after that goes straight to the menu — no activation, no setup.

> **Debian/Ubuntu note:** If you see a message about `ensurepip`, run:
> ```bash
> sudo apt install python3.12-venv   # adjust version to match your Python
> ```
> Then run `python3 comply_with_me.py` again.

## Usage

```
Comply With Me
----------------------------------------------------
  1. FedRAMP                          36 files  37.5 MB  last synced 2026-02-25
  2. NIST Final Publications          653 files  2.1 GB  last synced 2026-02-25
  3. NIST Draft Publications           92 files  146.0 MB  last synced 2026-02-25
  4. CMMC                              17 files  18.3 MB  last synced 2026-02-25
  5. DISA STIGs                         1 files  350.0 MB  last synced 2026-02-25
  6. CISA Binding Operational Directives  17 files  0.5 MB  last synced 2026-02-25

  7. Sync All
  8. Normalize Downloaded Documents
  0. Quit

Select:
```

Select a number to sync that framework, choose **Sync All** to pull everything at once, or choose **Normalize Downloaded Documents** to convert your downloaded files to Markdown and JSON.

Downloaded files land in `source-content/<framework>/`. The tool skips files it already has and only downloads what's changed or new.

## Normalization

The **Normalize** option converts downloaded documents into machine-readable formats suitable for AI pipelines, RAG systems, and MCP servers:

- **PDF files** — text extracted page-by-page via [pymupdf](https://pymupdf.readthedocs.io/)
- **HTML files** — main content extracted and structured by heading via BeautifulSoup

Each source file produces two output files side-by-side in `normalized-content/`:

| File | Purpose |
|---|---|
| `<stem>.md` | Human-readable Markdown with YAML frontmatter |
| `<stem>.json` | Machine-readable JSON with sections, full text, and metadata |

**JSON schema:**
```json
{
  "source_file": "ModelOverviewv2.pdf",
  "framework": "cmmc",
  "extracted_at": "2026-02-26T14:30:00",
  "sections": [
    { "heading": "Page 1", "level": 1, "content": "..." }
  ],
  "full_text": "Complete concatenated text..."
}
```

> **Note:** DISA STIGs are excluded from v1 normalization — their XCCDF XML structure requires a dedicated parser.

## How It Works

- **State tracking:** A `.cwm-state.json` file in `source-content/` records the hash and metadata of every downloaded file. On each sync, files are compared by hash — unchanged files are skipped.
- **Normalization:** Already-normalized files are skipped on re-runs. Use the normalize option again after syncing new documents to catch additions.
- **CMMC fallback:** The DoD portal uses WAF protection that blocks automated scrapers. The tool first attempts a live scrape; if that fails, it falls back to a curated list of known PDF URLs. A notice is printed when the fallback is used, along with the date the list was last verified.
- **DISA STIGs:** Downloads the full SRG/STIG archive ZIP from the DoD Cyber Exchange. This is a large file (~350 MB).

## Output Structure

```
source-content/
├── .cwm-state.json
├── fedramp/
├── nist/
│   ├── final-pubs/
│   └── draft-pubs/
├── cmmc/
├── disa-stigs/
└── cisa-bod/

normalized-content/
├── fedramp/
│   ├── fedramp-rev5-baselines.md
│   └── fedramp-rev5-baselines.json
├── nist/
│   ├── final-pubs/
│   └── draft-pubs/
├── cmmc/
└── cisa-bod/
```

## Known Limitations

- **DISA STIGs:** The probe logic searches recent months for the current archive. If DISA changes their naming convention, the downloader may need an update.
- **CMMC:** If live scraping fails and the fallback URL list is stale, some newer documents may be missed. The tool prints a notice with the verification date when this occurs.
- **NIST:** A small number of publications have no direct download link on CSRC and will be skipped.
- **Normalization — scanned PDFs:** PDFs that are image-only (no text layer) will produce empty or minimal output. OCR support is not included in v1.

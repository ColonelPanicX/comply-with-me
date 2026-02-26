"""Normalize downloaded compliance documents to Markdown and JSON.

Supported source formats:
  - PDF  (.pdf)  — text extracted page-by-page via pymupdf
  - HTML (.html) — main content extracted via BeautifulSoup

Unsupported formats are skipped with a notice (ZIP, DOCX, XLSX, XML).
DISA STIGs are excluded from v1 normalization — their XCCDF XML structure
requires a dedicated parser (future work).

Output (per source file, mirroring source subdir structure):
  normalized-content/<subdir>/<stem>.md
  normalized-content/<subdir>/<stem>.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Frameworks excluded from v1 normalization
SKIP_SUBDIRS: set[str] = {"disa-stigs"}

# File extensions this normalizer handles
PDF_EXTENSIONS = {".pdf"}
HTML_EXTENSIONS = {".html", ".htm"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | HTML_EXTENSIONS

# Extensions that are present in source dirs but intentionally skipped
KNOWN_UNSUPPORTED = {".zip", ".doc", ".docx", ".xlsx", ".xls", ".xml"}

# Files to always ignore (state files, hidden files, READMEs)
IGNORE_NAMES = {".cwm-state.json", "README.md"}


@dataclass
class NormalizeResult:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.processed) + len(self.skipped) + len(self.errors)


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _extract_pdf(path: Path) -> list[dict]:
    """Extract text from a PDF, returning one section per page.

    Requires pymupdf (imported as fitz).
    """
    import fitz  # type: ignore[import]

    sections: list[dict] = []
    try:
        doc = fitz.open(str(path))
        for page_num, page in enumerate(doc, 1):
            text = page.get_text().strip()
            if text:
                sections.append({
                    "heading": f"Page {page_num}",
                    "level": 1,
                    "content": text,
                })
        doc.close()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pymupdf failed to open {path.name}: {exc}") from exc

    return sections


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def _extract_html(path: Path) -> list[dict]:
    """Extract structured sections from a saved HTML page.

    Looks for the main content area (tries <main>, role=main, <article>,
    then falls back to <body>). Builds sections from heading tags.
    """
    from bs4 import BeautifulSoup, Tag

    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc

    soup = BeautifulSoup(html, "html.parser")

    # Find the most specific main content container available
    container: Optional[Tag] = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.body
    )
    if container is None:
        raw = soup.get_text(separator="\n", strip=True)
        return [{"heading": path.stem, "level": 1, "content": raw}]

    # Walk elements building heading-delimited sections
    sections: list[dict] = []
    current_heading = path.stem
    current_level = 1
    current_lines: list[str] = []

    HEADING_TAGS = {"h1", "h2", "h3", "h4"}
    CONTENT_TAGS = {"p", "li", "td", "th", "figcaption", "blockquote"}

    for element in container.find_all(HEADING_TAGS | CONTENT_TAGS):
        if element.name in HEADING_TAGS:
            # Flush previous section
            body = "\n".join(current_lines).strip()
            if body:
                sections.append({
                    "heading": current_heading,
                    "level": current_level,
                    "content": body,
                })
            current_heading = element.get_text(separator=" ", strip=True)
            current_level = int(element.name[1])
            current_lines = []
        else:
            text = element.get_text(separator=" ", strip=True)
            if text:
                current_lines.append(text)

    # Flush final section
    body = "\n".join(current_lines).strip()
    if body:
        sections.append({
            "heading": current_heading,
            "level": current_level,
            "content": body,
        })

    # If nothing structured was found, fall back to raw text
    if not sections:
        raw = container.get_text(separator="\n", strip=True)
        if raw:
            sections.append({"heading": path.stem, "level": 1, "content": raw})

    return sections


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_markdown(
    sections: list[dict],
    framework: str,
    source_file: str,
    extracted_at: str,
    dest: Path,
) -> None:
    lines: list[str] = [
        "---",
        f"source_file: {source_file}",
        f"framework: {framework}",
        f"extracted_at: \"{extracted_at}\"",
        "---",
        "",
        f"# {Path(source_file).stem}",
        "",
    ]
    for section in sections:
        prefix = "#" * min(section["level"] + 1, 6)
        heading = section["heading"]
        content = section["content"]
        lines += [f"{prefix} {heading}", "", content, ""]

    dest.write_text("\n".join(lines), encoding="utf-8")


def _write_json(
    sections: list[dict],
    framework: str,
    source_file: str,
    extracted_at: str,
    dest: Path,
) -> None:
    full_text = "\n\n".join(s["content"] for s in sections)
    payload = {
        "source_file": source_file,
        "framework": framework,
        "extracted_at": extracted_at,
        "sections": sections,
        "full_text": full_text,
    }
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-file normalization
# ---------------------------------------------------------------------------


def _normalize_file(
    source_path: Path,
    output_subdir: Path,
    framework: str,
    force: bool,
) -> tuple[str, str]:
    """Normalize a single source file. Returns (status, message).

    status is one of: "processed", "skipped", "unsupported", "error"
    """
    name = source_path.name
    ext = source_path.suffix.lower()

    if ext in KNOWN_UNSUPPORTED:
        return "unsupported", name

    if ext not in SUPPORTED_EXTENSIONS:
        return "unsupported", name

    stem = source_path.stem
    md_dest = output_subdir / f"{stem}.md"
    json_dest = output_subdir / f"{stem}.json"

    if not force and md_dest.exists() and json_dest.exists():
        return "skipped", name

    try:
        if ext in PDF_EXTENSIONS:
            sections = _extract_pdf(source_path)
        else:
            sections = _extract_html(source_path)
    except RuntimeError as exc:
        return "error", str(exc)

    if not sections:
        return "error", f"{name}: no text content extracted"

    extracted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    output_subdir.mkdir(parents=True, exist_ok=True)

    try:
        _write_markdown(sections, framework, name, extracted_at, md_dest)
        _write_json(sections, framework, name, extracted_at, json_dest)
    except OSError as exc:
        return "error", f"{name}: write failed: {exc}"

    return "processed", name


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def normalize_all(
    source_dir: Path,
    output_dir: Path,
    force: bool = False,
    progress_callback=None,
) -> NormalizeResult:
    """Walk source_dir by framework subdir and normalize all supported files.

    progress_callback(framework_key, filename) is called before each file
    if provided — useful for live CLI progress reporting.
    """
    from comply_with_me.downloaders import SERVICES

    result = NormalizeResult()

    for svc in SERVICES:
        if svc.subdir in SKIP_SUBDIRS:
            continue

        svc_source = source_dir / svc.subdir
        if not svc_source.exists():
            continue

        svc_output = output_dir / svc.subdir

        for source_path in sorted(svc_source.rglob("*")):
            if not source_path.is_file():
                continue
            if source_path.name in IGNORE_NAMES or source_path.name.startswith("."):
                continue

            if progress_callback:
                progress_callback(svc.key, source_path.name)

            status, msg = _normalize_file(source_path, svc_output, svc.key, force)

            if status == "processed":
                result.processed.append(msg)
            elif status == "skipped":
                result.skipped.append(msg)
            elif status == "unsupported":
                result.unsupported.append(msg)
            else:
                result.errors.append((msg, "extraction failed"))

    return result

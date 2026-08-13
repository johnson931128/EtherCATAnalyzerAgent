"""Deterministic page-level PDF to Markdown specification ingestion."""

import json
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF

from core.config import REPOSITORY_ROOT, SPEC_GENERATED_ROOT, SPEC_ORIGINAL_ROOT
from retrieval.pdf_spec import resolve_spec_pdf


def _relative_to_repository(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def _document_metadata(metadata: Optional[Dict[str, object]]) -> Dict[str, object]:
    if not metadata:
        return {}
    return {
        str(key): metadata[key]
        for key in sorted(metadata, key=lambda item: str(item))
    }


def _page_markdown(
    spec_name: str,
    source_name: str,
    page_number: int,
    text: str,
) -> str:
    return (
        "---\n"
        f"source: {source_name}\n"
        f"spec: {spec_name}\n"
        f"pdf_page: {page_number}\n"
        "---\n\n"
        f"# PDF Page {page_number}\n\n"
        f"{text}"
    )


def _write_manifest(manifest_path: Path, manifest: Dict[str, object]) -> None:
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ingest_spec(
    spec_name: str,
    original_root: Optional[Path] = None,
    generated_root: Optional[Path] = None,
) -> Dict[str, object]:
    """Convert exactly one specification PDF into deterministic page Markdown."""
    if not isinstance(spec_name, str):
        raise ValueError("Specification name must be a non-empty directory name")
    normalized_name = spec_name.strip()
    source_pdf = resolve_spec_pdf(
        normalized_name,
        original_root or SPEC_ORIGINAL_ROOT,
    )
    output_root = (
        Path(generated_root)
        if generated_root is not None
        else SPEC_GENERATED_ROOT
    )
    output_directory = output_root / normalized_name
    pages_directory = output_directory / "pages"
    manifest_path = output_directory / "manifest.json"
    pages_directory.mkdir(parents=True, exist_ok=True)

    for page_path in pages_directory.glob("page_*.md"):
        if page_path.is_file():
            page_path.unlink()

    generated_pages: List[str] = []
    extraction_failures: List[Dict[str, object]] = []

    try:
        document = fitz.open(str(source_pdf))
    except Exception as exc:
        raise RuntimeError(f"Could not open specification PDF: {source_pdf}") from exc

    try:
        document_metadata = _document_metadata(document.metadata)
        total_pages = len(document)
        for index in range(total_pages):
            page_number = index + 1
            try:
                text = document[index].get_text()
                page_path = pages_directory / f"page_{page_number:03d}.md"
                page_path.write_text(
                    _page_markdown(
                        normalized_name,
                        source_pdf.name,
                        page_number,
                        text,
                    ),
                    encoding="utf-8",
                )
                generated_pages.append(_relative_to_repository(page_path))
            except Exception as exc:
                extraction_failures.append(
                    {"pdf_page": page_number, "error": str(exc)}
                )
    finally:
        document.close()

    manifest: Dict[str, object] = {
        "spec": normalized_name,
        "source_filename": source_pdf.name,
        "source_relative_path": _relative_to_repository(source_pdf),
        "generated_output_relative_path": _relative_to_repository(
            output_root / normalized_name
        ),
        "generated_manifest_relative_path": _relative_to_repository(manifest_path),
        "generated_pages_relative_paths": generated_pages,
        "total_pdf_pages": total_pages,
        "successfully_generated_page_count": len(generated_pages),
        "extraction_failures": extraction_failures,
        "document_metadata": document_metadata,
    }
    _write_manifest(manifest_path, manifest)
    return manifest

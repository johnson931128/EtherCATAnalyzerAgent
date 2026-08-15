"""Docling PDF-to-Markdown specification ingestion."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.object_detection_engine_options import (
    TransformersObjectDetectionEngineOptions,
)
from docling.datamodel.pipeline_options import (
    LayoutObjectDetectionOptions,
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from core.config import REPOSITORY_ROOT, SPEC_GENERATED_ROOT, SPEC_ORIGINAL_ROOT


def _resolve_spec_pdf(spec_name: str, original_root: Path) -> Path:
    if not isinstance(spec_name, str) or not spec_name.strip():
        raise ValueError("Specification name must be a non-empty directory name")

    normalized_name = spec_name.strip()
    relative_name = Path(normalized_name)
    if (
        relative_name.is_absolute()
        or len(relative_name.parts) != 1
        or relative_name.parts[0] in {".", ".."}
    ):
        raise ValueError("Specification name must be a single directory name")

    spec_directory = original_root / normalized_name
    if not spec_directory.is_dir():
        raise FileNotFoundError(
            f"Specification directory not found: {spec_directory}"
        )

    pdf_paths = sorted(
        (
            path
            for path in spec_directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: path.name.casefold(),
    )
    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDF found in specification directory: {spec_directory}"
        )
    if len(pdf_paths) > 1:
        names = ", ".join(path.name for path in pdf_paths)
        raise RuntimeError(
            "Ambiguous specification source: expected exactly one PDF in "
            f"{spec_directory}, found {len(pdf_paths)} ({names})"
        )

    return pdf_paths[0]


def _relative_to_repository(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def _document_metadata(document: object) -> Dict[str, object]:
    origin = getattr(document, "origin", None)
    if origin is None or not hasattr(origin, "model_dump"):
        return {}

    metadata = origin.model_dump(mode="json", exclude_none=True)
    if not isinstance(metadata, dict):
        return {}
    return {
        str(key): metadata[key]
        for key in sorted(metadata, key=lambda item: str(item))
    }


def _normalize_markdown(markdown: str) -> str:
    normalized = re.sub(r"(?m)^- -(?=\S)", "  - ", markdown)
    return normalized.rstrip() + "\n"


def _build_pipeline_options() -> PdfPipelineOptions:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.layout_options = LayoutObjectDetectionOptions.from_preset(
        "layout_heron_default",
        engine_options=TransformersObjectDetectionEngineOptions(
            compile_model=False,
        ),
    )

    artifacts_path = os.environ.get("DOCLING_ARTIFACTS_PATH", "").strip()
    if artifacts_path:
        pipeline_options.artifacts_path = Path(artifacts_path)

    return pipeline_options


def _create_converter() -> DocumentConverter:
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=_build_pipeline_options(),
            ),
        }
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
    """Convert exactly one specification PDF into one readable Markdown file."""
    if not isinstance(spec_name, str):
        raise ValueError("Specification name must be a non-empty directory name")
    normalized_name = spec_name.strip()
    source_pdf = _resolve_spec_pdf(
        normalized_name,
        Path(original_root) if original_root is not None else SPEC_ORIGINAL_ROOT,
    )
    output_root = (
        Path(generated_root)
        if generated_root is not None
        else SPEC_GENERATED_ROOT
    )
    output_directory = output_root / normalized_name
    output_path = output_directory / f"{normalized_name}.md"
    manifest_path = output_directory / "manifest.json"
    stale_pages_directory = output_directory / "pages"

    converter = _create_converter()
    try:
        conversion_result = converter.convert(source_pdf)
        document = conversion_result.document
        markdown = _normalize_markdown(document.export_to_markdown())
    except Exception as exc:
        raise RuntimeError(
            f"Docling conversion failed for {source_pdf}: {exc}"
        ) from exc

    if stale_pages_directory.is_dir():
        shutil.rmtree(stale_pages_directory)

    output_directory.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    manifest: Dict[str, object] = {
        "spec": normalized_name,
        "source_filename": source_pdf.name,
        "source_relative_path": _relative_to_repository(source_pdf),
        "output_relative_path": _relative_to_repository(output_path),
        "manifest_relative_path": _relative_to_repository(manifest_path),
        "converter": "docling",
        "conversion_status": "completed",
        "document_metadata": _document_metadata(document),
    }
    _write_manifest(manifest_path, manifest)
    return manifest

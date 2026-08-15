import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from workflows.spec_ingestion import (
    _build_pipeline_options,
    _resolve_spec_pdf,
    ingest_spec,
)


class SpecIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.repository_root = Path(self.temp_directory.name)
        self.original_root = self.repository_root / "spec" / "original"
        self.generated_root = self.repository_root / "spec" / "generated"
        (self.original_root / "ET1100").mkdir(parents=True)
        self.generated_root.mkdir(parents=True)

    def _write_pdf(self, filename="ET1100 v2.5.pdf"):
        pdf_path = self.original_root / "ET1100" / filename
        pdf_path.write_bytes(b"%PDF-1.4\nmock fixture\n")
        return pdf_path

    def _mock_converter(self, markdown="# ET1100\n\nReadable evidence\n"):
        document = Mock()
        document.export_to_markdown.return_value = markdown
        document.origin.model_dump.return_value = {
            "binary_hash": 12345,
            "filename": "ET1100 v2.5.pdf",
            "mimetype": "application/pdf",
        }
        converter = Mock()
        converter.convert.return_value = SimpleNamespace(document=document)
        return converter, document

    def _ingest(self, converter=None):
        if converter is None:
            converter, _ = self._mock_converter()
        with (
            patch(
                "workflows.spec_ingestion.REPOSITORY_ROOT",
                self.repository_root,
            ),
            patch(
                "workflows.spec_ingestion._create_converter",
                return_value=converter,
            ),
        ):
            return ingest_spec(
                "ET1100",
                original_root=self.original_root,
                generated_root=self.generated_root,
            )

    def test_no_pdf_fails_for_resolution_and_ingestion(self):
        with self.assertRaises(FileNotFoundError):
            _resolve_spec_pdf("ET1100", self.original_root)

        with self.assertRaises(FileNotFoundError):
            self._ingest()

    def test_multiple_pdfs_fail_as_ambiguous_source(self):
        self._write_pdf("first.pdf")
        self._write_pdf("second.pdf")

        with self.assertRaisesRegex(RuntimeError, "Ambiguous specification source"):
            _resolve_spec_pdf("ET1100", self.original_root)

        with self.assertRaisesRegex(RuntimeError, "Ambiguous specification source"):
            self._ingest()

    def test_single_pdf_resolution(self):
        source_pdf = self._write_pdf()

        self.assertEqual(
            _resolve_spec_pdf("ET1100", self.original_root),
            source_pdf,
        )

    def test_single_pdf_creates_one_markdown_output(self):
        source_pdf = self._write_pdf()
        converter, document = self._mock_converter(
            "## 7 FMMU\n\nReadable FMMU evidence\n"
        )

        manifest = self._ingest(converter)
        output_path = self.generated_root / "ET1100" / "ET1100.md"

        converter.convert.assert_called_once_with(source_pdf)
        document.export_to_markdown.assert_called_once_with()
        self.assertEqual(
            output_path.read_text(encoding="utf-8"),
            "## 7 FMMU\n\nReadable FMMU evidence\n",
        )
        self.assertEqual(
            manifest["output_relative_path"],
            "spec/generated/ET1100/ET1100.md",
        )

    def test_manifest_uses_docling_single_output_schema(self):
        source_pdf = self._write_pdf()

        manifest = self._ingest()
        manifest_path = self.generated_root / "ET1100" / "manifest.json"
        persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest, persisted_manifest)
        self.assertEqual(
            set(manifest),
            {
                "spec",
                "source_filename",
                "source_relative_path",
                "output_relative_path",
                "manifest_relative_path",
                "converter",
                "conversion_status",
                "document_metadata",
            },
        )
        self.assertEqual(manifest["spec"], "ET1100")
        self.assertEqual(manifest["source_filename"], source_pdf.name)
        self.assertEqual(
            manifest["source_relative_path"],
            "spec/original/ET1100/ET1100 v2.5.pdf",
        )
        self.assertEqual(manifest["converter"], "docling")
        self.assertEqual(manifest["conversion_status"], "completed")
        self.assertEqual(
            manifest["document_metadata"],
            {
                "binary_hash": 12345,
                "filename": "ET1100 v2.5.pdf",
                "mimetype": "application/pdf",
            },
        )

    def test_successful_ingestion_removes_stale_page_output(self):
        self._write_pdf()
        pages_directory = self.generated_root / "ET1100" / "pages"
        pages_directory.mkdir(parents=True)
        (pages_directory / "page_001.md").write_text("stale", encoding="utf-8")
        (pages_directory / "page_999.md").write_text("stale", encoding="utf-8")

        self._ingest()

        self.assertFalse(pages_directory.exists())
        self.assertTrue(
            (self.generated_root / "ET1100" / "ET1100.md").is_file()
        )

    def test_docling_conversion_failure_is_reported_with_context(self):
        source_pdf = self._write_pdf()
        converter = Mock()
        converter.convert.side_effect = ValueError("layout failed")

        with self.assertRaisesRegex(
            RuntimeError,
            rf"Docling conversion failed for {re.escape(str(source_pdf))}.*layout failed",
        ):
            self._ingest(converter)

    def test_pipeline_disables_ocr_and_compile(self):
        with patch.dict(os.environ, {}, clear=True):
            pipeline_options = _build_pipeline_options()

        self.assertFalse(pipeline_options.do_ocr)
        self.assertTrue(pipeline_options.do_table_structure)
        self.assertFalse(
            pipeline_options.layout_options.engine_options.compile_model
        )
        self.assertIsNone(pipeline_options.artifacts_path)

    def test_pipeline_uses_local_artifacts_path_override(self):
        artifacts_path = self.repository_root / "docling-models"
        with patch.dict(
            os.environ,
            {"DOCLING_ARTIFACTS_PATH": str(artifacts_path)},
        ):
            pipeline_options = _build_pipeline_options()

        self.assertEqual(pipeline_options.artifacts_path, artifacts_path)

    def test_nested_list_artifact_is_normalized_without_other_cleanup(self):
        self._write_pdf()
        converter, _ = self._mock_converter(
            "- Buffered mode\n- -The buffered mode preserves data.\n"
        )

        self._ingest(converter)
        markdown = (
            self.generated_root / "ET1100" / "ET1100.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            markdown,
            "- Buffered mode\n  - The buffered mode preserves data.\n",
        )


if __name__ == "__main__":
    unittest.main()

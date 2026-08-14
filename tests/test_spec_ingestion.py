import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from retrieval.pdf_spec import resolve_spec_pdf
from workflows.spec_ingestion import ingest_spec


class SpecIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.repository_root = Path(self.temp_directory.name)
        self.original_root = self.repository_root / "spec" / "original"
        self.generated_root = self.repository_root / "spec" / "generated"
        (self.original_root / "ET1100").mkdir(parents=True)
        self.generated_root.mkdir(parents=True)

    def _write_pdf(self, page_texts, filename="ET1100 v2.5.pdf"):
        pdf_path = self.original_root / "ET1100" / filename
        if pdf_path.exists():
            pdf_path.unlink()

        document = fitz.open()
        document.set_metadata({"title": "Temporary ET1100 fixture"})
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(str(pdf_path))
        document.close()
        return pdf_path

    def _ingest(self):
        with patch("workflows.spec_ingestion.REPOSITORY_ROOT", self.repository_root):
            return ingest_spec(
                "ET1100",
                original_root=self.original_root,
                generated_root=self.generated_root,
            )

    def test_no_pdf_fails_for_resolution_and_ingestion(self):
        with self.assertRaises(FileNotFoundError):
            resolve_spec_pdf("ET1100", self.original_root)

        with self.assertRaises(FileNotFoundError):
            self._ingest()

    def test_multiple_pdfs_fail_as_ambiguous_source(self):
        self._write_pdf(["first"], filename="first.pdf")
        self._write_pdf(["second"], filename="second.pdf")

        with self.assertRaisesRegex(RuntimeError, "Ambiguous specification source"):
            resolve_spec_pdf("ET1100", self.original_root)

        with self.assertRaisesRegex(RuntimeError, "Ambiguous specification source"):
            self._ingest()

    def test_single_pdf_creates_manifest_and_page_markdown(self):
        source_pdf = self._write_pdf(["single page evidence"])

        manifest = self._ingest()
        output_directory = self.generated_root / "ET1100"
        page_path = output_directory / "pages" / "page_001.md"

        self.assertEqual(manifest["source_filename"], source_pdf.name)
        self.assertTrue((output_directory / "manifest.json").is_file())
        self.assertTrue(page_path.is_file())
        self.assertEqual(manifest["generated_manifest_relative_path"],
                         "spec/generated/ET1100/manifest.json")

    def test_page_markdown_contains_required_metadata(self):
        source_pdf = self._write_pdf(["metadata evidence"])

        self._ingest()
        page_text = (
            self.generated_root / "ET1100" / "pages" / "page_001.md"
        ).read_text(encoding="utf-8")

        self.assertIn(f"source: {source_pdf.name}", page_text)
        self.assertIn("spec: ET1100", page_text)
        self.assertIn("pdf_page: 1", page_text)
        self.assertIn("# PDF Page 1", page_text)

    def test_extracted_text_is_preserved_in_page_markdown(self):
        evidence = "unique extracted ET1100 evidence"
        self._write_pdf([evidence])

        self._ingest()
        page_text = (
            self.generated_root / "ET1100" / "pages" / "page_001.md"
        ).read_text(encoding="utf-8")

        self.assertIn(evidence, page_text)

    def test_multi_page_output_is_ordered_and_one_based(self):
        page_texts = ["first page evidence", "second page evidence", "third page evidence"]
        self._write_pdf(page_texts)
        manifest = self._ingest()
        page_paths = sorted(
            (self.generated_root / "ET1100" / "pages").glob("page_*.md")
        )

        self.assertEqual(
            [path.name for path in page_paths],
            ["page_001.md", "page_002.md", "page_003.md"],
        )
        self.assertEqual(manifest["total_pdf_pages"], 3)
        for page_number, (page_path, evidence) in enumerate(
            zip(page_paths, page_texts), start=1
        ):
            content = page_path.read_text(encoding="utf-8")
            self.assertIn(f"pdf_page: {page_number}", content)
            self.assertIn(evidence, content)

    def test_reingestion_removes_stale_page_markdown(self):
        source_pdf = self._write_pdf(["old page 1", "old page 2", "old page 3"])
        self._ingest()
        pages_directory = self.generated_root / "ET1100" / "pages"
        self.assertTrue((pages_directory / "page_003.md").exists())

        self._write_pdf(["new page 1"], filename=source_pdf.name)
        manifest = self._ingest()

        self.assertEqual(manifest["successfully_generated_page_count"], 1)
        self.assertEqual(
            [path.name for path in pages_directory.glob("page_*.md")],
            ["page_001.md"],
        )
        self.assertFalse((pages_directory / "page_002.md").exists())
        self.assertFalse((pages_directory / "page_003.md").exists())

    def test_manifest_reports_page_counts_paths_failures_and_metadata(self):
        self._write_pdf(["page one", "page two"])

        manifest = self._ingest()

        expected_keys = {
            "spec",
            "source_filename",
            "source_relative_path",
            "generated_output_relative_path",
            "generated_manifest_relative_path",
            "generated_pages_relative_paths",
            "total_pdf_pages",
            "successfully_generated_page_count",
            "extraction_failures",
            "document_metadata",
        }
        self.assertTrue(expected_keys.issubset(manifest))
        self.assertEqual(manifest["spec"], "ET1100")
        self.assertEqual(manifest["source_relative_path"],
                         "spec/original/ET1100/ET1100 v2.5.pdf")
        self.assertEqual(manifest["generated_output_relative_path"],
                         "spec/generated/ET1100")
        self.assertEqual(manifest["total_pdf_pages"], 2)
        self.assertEqual(manifest["successfully_generated_page_count"], 2)
        self.assertEqual(manifest["extraction_failures"], [])
        self.assertEqual(
            manifest["generated_pages_relative_paths"],
            [
                "spec/generated/ET1100/pages/page_001.md",
                "spec/generated/ET1100/pages/page_002.md",
            ],
        )
        self.assertEqual(
            manifest["document_metadata"]["title"],
            "Temporary ET1100 fixture",
        )


if __name__ == "__main__":
    unittest.main()

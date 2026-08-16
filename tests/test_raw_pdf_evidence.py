import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from agent import engineering_tool_agent
from retrieval.pdf_spec import (
    get_spec_raw_pages,
    search_spec_raw,
)


class RawPdfEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.original_root = Path(self.temp_directory.name) / "spec" / "original"
        self.spec_directory = self.original_root / "ET1100"
        self.spec_directory.mkdir(parents=True)
        self.pdf_path = self.spec_directory / "ET1100 fixture.pdf"
        self._write_pdf(
            [
                "Introduction page",
                "SyncManager control register and register bit definitions",
                "FMMU logical start bit and register table",
                "Unrelated page",
                "Another unrelated page",
                "Sixth page",
            ]
        )
        self.original_root_patch = patch(
            "retrieval.pdf_spec.SPEC_ORIGINAL_ROOT", self.original_root
        )
        self.original_root_patch.start()
        self.addCleanup(self.original_root_patch.stop)

    def _write_pdf(self, texts):
        document = fitz.open()
        try:
            for text in texts:
                page = document.new_page()
                page.insert_text((72, 72), text)
            document.save(self.pdf_path)
        finally:
            document.close()

    def test_search_spec_raw_returns_ranked_physical_page_evidence(self):
        matches = search_spec_raw(
            spec="ET1100",
            query="SyncManager control register",
            limit=1,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["spec"], "ET1100")
        self.assertEqual(matches[0]["source_filename"], self.pdf_path.name)
        self.assertEqual(matches[0]["pdf_page"], 2)
        self.assertIn("SyncManager", matches[0]["excerpt"])

    def test_get_spec_raw_pages_reads_complete_text_and_preserves_order(self):
        pages = get_spec_raw_pages(spec="ET1100", pages=[3, 1, 3])

        self.assertEqual([page["pdf_page"] for page in pages], [3, 1])
        self.assertEqual(pages[0]["source_filename"], self.pdf_path.name)
        self.assertIn("FMMU logical start bit", pages[0]["text"])
        self.assertIn("Introduction page", pages[1]["text"])

    def test_invalid_spec_is_rejected(self):
        with self.assertRaises(ValueError):
            search_spec_raw(spec="OTHER", query="register")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ValueError):
            search_spec_raw(spec="ET1100", query="   ")

    def test_invalid_limit_is_rejected(self):
        for limit in (0, 11, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                search_spec_raw(spec="ET1100", query="register", limit=limit)

    def test_invalid_page_is_rejected(self):
        for page in (0, -1, "2"):
            with self.subTest(page=page), self.assertRaises(ValueError):
                get_spec_raw_pages(spec="ET1100", pages=[page])

    def test_out_of_range_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "out of range"):
            get_spec_raw_pages(spec="ET1100", pages=[7])

    def test_max_pages_is_enforced_after_duplicate_removal(self):
        with self.assertRaisesRegex(ValueError, "at most 5"):
            get_spec_raw_pages(spec="ET1100", pages=[1, 2, 3, 4, 5, 6])

        pages = get_spec_raw_pages(spec="ET1100", pages=[1, 1, 2, 2, 3, 3])
        self.assertEqual([page["pdf_page"] for page in pages], [1, 2, 3])

    def test_unknown_agent_argument_is_rejected(self):
        action = json.dumps(
            {
                "action": "tool",
                "tool": "search_spec_raw",
                "arguments": {
                    "spec": "ET1100",
                    "query": "register",
                    "limit": 5,
                    "pdf_path": "C:\\outside.pdf",
                },
            }
        )

        with self.assertRaises(ValueError):
            engineering_tool_agent._parse_action(action)

    def test_agent_dispatches_search_spec_raw_without_accepting_a_pdf_path(self):
        evidence = [
            {
                "spec": "ET1100",
                "source_filename": "ET1100 fixture.pdf",
                "pdf_page": 2,
                "excerpt": "register evidence",
            }
        ]
        with patch.object(
            engineering_tool_agent,
            "search_spec_raw",
            return_value=evidence,
        ) as raw_search:
            result = json.loads(
                engineering_tool_agent._tool_result(
                    "search_spec_raw",
                    {
                        "spec": "ET1100",
                        "query": "register",
                        "limit": 5,
                    },
                )
            )

        raw_search.assert_called_once_with(
            spec="ET1100",
            query="register",
            limit=5,
        )
        self.assertEqual(result["matches"], evidence)

    def test_agent_dispatches_get_spec_raw_pages(self):
        evidence = [
            {
                "spec": "ET1100",
                "source_filename": "ET1100 fixture.pdf",
                "pdf_page": 3,
                "text": "raw page text",
            }
        ]
        with patch.object(
            engineering_tool_agent,
            "get_spec_raw_pages",
            return_value=evidence,
        ) as raw_pages:
            result = json.loads(
                engineering_tool_agent._tool_result(
                    "get_spec_raw_pages",
                    {"spec": "ET1100", "pages": [3, 3]},
                )
            )

        raw_pages.assert_called_once_with(spec="ET1100", pages=[3])
        self.assertEqual(result["pages"], evidence)


if __name__ == "__main__":
    unittest.main()

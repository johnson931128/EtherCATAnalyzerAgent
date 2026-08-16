import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import engineering_tool_agent
from retrieval import markdown_spec


MARKDOWN_FIXTURE = """## DOCUMENT HISTORY

FMMU and SyncManager appear in this historical index.

## CONTENTS

7 FMMU
8 SyncManager
AL status register 0x0800

## TABLES

| Table | Topic |
|---|---|
| 24 | FMMU |
| 25 | SyncManager |

## 7 FMMU

The FMMU logical start bit is defined here.

### 7.1 FMMU registers

The FMMU register description contains logical start bit details.

## 8 SyncManager

The SyncManager control register selects the mailbox mode.

### 8.1 Buffered mode

Buffered mode uses the SyncManager control register.

## AL status register

Register address 0x0800 contains the AL status register.

## Mailbox mode

Mailbox mode is described by the SyncManager control register.

## Distributed clocks

Distributed clocks use the system time registers.
"""


class MarkdownSpecRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.repository_root = Path(self.temp_directory.name)
        self.markdown_path = (
            self.repository_root / "spec" / "generated" / "ET1100" / "ET1100.md"
        )
        self.markdown_path.parent.mkdir(parents=True)
        self.markdown_path.write_text(MARKDOWN_FIXTURE, encoding="utf-8")
        self.path_patch = patch.object(
            markdown_spec, "SPEC_MARKDOWN_PATH", self.markdown_path
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_missing_markdown_reports_ingestion_command(self):
        self.markdown_path.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "/ingest-spec ET1100"):
            markdown_spec.load_spec_chunks()

    def test_heading_parsing_and_heading_path_hierarchy(self):
        chunks = markdown_spec.load_spec_chunks()
        fmmu = next(chunk for chunk in chunks if chunk["heading"] == "7 FMMU")
        buffered = next(
            chunk for chunk in chunks if chunk["heading"] == "8.1 Buffered mode"
        )

        self.assertEqual(fmmu["heading_path"], ["7 FMMU"])
        self.assertEqual(
            buffered["heading_path"], ["8 SyncManager", "8.1 Buffered mode"]
        )
        self.assertEqual(
            fmmu["source_relative_path"], "spec/generated/ET1100/ET1100.md"
        )

    def test_fmmu_query_prioritizes_real_section(self):
        matches = markdown_spec.search_spec_markdown("FMMU")

        self.assertEqual(matches[0]["heading"], "7 FMMU")
        self.assertIn("logical start bit", matches[0]["content"])
        self.assertIn("excerpt", matches[0])

    def test_syncmanager_query_returns_syncmanager_section(self):
        matches = markdown_spec.search_spec_markdown("SyncManager control register")

        self.assertEqual(matches[0]["heading"], "8 SyncManager")
        self.assertIn("mailbox mode", matches[0]["content"])

    def test_register_address_query_returns_register_section(self):
        matches = markdown_spec.search_spec_markdown("0x0800")

        self.assertEqual(matches[0]["heading"], "AL status register")
        self.assertIn("0x0800", matches[0]["content"])

    def test_front_matter_is_ranked_below_body(self):
        matches = markdown_spec.search_spec_markdown("FMMU")
        headings = [match["heading"] for match in matches]

        self.assertEqual(headings[0], "7 FMMU")
        self.assertLess(headings.index("7 FMMU"), headings.index("CONTENTS"))
        self.assertLess(headings.index("7 FMMU"), headings.index("TABLES"))

    def test_markdown_table_remains_one_chunk(self):
        with patch.object(markdown_spec, "MAX_CHUNK_CHARS", 40):
            chunks = markdown_spec.load_spec_chunks()

        table_chunks = [chunk for chunk in chunks if chunk["heading"] == "TABLES"]
        self.assertEqual(len(table_chunks), 1)
        self.assertIn("| 24 | FMMU |", table_chunks[0]["content"])
        self.assertIn("| 25 | SyncManager |", table_chunks[0]["content"])

    def test_agent_search_spec_dispatches_to_markdown_retrieval(self):
        evidence = [
            {
                "heading": "7 FMMU",
                "heading_path": ["7 FMMU"],
                "content": "FMMU evidence",
                "excerpt": "FMMU evidence",
                "source_relative_path": "spec/generated/ET1100/ET1100.md",
            }
        ]
        with patch.object(
            engineering_tool_agent,
            "search_spec_markdown",
            return_value=evidence,
        ) as markdown_search:
            result = json.loads(
                engineering_tool_agent._tool_result(
                    "search_spec", {"query": "FMMU"}
                )
            )

        markdown_search.assert_called_once_with("FMMU")
        self.assertEqual(result["matches"], evidence)


if __name__ == "__main__":
    unittest.main()

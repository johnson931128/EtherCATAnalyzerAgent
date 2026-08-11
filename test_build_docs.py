import tempfile
import unittest
from pathlib import Path

from build_docs import write_validated_document


class BuildDocsTests(unittest.TestCase):
    def test_write_validated_document_creates_then_updates_body_only(self):
        draft = "# EtherCAT EEPROM\n\n## Source\nET1100 PDF\n"

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "EtherCAT_EEPROM.md"

            self.assertEqual(write_validated_document(draft, target), "created")
            self.assertEqual(target.read_text(encoding="utf-8"), draft)
            self.assertNotIn("Evidence Used", target.read_text(encoding="utf-8"))

            updated = draft + "\n## Overview\nUpdated body\n"
            self.assertEqual(write_validated_document(updated, target), "updated")
            self.assertEqual(target.read_text(encoding="utf-8"), updated)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from workflows.build_docs import (
    _apply_grounded_eeprom_sections,
    validate_draft,
    write_validated_document,
)


class BuildDocsTests(unittest.TestCase):
    def _evidence(self):
        return [{"page_num": page} for page in (95, 96, 98, 99, 169, 170, 171)]

    def _valid_draft(self):
        return """# EtherCAT EEPROM

## Source
**Spec fact:** ET1100 Datasheet. (Page 95)

## Overview
**Spec fact:** The ET1100 exposes an ESI EEPROM interface. (Page 95)
**Engineering explanation:** The ESC performs the external EEPROM transaction.
**Analyzer note:** The analyzer observes the ESC register accesses.

## EEPROM Interface

### 0x0502 EEPROM Control / Status
**Spec fact:** Bit 0 is ECAT EEPROM Write Enable for EEPROM write commands;
it is not required for EEPROM Read commands. (Page 169)
**Engineering explanation:** Busy prevents overlapping operations.
**Analyzer note:** The analyzer observes 0x0502.

### 0x0504 EEPROM Address
**Spec fact:** 0x0504 is the EEPROM word address from the Master/ESC register
perspective. The underlying I2C access is byte-addressed and A[0] is handled
internally by the ESC. (Page 99)
**Engineering explanation:** The Master uses the register-level word address.
**Analyzer note:** Preserve the word address in the record.

### 0x0508 EEPROM Data
**Spec fact:** Read data is returned through 0x0508. (Page 171)
**Engineering explanation:** This is the returned data buffer.
**Analyzer note:** The analyzer reads the data register.

## EEPROM Read Procedure
1. Check Busy == 0.
2. Check and clear error status as required.
3. Write the target EEPROM word address to 0x0504.
4. Issue the EEPROM Read command through the 0x0502 command bits.
5. Wait until Busy == 0.
6. Check error status.
7. Read the returned data from 0x0508.

## Identity Information

### Vendor ID
**Spec fact:** Vendor ID is ESI EEPROM words 0x0008:0x0009. (Page 95)
**Engineering explanation:** It identifies the manufacturer.
**Analyzer note:** The word address is 0x0008.

### Product Code
**Spec fact:** Product Code is ESI EEPROM words 0x000A:0x000B. (Page 95)
**Engineering explanation:** It identifies the device model.
**Analyzer note:** The word address is 0x000A.

## Analyzer-Relevant Notes
**Analyzer note:** `pendingEepromReads` correlates successful 0x0502 read
commands and 0x0508 data reads by topology position and working-counter
progression. It maps 0x0008 to Vendor ID and 0x000A to Product Code.

## Source References
ET1100 Datasheet. (Pages 95, 98, 99, 169, 170)
"""

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

    def test_validate_draft_accepts_et1100_read_and_correlation_rules(self):
        self.assertEqual(validate_draft(self._valid_draft(), self._evidence()), [])

    def test_validate_draft_rejects_legacy_grounding_claims(self):
        draft = self._valid_draft().replace(
            "The underlying I2C access is byte-addressed and A[0] is handled\n"
            "internally by the ESC.",
            "The word/byte mismatch requires the analyzer to multiply by 2.",
        ).replace(
            "Vendor ID is ESI EEPROM words 0x0008:0x0009.",
            "Vendor ID is in register 0x0E08.",
        ).replace(
            "`pendingEepromReads` correlates successful 0x0502 read\n"
            "commands and 0x0508 data reads",
            "EEPROM transaction pairing is not implemented",
        )
        errors = validate_draft(draft, self._evidence())
        self.assertTrue(any("conversion instruction" in error for error in errors))
        self.assertTrue(any("unsupported ET1100" in error for error in errors))
        self.assertTrue(any("incorrectly deny" in error for error in errors))

    def test_grounded_sections_remove_model_legacy_claims(self):
        draft = self._valid_draft().replace(
            "## Source References\nET1100 Datasheet. (Pages 95, 98, 99, 169, 170)\n",
            "## Source References\nESC-specific identity registers 0x0E08 and 0x0E0C.\n",
        )
        grounded = _apply_grounded_eeprom_sections(draft, self._evidence())
        self.assertEqual(validate_draft(grounded, self._evidence()), [])
        self.assertNotIn("0x0E08", grounded)
        self.assertNotIn("0x0E0C", grounded)
        self.assertIn("pendingEepromReads", grounded)
        self.assertIn("A[0] is handled internally", grounded)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from retrieval import markdown_spec, sdo_verification


def _reference(heading, excerpt, source):
    return {
        "heading": heading,
        "heading_path": [heading],
        "excerpt": excerpt,
        "source_relative_path": source,
    }


class SdoReferenceRelevanceTests(unittest.TestCase):
    def test_unrelated_top_result_is_skipped_for_coe_sdo_reference(self):
        unrelated = _reference(
            "2.9.5.4 Avalon error code",
            "Avalon error code 0x030E:0x030F",
            "spec/generated/ET1100/ET1100.md",
        )
        valid = _reference(
            "CoE SDO request response",
            "Mailbox CoE SDO request and response handling, including abort.",
            "spec/generated/ET1100/ET1100.md",
        )

        def search(query, limit):
            self.assertEqual(limit, 5)
            if query == sdo_verification._SDO_REFERENCE_QUERIES[0]:
                return [
                    _reference(
                        "2.4 Working counter",
                        "Every EtherCAT datagram has a WKC working counter.",
                        "wkc.md",
                    )
                ]
            if query == sdo_verification._SDO_REFERENCE_QUERIES[1]:
                return [
                    _reference(
                        "3 Frame processing",
                        "The source MAC address is locally administered during frame processing.",
                        "mac.md",
                    )
                ]
            return [unrelated, valid]

        with patch.object(markdown_spec, "search_spec_markdown", side_effect=search):
            references = sdo_verification._build_reference_context()

        coe_reference = references[-1]
        self.assertEqual(coe_reference["heading_path"], ["CoE SDO request response"])
        self.assertNotEqual(coe_reference.get("heading_path"), unrelated["heading_path"])

    def test_all_unrelated_reference_candidates_are_insufficient(self):
        unrelated = _reference(
            "2.9.5.4 Avalon error code",
            "Avalon error code 0x030E:0x030F",
            "spec/generated/ET1100/ET1100.md",
        )
        with patch.object(
            markdown_spec,
            "search_spec_markdown",
            return_value=[unrelated],
        ):
            references = sdo_verification._build_reference_context()

        self.assertEqual(len(references), 3)
        self.assertTrue(all(reference["status"] == "insufficient" for reference in references))
        self.assertTrue(all("source" not in reference for reference in references))


if __name__ == "__main__":
    unittest.main()

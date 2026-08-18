import unittest

from retrieval.sdo_query import (
    extract_sdo_object_reference,
    has_sdo_capture_query_intent,
    is_sdo_object_capture_query,
)


class SDOQueryPlanningTests(unittest.TestCase):
    def test_extracts_hexadecimal_object_reference_as_integers(self):
        self.assertEqual(
            extract_sdo_object_reference("查 0X1A00:02 的 request frame"),
            {"index": 0x1A00, "subindex": 2},
        )

    def test_rejects_out_of_range_object_reference(self):
        self.assertIsNone(extract_sdo_object_reference("0x10000:01"))
        self.assertIsNone(extract_sdo_object_reference("0x1A00:100"))

    def test_object_mention_without_capture_intent_is_not_a_query(self):
        text = "0x1A00:02 是什麼意思？"
        self.assertFalse(has_sdo_capture_query_intent(text))
        self.assertFalse(is_sdo_object_capture_query(text))

    def test_capture_intent_requires_one_valid_object_reference(self):
        self.assertTrue(is_sdo_object_capture_query("幫我看 0x1A00:02 的 WKC 跟 abort"))
        self.assertFalse(is_sdo_object_capture_query("查 0x1A00:02 與 0x1C12:01 的 frame"))


if __name__ == "__main__":
    unittest.main()

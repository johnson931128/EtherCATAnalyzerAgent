import unittest

from retrieval.sdo_query import (
    assess_sdo_evidence,
    build_sdo_evidence_plan,
    build_sdo_query_spec,
    extract_sdo_object_reference,
    has_sdo_capture_query_intent,
    is_sdo_object_capture_query,
    normalize_sdo_object_query_result,
)


class SDOQueryPlanningTests(unittest.TestCase):
    def _datagram(
        self,
        frame_number,
        path_role,
        command,
        wkc,
        counter,
        sdo_request=None,
        sdo_response=None,
        abort_code=None,
    ):
        return {
            "frame_number": frame_number,
            "datagram_sequence": 1,
            "cmd": command,
            "cmd_name": command,
            "idx": "0x0000",
            "adp": "0x0001",
            "ado": "0x1000",
            "data_length": "0x0080",
            "wkc": wkc,
            "mailbox": {"type": "3", "counter": counter},
            "coe": {
                "type": "2",
                "sdo_request": sdo_request,
                "sdo_response": sdo_response,
                "index": "0x1a00",
                "subindex": "0x02",
                "data": "0x60430010",
                "abort_code": abort_code,
            },
            "_path_role": path_role,
        }

    def _frame(self, record):
        datagram = dict(record)
        path_role = datagram.pop("_path_role")
        return {
            "frame_number": datagram["frame_number"],
            "source_mac": None,
            "dest_mac": None,
            "ethercat_path_role": path_role,
            "datagrams": [datagram],
        }

    def _three_transaction_result(self):
        records = []
        for offset, counter in ((0, "1"), (1, "2"), (2, "3")):
            base = (41639, 111709, 215437)[offset]
            response_frame = (41786, 111856, 215610)[offset]
            records.extend(
                [
                    self._datagram(
                        base, "outgoing", "FPWR", "0", counter, sdo_request="1"
                    ),
                    self._datagram(
                        base + 1,
                        "returning",
                        "FPWR",
                        "1",
                        counter,
                        sdo_request="1",
                    ),
                    self._datagram(
                        response_frame,
                        "returning",
                        "FPRD",
                        "1",
                        str(int(counter) + 8),
                        sdo_response="1",
                    ),
                ]
            )
        return {
            "capture": "active.pcapng",
            "index": 0x1A00,
            "subindex": 2,
            "frames": [self._frame(record) for record in records],
        }

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

    def test_normalizes_path_and_coe_roles_without_request_response_confusion(self):
        result = normalize_sdo_object_query_result(self._three_transaction_result())
        rows = {row["frame_number"]: row for row in result["semantic_frames"]}

        self.assertEqual(rows[41639]["semantic_role"], "request_outgoing")
        self.assertEqual(rows[41640]["semantic_role"], "request_returning")
        self.assertEqual(rows[41786]["semantic_role"], "response")
        self.assertEqual(rows[41639]["mailbox_type"], "3")
        self.assertEqual(rows[41639]["coe_type"], "2")
        self.assertEqual(rows[41639]["data_length"], "0x0080")

        first = result["transactions"][0]
        self.assertEqual(first["request_outgoing"]["frame_number"], 41639)
        self.assertEqual(first["request_returning"]["frame_number"], 41640)
        self.assertEqual(first["response"]["frame_number"], 41786)
        self.assertEqual(first["request_exchange"]["pairing_status"], "grouped")
        self.assertEqual(first["written_data"], "0x60430010")
        self.assertIsNone(first["abort"])

    def test_repeated_operations_group_into_three_transactions(self):
        result = normalize_sdo_object_query_result(self._three_transaction_result())
        self.assertEqual(len(result["transactions"]), 3)
        self.assertEqual(
            [
                transaction["request_outgoing"]["frame_number"]
                for transaction in result["transactions"]
            ],
            [41639, 111709, 215437],
        )
        self.assertTrue(
            all(
                transaction["pairing_status"] == "grouped"
                for transaction in result["transactions"]
            )
        )

    def test_capture_intent_requires_one_valid_object_reference(self):
        self.assertTrue(is_sdo_object_capture_query("幫我看 0x1A00:02 的 WKC 跟 abort"))
        self.assertFalse(is_sdo_object_capture_query("查 0x1A00:02 與 0x1C12:01 的 frame"))

    def test_builds_integer_query_spec_and_single_scan_plan(self):
        task = "query 0x1A00:02 request response frame write data WKC abort"
        spec = build_sdo_query_spec(task)
        plan = build_sdo_evidence_plan(task, "active.pcapng")
        self.assertEqual(spec["index"], 0x1A00)
        self.assertEqual(spec["subindex"], 2)
        self.assertEqual(plan["primary_query"], "query_sdo_object")
        self.assertEqual(plan["arguments"]["index"], 0x1A00)
        self.assertEqual(plan["arguments"]["subindex"], 2)
        self.assertEqual(plan["planned_tshark_scans"], 1)

    def test_assessment_marks_complete_without_refinement(self):
        task = "query 0x1A00:02 request response frame write data WKC abort"
        plan = build_sdo_evidence_plan(task, "active.pcapng")
        normalized = normalize_sdo_object_query_result(self._three_transaction_result())
        assessment = assess_sdo_evidence(normalized, plan["query_spec"])
        self.assertEqual(assessment["status"], "COMPLETE")
        self.assertEqual(assessment["missing_evidence"], [])
        self.assertIsNone(assessment["refinement"])

    def test_assessment_does_not_call_request_only_evidence_complete(self):
        task = "query 0x1A00:02 request response frame WKC abort"
        plan = build_sdo_evidence_plan(task, "active.pcapng")
        request_only = normalize_sdo_object_query_result(
            {
                "index": 0x1A00,
                "subindex": 2,
                "frames": [
                    self._frame(
                        self._datagram(
                            41639,
                            "outgoing",
                            "FPWR",
                            "0",
                            "1",
                            sdo_request="1",
                        )
                    )
                ],
            }
        )
        assessment = assess_sdo_evidence(request_only, plan["query_spec"])
        self.assertEqual(assessment["status"], "PARTIAL")
        self.assertIn("request_response", assessment["missing_evidence"])

    def test_abort_is_terminal_abort_evidence_not_success(self):
        records = [
            self._datagram(500, "outgoing", "FPWR", "0", "4", sdo_request="1"),
            self._datagram(501, "returning", "FPWR", "1", "4", sdo_request="1"),
            self._datagram(
                502,
                "returning",
                "FPRD",
                "1",
                "4",
                sdo_response="1",
                abort_code="0x06020000",
            ),
        ]
        result = normalize_sdo_object_query_result(
            {"index": 0x1A00, "subindex": 2, "frames": [self._frame(r) for r in records]}
        )
        transaction = result["transactions"][0]
        self.assertEqual(result["semantic_frames"][2]["semantic_role"], "abort")
        self.assertEqual(transaction["abort"]["frame_number"], 502)
        self.assertIsNone(transaction["response"])
        self.assertNotEqual(transaction["pairing_status"], "success")

    def test_multiple_candidates_are_ambiguous_and_not_hard_paired(self):
        records = [
            self._datagram(600, "outgoing", "FPWR", "0", "5", sdo_request="1"),
            self._datagram(601, "returning", "FPWR", "1", "5", sdo_request="1"),
            self._datagram(602, "returning", "FPWR", "1", "5", sdo_request="1"),
            self._datagram(603, "returning", "FPRD", "1", "5", sdo_response="1"),
        ]
        result = normalize_sdo_object_query_result(
            {"index": 0x1A00, "subindex": 2, "frames": [self._frame(r) for r in records]}
        )
        transaction = result["transactions"][0]
        self.assertEqual(transaction["pairing_status"], "ambiguous")
        self.assertIsNone(transaction["request_returning"])


if __name__ == "__main__":
    unittest.main()

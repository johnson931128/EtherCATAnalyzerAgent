import unittest

from agent import engineering_tool_agent
from retrieval.result_document import build_result_document
from retrieval.sdo_rendering import (
    render_sdo_engineering_evidence,
    render_sdo_engineering_references,
    render_sdo_verification_summary,
)


def _result(index="0x1A00", subindex="0x01", result="PASS", data="0x60410010"):
    claim = {
        "station": 0x0001,
        "index": int(index, 16),
        "subindex": int(subindex, 16),
        "data": data,
        "request_frame": 41460,
        "response_frame": 41614,
        "claimed_success": True,
        "claimed_abort_code": None,
    }
    request = {
        "frame_number": 41460,
        "ethercat_path_role": "outgoing",
        "datagram": {
            "cmd": "0x05",
            "cmd_name": "FPWR",
            "adp": "0x0001",
            "ado": "0x1000",
            "wkc": "0",
            "coe": {
                "sdo_request": "1",
                "sdo_response": None,
                "index": "0x1a00",
                "subindex": "0x01",
                "data": data,
                "abort_code": None,
            },
        },
    }
    response = {
        "frame_number": 41614,
        "ethercat_path_role": "returning",
        "datagram": {
            "cmd": "0x04",
            "cmd_name": "FPRD",
            "adp": "0x0001",
            "ado": "0x10c0",
            "wkc": "1",
            "coe": {
                "sdo_request": None,
                "sdo_response": "3",
                "index": "0x1a00",
                "subindex": "0x01",
                "data": None,
                "abort_code": None,
            },
        },
    }
    return {
        "claim": claim,
        "result": result,
        "checks": {
            "request_frame": True,
            "station": True,
            "index": True,
            "subindex": True,
            "data": result == "PASS",
            "response_frame": True,
            "response_match": True,
            "abort_detected": False,
        },
        "request_evidence": request,
        "response_evidence": response,
        "wkc_evidence": {
            "request_outgoing_wkc": "0",
            "request_returning_wkc": "1",
            "response_wkc": "1",
        },
        "mismatch_reasons": (
            ["request.data expected 0x60410010 but observed 0x60430010"]
            if result == "FAIL"
            else []
        ),
    }


class SDORenderingTests(unittest.TestCase):
    def test_summary_renders_three_pass_rows(self):
        results = [
            _result("0x1C13", "0x00"),
            _result("0x1A00", "0x00"),
            _result("0x1A00", "0x01"),
        ]
        summary = render_sdo_verification_summary(results)
        self.assertIn("| 0x1C13:00 | PASS | 41460 | 41614 |", summary)
        self.assertEqual(summary.count("| PASS |"), 3)

    def test_pass_evidence_renders_engineering_fields(self):
        evidence = render_sdo_engineering_evidence([_result()])
        for expected in (
            "Station: 0x0001",
            "Data: 0x60410010",
            "Frame: 41460",
            "EtherCAT Path: outgoing",
            "Command: FPWR",
            "ADP: 0x0001",
            "ADO: 0x1000",
            "WKC: 0",
            "CoE: SDO Request",
            "Index/SubIndex: 0x1A00:01",
            "Abort Code: None",
        ):
            self.assertIn(expected, evidence)

    def test_fail_evidence_renders_expected_observed_and_reason(self):
        result = _result(result="FAIL")
        result["request_evidence"]["datagram"]["coe"]["data"] = "0x60430010"
        evidence = render_sdo_engineering_evidence([result])
        self.assertIn("Data match: FAIL", evidence)
        self.assertIn("Expected: 0x60410010", evidence)
        self.assertIn("Observed: 0x60430010", evidence)
        self.assertIn(
            "request.data expected 0x60410010 but observed 0x60430010", evidence
        )

    def test_inconclusive_evidence_renders_reason(self):
        result = _result(result="INCONCLUSIVE")
        result["response_evidence"] = None
        result["checks"]["response_frame"] = False
        result["checks"]["response_match"] = False
        result["mismatch_reasons"] = ["response frame 41614 is missing"]
        evidence = render_sdo_engineering_evidence([result])
        self.assertIn("Response frame: INCONCLUSIVE", evidence)
        self.assertIn("Reason: response frame 41614 is missing", evidence)

    def test_wkc_reference_is_independent_from_sdo_success(self):
        references = render_sdo_engineering_references(
            [{"source": "ET1100.md", "heading_path": "Working Counter", "excerpt": "WKC"}]
        )
        self.assertIn("WKC is EtherCAT Datagram execution evidence", references)
        self.assertIn("independent from CoE SDO transaction success", references)
        self.assertIn("ET1100.md - Working Counter - WKC", references)

    def test_deterministic_sections_do_not_depend_on_explanation_text(self):
        results = [_result()]
        first = "\n\n".join(
            (
                render_sdo_verification_summary(results),
                render_sdo_engineering_evidence(results),
                render_sdo_engineering_references([]),
            )
        )
        second = "\n\n".join(
            (
                render_sdo_verification_summary(results),
                render_sdo_engineering_evidence(results),
                render_sdo_engineering_references([]),
            )
        )
        self.assertEqual(first, second)
        self.assertNotIn("QWEN", first)

    def test_qwen_prompt_only_allows_explanation(self):
        prompt = engineering_tool_agent._sdo_verification_prompt(
            {"verification_results": [_result()]}
        )
        self.assertIn("Never change PASS, FAIL, or INCONCLUSIVE", prompt)
        self.assertIn("WKC is not SDO success", prompt)
        self.assertIn("without replacing the Python-generated Verification Summary", prompt)

    def test_result_document_keeps_deterministic_sections_outside_qwen(self):
        graph_result = {
            "capture_mode": "sdo_verification",
            "result": "QWEN EXPLANATION ONLY",
            "verification_context": {
                "verification_results": [_result()],
                "reference_context": [],
            },
        }
        document = build_result_document("DLL claim", graph_result)
        self.assertIn("## Verification Summary", document)
        self.assertIn("## Engineering Evidence", document)
        self.assertIn("## Engineering References", document)
        self.assertIn("## Explanation\n\nQWEN EXPLANATION ONLY", document)
        self.assertIn("| 0x1A00:01 | PASS | 41460 | 41614 |", document)

    def test_non_sdo_result_format_is_unchanged(self):
        document = build_result_document(
            "normal task",
            {
                "result": "normal answer",
                "capture_mode": "",
                "selected_docs": "docs",
                "selected_source": "source",
            },
        )
        self.assertIn("## Result\nnormal answer", document)
        self.assertNotIn("## Verification Summary", document)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import config
from retrieval import sdo_verification


REQUEST_CLAIM = {
    "station": 0x0001,
    "index": 0x1A00,
    "subindex": 0x01,
    "data": "0x60410010",
    "request_frame": 41460,
    "response_frame": 41614,
    "claimed_success": True,
    "claimed_abort_code": None,
}


def _datagram(adp, coe, wkc="0"):
    return {
        "frame_number": 0,
        "datagram_sequence": 1,
        "cmd": "0x05",
        "cmd_name": "FPWR",
        "idx": "0x94",
        "adp": adp,
        "ado": "0x1000",
        "data_length": "128",
        "wkc": wkc,
        "mailbox": {"type": "3", "counter": "0"},
        "coe": coe,
    }


def _frame(frame_number, role, datagrams):
    return {
        "frame_number": frame_number,
        "source_mac": "00:18:23:13:02:09"
        if role == "outgoing"
        else "02:18:23:13:02:09",
        "dest_mac": "ff:ff:ff:ff:ff:ff",
        "ethercat_path_role": role,
        "datagrams": datagrams,
    }


def _request_datagram(adp="0x0001", data="0x60410010", wkc="0"):
    return _datagram(
        adp,
        {
            "type": "2",
            "sdo_request": "1",
            "sdo_response": None,
            "index": "0x1a00",
            "subindex": "0x01",
            "data": data,
            "abort_code": None,
        },
        wkc,
    )


def _response_datagram(abort_code=None, wkc="1"):
    datagram = _datagram(
        "0x0001",
        {
            "type": "3",
            "sdo_request": None,
            "sdo_response": "3",
            "index": "0x1a00",
            "subindex": "0x01",
            "data": None,
            "abort_code": abort_code,
        },
        wkc,
    )
    datagram["cmd"] = "0x04"
    datagram["cmd_name"] = "FPRD"
    datagram["ado"] = "0x10c0"
    return datagram


class SDOVerificationTests(unittest.TestCase):
    def test_parser_reads_one_dll_transaction(self):
        text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        self.assertEqual(
            sdo_verification.parse_sdo_transaction_claims(text), [REQUEST_CLAIM]
        )

    def test_parser_reads_multiple_transactions(self):
        text = "\n".join(
            [
                "Configured Slave Address: 0x0001, Object: 0x1A00:01, Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, Success: True, Abort Code: N/A",
                "Configured Slave Address: 0x0001, Object: 0x1A00:02, Data: 0x60430010, Request Frame: 41639, Response Frame: 41791, Success: False, Abort Code: 0x05040005",
            ]
        )
        claims = sdo_verification.parse_sdo_transaction_claims(text)
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[1]["claimed_abort_code"], 0x05040005)

    def test_structured_data_detector_is_separate_from_explicit_intent(self):
        self.assertTrue(
            sdo_verification.contains_sdo_transaction_data(
                "Configured Slave Address: 0x0001"
            )
        )
        self.assertFalse(
            sdo_verification.is_explicit_sdo_verification(
                "Please verify this\nConfigured Slave Address: 0x0001"
            )
        )
        self.assertTrue(sdo_verification.is_explicit_sdo_verification("VERIFY SDO\n"))

    def test_explicit_verify_prefix_is_removed_before_claim_parsing(self):
        task = "verify\n\n" + (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        stripped = sdo_verification.remove_explicit_sdo_verification_prefix(task)
        self.assertFalse(stripped.casefold().startswith("verify"))
        self.assertTrue(stripped.startswith("Configured Slave Address:"))

    def test_context_removes_explicit_verify_before_parser(self):
        claims_text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        with patch.object(
            sdo_verification,
            "_build_reference_context",
            return_value=[],
        ), patch.object(
            sdo_verification,
            "parse_sdo_transaction_claims",
            return_value=[REQUEST_CLAIM],
        ) as parse_claims, patch.object(
            sdo_verification,
            "verify_sdo_transactions",
            return_value=[],
        ):
            context = sdo_verification.build_sdo_verification_context(
                "verify\n" + claims_text
            )

        parse_claims.assert_called_once_with(claims_text)
        self.assertEqual(context["parsed_claims"], [REQUEST_CLAIM])

    def test_sdo_intent_classifier_accepts_only_supported_enum(self):
        response = type("Response", (), {"content": '{"intent":"explanation"}'})()
        client = SimpleNamespace(invoke=Mock(return_value=response))
        with patch.object(sdo_verification.llm, "_client", client):
            intent = sdo_verification.classify_sdo_intent(
                "What do these SDO outputs mean?\nConfigured Slave Address: ..."
            )

        self.assertEqual(intent, "explanation")
        client.invoke.assert_called_once()

    def test_invalid_sdo_intent_response_is_unclear(self):
        response = type("Response", (), {"content": '{"intent":"tool_call"}'})()
        client = SimpleNamespace(invoke=Mock(return_value=response))
        with patch.object(sdo_verification.llm, "_client", client):
            self.assertEqual(
                sdo_verification.classify_sdo_intent(
                    "Configured Slave Address: ..."
                ),
                "unclear",
            )

    def test_planner_deduplicates_frames_for_one_query(self):
        second_claim = dict(REQUEST_CLAIM, request_frame=41460, response_frame=41791)
        calls = []

        def query(capture, frames):
            calls.append((capture, frames))
            return {"frames": []}

        sdo_verification.verify_sdo_transactions(
            [REQUEST_CLAIM, second_claim], "sample.pcapng", frame_query=query
        )
        self.assertEqual(calls, [("sample.pcapng", [41460, 41614, 41791])])

    def _verify(self, request_datagram=None, response_datagram=None):
        request = request_datagram or _request_datagram()
        response = response_datagram or _response_datagram()
        frames = {
            "frames": [
                _frame(41460, "outgoing", [request]),
                _frame(41614, "returning", [response]),
            ]
        }
        return sdo_verification.verify_sdo_transactions(
            [REQUEST_CLAIM], "sample.pcapng", frame_query=lambda capture, numbers: frames
        )[0]

    def test_matching_request_and_response_is_pass(self):
        result = self._verify()
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["checks"]["abort_detected"])
        self.assertEqual(result["wkc_evidence"]["request_outgoing_wkc"], "0")
        self.assertEqual(result["wkc_evidence"]["response_wkc"], "1")

    def test_request_data_mismatch_is_fail(self):
        result = self._verify(request_datagram=_request_datagram(data="0x60430010"))
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "request.data expected 0x60410010 but observed 0x60430010",
            result["mismatch_reasons"],
        )

    def test_response_abort_is_fail(self):
        result = self._verify(response_datagram=_response_datagram("0x05040005"))
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(result["checks"]["abort_detected"])

    def test_missing_response_frame_is_inconclusive(self):
        result = sdo_verification.verify_sdo_transactions(
            [REQUEST_CLAIM],
            "sample.pcapng",
            frame_query=lambda capture, numbers: {
                "frames": [_frame(41460, "outgoing", [_request_datagram()])]
            },
        )[0]
        self.assertEqual(result["result"], "INCONCLUSIVE")
        self.assertFalse(result["checks"]["response_frame"])

    def test_multi_datagram_fields_are_not_cross_paired(self):
        request_frame = _frame(
            41460,
            "outgoing",
            [
                _datagram("0x0001", None, wkc="0"),
                _request_datagram(adp="0x0002"),
            ],
        )
        response_frame = _frame(41614, "returning", [_response_datagram()])
        result = sdo_verification.verify_sdo_transactions(
            [REQUEST_CLAIM],
            "sample.pcapng",
            frame_query=lambda capture, numbers: {
                "frames": [request_frame, response_frame]
            },
        )[0]
        self.assertEqual(result["result"], "FAIL")
        self.assertIn(
            "request.station expected 0x0001 but observed 0x0002",
            result["mismatch_reasons"],
        )

    def test_context_has_deterministic_verification_shape(self):
        with patch.object(
            sdo_verification,
            "_build_reference_context",
            return_value=[{"query": "fixed", "excerpt": "evidence"}],
        ), patch.object(
            sdo_verification,
            "verify_sdo_transactions",
            return_value=[{"claim": REQUEST_CLAIM, "result": "PASS"}],
        ):
            context = sdo_verification.build_sdo_verification_context(
                "Capture: sample.pcapng\n"
                "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
                "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
                "Success: True, Abort Code: N/A"
            )
        self.assertEqual(
            set(context),
            {
                "user_question",
                "parsed_claims",
                "verification_results",
                "reference_context",
                "capture",
            },
        )
        self.assertEqual(context["capture"], "sample.pcapng")

    def _build_context_with_capture(
        self, text, capture=None, active_capture=None, default=None
    ):
        with patch.object(config, "DEFAULT_CAPTURE_NAME", default), patch.object(
            sdo_verification,
            "_build_reference_context",
            return_value=[],
        ), patch.object(
            sdo_verification,
            "verify_sdo_transactions",
            return_value=[],
        ) as verify:
            context = sdo_verification.build_sdo_verification_context(
                text, capture=capture, active_capture=active_capture
            )
        return context, verify

    def test_context_task_capture_precedes_default(self):
        text = (
            "Capture: task.pcapng\n"
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, verify = self._build_context_with_capture(
            text, active_capture="active.pcapng", default="default.pcapng"
        )
        self.assertEqual(context["capture"], "task.pcapng")
        verify.assert_called_once_with(context["parsed_claims"], "task.pcapng")

    def test_context_uses_default_when_task_has_no_capture(self):
        text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, verify = self._build_context_with_capture(
            text, default="PowerOn.pcapng"
        )
        self.assertEqual(context["capture"], "PowerOn.pcapng")
        verify.assert_called_once_with(context["parsed_claims"], "PowerOn.pcapng")

    def test_context_explicit_capture_precedes_task_and_default(self):
        text = (
            "Capture: task.pcapng\n"
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, verify = self._build_context_with_capture(
            text,
            capture="explicit.pcapng",
            active_capture="active.pcapng",
            default="default.pcapng",
        )
        self.assertEqual(context["capture"], "explicit.pcapng")
        verify.assert_called_once_with(context["parsed_claims"], "explicit.pcapng")

    def test_context_active_capture_precedes_default_without_task_capture(self):
        text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, active_verify = self._build_context_with_capture(
            text, active_capture="active.pcapng", default="default.pcapng"
        )
        self.assertEqual(context["capture"], "active.pcapng")
        active_verify.assert_called_once_with(context["parsed_claims"], "active.pcapng")

    def test_context_invalid_default_is_inconclusive(self):
        text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, verify = self._build_context_with_capture(text, default="bad.txt")
        self.assertIsNone(context["capture"])
        self.assertEqual(context["verification_results"][0]["result"], "INCONCLUSIVE")
        self.assertIn(".pcap", context["verification_results"][0]["mismatch_reasons"][0])
        verify.assert_not_called()

    def test_context_without_capture_or_default_is_inconclusive(self):
        text = (
            "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
            "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
            "Success: True, Abort Code: N/A"
        )
        context, verify = self._build_context_with_capture(text)
        self.assertIsNone(context["capture"])
        self.assertEqual(context["verification_results"][0]["result"], "INCONCLUSIVE")
        self.assertEqual(
            context["verification_results"][0]["mismatch_reasons"],
            ["capture logical filename is missing"],
        )
        verify.assert_not_called()

if __name__ == "__main__":
    unittest.main()

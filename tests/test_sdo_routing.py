import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


def _load_engineering_tool_agent():
    if "agent.engineering_tool_agent" in sys.modules:
        return sys.modules["agent.engineering_tool_agent"]
    fake_fitz = types.ModuleType("fitz")
    with patch.dict(sys.modules, {"fitz": fake_fitz}):
        return importlib.import_module("agent.engineering_tool_agent")


engineering_tool_agent = _load_engineering_tool_agent()


SDO_CLAIMS = (
    "Configured Slave Address: 0x0001, Object: 0x1A00:01, "
    "Data: 0x60410010, Request Frame: 41460, Response Frame: 41614, "
    "Success: True, Abort Code: N/A"
)


class SDORoutingTests(unittest.TestCase):
    def _state(self, task):
        return {"task": task, "active_capture": "active.pcapng"}

    def test_explicit_sdo_object_query_uses_one_deterministic_query(self):
        query_result = {
            "capture": "active.pcapng",
            "index": 0x1A00,
            "subindex": 2,
            "frames": [],
        }
        task = "幫我查目前封包中 0x1A00:02 的 SDO 操作"
        with patch.object(
            engineering_tool_agent,
            "query_sdo_object",
            return_value=query_result,
        ) as query, patch.object(
            engineering_tool_agent,
            "find_first_coe_sdo_packet",
        ) as find_first, patch.object(
            engineering_tool_agent,
            "_run_sdo_object_query_agent",
            return_value={"result": "explained"},
        ) as explain:
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state(task)
            )

        query.assert_called_once_with(
            capture="active.pcapng",
            index=6656,
            subindex=2,
            frame_start=None,
            frame_end=None,
        )
        find_first.assert_not_called()
        explain.assert_called_once()
        normalized = explain.call_args.args[1]
        self.assertIn("semantic_frames", normalized)
        self.assertIn("transactions", normalized)
        self.assertIn("query_spec", normalized)
        self.assertIn("evidence_plan", normalized)
        self.assertIn("evidence_assessment", normalized)
        self.assertIn("evidence_trace", normalized)
        self.assertEqual(result, {"result": "explained"})

    def test_wkc_abort_object_query_uses_integer_arguments(self):
        task = "幫我看 0x1A00:02 的 WKC 跟 abort"
        with patch.object(
            engineering_tool_agent,
            "query_sdo_object",
            return_value={"frames": []},
        ) as query, patch.object(
            engineering_tool_agent,
            "_run_sdo_object_query_agent",
            return_value={"result": "explained"},
        ):
            engineering_tool_agent.run_engineering_tool_agent(self._state(task))

        arguments = query.call_args.kwargs
        self.assertIs(type(arguments["index"]), int)
        self.assertIs(type(arguments["subindex"]), int)
        self.assertEqual(arguments["index"], 0x1A00)
        self.assertEqual(arguments["subindex"], 2)
        self.assertEqual(query.call_count, 1)

    def test_object_explanation_does_not_use_capture_query(self):
        client = SimpleNamespace(
            invoke=Mock(
                return_value=SimpleNamespace(
                    content='{"action":"final","answer":"explained"}'
                )
            )
        )
        with patch.object(
            engineering_tool_agent,
            "query_sdo_object",
        ) as query, patch.object(
            engineering_tool_agent,
            "find_first_coe_sdo_packet",
        ) as find_first, patch.object(
            engineering_tool_agent.llm,
            "_client",
            client,
        ):
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state("0x1A00:02 是什麼意思？")
            )

        query.assert_not_called()
        find_first.assert_not_called()
        self.assertEqual(result["result"], "explained")

    def test_object_query_without_active_capture_returns_clear_message(self):
        state = {"task": "幫我查 0x1A00:02 的 request frame", "active_capture": None}
        with patch.object(engineering_tool_agent, "query_sdo_object") as query:
            result = engineering_tool_agent.run_engineering_tool_agent(state)

        query.assert_not_called()
        self.assertIn("No active capture selected", result["result"])

    def test_explicit_verify_bypasses_intent_classifier_and_strips_control_line(self):
        context = {"parsed_claims": [{"request_frame": 41460}]}
        for prefix in ("verify", "verify sdo"):
            with self.subTest(prefix=prefix), patch.object(
                engineering_tool_agent,
                "classify_sdo_intent",
            ) as classify, patch.object(
                engineering_tool_agent,
                "build_sdo_verification_context",
                return_value=context,
            ) as build_context, patch.object(
                engineering_tool_agent,
                "_run_sdo_verification_agent",
                return_value={"result": "verified"},
            ) as run_verifier:
                result = engineering_tool_agent.run_engineering_tool_agent(
                    self._state(prefix + "\n\n" + SDO_CLAIMS)
                )

            classify.assert_not_called()
            build_context.assert_called_once_with(
                SDO_CLAIMS, active_capture="active.pcapng"
            )
            run_verifier.assert_called_once()
            self.assertEqual(result, {"result": "verified"})

    def test_natural_language_verification_uses_classifier_then_verifier(self):
        context = {"parsed_claims": [{"request_frame": 41460}]}
        with patch.object(
            engineering_tool_agent,
            "classify_sdo_intent",
            return_value="sdo_verification",
        ) as classify, patch.object(
            engineering_tool_agent,
            "build_sdo_verification_context",
            return_value=context,
        ) as build_context, patch.object(
            engineering_tool_agent,
            "_run_sdo_verification_agent",
            return_value={"result": "verified"},
        ) as run_verifier:
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state("Please verify these results.\n" + SDO_CLAIMS)
            )

        classify.assert_called_once()
        build_context.assert_called_once_with(
            "Please verify these results.\n" + SDO_CLAIMS,
            active_capture="active.pcapng",
        )
        run_verifier.assert_called_once()
        self.assertEqual(result, {"result": "verified"})

    def test_explanation_bypasses_deterministic_verifier(self):
        with patch.object(
            engineering_tool_agent,
            "classify_sdo_intent",
            return_value="explanation",
        ), patch.object(
            engineering_tool_agent,
            "_run_sdo_verification_agent",
        ) as run_verifier, patch.object(
            engineering_tool_agent.llm,
            "_client",
            SimpleNamespace(
                invoke=Mock(
                    return_value=SimpleNamespace(
                        content='{"action":"final","answer":"explained"}'
                    )
                )
            ),
        ):
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state("What do these outputs mean?\n" + SDO_CLAIMS)
            )

        run_verifier.assert_not_called()
        self.assertEqual(result["result"], "explained")

    def test_bare_structured_output_returns_clarification_without_verifier(self):
        with patch.object(
            engineering_tool_agent,
            "classify_sdo_intent",
            return_value="unclear",
        ) as classify, patch.object(
            engineering_tool_agent,
            "build_sdo_verification_context",
        ) as build_context, patch.object(
            engineering_tool_agent,
            "_run_sdo_verification_agent",
        ) as run_verifier:
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state(SDO_CLAIMS)
            )

        classify.assert_called_once()
        build_context.assert_not_called()
        run_verifier.assert_not_called()
        self.assertIn("requested action is unclear", result["result"])

    def test_explicit_verify_without_claims_returns_error_without_qwen(self):
        client = SimpleNamespace(invoke=Mock())
        with patch.object(
            engineering_tool_agent,
            "classify_sdo_intent",
        ) as classify, patch.object(
            engineering_tool_agent.llm,
            "_client",
            client,
        ), patch.object(
            engineering_tool_agent,
            "_run_sdo_verification_agent",
        ) as run_verifier:
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state("verify\nPlease check this")
            )

        classify.assert_not_called()
        client.invoke.assert_not_called()
        run_verifier.assert_not_called()
        self.assertIn("no SDO transaction structured data", result["result"])

    def test_non_sdo_task_does_not_call_sdo_intent_classifier(self):
        client = SimpleNamespace(
            invoke=Mock(
                return_value=SimpleNamespace(
                    content='{"action":"final","answer":"normal"}'
                )
            )
        )
        with patch.object(
            engineering_tool_agent,
            "classify_sdo_intent",
        ) as classify, patch.object(
            engineering_tool_agent.llm,
            "_client",
            client,
        ):
            result = engineering_tool_agent.run_engineering_tool_agent(
                self._state("What is an EtherCAT working counter?")
            )

        classify.assert_not_called()
        self.assertEqual(result["result"], "normal")


    def test_object_query_prompt_preserves_semantic_safety(self):
        prompt = engineering_tool_agent._sdo_object_query_prompt(
            "查 0x1A00:02 的 request/response frame",
            {"semantic_frames": [], "transactions": []},
        )
        self.assertIn(
            "EtherCAT outgoing/returning path roles are not CoE SDO request/response roles",
            prompt,
        )
        self.assertIn(
            "`request_returning` is the same SDO Request copied after traversing the Slave",
            prompt,
        )
        self.assertIn(
            "WKC is EtherCAT Datagram processing/execution evidence",
            prompt,
        )
        self.assertIn(
            "Python's grouped transactions and evidence assessment are authoritative",
            prompt,
        )
        self.assertIn(
            "Do not regroup, change pairing, invent frames or values",
            prompt,
        )
        self.assertIn("If Python evidence is ambiguous or incomplete", prompt)
        self.assertNotIn("## 查詢結果", prompt)
        self.assertNotIn("## Transaction N", prompt)
        self.assertNotIn("## 總結", prompt)


    def test_sdo_query_prompt_allows_communication_choice_and_keeps_evidence(self):
        query_result = {
            "query_spec": {"index": 0x1A00, "subindex": 2},
            "evidence_plan": {"planned_tshark_scans": 1},
            "evidence_assessment": {"status": "COMPLETE"},
            "evidence_trace": {"tshark_scans": 1, "evidence_status": "COMPLETE"},
            "transactions": [
                {
                    "transaction_number": 1,
                    "request_outgoing": {"frame_number": 41639},
                    "request_returning": {"frame_number": 41640},
                    "response": {"frame_number": 41786},
                },
                {
                    "transaction_number": 2,
                    "request_outgoing": {"frame_number": 111709},
                    "request_returning": {"frame_number": 111710},
                    "response": {"frame_number": 111856},
                },
                {
                    "transaction_number": 3,
                    "request_outgoing": {"frame_number": 215437},
                    "request_returning": {"frame_number": 215438},
                    "response": {"frame_number": 215610},
                },
            ],
        }
        prompt = engineering_tool_agent._sdo_object_query_prompt(
            "幫我查目前封包中 0x1A00:02 的 SDO 操作", query_result
        )

        for required_text in (
            "Traditional Chinese",
            "Answer the user's actual engineering question directly",
            "Prose, bullets, or a Markdown table are all appropriate",
            "Avoid redundant repetition",
            "do not silently omit a relevant transaction",
            "Transport protocol requirement (not an answer-format template)",
            "inside the answer string",
            '"status":"COMPLETE"',
            '"tshark_scans":1',
        ):
            self.assertIn(required_text, prompt)
        for frame_number in (
            41639,
            41640,
            41786,
            111709,
            111710,
            111856,
            215437,
            215438,
            215610,
        ):
            self.assertIn(str(frame_number), prompt)
        self.assertIn("evidence_assessment", prompt)
        self.assertIn("evidence_trace", prompt)
        self.assertIn("WKC=1 does not mean SDO success", prompt)
        self.assertNotIn("<concise explanation>", prompt)


if __name__ == "__main__":
    unittest.main()

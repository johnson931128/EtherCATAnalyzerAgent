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


if __name__ == "__main__":
    unittest.main()

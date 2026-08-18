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

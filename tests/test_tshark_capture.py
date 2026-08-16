import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import engineering_tool_agent
from retrieval import tshark_capture


class TSharkCaptureToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.capture_root = Path(self.temp_directory.name) / "captures"
        self.capture_root.mkdir()
        self.capture_path = self.capture_root / "sample.pcapng"
        self.capture_path.write_bytes(b"fixture capture")
        self.root_patch = patch.object(
            tshark_capture, "CAPTURE_INPUT_ROOT", self.capture_root
        )
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def _completed(self, stdout="", stderr="", returncode=0):
        return SimpleNamespace(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )

    def test_capture_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            tshark_capture.resolve_capture_path("../sample.pcapng")

    def test_absolute_capture_path_is_rejected(self):
        with self.assertRaises(ValueError):
            tshark_capture.resolve_capture_path(
                str(Path(self.temp_directory.name) / "sample.pcapng")
            )

    def test_unsupported_capture_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            tshark_capture.validate_capture_name("sample.txt")

    def test_missing_capture_is_reported(self):
        with self.assertRaisesRegex(FileNotFoundError, "Capture not found"):
            tshark_capture.resolve_capture_path("missing.pcapng")

    def test_empty_and_unsafe_display_filters_are_rejected(self):
        for display_filter in ("", "   ", "frame.number == 1\n", "frame\x00"):
            with self.subTest(display_filter=repr(display_filter)):
                with self.assertRaises(ValueError):
                    tshark_capture.query_capture(
                        "sample.pcapng",
                        display_filter,
                        ["frame.number"],
                    )

    def test_invalid_limit_is_rejected(self):
        for limit in (0, 201, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                tshark_capture.query_capture(
                    "sample.pcapng",
                    "frame.number == 1",
                    ["frame.number"],
                    limit=limit,
                )

    def test_unknown_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported capture field"):
            tshark_capture.query_capture(
                "sample.pcapng",
                "frame.number == 1",
                ["frame.number", "evil.field"],
            )

    def test_duplicate_fields_are_removed_and_request_order_is_preserved(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed("41462\t0x01\t0x0000\n"),
        ) as run:
            result = tshark_capture.query_capture(
                "sample.pcapng",
                "frame.number == 41462",
                ["frame.number", "ecat.cmd", "frame.number", "ecat.ado"],
            )

        self.assertEqual(
            result["fields"], ["frame.number", "ecat.cmd", "ecat.ado"]
        )
        self.assertEqual(
            list(result["matches"][0]), ["frame.number", "ecat.cmd", "ecat.ado"]
        )
        command = run.call_args.args[0]
        self.assertEqual(command[0], "tshark")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(command.count("-e"), 3)

    def test_query_capture_returns_structured_frame_rows(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed('"41462"\t"1.25"\n'),
        ):
            result = tshark_capture.query_capture(
                "sample.pcapng",
                "frame.number == 41462",
                ["frame.number", "frame.time_epoch"],
                limit=50,
            )

        self.assertEqual(result["capture"], "sample.pcapng")
        self.assertEqual(
            result["matches"],
            [{"frame.number": "41462", "frame.time_epoch": "1.25"}],
        )
        self.assertNotIn("table", result)

    def test_query_capture_does_not_pair_multi_datagram_fields(self):
        output = '"41462"\t"0x01,0x02"\t"1,2"\n'
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(output),
        ):
            result = tshark_capture.query_capture(
                "sample.pcapng",
                "ecat",
                ["frame.number", "ecat.cmd", "ecat.cnt"],
            )

        self.assertEqual(result["matches"][0]["ecat.cmd"], "0x01,0x02")
        self.assertEqual(result["matches"][0]["ecat.cnt"], "1,2")
        self.assertIn("no EtherCAT datagram pairing", result["association"])

    def test_tshark_nonzero_exit_is_reported(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(stderr="Invalid filter", returncode=2),
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid filter"):
                tshark_capture.query_capture(
                    "sample.pcapng",
                    "not a valid filter",
                    ["frame.number"],
                )

    def test_missing_tshark_executable_is_reported(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            side_effect=FileNotFoundError,
        ):
            with self.assertRaisesRegex(FileNotFoundError, "TShark executable not found"):
                tshark_capture.query_capture(
                    "sample.pcapng",
                    "frame.number == 1",
                    ["frame.number"],
                )

    def test_invalid_frame_number_is_rejected(self):
        for frame_number in (0, -1, True, "41462"):
            with self.subTest(frame_number=frame_number), self.assertRaises(ValueError):
                tshark_capture.export_frame_json("sample.pcapng", frame_number)

    def test_export_frame_json_preserves_canonical_packet_tree(self):
        packet = {
            "_source": {
                "layers": {
                    "frame": {"frame.number": "41462"},
                    "eth": {},
                    "ecat": {
                        "EtherCAT datagram: Cmd: APRD": {
                            "Header": {"ecat.cmd": "1"},
                            "ecat.cnt": "1",
                        },
                        "EtherCAT datagram: Cmd: LWR": {
                            "Header": {"ecat.cmd": "2"},
                            "ecat.cnt": "2",
                        },
                    },
                    "ecat_mailbox": {},
                }
            }
        }
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ) as run:
            result = tshark_capture.export_frame_json("sample.pcapng", 41462)

        self.assertEqual(result["packet"], packet)
        command = run.call_args.args[0]
        self.assertIn("frame.number == 41462", command)
        self.assertIn("frame eth ecat ecat_mailbox", command)

    def test_export_frame_json_malformed_json_is_rejected(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed("not json"),
        ):
            with self.assertRaisesRegex(ValueError, "Malformed TShark JSON"):
                tshark_capture.export_frame_json("sample.pcapng", 41462)

    def test_export_frame_json_reports_frame_not_found(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed("[]"),
        ):
            with self.assertRaisesRegex(LookupError, "was not found"):
                tshark_capture.export_frame_json("sample.pcapng", 41462)

    def test_export_frame_json_rejects_multiple_packets(self):
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed("[{}, {}]"),
        ):
            with self.assertRaisesRegex(RuntimeError, "exactly one packet"):
                tshark_capture.export_frame_json("sample.pcapng", 41462)

    def test_agent_rejects_unknown_capture_argument(self):
        action = json.dumps(
            {
                "action": "tool",
                "tool": "query_capture",
                "arguments": {
                    "capture": "sample.pcapng",
                    "display_filter": "frame.number == 1",
                    "fields": ["frame.number"],
                    "limit": 50,
                    "command": "tshark -r sample.pcapng",
                },
            }
        )
        with self.assertRaises(ValueError):
            engineering_tool_agent._parse_action(action)

    def test_agent_dispatches_query_capture(self):
        evidence = {
            "capture": "sample.pcapng",
            "matches": [{"frame.number": "41462"}],
        }
        arguments = {
            "capture": "sample.pcapng",
            "display_filter": "frame.number == 41462",
            "fields": ["frame.number"],
            "limit": 50,
        }
        with patch.object(
            engineering_tool_agent,
            "query_capture",
            return_value=evidence,
        ) as query:
            result = json.loads(
                engineering_tool_agent._tool_result("query_capture", arguments)
            )

        query.assert_called_once_with(**arguments)
        self.assertEqual(result, evidence)

    def test_agent_dispatches_export_frame_json(self):
        evidence = {"capture": "sample.pcapng", "frame_number": 41462, "packet": {}}
        arguments = {"capture": "sample.pcapng", "frame_number": 41462}
        with patch.object(
            engineering_tool_agent,
            "export_frame_json",
            return_value=evidence,
        ) as export:
            result = json.loads(
                engineering_tool_agent._tool_result("export_frame_json", arguments)
            )

        export.assert_called_once_with(**arguments)
        self.assertEqual(result, evidence)

    def test_capture_tool_cache_keys_are_stable_after_field_deduplication(self):
        first = {
            "capture": "sample.pcapng",
            "display_filter": "frame.number == 1",
            "fields": ["frame.number", "ecat.cmd", "frame.number"],
            "limit": 50,
        }
        second = {
            "capture": "sample.pcapng",
            "display_filter": "frame.number == 1",
            "fields": ["frame.number", "ecat.cmd"],
            "limit": 50,
        }
        self.assertEqual(
            engineering_tool_agent._tool_call_key("query_capture", first),
            engineering_tool_agent._tool_call_key("query_capture", second),
        )


if __name__ == "__main__":
    unittest.main()

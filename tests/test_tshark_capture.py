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

    def _packet(self, frame_number, datagrams, source_mac=None, dest_mac=None):
        eth = {}
        if source_mac is not None:
            eth["eth.src"] = source_mac
        if dest_mac is not None:
            eth["eth.dst"] = dest_mac
        return {
            "_source": {
                "layers": {
                    "frame": {"frame.number": str(frame_number)},
                    "eth": eth,
                    "ecat": {
                        f"EtherCAT datagram: {sequence}": datagram
                        for sequence, datagram in enumerate(datagrams, start=1)
                    },
                    "ecat_mailbox": {},
                }
            }
        }

    def _sdo_datagram(
        self,
        adp="0x0001",
        subindex="0x01",
        wkc="0x0001",
        cmd="0x05",
        ado="0x1000",
        sdo_request="0x01",
        sdo_response=None,
    ):
        return {
            "Header": {
                "ecat.cmd": cmd,
                "ecat.idx": "0x01",
                "ecat.adp": adp,
                "ecat.ado": ado,
                "ecat.subframe.length": "0x000a",
            },
            "ecat.cnt": wkc,
            "ecat_mailbox": {
                "ecat_mailbox.type": "0x03",
                "ecat_mailbox.counter": "0x01",
                "ecat_mailbox.coe": {
                    "ecat_mailbox.coe.type": "0x02",
                    "ecat_mailbox.coe.sdoreq": sdo_request,
                    "ecat_mailbox.coe.sdores": sdo_response,
                    "ecat_mailbox.coe.sdoidx": "0x1a00",
                    "ecat_mailbox.coe.sdosub": subindex,
                    "ecat_mailbox.coe.sdodata": "0x60410010",
                    "ecat_mailbox.coe.abortcode": None,
                },
            },
        }

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

    def test_query_frames_batches_one_tshark_call_and_deduplicates_frames(self):
        packets = [
            self._packet(41460, [self._sdo_datagram()]),
            self._packet(41614, [self._sdo_datagram(adp="0x0002")]),
        ]
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps(packets)),
        ) as run:
            result = tshark_capture.query_frames(
                "sample.pcapng", [41460, 41614, 41460]
            )

        self.assertEqual(result["requested_frames"], [41460, 41614])
        self.assertEqual(result["returned_frames"], [41460, 41614])
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("frame.number in {41460,41614}", command)
        self.assertIn("-T", command)
        self.assertIn("json", command)
        self.assertIn("frame eth ecat ecat_mailbox", command)

    def test_query_frames_reports_missing_frames(self):
        packet = self._packet(41460, [self._sdo_datagram()])
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ):
            result = tshark_capture.query_frames(
                "sample.pcapng", [41460, 41614]
            )

        self.assertEqual(result["returned_frames"], [41460])
        self.assertEqual(result["missing_frames"], [41614])

    def test_query_frames_parses_frame_macs_and_command_names(self):
        packets = [
            self._packet(
                41460,
                [self._sdo_datagram(cmd="0x04")],
                source_mac="00:11:22:33:44:55",
                dest_mac="ff:ff:ff:ff:ff:ff",
            ),
            self._packet(
                41461,
                [self._sdo_datagram(cmd="0xff")],
                source_mac="00:11:22:33:44:55",
                dest_mac="ff:ff:ff:ff:ff:ff",
            ),
        ]
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps(packets)),
        ):
            result = tshark_capture.query_frames("sample.pcapng", [41460, 41461])

        first, second = result["frames"]
        self.assertEqual(first["source_mac"], "00:11:22:33:44:55")
        self.assertEqual(first["dest_mac"], "ff:ff:ff:ff:ff:ff")
        self.assertEqual(first["datagrams"][0]["cmd_name"], "FPRD")
        self.assertIsNone(second["datagrams"][0]["cmd_name"])

    def test_command_name_maps_numeric_ecat_commands(self):
        packets = [
            self._packet(
                1,
                [self._sdo_datagram(cmd="0x04"), self._sdo_datagram(cmd="0x05")],
            )
        ]
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps(packets)),
        ):
            result = tshark_capture.query_frames("sample.pcapng", [1])

        self.assertEqual(
            [datagram["cmd_name"] for datagram in result["frames"][0]["datagrams"]],
            ["FPRD", "FPWR"],
        )

    def test_path_role_requires_original_and_modified_mac_pair(self):
        packets = [
            self._packet(
                500,
                [self._sdo_datagram(wkc="0x0001")],
                source_mac="02:11:22:33:44:55",
            ),
            self._packet(
                100,
                [self._sdo_datagram(wkc="0x0001")],
                source_mac="00:11:22:33:44:55",
            ),
        ]
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps(packets)),
        ):
            result = tshark_capture.query_frames("sample.pcapng", [500, 100])

        self.assertEqual(
            [frame["ethercat_path_role"] for frame in result["frames"]],
            ["returning", "outgoing"],
        )

    def test_local_mac_without_original_variant_is_unknown(self):
        packet = self._packet(
            500,
            [self._sdo_datagram()],
            source_mac="02:11:22:33:44:55",
        )
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ):
            result = tshark_capture.query_frames("sample.pcapng", [500])

        self.assertEqual(result["frames"][0]["ethercat_path_role"], "unknown")

    def test_query_frames_rejects_invalid_frame_numbers(self):
        invalid_values = [[], [0], [-1], [True], ["41460"], list(range(1, 52))]
        for frame_numbers in invalid_values:
            with self.subTest(frame_numbers=frame_numbers), self.assertRaises(
                ValueError
            ):
                tshark_capture.query_frames("sample.pcapng", frame_numbers)

    def test_query_frames_keeps_fields_inside_datagram_boundaries(self):
        packet = self._packet(
            41460,
            [
                self._sdo_datagram(adp="0x0001", wkc="0x0001"),
                {
                    "Header": {
                        "ecat.cmd": "APRD",
                        "ecat.adp": "0x0002",
                        "ecat.ado": "0x0130",
                    },
                    "ecat.cnt": "0x0009",
                },
            ],
        )
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ):
            result = tshark_capture.query_frames("sample.pcapng", [41460])

        datagrams = result["frames"][0]["datagrams"]
        self.assertEqual(datagrams[0]["adp"], "0x0001")
        self.assertEqual(datagrams[0]["wkc"], "0x0001")
        self.assertEqual(datagrams[0]["coe"]["index"], "0x1a00")
        self.assertEqual(datagrams[1]["adp"], "0x0002")
        self.assertEqual(datagrams[1]["wkc"], "0x0009")
        self.assertIsNone(datagrams[1]["coe"])

    def test_query_sdo_object_builds_index_filter_and_returns_matching_datagrams(self):
        packet = self._packet(
            41460,
            [
                self._sdo_datagram(subindex="0x01"),
                self._sdo_datagram(adp="0x0002", subindex="0x02"),
            ],
        )
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ) as run:
            result = tshark_capture.query_sdo_object(
                "sample.pcapng", 0x1A00, None, None, None
            )

        self.assertEqual(len(result["frames"]), 1)
        self.assertEqual(len(result["frames"][0]["datagrams"]), 2)
        command = run.call_args.args[0]
        self.assertIn("ecat_mailbox.coe.sdoidx == 0x1a00", command)
        self.assertNotIn("ecat_mailbox.coe.sdosub ==", command)

    def test_query_sdo_object_builds_subindex_and_frame_range_filter(self):
        packet = self._packet(41460, [self._sdo_datagram()])
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ) as run:
            tshark_capture.query_sdo_object(
                "sample.pcapng", 0x1A00, 0x01, 41400, 42500
            )

        command = run.call_args.args[0]
        display_filter = command[command.index("-Y") + 1]
        self.assertIn("ecat_mailbox.coe.sdoidx == 0x1a00", display_filter)
        self.assertIn("ecat_mailbox.coe.sdosub == 0x01", display_filter)
        self.assertIn("frame.number >= 41400", display_filter)
        self.assertIn("frame.number <= 42500", display_filter)

    def test_query_sdo_object_returns_only_matching_datagram(self):
        packet = self._packet(
            41460,
            [
                self._sdo_datagram(subindex="0x01"),
                self._sdo_datagram(adp="0x0002", subindex="0x02"),
            ],
        )
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps([packet])),
        ):
            result = tshark_capture.query_sdo_object(
                "sample.pcapng", 0x1A00, 0x01, None, None
            )

        self.assertEqual(len(result["frames"][0]["datagrams"]), 1)
        self.assertEqual(result["frames"][0]["datagrams"][0]["adp"], "0x0001")

    def test_query_sdo_object_keeps_outgoing_and_returning_sdo_copies(self):
        packets = [
            self._packet(
                41460,
                [self._sdo_datagram(wkc="0", cmd="0x05")],
                source_mac="00:18:23:13:02:09",
            ),
            self._packet(
                41461,
                [self._sdo_datagram(wkc="1", cmd="0x05")],
                source_mac="02:18:23:13:02:09",
            ),
            self._packet(
                41614,
                [
                    self._sdo_datagram(
                        wkc="1",
                        cmd="0x04",
                        ado="0x10c0",
                        sdo_request=None,
                        sdo_response="0x01",
                    )
                ],
                source_mac="02:18:23:13:02:09",
            ),
        ]
        with patch.object(
            tshark_capture.subprocess,
            "run",
            return_value=self._completed(json.dumps(packets)),
        ):
            result = tshark_capture.query_sdo_object(
                "sample.pcapng", 0x1A00, 0x01, 41400, 42500
            )

        self.assertEqual(result["returned_frames"], [41460, 41461, 41614])
        self.assertEqual(
            [frame["ethercat_path_role"] for frame in result["frames"]],
            ["outgoing", "returning", "returning"],
        )
        self.assertEqual(
            [frame["datagrams"][0]["cmd_name"] for frame in result["frames"]],
            ["FPWR", "FPWR", "FPRD"],
        )

    def test_query_sdo_object_rejects_invalid_arguments(self):
        invalid_arguments = [
            {"index": -1, "subindex": None, "frame_start": None, "frame_end": None},
            {"index": 0x10000, "subindex": None, "frame_start": None, "frame_end": None},
            {"index": 0x1A00, "subindex": -1, "frame_start": None, "frame_end": None},
            {"index": 0x1A00, "subindex": 0x100, "frame_start": None, "frame_end": None},
            {"index": 0x1A00, "subindex": True, "frame_start": None, "frame_end": None},
            {"index": 0x1A00, "subindex": None, "frame_start": 0, "frame_end": None},
            {"index": 0x1A00, "subindex": None, "frame_start": True, "frame_end": None},
            {"index": 0x1A00, "subindex": None, "frame_start": 20, "frame_end": 10},
        ]
        for values in invalid_arguments:
            arguments = {"capture": "sample.pcapng", **values}
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                tshark_capture.validate_query_sdo_object_arguments(arguments)

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

    def test_agent_rejects_malformed_new_capture_tool_arguments(self):
        for tool, arguments in (
            (
                "query_frames",
                {"capture": "sample.pcapng", "frame_numbers": [41462], "argv": []},
            ),
            (
                "query_sdo_object",
                {
                    "capture": "sample.pcapng",
                    "index": 0x1A00,
                    "subindex": 1,
                    "frame_start": None,
                },
            ),
        ):
            action = json.dumps(
                {"action": "tool", "tool": tool, "arguments": arguments}
            )
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                engineering_tool_agent._parse_action(action)

    def test_agent_dispatches_new_capture_tools(self):
        frame_evidence = {"capture": "sample.pcapng", "frames": []}
        frame_arguments = {"capture": "sample.pcapng", "frame_numbers": [41462]}
        with patch.object(
            engineering_tool_agent, "query_frames", return_value=frame_evidence
        ) as query_frames:
            result = json.loads(
                engineering_tool_agent._tool_result("query_frames", frame_arguments)
            )
        query_frames.assert_called_once_with(**frame_arguments)
        self.assertEqual(result, frame_evidence)

        sdo_evidence = {"capture": "sample.pcapng", "frames": []}
        sdo_arguments = {
            "capture": "sample.pcapng",
            "index": 0x1A00,
            "subindex": 1,
            "frame_start": None,
            "frame_end": None,
        }
        with patch.object(
            engineering_tool_agent, "query_sdo_object", return_value=sdo_evidence
        ) as query_sdo:
            result = json.loads(
                engineering_tool_agent._tool_result(
                    "query_sdo_object", sdo_arguments
                )
            )
        query_sdo.assert_called_once_with(**sdo_arguments)
        self.assertEqual(result, sdo_evidence)

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

    def test_query_frames_cache_key_reuses_same_batch_frame_set(self):
        first = {"capture": "sample.pcapng", "frame_numbers": [41462, 41460, 41462]}
        second = {"capture": "sample.pcapng", "frame_numbers": [41460, 41462]}
        self.assertEqual(
            engineering_tool_agent._tool_call_key("query_frames", first),
            engineering_tool_agent._tool_call_key("query_frames", second),
        )

    def test_query_sdo_cache_key_is_stable_after_validation(self):
        arguments = {
            "capture": "sample.pcapng",
            "index": 0x1A00,
            "subindex": None,
            "frame_start": None,
            "frame_end": None,
        }
        self.assertEqual(
            engineering_tool_agent._tool_call_key("query_sdo_object", arguments),
            ("query_sdo_object", "sample.pcapng", 0x1A00, None, None, None),
        )


if __name__ == "__main__":
    unittest.main()

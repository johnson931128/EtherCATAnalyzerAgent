import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import tshark_runtime


class TSharkRuntimeTests(unittest.TestCase):
    def setUp(self):
        tshark_runtime._RUNTIME_CHECKS.clear()

    def tearDown(self):
        tshark_runtime._RUNTIME_CHECKS.clear()

    def _completed(self, stdout="tshark version 4.0.0", stderr="", returncode=0):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    def test_explicit_valid_tshark_path_is_ok(self):
        with patch.object(
            tshark_runtime.subprocess,
            "run",
            return_value=self._completed(),
        ) as run:
            result = tshark_runtime.check_tshark_runtime(sys.executable)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["resolved"], sys.executable)
        self.assertEqual(run.call_args.args[0], [sys.executable, "--version"])
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_explicit_missing_tshark_path_is_error(self):
        missing = Path(__file__).resolve().parent / "missing-tshark.exe"
        result = tshark_runtime.check_tshark_runtime(str(missing))

        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(
            result["message"], f"TShark executable not found: {missing}"
        )

    def test_bare_tshark_resolved_on_path_is_ok(self):
        client = Mock(return_value=self._completed())
        with patch.object(tshark_runtime.shutil, "which", return_value="tshark"), patch.object(
            tshark_runtime.subprocess, "run", client
        ):
            result = tshark_runtime.check_tshark_runtime("tshark")

        self.assertEqual(result["status"], "OK")
        client.assert_called_once()

    def test_bare_tshark_missing_on_path_is_error(self):
        with patch.object(tshark_runtime.shutil, "which", return_value=None), patch.object(
            tshark_runtime.subprocess, "run"
        ) as run:
            result = tshark_runtime.check_tshark_runtime("tshark")

        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["message"], "TShark executable not found: tshark")
        run.assert_not_called()

    def test_failed_preflight_guards_later_resolution(self):
        missing = "missing-tshark-command"
        with patch.object(tshark_runtime.shutil, "which", return_value=None):
            tshark_runtime.check_tshark_runtime(missing)

        with self.assertRaisesRegex(RuntimeError, "TShark executable not found"):
            tshark_runtime.resolve_tshark_executable(missing)


if __name__ == "__main__":
    unittest.main()

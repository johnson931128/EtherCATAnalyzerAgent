import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliStartupTests(unittest.TestCase):
    def _run_python(self, code, env=None):
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_import_main_keeps_heavy_modules_unloaded(self):
        result = self._run_python(
            "import main, sys; print('ok'); "
            "print([name for name in ('docling', 'fitz', 'langchain_openai') "
            "if name in sys.modules])"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)
        self.assertIn("[]", result.stdout)
        self.assertNotIn("fitz API is deprecated", result.stderr)

    def test_startup_preflight_keeps_heavy_modules_unloaded(self):
        env = os.environ.copy()
        env["TSHARK_EXECUTABLE"] = r"C:\missing\tshark.exe"
        result = self._run_python(
            "import main, sys; main.print_startup_diagnostics(); "
            "print([name for name in ('docling', 'fitz', 'langchain_openai') "
            "if name in sys.modules])",
            env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[]", result.stdout)

    def test_startup_diagnostics_show_runtime_capture_state(self):
        env = os.environ.copy()
        env.update(
            {
                "CAPTURE_INPUT_ROOT": r"D:\EtherCATAnalyzer\Data\Pcap",
                "TSHARK_EXECUTABLE": r"C:\WiresharkPortable64\App\Wireshark\tshark.exe",
            }
        )
        result = self._run_python("import main; main.print_startup_diagnostics()", env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(r"Capture root: D:\EtherCATAnalyzer\Data\Pcap", result.stdout)
        self.assertIn("Active capture: Not selected", result.stdout)
        self.assertIn(
            r"TShark: C:\WiresharkPortable64\App\Wireshark\tshark.exe",
            result.stdout,
        )

    def test_startup_diagnostics_do_not_display_default_capture(self):
        env = os.environ.copy()
        env["DEFAULT_CAPTURE_NAME"] = "PowerOn.pcapng"
        env["TSHARK_EXECUTABLE"] = r"C:\missing\tshark.exe"
        result = self._run_python("import main; main.print_startup_diagnostics()", env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Active capture: Not selected", result.stdout)
        self.assertNotIn("Default capture:", result.stdout)


if __name__ == "__main__":
    unittest.main()

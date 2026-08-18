import unittest
from pathlib import Path
from unittest.mock import patch

import main


class CliCaptureTests(unittest.TestCase):
    def test_list_available_captures_is_direct_and_deterministic(self):
        class Entry:
            def __init__(self, name, is_file=True):
                self.name = name
                self.suffix = Path(name).suffix
                self._is_file = is_file

            def is_file(self):
                return self._is_file

        entries = [
            Entry("z.pcapng"),
            Entry("A.pcap"),
            Entry("ignored.txt"),
            Entry("nested", is_file=False),
        ]
        root = Path(__file__).resolve().parents[1] / "captures"
        with patch.object(Path, "iterdir", return_value=entries):
            self.assertEqual(
                main.list_available_captures(root), ["A.pcap", "z.pcapng"]
            )

    def test_set_active_capture_accepts_existing_logical_filename(self):
        self.assertEqual(main.set_active_capture("test.pcapng"), "test.pcapng")

    def test_set_active_capture_rejects_paths_and_missing_files(self):
        for filename in (
            "../PowerOn.pcapng",
            r"D:\captures\PowerOn.pcapng",
            r"folder\PowerOn.pcapng",
            "Missing.pcapng",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises((OSError, ValueError)):
                    main.set_active_capture(filename)

    def test_local_settings_example_is_committable_without_default_capture(self):
        example = Path(__file__).resolve().parents[1] / "local.settings.example.ps1"
        gitignore = example.parent / ".gitignore"

        contents = example.read_text(encoding="utf-8")
        self.assertIn('$env:CAPTURE_INPUT_ROOT="', contents)
        self.assertIn('$env:TSHARK_EXECUTABLE="', contents)
        self.assertNotIn("DEFAULT_CAPTURE_NAME", contents)
        self.assertIn("local.settings.ps1", gitignore.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

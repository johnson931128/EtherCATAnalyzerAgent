import os
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT / "spec"
SPEC_ORIGINAL_ROOT = SPEC_ROOT / "original"
SPEC_GENERATED_ROOT = SPEC_ROOT / "generated"
CAPTURE_INPUT_ROOT = Path(
    os.environ.get("CAPTURE_INPUT_ROOT", str(REPOSITORY_ROOT / "captures"))
).expanduser()
TSHARK_EXECUTABLE = os.environ.get("TSHARK_EXECUTABLE", "tshark").strip()

PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DOCS_READ_PATH = PROJECT_ROOT / "docs" / "read"

CAPTURE_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json")
RAW_TSHARK_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\output.json")

SOURCE_FILES = {
    "slave_discovery":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Analysis" / "SlaveDiscoveryAnalyzer.cs",

    "datagram_record":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "EtherCatDatagramRecord.cs",

    "discovered_slave":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "DiscoveredSlave.cs",
}

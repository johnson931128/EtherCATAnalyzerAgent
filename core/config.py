from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DOCS_READ_PATH = PROJECT_ROOT / "docs" / "read"

CAPTURE_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json")
RAW_TSHARK_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\output.json")

ET1100_SPEC_PATH = (
    REPOSITORY_ROOT
    / "spec"
    / "original"
    / "ET1100"
    / "ET1100_v2.5_2025-07-28.pdf"
)


SOURCE_FILES = {
    "slave_discovery":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Analysis" / "SlaveDiscoveryAnalyzer.cs",

    "datagram_record":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "EtherCatDatagramRecord.cs",

    "discovered_slave":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "DiscoveredSlave.cs",
}

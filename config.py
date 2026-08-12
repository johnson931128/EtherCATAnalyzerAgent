from pathlib import Path


PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DOCS_READ_PATH = PROJECT_ROOT / "docs" / "read"

CAPTURE_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json")
RAW_TSHARK_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\output.json")

ET1100_SPEC_PATH = Path(r"D:\DATA\SPEC\EtherCAT_ET1100_Datasheet_all_v1i8.pdf")


SOURCE_FILES = {
    "slave_discovery":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Analysis" / "SlaveDiscoveryAnalyzer.cs",

    "datagram_record":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "EtherCatDatagramRecord.cs",

    "discovered_slave":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "DiscoveredSlave.cs",
}

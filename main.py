import json
import re
from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END


class AgentState(TypedDict):
    task: str
    context: str
    docs_index: str
    selected_docs: str
    docs_content: str
    selected_source: str
    source_code: str
    capture_mode: str
    capture_evidence: str
    result: str


PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DOCS_READ_PATH = PROJECT_ROOT / "docs" / "read"

CAPTURE_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json")

ET1100_SPEC_PATH = Path(r"D:\DATA\SPEC\EtherCAT_ET1100_Datasheet_all_v1i8.pdf")


SOURCE_FILES = {
    "slave_discovery":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Analysis" / "SlaveDiscoveryAnalyzer.cs",

    "datagram_record":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "EtherCatDatagramRecord.cs",

    "discovered_slave":
        PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "DiscoveredSlave.cs",
}


llm = ChatOpenAI(
    model="Qwen/Qwen3.5-122B-A10B",
    base_url="http://127.0.0.1:5000/v1",
    api_key="local-proxy",
    temperature=0,
    timeout=120,
    max_retries=0,
)


def parse_number(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()

    if text.lower().startswith("0x"):
        return int(text, 16)

    return int(text)


def calculate_topology_position(initial_adp):
    distance_from_zero = (-initial_adp) & 0xFFFF
    return distance_from_zero + 1


def build_auto_increment_pairs(records):
    auto_increment_command_codes = {0x01, 0x02, 0x03, 0x0D}
    records_by_time = {}

    for record in records:
        command_code = parse_number(record.get("CommandCode"))

        if command_code not in auto_increment_command_codes:
            continue

        time_utc = record.get("TimeUtc")
        records_by_time.setdefault(time_utc, []).append(record)

    timestamp_groups = sorted(
        records_by_time.values(),
        key=lambda group: min(record["FrameNumber"] for record in group)
    )

    pairs = []

    for timestamp_group in timestamp_groups:
        records_by_frame = {}

        for record in timestamp_group:
            frame_number = record.get("FrameNumber")
            records_by_frame.setdefault(frame_number, []).append(record)

        frame_groups = [
            records_by_frame[frame_number]
            for frame_number in sorted(records_by_frame)
        ]

        if len(frame_groups) != 2:
            continue

        outgoing_frame = sorted(
            frame_groups[0],
            key=lambda record: record.get("DatagramSequence")
        )
        returning_frame = sorted(
            frame_groups[1],
            key=lambda record: record.get("DatagramSequence")
        )

        if not outgoing_frame or not returning_frame:
            continue

        outgoing_source = outgoing_frame[0].get("SourceMac") or ""
        returning_source = returning_frame[0].get("SourceMac") or ""

        if outgoing_source.casefold() == returning_source.casefold():
            continue

        returning_by_key = {}

        for record in returning_frame:
            key = auto_increment_pair_key(record)
            returning_by_key.setdefault(key, record)

        for outgoing in outgoing_frame:
            returning = returning_by_key.get(auto_increment_pair_key(outgoing))

            if returning is None:
                continue

            pairs.append({
                "Outgoing": outgoing,
                "Returning": returning,
            })

    return pairs


def auto_increment_pair_key(record):
    return (
        parse_number(record.get("DatagramSequence")),
        parse_number(record.get("CommandCode")),
        parse_number(record.get("ProtocolIndex")),
        parse_number(record.get("Ado")),
        parse_number(record.get("DataLength")),
    )


def build_pair_evidence(pair):
    outgoing = pair["Outgoing"]
    returning = pair["Returning"]
    outgoing_adp = parse_number(outgoing.get("Adp"))
    outgoing_working_counter = parse_number(outgoing.get("WorkingCounter"))
    returning_working_counter = parse_number(returning.get("WorkingCounter"))

    evidence = {
        "OutgoingFrame": outgoing.get("FrameNumber"),
        "ReturningFrame": returning.get("FrameNumber"),
        "DatagramSequence": outgoing.get("DatagramSequence"),
        "CommandCode": outgoing.get("CommandCode"),
        "OutgoingAdp": outgoing.get("Adp"),
        "ReturningAdp": returning.get("Adp"),
        "Ado": outgoing.get("Ado"),
        "OutgoingWorkingCounter": outgoing_working_counter,
        "ReturningWorkingCounter": returning_working_counter,
        "WorkingCounterDelta": (
            returning_working_counter - outgoing_working_counter
        ),
    }

    if outgoing_adp is not None:
        evidence["CalculatedTopologyPosition"] = (
            calculate_topology_position(outgoing_adp)
        )

    return evidence


def load_context(state: AgentState):
    context = AGENTS_PATH.read_text(encoding="utf-8")
    return {"context": context}


def load_docs_index(state: AgentState):
    entries = []

    for path in sorted(DOCS_READ_PATH.glob("*.md")):
        headings = []

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()

            if stripped.startswith("#"):
                headings.append(stripped)

        entry = path.name

        if headings:
            entry += "\n" + "\n".join(f"  {heading}" for heading in headings)

        entries.append(entry)

    return {"docs_index": "\n\n".join(entries)}


def select_docs(state: AgentState):
    prompt = f"""
任務：

{state["task"]}

以下是 docs/read 可用文件索引：

{state["docs_index"]}

請選出最多 2 個與任務最相關的 Markdown 文件。

只能回覆完整檔名，每行一個。
不要加編號。
不要加說明。
如果沒有相關文件，只回覆 NONE。
"""

    response = llm.invoke(prompt)

    return {"selected_docs": response.content.strip()}


def load_selected_docs(state: AgentState):
    if state["selected_docs"].strip().upper() == "NONE":
        return {"docs_content": ""}

    available_docs = {
        path.name: path
        for path in DOCS_READ_PATH.glob("*.md")
    }

    contents = []

    for line in state["selected_docs"].splitlines():
        file_name = line.strip()
        file_name = file_name.strip("`")
        file_name = file_name.lstrip("-* ").strip()

        path = available_docs.get(file_name)

        if path is None:
            continue

        content = path.read_text(encoding="utf-8")
        contents.append(f"===== {file_name} =====\n{content}")

    return {"docs_content": "\n\n".join(contents)}


def select_source(state: AgentState):
    symbols = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", state["task"])

    for symbol in symbols:
        if len(symbol) < 4:
            continue

        for source_name, source_path in SOURCE_FILES.items():
            source_code = source_path.read_text(encoding="utf-8")

            if symbol in source_code:
                return {"selected_source": source_name}

    prompt = f"""
任務：

{state["task"]}

只能從以下程式碼檔案選一個最相關的：

slave_discovery
datagram_record
discovered_slave

只回覆選項名稱，不要解釋。
"""

    response = llm.invoke(prompt)

    selected_source = response.content.strip()

    return {"selected_source": selected_source}


def inspect_source(state: AgentState):
    source_path = SOURCE_FILES[state["selected_source"]]
    source_code = source_path.read_text(encoding="utf-8")

    return {"source_code": source_code}


def select_capture_mode(state: AgentState):
    task = state["task"].lower()

    eeprom_keywords = [
        "bindeepromidentity",
        "eeprom",
        "vendor id",
        "vendorid",
        "product code",
        "productcode",
    ]

    topology_keywords = [
        "calculatetopologyposition",
        "topology position",
        "topology",
        "拓撲位置",
        "拓樸位置",
    ]

    if any(keyword in task for keyword in eeprom_keywords):
        return {"capture_mode": "eeprom_identity"}

    if any(keyword in task for keyword in topology_keywords):
        return {"capture_mode": "topology_position"}

    return {"capture_mode": "none"}


def query_topology_capture(pairs):
    matches = []

    for pair in pairs:
        outgoing = pair["Outgoing"]
        command_code = parse_number(outgoing.get("CommandCode"))
        ado = parse_number(outgoing.get("Ado"))

        if command_code != 0x02:
            continue

        if ado != 0x0010:
            continue

        if parse_number(outgoing.get("Adp")) is None:
            continue

        evidence = build_pair_evidence(pair)
        evidence["ConfiguredStationAddressData"] = (
            outgoing.get("RegisterDataHex") or outgoing.get("DataHex")
        )
        matches.append(evidence)

    return matches[:20]


def query_eeprom_capture(pairs):
    matches = []

    for pair in pairs:
        outgoing = pair["Outgoing"]
        returning = pair["Returning"]
        command_code = parse_number(outgoing.get("CommandCode"))
        ado = parse_number(outgoing.get("Ado"))

        is_eeprom_control = command_code == 0x02 and ado == 0x0502
        is_eeprom_data = command_code == 0x01 and ado == 0x0508

        if not is_eeprom_control and not is_eeprom_data:
            continue

        if parse_number(outgoing.get("Adp")) is None:
            continue

        evidence = build_pair_evidence(pair)
        evidence["EepromControlStatus"] = outgoing.get("EepromControlStatus")
        evidence["EepromWordAddress"] = outgoing.get("EepromWordAddress")
        evidence["EepromData"] = returning.get("EepromData")
        matches.append(evidence)

    return matches[:40]


def query_capture(state: AgentState):
    records = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
    pairs = build_auto_increment_pairs(records)

    if state["capture_mode"] == "topology_position":
        matches = query_topology_capture(pairs)

    elif state["capture_mode"] == "eeprom_identity":
        matches = query_eeprom_capture(pairs)

    else:
        return {
            "capture_evidence": "No capture query was selected for this task."
        }

    capture_evidence = json.dumps(
        matches,
        ensure_ascii=False,
        indent=2
    )

    return {"capture_evidence": capture_evidence}


def analyze(state: AgentState):
    prompt = f"""
以下是 EtherCATAnalyzer 專案規則：

{state["context"]}

以下是從 docs/read 選出的相關專案筆記：

{state["docs_content"]}

注意：

docs/read 是整理過的參考資料，不代表完整 EtherCAT protocol specification。
如果 docs/read 沒有足夠資訊支持 protocol fact，不得使用一般模型知識補完。
應明確說明需要查完整 ET1100 specification。

完整 ET1100 specification 路徑為：

{ET1100_SPEC_PATH}

目前尚未把完整 PDF evidence 接入這個 Graph，因此不能假裝已經查過完整 ET1100 specification。

以下是目前分析的 source code：

{state["source_code"]}

Capture query mode：

{state["capture_mode"]}

以下是 Python 從 ethercat-datagrams.json 實際查詢得到的 capture evidence：

{state["capture_evidence"]}

Capture evidence contract:

- Python has already paired Outgoing and Returning datagrams deterministically.
- Do not infer packet direction or reconstruct pairs.
- CalculatedTopologyPosition is calculated only from OutgoingAdp.
- ReturningAdp must never be treated as a topology address.
- EepromControlStatus and EepromWordAddress come from Outgoing.
- EepromData comes from Returning.
- ConfiguredStationAddressData comes from Outgoing.

如果 evidence 中存在 CalculatedTopologyPosition：

該值是 Python 依照目前 C# CalculateTopologyPosition 的 16-bit unchecked arithmetic
預先計算出的 deterministic evidence。

不得自行重新計算或覆寫 CalculatedTopologyPosition。

任務：

{state["task"]}

回答時必須嚴格區分：

1. Source Code：目前程式實際實作的行為。
2. Capture Evidence：目前 JSON 實際觀察到的行為。
3. docs/read：整理過的參考資料。
4. Full Specification：目前尚未由 Python 擷取的完整 ET1100 PDF。

不得把 docs/read、Agent prompt 或模型一般知識誤稱為 AGENTS.md 規則。

不得因為目前查詢結果沒有某種封包，就推論整份 capture 不存在該封包。
只能描述本次 capture query 實際查到的內容。

如果一般模型知識與 Source Code 或 Capture Evidence 衝突，描述本專案時以實際 evidence 為準。
"""

    response = llm.invoke(prompt)

    return {"result": response.content}


builder = StateGraph(AgentState)

builder.add_node("load_context", load_context)
builder.add_node("load_docs_index", load_docs_index)
builder.add_node("select_docs", select_docs)
builder.add_node("load_selected_docs", load_selected_docs)
builder.add_node("select_source", select_source)
builder.add_node("inspect_source", inspect_source)
builder.add_node("select_capture_mode", select_capture_mode)
builder.add_node("query_capture", query_capture)
builder.add_node("analyze", analyze)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "load_docs_index")
builder.add_edge("load_docs_index", "select_docs")
builder.add_edge("select_docs", "load_selected_docs")
builder.add_edge("load_selected_docs", "select_source")
builder.add_edge("select_source", "inspect_source")
builder.add_edge("inspect_source", "select_capture_mode")
builder.add_edge("select_capture_mode", "query_capture")
builder.add_edge("query_capture", "analyze")
builder.add_edge("analyze", END)

graph = builder.compile()


if __name__ == "__main__":
    print("EtherCAT Analyzer Agent")
    print("輸入 exit 離開")

    while True:
        task = input("\n> ").strip()

        if task.lower() in {"exit", "quit", "q"}:
            break

        if not task:
            continue

        result = graph.invoke({
            "task": task
        })

        print(f"\nSelected docs:\n{result['selected_docs']}")
        print(f"\nSelected source: {result['selected_source']}")
        print(f"Capture mode: {result['capture_mode']}")
        print()
        print(result["result"])

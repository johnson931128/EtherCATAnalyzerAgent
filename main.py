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
    selected_source: str
    source_code: str
    capture_evidence: str
    result: str


PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DOCS_READ_PATH = PROJECT_ROOT / "docs" / "read"
CAPTURE_PATH = Path(r"D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json")

SOURCE_FILES = {
    "slave_discovery": PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Analysis" / "SlaveDiscoveryAnalyzer.cs",
    "datagram_record": PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "EtherCatDatagramRecord.cs",
    "discovered_slave": PROJECT_ROOT / "AnalyzerDll" / "EtherCATAnalyzer" / "Models" / "DiscoveredSlave.cs",
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


def load_context(state: AgentState):
    context = AGENTS_PATH.read_text(encoding="utf-8")
    return {"context": context}


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
    return {"selected_source": response.content.strip()}


def inspect_source(state: AgentState):
    source_path = SOURCE_FILES[state["selected_source"]]
    source_code = source_path.read_text(encoding="utf-8")
    return {"source_code": source_code}

def calculate_topology_position(initial_adp):
    distance_from_zero = (-initial_adp) & 0xFFFF
    return distance_from_zero + 1

def query_capture(state: AgentState):
    records = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))

    matches = []

    for record in records:
        command_code = parse_number(record.get("CommandCode"))
        ado = parse_number(record.get("Ado"))
        working_counter = parse_number(record.get("WorkingCounter"))

        if command_code != 0x02:
            continue

        if ado != 0x0010:
            continue

        if working_counter != 0:
            continue

        adp = parse_number(record.get("Adp"))

        matches.append({
            "FrameNumber": record.get("FrameNumber"),
            "DatagramSequence": record.get("DatagramSequence"),
            "CommandCode": record.get("CommandCode"),
            "Adp": record.get("Adp"),
            "Ado": record.get("Ado"),
            "DataHex": record.get("RegisterDataHex") or record.get("DataHex"),
            "WorkingCounter": record.get("WorkingCounter"),
            "CalculatedTopologyPosition": calculate_topology_position(adp),
        })

    capture_evidence = json.dumps(matches[:20], ensure_ascii=False, indent=2)

    return {"capture_evidence": capture_evidence}

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

def analyze(state: AgentState):
    prompt = f"""
以下是 EtherCATAnalyzer 專案規則：
CalculatedTopologyPosition 是 Python 依照目前 C# 實作的 16-bit unchecked arithmetic 預先計算的 deterministic evidence。
不得自行重新計算或覆寫此值。

{state["context"]}

以下是目前分析的 source code：

{state["source_code"]}

以下是從 ethercat-datagrams.json 實際查詢得到的 capture evidence。
這些資料代表專案實際觀察到的封包行為：

{state["capture_evidence"]}

任務：

{state["task"]}

分析時必須區分：

1. Source code 實際實作的行為。
2. Capture evidence 實際觀察到的行為。
3. 沒有 evidence 支持的 EtherCAT protocol facts 不要自行假設。

如果一般知識與 capture evidence 衝突，描述本專案行為時以 capture evidence 為準。
"""

    response = llm.invoke(prompt)
    return {"result": response.content}


builder = StateGraph(AgentState)

builder.add_node("load_context", load_context)
builder.add_node("select_source", select_source)
builder.add_node("inspect_source", inspect_source)
builder.add_node("query_capture", query_capture)
builder.add_node("analyze", analyze)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "load_docs_index")
builder.add_edge("load_docs_index", "select_source")
builder.add_edge("select_source", "inspect_source")
builder.add_edge("inspect_source", "query_capture")
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

        print("\nDocs index:")
        print(result["docs_index"])
        print(f"\nSelected source: {result['selected_source']}")
        print()
        print(result["result"])
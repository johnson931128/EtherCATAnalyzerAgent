import re
from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END


class AgentState(TypedDict):
    task: str
    context: str
    selected_source: str
    source_code: str
    result: str


PROJECT_ROOT = Path(r"D:\EtherCATAnalyzer\EtherCATAnalyzer_net472")
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"

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

只回覆選項名稱。
"""

    response = llm.invoke(prompt)
    return {"selected_source": response.content.strip()}


def inspect_source(state: AgentState):
    source_path = SOURCE_FILES[state["selected_source"]]
    source_code = source_path.read_text(encoding="utf-8")
    return {"source_code": source_code}


def analyze(state: AgentState):
    prompt = f"""
以下是 EtherCATAnalyzer 專案規則：

{state["context"]}

目前選擇的程式碼：
{state["selected_source"]}

程式碼內容：

{state["source_code"]}

任務：

{state["task"]}
"""

    response = llm.invoke(prompt)
    return {"result": response.content}


builder = StateGraph(AgentState)

builder.add_node("load_context", load_context)
builder.add_node("select_source", select_source)
builder.add_node("inspect_source", inspect_source)
builder.add_node("analyze", analyze)

builder.add_edge(START, "load_context")
builder.add_edge("load_context", "select_source")
builder.add_edge("select_source", "inspect_source")
builder.add_edge("inspect_source", "analyze")
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

        print(f"\nSelected source: {result['selected_source']}")
        print()
        print(result["result"])
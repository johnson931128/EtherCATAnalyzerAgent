import re

from config import SOURCE_FILES
from llm import llm
from state import AgentState


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

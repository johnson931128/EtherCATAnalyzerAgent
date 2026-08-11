from config import DOCS_READ_PATH
from llm import llm
from state import AgentState


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

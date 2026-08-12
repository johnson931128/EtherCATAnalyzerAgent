from pathlib import Path

from config import DOCS_READ_PATH
from llm import llm
from state import AgentState


MAX_SELECTED_DOCS = 2


def _markdown_documents():
    root = DOCS_READ_PATH.resolve()
    return sorted(
        (
            path.relative_to(root).as_posix(),
            path,
        )
        for path in root.rglob("*.md")
        if path.is_file()
    )


def _safe_document_path(identifier):
    if not isinstance(identifier, str):
        return None

    identifier = identifier.strip().strip("`").replace("\\", "/")
    identifier = identifier.lstrip("-* ").strip()
    if not identifier or Path(identifier).is_absolute():
        return None

    relative_path = Path(identifier)
    if ".." in relative_path.parts:
        return None

    root = DOCS_READ_PATH.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None

    if candidate.suffix.casefold() != ".md" or not candidate.is_file():
        return None
    return candidate


def load_docs_index(state: AgentState):
    entries = []

    for relative_path, path in _markdown_documents():
        headings = []

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()

            if stripped.startswith("#"):
                headings.append(stripped)

        entry = relative_path

        if headings:
            entry += "\n" + "\n".join(f"  {heading}" for heading in headings)

        entries.append(entry)

    return {"docs_index": "\n\n".join(entries)}


def select_docs(state: AgentState):
    prompt = f"""
Select at most {MAX_SELECTED_DOCS} documents. Return only their relative Markdown paths from docs/read,
one per line, such as notes/EtherCAT_EEPROM.md. Return NONE when no document is relevant.

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

    contents = []

    for line in state["selected_docs"].splitlines():
        if len(contents) >= MAX_SELECTED_DOCS:
            break

        document_id = line.strip()
        document_id = document_id.strip("`")
        document_id = document_id.lstrip("-* ").strip()
        path = _safe_document_path(document_id)

        if path is None:
            continue

        content = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(DOCS_READ_PATH.resolve()).as_posix()
        contents.append(f"===== {relative_path} =====\n{content}")

    return {"docs_content": "\n\n".join(contents)}

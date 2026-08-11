from typing import TypedDict


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

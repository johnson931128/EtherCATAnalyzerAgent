from typing import Optional, TypedDict


class AgentState(TypedDict):
    task: str
    route_mode: str
    task_type: str
    context: str
    docs_index: str
    selected_docs: str
    docs_content: str
    selected_source: str
    source_code: str
    capture_mode: str
    capture_evidence: str
    result: str
    pdf_evidence: list
    build_docs_validation: str
    generated_file_path: str
    generated_file_status: str
    tools_used: list
    verification_context: dict
    active_capture: Optional[str]

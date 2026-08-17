"""Result document assembly for graph outputs."""

from typing import Any, Dict

from retrieval.sdo_rendering import (
    render_sdo_engineering_evidence,
    render_sdo_engineering_references,
    render_sdo_verification_summary,
)


def build_result_document(task: str, graph_result: Dict[str, Any]) -> str:
    """Assemble the persisted result without changing non-SDO formatting."""
    selected_docs = graph_result.get("selected_docs", "")
    selected_source = graph_result.get("selected_source", "")
    capture_mode = graph_result.get("capture_mode", "")
    agent_result = graph_result.get("result", "")
    task_section = task if task.endswith("\n") else task + "\n"
    selected_source_line = "- Selected source:"

    if selected_source:
        selected_source_line += f" {selected_source}"

    if capture_mode == "sdo_verification":
        verification_context = graph_result.get("verification_context", {})
        verification_context = (
            verification_context if isinstance(verification_context, dict) else {}
        )
        verification_results = verification_context.get("verification_results", [])
        verification_results = (
            verification_results if isinstance(verification_results, list) else []
        )
        return (
            "# EtherCAT Analyzer Agent Result\n\n"
            "## Task\n"
            f"{task_section}\n"
            "## Routing\n"
            f"- Selected docs:\n{selected_docs}\n"
            f"{selected_source_line}\n"
            f"- Capture mode: {capture_mode}\n\n"
            "## Verification Summary\n\n"
            f"{render_sdo_verification_summary(verification_results)}\n\n"
            "## Engineering Evidence\n\n"
            f"{render_sdo_engineering_evidence(verification_results)}\n\n"
            "## Engineering References\n\n"
            f"{render_sdo_engineering_references(verification_context.get('reference_context', []))}\n\n"
            "## Explanation\n\n"
            f"{agent_result}\n"
        )

    return (
        "# EtherCAT Analyzer Agent Result\n\n"
        "## Task\n"
        f"{task_section}\n"
        "## Routing\n"
        f"- Selected docs:\n{selected_docs}\n"
        f"{selected_source_line}\n"
        f"- Capture mode: {capture_mode}\n\n"
        "## Result\n"
        f"{agent_result}\n"
    )

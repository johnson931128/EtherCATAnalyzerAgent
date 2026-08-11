import argparse
from pathlib import Path

from graph import graph


PROJECT_ROOT = Path(__file__).resolve().parent
TASK_PATH = PROJECT_ROOT / "task.md"
RESULT_PATH = PROJECT_ROOT / "result.md"


def build_result_document(task, graph_result):
    selected_docs = graph_result.get("selected_docs", "")
    selected_source = graph_result.get("selected_source", "")
    capture_mode = graph_result.get("capture_mode", "")
    agent_result = graph_result.get("result", "")
    task_section = task if task.endswith("\n") else task + "\n"
    selected_source_line = "- Selected source:"

    if selected_source:
        selected_source_line += f" {selected_source}"

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


def append_build_docs_result(existing, report):
    for marker in (
        "# Generated ET1100 Documentation Draft",
        "# Build Docs Execution Report",
    ):
        if marker in existing:
            existing = existing.split(marker, 1)[0].rstrip()

    while existing.endswith("---"):
        existing = existing[:-3].rstrip()

    separator = "\n\n---\n\n"
    return (
        existing.rstrip()
        + separator
        + report.strip()
        + "\n"
    )


def main(task_override=None):
    task = task_override or TASK_PATH.read_text(encoding="utf-8")
    graph_result = graph.invoke({"task": task})
    if graph_result.get("task_type") == "build_docs":
        existing = RESULT_PATH.read_text(encoding="utf-8") if RESULT_PATH.exists() else ""
        result_document = append_build_docs_result(existing, graph_result["result"])
    else:
        result_document = build_result_document(task, graph_result)
    RESULT_PATH.write_text(result_document, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", help="Task text override; task.md remains unchanged")
    args = parser.parse_args()
    main(args.task)

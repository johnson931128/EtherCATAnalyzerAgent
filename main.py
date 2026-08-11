import argparse
from pathlib import Path

from graph import graph


PROJECT_ROOT = Path(__file__).resolve().parent
TASK_PATH = PROJECT_ROOT / "task.md"
RESULT_PATH = PROJECT_ROOT / "result.md"

HELP_TEXT = """Commands:
  /read task.md  Read the project task.md and run it through the Agent
  /help          Show this help
  /exit          Exit the Agent

Enter any other text to run it directly through the Agent."""


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


def run_task(task):
    """Run one task through the existing graph and persist its result."""
    graph_result = graph.invoke({"task": task})
    if graph_result.get("task_type") == "build_docs":
        existing = RESULT_PATH.read_text(encoding="utf-8") if RESULT_PATH.exists() else ""
        result_document = append_build_docs_result(existing, graph_result["result"])
    else:
        result_document = build_result_document(task, graph_result)
    RESULT_PATH.write_text(result_document, encoding="utf-8")
    return graph_result


def interactive_cli():
    """Run the persistent command-line interface."""
    print("EtherCAT Analyzer Agent")
    print("Type /help for commands.\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        command = user_input.casefold()
        if command == "/exit":
            break
        if command == "/help":
            print(HELP_TEXT)
            continue
        if command.startswith("/read"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/read":
                print("Usage: /read task.md")
                continue
            if parts[1].strip().casefold() != "task.md":
                print("Only the project task.md is supported: /read task.md")
                continue
            task = TASK_PATH.read_text(encoding="utf-8")
        elif user_input.startswith("/"):
            print("Unknown command. Type /help for commands.")
            continue
        else:
            task = user_input

        try:
            run_task(task)
            print(f"Completed. Result written to {RESULT_PATH}")
        except Exception as exc:
            print(f"Task failed: {exc}")


def main(task_override=None):
    if task_override is not None:
        run_task(task_override)
        return
    interactive_cli()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", help="Task text override; task.md remains unchanged")
    args = parser.parse_args()
    main(args.task)

import argparse
import json
from pathlib import Path

from agent.graph import graph
from core.config import RAW_TSHARK_PATH
from retrieval.pdf_spec import search_pdf
from retrieval.raw_capture import find_first_coe_sdo_packet
from retrieval.source_retrieval import search_source, select_source_with_llm
from retrieval.spec_retrieval import plan_spec_queries, select_spec_with_llm
from workflows.spec_ingestion import ingest_spec


PROJECT_ROOT = Path(__file__).resolve().parent
TASK_PATH = PROJECT_ROOT / "task.md"
RESULT_PATH = PROJECT_ROOT / "result.md"

HELP_TEXT = """Commands:
  /read task.md  Read the project task.md and run it through the Agent
  /source QUERY  Search C# source files without invoking the Agent graph
  /source-ai TASK  Ask Qwen to select relevant C# source files
  /spec QUERY     Search the ET1100 PDF without invoking the Agent graph
  /spec-ai TASK   Ask Qwen to select relevant ET1100 PDF pages
  /spec-plan TASK Ask Qwen to plan ET1100 specification queries
  /ingest-spec NAME  Convert the single local specification PDF to raw Markdown
  /raw-coe-sdo    Find the first raw CoE SDO packet
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


def run_task(task, use_tool_agent=False):
    """Run one task through the existing graph and persist its result."""
    graph_input = {"task": task}
    if use_tool_agent:
        graph_input["route_mode"] = "tool_agent"
    graph_result = graph.invoke(graph_input)
    if graph_result.get("task_type") == "build_docs":
        existing = RESULT_PATH.read_text(encoding="utf-8") if RESULT_PATH.exists() else ""
        result_document = append_build_docs_result(existing, graph_result["result"])
    else:
        result_document = build_result_document(task, graph_result)
    RESULT_PATH.write_text(result_document, encoding="utf-8")
    return graph_result


def print_source_results(query):
    """Print compact deterministic source matches for one CLI query."""
    results = search_source(query)
    if not results:
        print(f"No C# source matches found for: {query}")
        return

    print(f"C# source matches for: {query}")
    for index, result in enumerate(results, start=1):
        symbols = ", ".join(result["matched_symbols"]) or "(text match only)"
        print(f"{index}. {result['path']}")
        print(f"   Symbols: {symbols}")
        print(f"   Match: {result['reason']}")


def print_source_ai_results(task):
    """Print only Qwen's selected source paths."""
    result = select_source_with_llm(task)
    for path in result["selected_paths"]:
        print(path)


def print_spec_results(query):
    """Print up to eight ET1100 PDF matches for one CLI query."""
    results = search_pdf([query])
    print(f"ET1100 matches for: {query}")
    if not results:
        print("No PDF matches found.")
        return

    for index, result in enumerate(results[:8], start=1):
        matched_keyword = result["matches"][0]
        print(f"\n{index}. PDF page {result['page_num']}")
        print(f"   Match: {matched_keyword}")
        print(f"   Excerpt: {result['excerpt']}")


def print_spec_ai_results(task):
    """Print selected ET1100 PDF pages with short excerpts only."""
    result = select_spec_with_llm(task)
    selected_pages = result["selected_pages"]
    page_texts = result["page_texts"]
    if not selected_pages:
        print("No relevant ET1100 PDF pages found.")
        return

    print(f"ET1100 selected pages for: {task}")
    for page_num in selected_pages:
        excerpt = " ".join(page_texts[page_num].split())
        if len(excerpt) > 240:
            excerpt = excerpt[:240].rstrip() + "..."
        print(f"\nPDF page {page_num}")
        print(f"   Excerpt: {excerpt}")


def print_spec_plan_results(task):
    """Print Qwen's ET1100 specification queries."""
    queries = plan_spec_queries(task)
    print("Spec queries:")
    for index, query in enumerate(queries, start=1):
        print(f"\n{index}. {query}")


def print_raw_coe_sdo_result():
    """Print only the first raw CoE SDO packet match."""
    result = find_first_coe_sdo_packet(RAW_TSHARK_PATH)
    if result is None:
        print("No CoE SDO packet found.")
        return

    datagram = result["datagram"]
    print(f"Frame Number: {result['frame_number']}")
    print("\necat_mailbox:")
    print(json.dumps(result["ecat_mailbox"], ensure_ascii=False, indent=2))
    print("\necat_mailbox.coe_tree:")
    print(json.dumps(result["coe_tree"], ensure_ascii=False, indent=2))
    print("\nEtherCAT Datagram:")
    print(f"Command: {datagram['Command']}")
    print(f"ADP: {datagram['ADP']}")
    print(f"ADO: {datagram['ADO']}")
    print(f"Data Length: {datagram['Data Length']}")
    print(f"WKC: {datagram['WKC']}")


def print_spec_ingest_result(spec_name):
    """Run deterministic PDF-to-Markdown ingestion for one specification."""
    manifest = ingest_spec(spec_name)
    print(f"Ingested specification: {manifest['spec']}")
    print(f"Source PDF: {manifest['source_relative_path']}")
    print(
        "Generated pages: "
        f"{manifest['successfully_generated_page_count']} / "
        f"{manifest['total_pdf_pages']}"
    )
    print(f"Manifest: {manifest['generated_manifest_relative_path']}")
    if manifest["extraction_failures"]:
        print(f"Extraction failures: {len(manifest['extraction_failures'])}")


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
        if command == "/raw-coe-sdo":
            try:
                print_raw_coe_sdo_result()
            except Exception as exc:
                print(f"Raw CoE SDO search failed: {exc}")
            continue
        if command.startswith("/ingest-spec"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/ingest-spec":
                print("Usage: /ingest-spec <spec-name>")
                continue
            try:
                print_spec_ingest_result(parts[1].strip())
            except Exception as exc:
                print(f"Spec ingestion failed: {exc}")
            continue
        if command.startswith("/spec-plan"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/spec-plan":
                print("Usage: /spec-plan <task>")
                continue
            try:
                print_spec_plan_results(parts[1].strip())
            except Exception as exc:
                print(f"Spec planning failed: {exc}")
            continue
        if command.startswith("/spec-ai"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/spec-ai":
                print("Usage: /spec-ai <task>")
                continue
            try:
                print_spec_ai_results(parts[1].strip())
            except Exception as exc:
                print(f"Spec selection failed: {exc}")
            continue
        if command.startswith("/spec"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/spec":
                print("Usage: /spec <query>")
                continue
            print_spec_results(parts[1].strip())
            continue
        if command.startswith("/source-ai"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/source-ai":
                print("Usage: /source-ai <task>")
                continue
            try:
                print_source_ai_results(parts[1].strip())
            except Exception as exc:
                print(f"Source selection failed: {exc}")
            continue
        if command.startswith("/source"):
            parts = user_input.split(maxsplit=1)
            if len(parts) != 2 or parts[0].casefold() != "/source":
                print("Usage: /source <query>")
                continue
            print_source_results(parts[1].strip())
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
            graph_result = run_task(task, use_tool_agent=not user_input.startswith("/"))
            for tool_name in graph_result.get("tools_used", []):
                print(f"Tool: {tool_name}")
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

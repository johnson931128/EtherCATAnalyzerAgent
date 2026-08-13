from langgraph.graph import END, START, StateGraph

from agent.analysis import analyze
from agent.engineering_tool_agent import run_engineering_tool_agent
from core.context import load_context
from core.state import AgentState
from retrieval.capture import query_capture, select_capture_mode
from retrieval.docs import load_docs_index, load_selected_docs, select_docs
from retrieval.source import select_source
from workflows.build_docs import build_docs
from workflows.result_check import is_result_check_task, result_check


def is_build_docs_task(task: str) -> bool:
    lowered = task.casefold()
    if "build_docs" in lowered:
        return True

    if "markdown" in lowered and (
        "pdf" in lowered or "documentation" in lowered
    ):
        return True

    has_eeprom = "eeprom" in lowered
    has_document_intent = any(
        marker in lowered
        for marker in ("markdown", "documentation", "docs/read", "文件", "規格")
    )
    has_generation_intent = any(
        marker in lowered
        for marker in (
            "create",
            "draft",
            "generate",
            "建立",
            "整理",
        )
    )

    return (
        has_eeprom
        and has_document_intent
        and has_generation_intent
    ) or (
        "markdown" in lowered
        and "eeprom" in lowered
        and "et1100" in lowered
    )


def route_task(state: AgentState) -> str:
    if is_build_docs_task(state["task"]):
        return "build_docs"
    if is_result_check_task(state["task"]):
        return "result_check"
    if state.get("route_mode") == "tool_agent":
        return "tool_agent"
    return "analysis"


builder = StateGraph(AgentState)

builder.add_node("route_task", lambda state: state)
builder.add_node("build_docs", build_docs)
builder.add_node("load_context", load_context)
builder.add_node("load_docs_index", load_docs_index)
builder.add_node("select_docs", select_docs)
builder.add_node("load_selected_docs", load_selected_docs)
builder.add_node("tool_agent", run_engineering_tool_agent)
builder.add_node("select_source", select_source)
builder.add_node("select_capture_mode", select_capture_mode)
builder.add_node("query_capture", query_capture)
builder.add_node("analyze", analyze)
builder.add_node("result_check", result_check)

builder.add_edge(START, "route_task")
builder.add_conditional_edges(
    "route_task",
    route_task,
    {
        "build_docs": "build_docs",
        "result_check": "result_check",
        "tool_agent": "tool_agent",
        "analysis": "load_context",
    },
)
builder.add_edge("build_docs", END)
builder.add_edge("tool_agent", END)
builder.add_edge("load_context", "load_docs_index")
builder.add_edge("load_docs_index", "select_docs")
builder.add_edge("select_docs", "load_selected_docs")
builder.add_edge("load_selected_docs", "select_source")
builder.add_edge("select_source", "select_capture_mode")
builder.add_edge("select_capture_mode", "query_capture")
builder.add_edge("query_capture", "analyze")
builder.add_edge("analyze", END)
builder.add_edge("result_check", END)

graph = builder.compile()

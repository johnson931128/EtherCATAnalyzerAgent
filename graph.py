from langgraph.graph import END, START, StateGraph

from analysis import analyze
from build_docs import build_docs
from capture import query_capture, select_capture_mode
from context import load_context
from docs import load_docs_index, load_selected_docs, select_docs
from result_check import is_result_check_task, result_check
from source import inspect_source, select_source
from state import AgentState


def is_build_docs_task(task: str) -> bool:
    lowered = task.casefold()
    return "build_docs" in lowered or (
        "markdown" in lowered
        and ("pdf" in lowered or "documentation" in lowered)
    )


def route_task(state: AgentState) -> str:
    if is_build_docs_task(state["task"]):
        return "build_docs"
    if is_result_check_task(state["task"]):
        return "result_check"
    return "analysis"


builder = StateGraph(AgentState)

builder.add_node("route_task", lambda state: state)
builder.add_node("build_docs", build_docs)
builder.add_node("load_context", load_context)
builder.add_node("load_docs_index", load_docs_index)
builder.add_node("select_docs", select_docs)
builder.add_node("load_selected_docs", load_selected_docs)
builder.add_node("select_source", select_source)
builder.add_node("inspect_source", inspect_source)
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
        "analysis": "load_context",
    },
)
builder.add_edge("build_docs", END)
builder.add_edge("load_context", "load_docs_index")
builder.add_edge("load_docs_index", "select_docs")
builder.add_edge("select_docs", "load_selected_docs")
builder.add_edge("load_selected_docs", "select_source")
builder.add_edge("select_source", "inspect_source")
builder.add_edge("inspect_source", "select_capture_mode")
builder.add_edge("select_capture_mode", "query_capture")
builder.add_edge("query_capture", "analyze")
builder.add_edge("analyze", END)
builder.add_edge("result_check", END)

graph = builder.compile()

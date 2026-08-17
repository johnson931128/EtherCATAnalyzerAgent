from langgraph.graph import END, START, StateGraph

from core.state import AgentState


def _build_docs(state):
    from workflows.build_docs import build_docs

    return build_docs(state)


def _load_context(state):
    from core.context import load_context

    return load_context(state)


def _load_docs_index(state):
    from retrieval.docs import load_docs_index

    return load_docs_index(state)


def _select_docs(state):
    from retrieval.docs import select_docs

    return select_docs(state)


def _load_selected_docs(state):
    from retrieval.docs import load_selected_docs

    return load_selected_docs(state)


def _tool_agent(state):
    from agent.engineering_tool_agent import run_engineering_tool_agent

    return run_engineering_tool_agent(state)


def _select_source(state):
    from retrieval.source import select_source

    return select_source(state)


def _select_capture_mode(state):
    from retrieval.capture import select_capture_mode

    return select_capture_mode(state)


def _query_capture(state):
    from retrieval.capture import query_capture

    return query_capture(state)


def _analyze(state):
    from agent.analysis import analyze

    return analyze(state)


def _result_check(state):
    from workflows.result_check import result_check

    return result_check(state)


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
    from retrieval.sdo_verification import is_sdo_transaction_input
    from workflows.result_check import is_result_check_task

    if is_sdo_transaction_input(state["task"]):
        return "tool_agent"
    if is_build_docs_task(state["task"]):
        return "build_docs"
    if is_result_check_task(state["task"]):
        return "result_check"
    if state.get("route_mode") == "tool_agent":
        return "tool_agent"
    return "analysis"


builder = StateGraph(AgentState)

builder.add_node("route_task", lambda state: state)
builder.add_node("build_docs", _build_docs)
builder.add_node("load_context", _load_context)
builder.add_node("load_docs_index", _load_docs_index)
builder.add_node("select_docs", _select_docs)
builder.add_node("load_selected_docs", _load_selected_docs)
builder.add_node("tool_agent", _tool_agent)
builder.add_node("select_source", _select_source)
builder.add_node("select_capture_mode", _select_capture_mode)
builder.add_node("query_capture", _query_capture)
builder.add_node("analyze", _analyze)
builder.add_node("result_check", _result_check)

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

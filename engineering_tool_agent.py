"""Bounded read-only tool workflow for engineering analysis."""

import json
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from config import RAW_TSHARK_PATH
from llm import llm
from pdf_spec import search_pdf
from raw_capture import find_first_coe_sdo_packet
from source_retrieval import search_source
from state import AgentState


MAX_TOOL_CALLS = 3
MAX_QUERY_LENGTH = 200

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_source",
            "description": (
                "Search EtherCATAnalyzer C# source deterministically by filename, "
                "symbol, or source text. Returns compact match metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A specific C# filename, symbol, or technical term.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_spec",
            "description": (
                "Search the ET1100 PDF deterministically for one exact technical term "
                "or short phrase. Returns matching page numbers and short excerpts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "An ET1100 register address, field name, or short phrase."
                        ),
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_first_coe_sdo",
            "description": (
                "Return compact evidence from the first raw TShark EtherCAT datagram "
                "containing a CoE SDO field. Takes no arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

_SYSTEM_PROMPT = """You are an engineering analysis agent for EtherCATAnalyzer.
Use the available read-only tools only when their evidence is needed. Tool results are
compact retrieval evidence, not permission to invent missing details. Prefer specific
queries such as a C# symbol, ET1100 register address, or exact protocol phrase. Base the
final answer on collected evidence, distinguish source behavior from specification facts
and capture observations, and state when evidence is insufficient. Do not reveal hidden
reasoning. Return a concise engineering answer, not tool-call JSON."""


def _validated_query(arguments: Any) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        raise ValueError("Expected exactly one string argument: query")
    query = arguments["query"]
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must not exceed {MAX_QUERY_LENGTH} characters")
    return query


def _search_source_tool(arguments: Any) -> Dict[str, object]:
    query = _validated_query(arguments)
    matches = search_source(query, max_results=3)
    compact_matches = []
    for match in matches:
        text = Path(str(match["path"])).read_text(
            encoding="utf-8-sig", errors="replace"
        )
        excerpt_term = next(iter(match["matched_symbols"]), query)
        position = text.casefold().find(str(excerpt_term).casefold())
        if position < 0:
            excerpt = ""
        else:
            start = max(0, position - 350)
            end = min(len(text), position + len(str(excerpt_term)) + 350)
            excerpt = text[start:end]
        compact_matches.append(
            {
                "path": match["path"],
                "matched_symbols": match["matched_symbols"],
                "reason": match["reason"],
                "excerpt": excerpt,
            }
        )
    return {
        "query": query,
        "matches": compact_matches,
    }


def _search_spec_tool(arguments: Any) -> Dict[str, object]:
    query = _validated_query(arguments)
    matches = search_pdf([query])[:5]
    return {
        "query": query,
        "matches": [
            {
                "page_num": match["page_num"],
                "matched_terms": match["matches"],
                "excerpt": match["excerpt"],
            }
            for match in matches
        ],
    }


def _find_first_coe_sdo_tool(arguments: Any) -> Dict[str, object]:
    if not isinstance(arguments, dict) or arguments:
        raise ValueError("find_first_coe_sdo takes no arguments")
    result = find_first_coe_sdo_packet(RAW_TSHARK_PATH)
    if result is None:
        return {"match": None}

    mailbox = result.get("ecat_mailbox")
    mailbox_header = mailbox.get("Header") if isinstance(mailbox, dict) else None
    return {
        "match": {
            "frame_number": result.get("frame_number"),
            "datagram": result.get("datagram"),
            "mailbox_header": mailbox_header,
            "coe_tree": result.get("coe_tree"),
        }
    }


_TOOL_HANDLERS = {
    "search_source": _search_source_tool,
    "search_spec": _search_spec_tool,
    "find_first_coe_sdo": _find_first_coe_sdo_tool,
}


def _tool_result(name: str, arguments: Any) -> str:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unsupported tool: {name}"})
    try:
        result = handler(arguments)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def run_engineering_tool_agent(state: AgentState):
    """Run Qwen with at most MAX_TOOL_CALLS deterministic tool executions."""
    tool_llm = llm.bind_tools(_TOOL_SCHEMAS)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=state["task"]),
    ]
    tools_used: List[str] = []
    tool_call_count = 0

    while tool_call_count < MAX_TOOL_CALLS:
        response = tool_llm.invoke(messages)
        messages.append(response)
        tool_calls = list(getattr(response, "tool_calls", None) or [])
        if not tool_calls:
            return {
                "result": _message_text(response.content),
                "capture_mode": "tool_agent",
                "task_type": "analysis",
                "tools_used": tools_used,
            }

        for tool_call in tool_calls:
            name = str(tool_call.get("name", ""))
            call_id = str(tool_call.get("id", ""))
            if tool_call_count >= MAX_TOOL_CALLS:
                content = json.dumps({"error": "Tool-call limit reached"})
            else:
                tool_call_count += 1
                tools_used.append(name)
                content = _tool_result(name, tool_call.get("args", {}))
            messages.append(ToolMessage(content=content, tool_call_id=call_id))

        if tool_call_count >= MAX_TOOL_CALLS:
            break

    final_response = llm.invoke(
        messages
        + [
            SystemMessage(
                content=(
                    "The tool-call limit has been reached. Do not request or describe "
                    "additional tool calls. Produce the final engineering answer now "
                    "using only the evidence already collected."
                )
            )
        ]
    )
    return {
        "result": _message_text(final_response.content),
        "capture_mode": "tool_agent",
        "task_type": "analysis",
        "tools_used": tools_used,
    }

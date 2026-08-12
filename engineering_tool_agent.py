"""Bounded read-only tool workflow for engineering analysis."""

import json
from pathlib import Path
from typing import Any, Dict, List

from config import RAW_TSHARK_PATH
from llm import llm
from pdf_spec import search_pdf
from raw_capture import find_first_coe_sdo_packet
from source_retrieval import search_source
from state import AgentState


MAX_TOOL_CALLS = 3
MAX_QUERY_LENGTH = 200

_SYSTEM_PROMPT = """You are an engineering analysis agent for EtherCATAnalyzer.
Use only the following read-only tools when their evidence is needed:
- search_source(query): deterministic C# source search
- search_spec(query): deterministic ET1100 PDF search
- find_first_coe_sdo(): first raw TShark CoE SDO match, with no arguments

On every turn return exactly one JSON object and no markdown fences. To request a tool:
{"action":"tool","tool":"<allowed tool name>","arguments":{...}}
To finish:
{"action":"final","answer":"<concise engineering answer>"}

Tool results are compact retrieval evidence, not permission to invent missing details.
Prefer specific queries. Distinguish source behavior from specification facts and capture
observations, and state when evidence is insufficient. Do not reveal hidden reasoning."""


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


def _parse_action(content: Any) -> Dict[str, Any]:
    if not isinstance(content, str):
        raise ValueError("Qwen response must be a JSON string")

    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Qwen response was not valid JSON") from exc

    if not isinstance(action, dict) or action.get("action") not in {"tool", "final"}:
        raise ValueError("Qwen JSON action must be tool or final")

    if action["action"] == "final":
        if set(action) != {"action", "answer"} or not isinstance(action["answer"], str):
            raise ValueError("Final action requires only a string answer")
        return action

    if set(action) != {"action", "tool", "arguments"}:
        raise ValueError("Tool action requires tool and arguments")
    if action["tool"] not in _TOOL_HANDLERS:
        raise ValueError(f"Unsupported tool: {action['tool']}")
    if not isinstance(action["arguments"], dict):
        raise ValueError("Tool arguments must be a JSON object")
    return action


def _agent_prompt(task: str, evidence: List[str], force_final: bool = False) -> str:
    prompt = _SYSTEM_PROMPT + f"\n\nUser task:\n{task.strip()}"
    if evidence:
        prompt += "\n\nEvidence collected from deterministic tools:\n" + "\n\n".join(evidence)
    if force_final:
        prompt += (
            "\n\nThe maximum tool-call limit has been reached. Return only a final JSON "
            "object with action=final. Do not request another tool."
        )
    else:
        prompt += "\n\nChoose one next action and return only the required JSON object."
    return prompt


def run_engineering_tool_agent(state: AgentState):
    """Run Qwen with at most MAX_TOOL_CALLS deterministic tool executions."""
    tools_used: List[str] = []
    evidence: List[str] = []
    tool_call_count = 0
    prompt = _agent_prompt(state["task"], evidence)

    while tool_call_count < MAX_TOOL_CALLS:
        response = llm.invoke(prompt)
        try:
            action = _parse_action(response.content)
        except ValueError as exc:
            evidence.append(json.dumps({"protocol_error": str(exc)}))
            prompt = _agent_prompt(state["task"], evidence, force_final=True)
            break

        if action["action"] == "final":
            return {
                "result": action["answer"],
                "capture_mode": "tool_agent",
                "task_type": "analysis",
                "tools_used": tools_used,
            }

        name = action["tool"]
        tool_call_count += 1
        tools_used.append(name)
        result = _tool_result(name, action["arguments"])
        evidence.append(f"Tool: {name}\nResult: {result}")
        prompt = _agent_prompt(
            state["task"], evidence, force_final=tool_call_count >= MAX_TOOL_CALLS
        )

        if tool_call_count >= MAX_TOOL_CALLS:
            break

    final_response = llm.invoke(prompt)
    try:
        final_action = _parse_action(final_response.content)
        if final_action["action"] != "final":
            final_answer = _message_text(final_response.content)
        else:
            final_answer = final_action["answer"]
    except ValueError:
        final_answer = _message_text(final_response.content)
    return {
        "result": final_answer,
        "capture_mode": "tool_agent",
        "task_type": "analysis",
        "tools_used": tools_used,
    }

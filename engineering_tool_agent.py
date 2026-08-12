"""Bounded read-only tool workflow for engineering analysis."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from config import RAW_TSHARK_PATH
from llm import llm
from pdf_spec import search_pdf
from raw_capture import find_first_coe_sdo_packet
from source_retrieval import search_source
from state import AgentState


MAX_TOOL_CALLS = 3
MAX_AGENT_TURNS = 6
MAX_QUERY_LENGTH = 200
_SPEC_STOP_WORDS = {
    "about",
    "and",
    "for",
    "from",
    "how",
    "into",
    "is",
    "of",
    "the",
    "to",
    "with",
}
_SPEC_FRONT_MATTER = (
    "document history",
    "revision history",
    "table of contents",
    "contents",
    "list of tables",
    "list of figures",
    "glossary",
)
_SPEC_TECHNICAL_TERMS = (
    "address",
    "bit",
    "command",
    "datagram",
    "definition",
    "ethercat",
    "increment",
    "procedure",
    "register",
    "request",
    "response",
    "rule",
    "table",
    "working counter",
)

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
observations. In the final answer, distinguish directly retrieved specification evidence
from inference, do not invent protocol mechanisms unsupported by retrieved evidence, and
do not generalize a command-specific table rule into a simpler universal rule. State
explicitly when the available evidence is insufficient. Do not reveal hidden reasoning."""


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


def _spec_search_terms(query: str) -> List[str]:
    tokens = re.findall(r"0x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9-]*", query)
    words = [
        token
        for token in tokens
        if token.casefold().startswith("0x")
        or (len(token) >= 3 and token.casefold() not in _SPEC_STOP_WORDS)
    ]
    phrases = [
        f"{first} {second}"
        for first, second in zip(words, words[1:])
    ]
    terms = [query, *phrases, *words]
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def _score_spec_result(query: str, result: Dict[str, object]) -> int:
    text = str(result.get("text", ""))
    folded_text = text.casefold()
    folded_query = query.casefold()
    matched_terms = {
        str(term).casefold() for term in result.get("matches", [])
    }
    score = len(matched_terms) * 25
    if folded_query in folded_text:
        score += 100

    for term in _SPEC_TECHNICAL_TERMS:
        if term in folded_text:
            score += 8

    context = folded_text[:1600]
    if any(marker in context for marker in ("section ", "table ", "register")):
        score += 20

    for marker in _SPEC_FRONT_MATTER:
        if marker in folded_text:
            score -= 90
    if "introduction" in context or "general overview" in context:
        score -= 35
    return score


def _search_spec_tool(arguments: Any) -> Dict[str, object]:
    query = _validated_query(arguments)
    candidates = search_pdf(_spec_search_terms(query))
    matches = sorted(
        candidates,
        key=lambda result: (
            -_score_spec_result(query, result),
            int(result["page_num"]),
        ),
    )[:5]
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


def _tool_call_key(name: str, arguments: Any):
    if name in {"search_source", "search_spec"}:
        query = _validated_query(arguments)
        return name, " ".join(query.split()).casefold()
    if name == "find_first_coe_sdo":
        return name, json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return name, json.dumps(arguments, sort_keys=True, default=str)


def _tool_display(name: str, arguments: Any) -> str:
    if name == "find_first_coe_sdo":
        return "find_first_coe_sdo()"
    try:
        query = _validated_query(arguments)
    except (TypeError, ValueError):
        return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
    return f'{name}("{" ".join(query.split())}")'


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
    cached_results: Dict[object, str] = {}
    tool_call_count = 0
    agent_turn_count = 0
    prompt = _agent_prompt(state["task"], evidence)

    while tool_call_count < MAX_TOOL_CALLS and agent_turn_count < MAX_AGENT_TURNS:
        agent_turn_count += 1
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
        arguments = action["arguments"]
        display = _tool_display(name, arguments)
        try:
            call_key = _tool_call_key(name, arguments)
        except (TypeError, ValueError):
            call_key = None

        if call_key is not None and call_key in cached_results:
            result = cached_results[call_key]
            tools_used.append(f"{display} [reused]")
        else:
            tool_call_count += 1
            tools_used.append(display)
            result = _tool_result(name, arguments)
            if call_key is not None:
                cached_results[call_key] = result

        evidence.append(f"Tool: {display}\nResult: {result}")
        prompt = _agent_prompt(
            state["task"], evidence, force_final=tool_call_count >= MAX_TOOL_CALLS
        )

        if tool_call_count >= MAX_TOOL_CALLS:
            break

    final_response = llm.invoke(_agent_prompt(state["task"], evidence, force_final=True))
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

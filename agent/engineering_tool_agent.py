"""Bounded read-only tool workflow for engineering analysis."""

import json
from pathlib import Path
from typing import Any, Dict, List

from core.config import RAW_TSHARK_PATH
from core.llm import llm
from core.state import AgentState
from retrieval.markdown_spec import search_spec_markdown
from retrieval.pdf_spec import (
    MAX_RAW_PAGE_COUNT,
    MAX_RAW_SEARCH_LIMIT,
    RAW_SPEC_NAME,
    get_spec_raw_pages,
    search_spec_raw,
)
from retrieval.raw_capture import find_first_coe_sdo_packet
from retrieval.sdo_verification import build_sdo_verification_context
from retrieval.source_retrieval import search_source
from retrieval.tshark_capture import (
    export_frame_json,
    query_frames,
    query_sdo_object,
    query_capture,
    validate_export_frame_arguments,
    validate_query_frames_arguments,
    validate_query_sdo_object_arguments,
    validate_query_capture_arguments,
)


MAX_TOOL_CALLS = 3
MAX_AGENT_TURNS = 6
MAX_QUERY_LENGTH = 200
_SYSTEM_PROMPT = """You are an engineering analysis agent for EtherCATAnalyzer.
ET1100.md is the primary readable specification source. Use the raw PDF evidence tools
only as a fallback or verification source when Docling output contains <!-- image -->,
<!-- formula-not-decoded -->, a suspicious Markdown table, a questionable register
address or bit value, or when the user explicitly requests original PDF page evidence.
Do not request raw PDF evidence by default when the readable source is sufficient.

Use only the following read-only tools when their evidence is needed:
- search_source(query): deterministic C# source search
- search_spec(query): primary deterministic ET1100.md readable evidence search
- query_frames(capture, frame_numbers): one bounded JSON query for exact frames
- query_sdo_object(capture, index, subindex, frame_start, frame_end): bounded SDO JSON query
- query_capture(capture, display_filter, fields, limit): bounded frame-level TShark field query
- export_frame_json(capture, frame_number): exact one-frame canonical TShark JSON evidence
- search_spec_raw(spec, query, limit): bounded original ET1100 PDF page search
- get_spec_raw_pages(spec, pages): bounded complete original PDF page text
- find_first_coe_sdo(): first raw TShark CoE SDO match, with no arguments

Capture query policy:
- Exact frame(s) known -> query_frames; batch all related frames in one call.
- Exact SDO Index/SubIndex known -> query_sdo_object.
- Broad or unknown capture search -> query_capture with fields.
- Need original full packet tree -> export_frame_json.
- Never treat query_capture flat fields as EtherCAT Datagram association proof.
- Prefer the fewest TShark invocations and avoid repeated PCAP scans.
- Compact JSON evidence includes frame-level source/destination MAC and a conservative
  ethercat_path_role; distinguish that path role from CoE SDO request/response fields.
- Do not infer path direction from WKC, command, frame adjacency, or CoE request/response.
- Never generate or execute a shell, PowerShell, Python, or arbitrary TShark command.

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


def _search_spec_tool(arguments: Any) -> Dict[str, object]:
    query = _validated_query(arguments)
    return {
        "query": query,
        "matches": search_spec_markdown(query),
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


def _validated_raw_search_arguments(arguments: Any):
    if not isinstance(arguments, dict) or set(arguments) != {"spec", "query", "limit"}:
        raise ValueError("search_spec_raw expects exactly: spec, query, limit")
    spec = arguments["spec"]
    if not isinstance(spec, str) or spec.strip() != RAW_SPEC_NAME:
        raise ValueError(f"spec must be exactly '{RAW_SPEC_NAME}'")
    query = _validated_query({"query": arguments["query"]})
    limit = arguments["limit"]
    if type(limit) is not int or not 1 <= limit <= MAX_RAW_SEARCH_LIMIT:
        raise ValueError(
            f"limit must be an integer between 1 and {MAX_RAW_SEARCH_LIMIT}"
        )
    return spec.strip(), query, limit


def _validated_raw_pages_arguments(arguments: Any):
    if not isinstance(arguments, dict) or set(arguments) != {"spec", "pages"}:
        raise ValueError("get_spec_raw_pages expects exactly: spec, pages")
    spec = arguments["spec"]
    if not isinstance(spec, str) or spec.strip() != RAW_SPEC_NAME:
        raise ValueError(f"spec must be exactly '{RAW_SPEC_NAME}'")
    pages = arguments["pages"]
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must be a non-empty list")
    unique_pages = []
    for page in pages:
        if type(page) is not int or page <= 0:
            raise ValueError("each page must be a positive integer")
        if page not in unique_pages:
            unique_pages.append(page)
    if len(unique_pages) > MAX_RAW_PAGE_COUNT:
        raise ValueError(
            f"pages must contain at most {MAX_RAW_PAGE_COUNT} unique page numbers"
        )
    return spec.strip(), unique_pages


def _search_spec_raw_tool(arguments: Any) -> Dict[str, object]:
    spec, query, limit = _validated_raw_search_arguments(arguments)
    return {
        "query": query,
        "matches": search_spec_raw(spec=spec, query=query, limit=limit),
    }


def _get_spec_raw_pages_tool(arguments: Any) -> Dict[str, object]:
    spec, pages = _validated_raw_pages_arguments(arguments)
    return {
        "pages": get_spec_raw_pages(spec=spec, pages=pages),
    }


def _query_capture_tool(arguments: Any) -> Dict[str, object]:
    validated = validate_query_capture_arguments(arguments)
    return query_capture(**validated)


def _export_frame_json_tool(arguments: Any) -> Dict[str, object]:
    validated = validate_export_frame_arguments(arguments)
    return export_frame_json(**validated)


def _query_frames_tool(arguments: Any) -> Dict[str, object]:
    validated = validate_query_frames_arguments(arguments)
    return query_frames(**validated)


def _query_sdo_object_tool(arguments: Any) -> Dict[str, object]:
    validated = validate_query_sdo_object_arguments(arguments)
    return query_sdo_object(**validated)


_TOOL_HANDLERS = {
    "search_source": _search_source_tool,
    "search_spec": _search_spec_tool,
    "search_spec_raw": _search_spec_raw_tool,
    "get_spec_raw_pages": _get_spec_raw_pages_tool,
    "query_capture": _query_capture_tool,
    "export_frame_json": _export_frame_json_tool,
    "query_frames": _query_frames_tool,
    "query_sdo_object": _query_sdo_object_tool,
    "find_first_coe_sdo": _find_first_coe_sdo_tool,
}


def _tool_result(name: str, arguments: Any) -> str:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unsupported tool: {name}"})
    try:
        result = handler(arguments)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def _tool_call_key(name: str, arguments: Any):
    if name in {"search_source", "search_spec"}:
        query = _validated_query(arguments)
        return name, " ".join(query.split()).casefold()
    if name == "search_spec_raw":
        spec, query, limit = _validated_raw_search_arguments(arguments)
        return name, spec, " ".join(query.split()).casefold(), limit
    if name == "get_spec_raw_pages":
        spec, pages = _validated_raw_pages_arguments(arguments)
        return name, spec, tuple(pages)
    if name == "query_capture":
        validated = validate_query_capture_arguments(arguments)
        return (
            name,
            validated["capture"],
            validated["display_filter"],
            tuple(validated["fields"]),
            validated["limit"],
        )
    if name == "export_frame_json":
        validated = validate_export_frame_arguments(arguments)
        return name, validated["capture"], validated["frame_number"]
    if name == "query_frames":
        validated = validate_query_frames_arguments(arguments)
        return name, validated["capture"], tuple(sorted(validated["frame_numbers"]))
    if name == "query_sdo_object":
        validated = validate_query_sdo_object_arguments(arguments)
        return (
            name,
            validated["capture"],
            validated["index"],
            validated["subindex"],
            validated["frame_start"],
            validated["frame_end"],
        )
    if name == "find_first_coe_sdo":
        return name, json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return name, json.dumps(arguments, sort_keys=True, default=str)


def _tool_display(name: str, arguments: Any) -> str:
    if name == "find_first_coe_sdo":
        return "find_first_coe_sdo()"
    if name == "search_spec_raw":
        try:
            spec, query, limit = _validated_raw_search_arguments(arguments)
        except (TypeError, ValueError):
            return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        return f'{name}(spec="{spec}", query="{" ".join(query.split())}", limit={limit})'
    if name == "get_spec_raw_pages":
        try:
            spec, pages = _validated_raw_pages_arguments(arguments)
        except (TypeError, ValueError):
            return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        return f"{name}(spec=\"{spec}\", pages={pages})"
    if name == "query_capture":
        try:
            validated = validate_query_capture_arguments(arguments)
        except (TypeError, ValueError):
            return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        return f"{name}({json.dumps(validated, ensure_ascii=False, sort_keys=True)})"
    if name == "export_frame_json":
        try:
            validated = validate_export_frame_arguments(arguments)
        except (TypeError, ValueError):
            return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        return f"{name}({json.dumps(validated, ensure_ascii=False, sort_keys=True)})"
    if name in {"query_frames", "query_sdo_object"}:
        try:
            if name == "query_frames":
                validated = validate_query_frames_arguments(arguments)
            else:
                validated = validate_query_sdo_object_arguments(arguments)
        except (TypeError, ValueError):
            return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        return f"{name}({json.dumps(validated, ensure_ascii=False, sort_keys=True)})"
    try:
        query = _validated_query(arguments)
    except (TypeError, ValueError):
        return f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
    return f'{name}("{" ".join(query.split())}")'


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _validate_tool_arguments(name: str, arguments: Any) -> None:
    if name in {"search_source", "search_spec"}:
        _validated_query(arguments)
        return
    if name == "search_spec_raw":
        _validated_raw_search_arguments(arguments)
        return
    if name == "get_spec_raw_pages":
        _validated_raw_pages_arguments(arguments)
        return
    if name == "query_capture":
        validate_query_capture_arguments(arguments)
        return
    if name == "export_frame_json":
        validate_export_frame_arguments(arguments)
        return
    if name == "query_frames":
        validate_query_frames_arguments(arguments)
        return
    if name == "query_sdo_object":
        validate_query_sdo_object_arguments(arguments)
        return
    if name == "find_first_coe_sdo":
        if not isinstance(arguments, dict) or arguments:
            raise ValueError("find_first_coe_sdo takes no arguments")
        return
    raise ValueError(f"Unsupported tool: {name}")


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
    _validate_tool_arguments(action["tool"], action["arguments"])
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


def _sdo_verification_prompt(context: Dict[str, object]) -> str:
    return (
        "You explain deterministic EtherCAT SDO verification results.\n"
        "Python has already parsed the DLL claims, selected all frames, paired fields "
        "only within EtherCAT datagrams, and assigned PASS, FAIL, or INCONCLUSIVE.\n"
        "The result values and all deterministic evidence are authoritative. Never "
        "change PASS, FAIL, or INCONCLUSIVE, invent evidence, re-parse claims, select "
        "frames, build filters, request another tool, or produce a summary table. "
        "Explain mismatches and WKC as independent evidence; WKC is not SDO success. "
        "Return only a concise human-readable explanation, without replacing the "
        "Python-generated Verification Summary, Engineering Evidence, or Engineering "
        "References sections.\n"
        "Return exactly one JSON object: "
        '{"action":"final","answer":"<concise explanation>"}.\n\n'
        "Deterministic verification context:\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def _run_sdo_verification_agent(task: str, context: Dict[str, object]):
    try:
        response = llm.invoke(_sdo_verification_prompt(context))
        action = _parse_action(response.content)
        if action["action"] == "final":
            answer = action["answer"]
        else:
            answer = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        answer = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return {
        "result": answer,
        "capture_mode": "sdo_verification",
        "task_type": "verification",
        "tools_used": ["deterministic_sdo_verification"],
        "verification_context": context,
    }


def run_engineering_tool_agent(state: AgentState):
    """Run Qwen with at most MAX_TOOL_CALLS deterministic tool executions."""
    verification_context = build_sdo_verification_context(state["task"])
    if verification_context is not None:
        return _run_sdo_verification_agent(state["task"], verification_context)

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

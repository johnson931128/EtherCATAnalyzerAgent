"""Deterministic SDO transaction verification primitives."""

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from core import config
from core.llm import llm
from retrieval.tshark_capture import query_frames


_TRANSACTION_START = re.compile(
    r"Configured\s+Slave\s+Address\s*:", re.IGNORECASE
)
_HEX = r"0x[0-9a-fA-F]+"
_OBJECT_SUBINDEX = r"(?:0x)?[0-9a-fA-F]+"
_CAPTURE_TOKEN = re.compile(r"[A-Za-z0-9_.-]+\.(?:pcapng|pcap)\b", re.IGNORECASE)


class SDOClaimParseError(ValueError):
    """Raised when one or more DLL SDO transaction claims are malformed."""

    def __init__(self, errors: List[Dict[str, object]]):
        self.errors = errors
        details = "; ".join(
            f"transaction {error['transaction']}: {error['message']}"
            for error in errors
        )
        super().__init__(details or "No SDO transaction claims found")


def _parse_hex(value: str, field_name: str) -> int:
    try:
        return int(value, 16)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be hexadecimal") from exc


def _extract_field(segment: str, label: str, pattern: str) -> Optional[str]:
    match = re.search(
        rf"{re.escape(label)}\s*:\s*({pattern})(?=\s*(?:,|;|$))",
        segment,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _parse_claim(segment: str, transaction_number: int) -> Dict[str, object]:
    errors: List[str] = []
    station_text = _extract_field(segment, "Configured Slave Address", _HEX)
    object_match = re.search(
        rf"Object\s*:\s*({_HEX})\s*:\s*({_OBJECT_SUBINDEX})(?=\s*(?:,|;|$))",
        segment,
        re.IGNORECASE,
    )
    data_text = _extract_field(segment, "Data", _HEX)
    request_frame_text = _extract_field(segment, "Request Frame", r"\d+")
    response_frame_text = _extract_field(segment, "Response Frame", r"\d+")
    success_text = _extract_field(segment, "Success", r"True|False")
    abort_text = _extract_field(
        segment, "Abort Code", rf"(?:{_HEX}|N/A|None|null)"
    )

    for field_name, value in (
        ("Configured Slave Address", station_text),
        ("Object", object_match),
        ("Data", data_text),
        ("Request Frame", request_frame_text),
        ("Response Frame", response_frame_text),
        ("Success", success_text),
        ("Abort Code", abort_text),
    ):
        if value is None:
            errors.append(f"missing required field: {field_name}")

    if errors:
        raise SDOClaimParseError(
            [{"transaction": transaction_number, "message": ", ".join(errors)}]
        )

    try:
        station = _parse_hex(station_text, "station")
        index = _parse_hex(object_match.group(1), "index")
        subindex = _parse_hex(object_match.group(2), "subindex")
        data = data_text.lower()
        request_frame = int(request_frame_text, 10)
        response_frame = int(response_frame_text, 10)
        claimed_success = success_text.casefold() == "true"
        claimed_abort_code = (
            None
            if abort_text.casefold() in {"n/a", "none", "null"}
            else _parse_hex(abort_text, "claimed_abort_code")
        )
    except (AttributeError, ValueError) as exc:
        raise SDOClaimParseError(
            [{"transaction": transaction_number, "message": str(exc)}]
        ) from exc

    range_errors = []
    if not 0 <= station <= 0xFFFF:
        range_errors.append("station must be between 0x0000 and 0xFFFF")
    if not 0 <= index <= 0xFFFF:
        range_errors.append("index must be between 0x0000 and 0xFFFF")
    if not 0 <= subindex <= 0xFF:
        range_errors.append("subindex must be between 0x00 and 0xFF")
    if request_frame <= 0 or response_frame <= 0:
        range_errors.append("request/response frame must be positive")
    if range_errors:
        raise SDOClaimParseError(
            [{"transaction": transaction_number, "message": ", ".join(range_errors)}]
        )

    return {
        "station": station,
        "index": index,
        "subindex": subindex,
        "data": data,
        "request_frame": request_frame,
        "response_frame": response_frame,
        "claimed_success": claimed_success,
        "claimed_abort_code": claimed_abort_code,
    }


def parse_sdo_transaction_claims(text: Any) -> List[Dict[str, object]]:
    """Parse the currently supported DLL SDO transaction output format."""
    if not isinstance(text, str) or not text.strip():
        raise SDOClaimParseError(
            [{"transaction": 1, "message": "input must be non-empty text"}]
        )

    starts = list(_TRANSACTION_START.finditer(text))
    if not starts:
        raise SDOClaimParseError(
            [{"transaction": 1, "message": "no SDO transaction claim found"}]
        )

    claims = []
    errors = []
    for number, start in enumerate(starts, start=1):
        end = starts[number].start() if number < len(starts) else len(text)
        segment = text[start.start() : end]
        try:
            claims.append(_parse_claim(segment, number))
        except SDOClaimParseError as exc:
            errors.extend(exc.errors)
    if errors:
        raise SDOClaimParseError(errors)
    return claims


def contains_sdo_transaction_data(text: Any) -> bool:
    """Return whether text contains the DLL SDO transaction marker."""
    return isinstance(text, str) and bool(_TRANSACTION_START.search(text))


def is_sdo_transaction_input(text: Any) -> bool:
    """Backward-compatible alias for structured SDO content detection."""
    return contains_sdo_transaction_data(text)


_EXPLICIT_VERIFY_LINES = frozenset({"verify", "verify sdo"})


def is_explicit_sdo_verification(text: Any) -> bool:
    """Return whether the first non-empty line explicitly requests verification."""
    if not isinstance(text, str):
        return False
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line.casefold() in _EXPLICIT_VERIFY_LINES


def remove_explicit_sdo_verification_prefix(text: str) -> str:
    """Remove the first-line verify control from a task before claim parsing."""
    if not is_explicit_sdo_verification(text):
        return text
    lines = text.splitlines()
    first_content = next(
        index for index, line in enumerate(lines) if line.strip()
    )
    return "\n".join(lines[first_content + 1:]).lstrip("\r\n")


SDO_INTENTS = frozenset({"sdo_verification", "explanation", "unclear"})
_SDO_INTENT_PROMPT = """You only classify the user's intent for text that contains structured EtherCAT SDO Analyzer output.

Choose exactly one:
- sdo_verification: the user asks to verify, validate, check correctness, confirm whether Analyzer results are correct, or compare claims against capture evidence.
- explanation: the user asks what the output means, asks for interpretation, teaching, discussion, or another engineering question without asking for independent verification.
- unclear: the text contains SDO transaction output but does not state what action the user wants.

Examples:
- "Please verify these SDO transactions" -> sdo_verification
- "What do these three outputs mean?" -> explanation
- only SDO transaction output with no request -> unclear

Return only this JSON schema and no tool call:
{"intent":"sdo_verification|explanation|unclear"}

User text:
"""


def _parse_sdo_intent(content: Any) -> str:
    if not isinstance(content, str):
        raise ValueError("SDO intent response must be a JSON string")
    parsed = json.loads(content.strip())
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"intent"}
        or parsed["intent"] not in SDO_INTENTS
    ):
        raise ValueError("SDO intent response must contain one supported intent")
    return parsed["intent"]


def classify_sdo_intent(text: str) -> str:
    """Classify SDO user intent without performing protocol analysis."""
    try:
        response = llm.invoke(_SDO_INTENT_PROMPT + text.strip())
        return _parse_sdo_intent(response.content)
    except Exception:
        return "unclear"


def extract_capture_name(text: str) -> Optional[str]:
    """Extract one logical capture filename, rejecting path-shaped tokens."""
    matches = list(_CAPTURE_TOKEN.finditer(text))
    if not matches:
        return None
    for match in matches:
        if match.start() > 0 and text[match.start() - 1] in {"/", "\\"}:
            raise ValueError("capture must be provided as a logical filename")
    names = list(dict.fromkeys(match.group(0) for match in matches))
    if len(names) != 1:
        raise ValueError("exactly one logical capture filename is required")
    return names[0]


def _as_int(value: Any) -> Optional[int]:
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            try:
                return int(value, 10)
            except ValueError:
                return None
    return None


def _hex_equal(left: Any, right: Any) -> bool:
    left_value = _as_int(left)
    right_value = _as_int(right)
    return left_value is not None and right_value is not None and left_value == right_value


def _present(value: Any) -> bool:
    return value is not None and value != ""


def plan_sdo_frame_query(claims: Sequence[Dict[str, object]]) -> List[int]:
    """Collect unique request/response frames in first-seen order."""
    if not isinstance(claims, (list, tuple)) or not claims:
        raise ValueError("claims must be a non-empty sequence")

    frame_numbers: List[int] = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("each SDO claim must be an object")
        for field_name in ("request_frame", "response_frame"):
            frame_number = claim.get(field_name)
            if type(frame_number) is not int or frame_number <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
            if frame_number not in frame_numbers:
                frame_numbers.append(frame_number)
    return frame_numbers


def _format_hex(value: Any, width: int = 0) -> str:
    number = _as_int(value)
    if number is None:
        return "null"
    return f"0x{number:0{width}x}"


def _frame_evidence(frame: Dict[str, object], datagram: Optional[Dict[str, object]]):
    if datagram is None:
        return None
    return {
        "frame_number": frame.get("frame_number"),
        "source_mac": frame.get("source_mac"),
        "dest_mac": frame.get("dest_mac"),
        "ethercat_path_role": frame.get("ethercat_path_role", "unknown"),
        "datagram": datagram,
    }


def _datagram_checks(
    datagram: Dict[str, object], claim: Dict[str, object], kind: str
):
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    request_or_response = "sdo_request" if kind == "request" else "sdo_response"
    if not _present(coe.get(request_or_response)):
        return None

    checks = {
        "station": _as_int(datagram.get("adp")) == claim["station"],
        "index": _as_int(coe.get("index")) == claim["index"],
        "subindex": _as_int(coe.get("subindex")) == claim["subindex"],
    }
    if kind == "request":
        checks["data"] = _hex_equal(coe.get("data"), claim["data"])
    return checks


def _datagram_mismatch_reasons(
    datagram: Dict[str, object], checks: Dict[str, bool], claim: Dict[str, object], kind: str
) -> List[str]:
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    reasons = []
    prefix = f"{kind}."
    if not checks["station"]:
        reasons.append(
            f"{prefix}station expected {_format_hex(claim['station'], 4)} "
            f"but observed {_format_hex(datagram.get('adp'), 4)}"
        )
    if not checks["index"]:
        reasons.append(
            f"{prefix}index expected {_format_hex(claim['index'], 4)} "
            f"but observed {_format_hex(coe.get('index'), 4)}"
        )
    if not checks["subindex"]:
        reasons.append(
            f"{prefix}subindex expected {_format_hex(claim['subindex'], 2)} "
            f"but observed {_format_hex(coe.get('subindex'), 2)}"
        )
    if kind == "request" and not checks["data"]:
        reasons.append(
            f"{prefix}data expected {claim['data']} "
            f"but observed {coe.get('data') if _present(coe.get('data')) else 'null'}"
        )
    return reasons


def _find_sdo_datagram(
    frame: Optional[Dict[str, object]], claim: Dict[str, object], kind: str
):
    if frame is None:
        return None, {"station": False, "index": False, "subindex": False, **({"data": False} if kind == "request" else {})}, [
            f"{kind} frame {claim[f'{kind}_frame']} is missing"
        ], True

    candidates = []
    for datagram in frame.get("datagrams", []):
        if not isinstance(datagram, dict):
            continue
        checks = _datagram_checks(datagram, claim, kind)
        if checks is not None:
            candidates.append((datagram, checks))
            if all(checks.values()):
                return datagram, checks, [], False

    empty_checks = {
        "station": False,
        "index": False,
        "subindex": False,
    }
    if kind == "request":
        empty_checks["data"] = False
    if not candidates:
        return (
            None,
            empty_checks,
            [f"{kind} CoE SDO {kind} datagram is missing"],
            True,
        )

    datagram, checks = max(candidates, key=lambda item: sum(item[1].values()))
    return (
        datagram,
        checks,
        _datagram_mismatch_reasons(datagram, checks, claim, kind),
        False,
    )


def _path_role_status(
    frame: Optional[Dict[str, object]], expected: str, kind: str
):
    if frame is None:
        return False, True, []
    role = frame.get("ethercat_path_role", "unknown")
    if role == expected:
        return True, False, []
    if role == "unknown":
        return False, True, [f"{kind} frame path role is unknown"]
    return (
        False,
        False,
        [f"{kind} frame path role expected {expected} but observed {role}"],
    )


def _find_returning_request_wkc(
    frames: Sequence[Dict[str, object]], claim: Dict[str, object]
):
    for frame in frames:
        if frame.get("ethercat_path_role") != "returning":
            continue
        if frame.get("frame_number") == claim["request_frame"]:
            continue
        for datagram in frame.get("datagrams", []):
            if not isinstance(datagram, dict):
                continue
            checks = _datagram_checks(datagram, claim, "request")
            if checks is not None and all(checks.values()):
                return datagram.get("wkc")
    return None


def _verify_sdo_claim(
    claim: Dict[str, object], frames: Sequence[Dict[str, object]], frame_lookup: Dict[int, Dict[str, object]]
) -> Dict[str, object]:
    request_frame = frame_lookup.get(claim["request_frame"])
    response_frame = frame_lookup.get(claim["response_frame"])
    checks = {
        "request_frame": request_frame is not None,
        "station": False,
        "index": False,
        "subindex": False,
        "data": False,
        "response_frame": response_frame is not None,
        "response_match": False,
        "abort_detected": False,
    }
    mismatch_reasons: List[str] = []
    inconclusive = False
    explicit_failure = False

    request_role_ok, request_role_inconclusive, reasons = _path_role_status(
        request_frame, "outgoing", "request"
    )
    mismatch_reasons.extend(reasons)
    inconclusive = inconclusive or request_role_inconclusive
    if reasons and not request_role_inconclusive:
        explicit_failure = True

    request_datagram, request_checks, reasons, request_missing = _find_sdo_datagram(
        request_frame, claim, "request"
    )
    checks.update(request_checks)
    mismatch_reasons.extend(reasons)
    inconclusive = inconclusive or request_missing
    if reasons and not request_missing:
        explicit_failure = True

    response_role_ok, response_role_inconclusive, reasons = _path_role_status(
        response_frame, "returning", "response"
    )
    mismatch_reasons.extend(reasons)
    inconclusive = inconclusive or response_role_inconclusive
    if reasons and not response_role_inconclusive:
        explicit_failure = True

    response_datagram, response_checks, reasons, response_missing = _find_sdo_datagram(
        response_frame, claim, "response"
    )
    checks["response_match"] = all(response_checks.values())
    mismatch_reasons.extend(reasons)
    inconclusive = inconclusive or response_missing
    if reasons and not response_missing:
        explicit_failure = True

    response_coe = response_datagram.get("coe") if isinstance(response_datagram, dict) else None
    response_coe = response_coe if isinstance(response_coe, dict) else {}
    abort_code = response_coe.get("abort_code")
    checks["abort_detected"] = _present(abort_code)
    if checks["abort_detected"]:
        explicit_failure = True
        mismatch_reasons.append(f"response.abort_code observed {abort_code}")

    claim_abort_code = claim.get("claimed_abort_code")
    if claim_abort_code is not None:
        if not checks["abort_detected"]:
            explicit_failure = True
            mismatch_reasons.append(
                f"claimed_abort_code expected {_format_hex(claim_abort_code, 8)} but response has no abort"
            )
        elif _as_int(abort_code) != claim_abort_code:
            explicit_failure = True
            mismatch_reasons.append(
                f"claimed_abort_code expected {_format_hex(claim_abort_code, 8)} "
                f"but observed {abort_code}"
            )

    evidence_complete = (
        request_role_ok
        and response_role_ok
        and checks["request_frame"]
        and checks["response_frame"]
        and checks["station"]
        and checks["index"]
        and checks["subindex"]
        and checks["data"]
        and checks["response_match"]
        and not checks["abort_detected"]
    )
    if evidence_complete and claim.get("claimed_success") is not True:
        explicit_failure = True
        mismatch_reasons.append(
            "claimed_success is false but evidence matches without an SDO abort"
        )

    if explicit_failure:
        result = "FAIL"
    elif inconclusive:
        result = "INCONCLUSIVE"
    else:
        result = "PASS"

    return {
        "claim": claim,
        "result": result,
        "checks": checks,
        "request_evidence": _frame_evidence(request_frame, request_datagram),
        "response_evidence": _frame_evidence(response_frame, response_datagram),
        "wkc_evidence": {
            "request_outgoing_wkc": request_datagram.get("wkc") if request_datagram else None,
            "request_returning_wkc": _find_returning_request_wkc(frames, claim),
            "response_wkc": response_datagram.get("wkc") if response_datagram else None,
        },
        "mismatch_reasons": mismatch_reasons,
    }


def verify_sdo_transactions(
    claims: Sequence[Dict[str, object]],
    capture: str,
    frame_query=None,
) -> List[Dict[str, object]]:
    """Verify all claims using exactly one deterministic batch frame query."""
    frame_numbers = plan_sdo_frame_query(claims)
    query = frame_query or query_frames
    try:
        query_result = query(capture, frame_numbers)
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return [
            {
                "claim": claim,
                "result": "INCONCLUSIVE",
                "checks": {
                    "request_frame": False,
                    "station": False,
                    "index": False,
                    "subindex": False,
                    "data": False,
                    "response_frame": False,
                    "response_match": False,
                    "abort_detected": False,
                },
                "request_evidence": None,
                "response_evidence": None,
                "wkc_evidence": {
                    "request_outgoing_wkc": None,
                    "request_returning_wkc": None,
                    "response_wkc": None,
                },
                "mismatch_reasons": [f"frame evidence query failed: {exc}"],
            }
            for claim in claims
        ]

    frames = query_result.get("frames", []) if isinstance(query_result, dict) else []
    frames = frames if isinstance(frames, list) else []
    frame_lookup = {
        frame.get("frame_number"): frame
        for frame in frames
        if isinstance(frame, dict) and type(frame.get("frame_number")) is int
    }
    return [_verify_sdo_claim(claim, frames, frame_lookup) for claim in claims]


_SDO_REFERENCE_QUERIES = (
    "EtherCAT datagram working counter",
    "source MAC address locally administered frame processing",
    "CoE SDO abort code request response",
)
_SDO_REFERENCE_SEARCH_LIMIT = 5
_SDO_REFERENCE_RELEVANCE_RULES = {
    _SDO_REFERENCE_QUERIES[0]: (
        ("working counter", "wkc"),
        ("ethercat datagram",),
    ),
    _SDO_REFERENCE_QUERIES[1]: (
        ("source mac", "mac address"),
        ("locally administered", "frame processing"),
    ),
    _SDO_REFERENCE_QUERIES[2]: (
        ("coe", "sdo", "mailbox"),
        ("request", "response", "abort"),
    ),
}


def _reference_search_text(match: Dict[str, object]) -> str:
    heading_path = match.get("heading_path", [])
    if isinstance(heading_path, (list, tuple)):
        heading_path = " ".join(str(item) for item in heading_path)
    return " ".join(
        str(value)
        for value in (
            match.get("heading", ""),
            heading_path,
            match.get("excerpt", ""),
        )
        if value
    ).casefold()


def _contains_reference_term(text: str, term: str) -> bool:
    return bool(re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE))


def _reference_is_relevant(query: str, match: object) -> bool:
    if not isinstance(match, dict):
        return False
    text = _reference_search_text(match)
    return all(
        any(_contains_reference_term(text, term) for term in alternatives)
        for alternatives in _SDO_REFERENCE_RELEVANCE_RULES[query]
    )


def _build_reference_context() -> List[Dict[str, object]]:
    from retrieval.markdown_spec import search_spec_markdown

    references = []
    for query in _SDO_REFERENCE_QUERIES:
        try:
            matches = search_spec_markdown(
                query,
                limit=_SDO_REFERENCE_SEARCH_LIMIT,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            references.append(
                {
                    "query": query,
                    "status": "insufficient",
                    "reason": str(exc),
                }
            )
            continue
        match = next(
            (candidate for candidate in matches if _reference_is_relevant(query, candidate)),
            None,
        )
        if match is None:
            references.append(
                {
                    "query": query,
                    "status": "insufficient",
                    "reason": "no bounded search result passed relevance validation",
                }
            )
            continue
        references.append(
            {
                "query": query,
                "source": match.get("source_relative_path"),
                "heading_path": match.get("heading_path"),
                "excerpt": match.get("excerpt"),
            }
        )
    return references


def _inconclusive_result(claim: Dict[str, object], reason: str):
    return {
        "claim": claim,
        "result": "INCONCLUSIVE",
        "checks": {
            "request_frame": False,
            "station": False,
            "index": False,
            "subindex": False,
            "data": False,
            "response_frame": False,
            "response_match": False,
            "abort_detected": False,
        },
        "request_evidence": None,
        "response_evidence": None,
        "wkc_evidence": {
            "request_outgoing_wkc": None,
            "request_returning_wkc": None,
            "response_wkc": None,
        },
        "mismatch_reasons": [reason],
    }


def build_sdo_verification_context(
    user_question: str,
    capture: Optional[str] = None,
    active_capture: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """Build the deterministic context handed to the explanation agent."""
    if is_explicit_sdo_verification(user_question):
        user_question = remove_explicit_sdo_verification_prefix(user_question)
    if not contains_sdo_transaction_data(user_question):
        return None

    reference_context = _build_reference_context()
    context: Dict[str, object] = {
        "user_question": user_question,
        "parsed_claims": [],
        "verification_results": [],
        "reference_context": reference_context,
    }
    try:
        claims = parse_sdo_transaction_claims(user_question)
    except SDOClaimParseError as exc:
        context["parse_errors"] = exc.errors
        return context

    context["parsed_claims"] = claims
    try:
        if capture is not None:
            capture_name = capture
        else:
            capture_name = extract_capture_name(user_question)
            if capture_name is None:
                capture_name = active_capture or config.DEFAULT_CAPTURE_NAME
        if capture_name is None or not str(capture_name).strip():
            raise ValueError("capture logical filename is missing")
        from retrieval.tshark_capture import validate_capture_name

        capture_name = validate_capture_name(capture_name)
    except (TypeError, ValueError) as exc:
        context["verification_results"] = [
            _inconclusive_result(claim, str(exc)) for claim in claims
        ]
        context["capture"] = None
        return context

    context["capture"] = capture_name
    context["verification_results"] = verify_sdo_transactions(claims, capture_name)
    return context

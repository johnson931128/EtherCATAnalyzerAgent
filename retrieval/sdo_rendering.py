"""Deterministic Markdown rendering for SDO verification results."""

from typing import Any, Dict, Iterable, List, Optional, Sequence


def _value(value: Any, default: str = "") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _int_value(value: Any) -> Optional[int]:
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


def _hex(value: Any, width: int) -> str:
    number = _int_value(value)
    return f"0x{number:0{width}X}" if number is not None else "Not available"


def _object_name(claim: Dict[str, Any]) -> str:
    subindex = _int_value(claim.get("subindex"))
    subindex_text = f"{subindex:02X}" if subindex is not None else "Not available"
    return f"{_hex(claim.get('index'), 4)}:{subindex_text}"


def _result_value(result: Dict[str, Any]) -> str:
    value = result.get("result")
    return value if value in {"PASS", "FAIL", "INCONCLUSIVE"} else "INCONCLUSIVE"


def _check_status(value: Any, result: str) -> str:
    if value is True:
        return "PASS"
    return result


def _reason(result: Dict[str, Any], marker: str, fallback: str) -> str:
    reasons = result.get("mismatch_reasons")
    if isinstance(reasons, list):
        for reason in reasons:
            if marker in str(reason).casefold():
                return str(reason)
    return fallback


def render_sdo_verification_summary(
    verification_results: Sequence[Dict[str, Any]],
) -> str:
    """Render one deterministic summary row per parsed claim."""
    lines = [
        "| Object | Result | Request | Response |",
        "| --- | --- | ---: | ---: |",
    ]
    for result in verification_results:
        claim = result.get("claim") if isinstance(result, dict) else {}
        claim = claim if isinstance(claim, dict) else {}
        lines.append(
            "| {object_name} | {result} | {request} | {response} |".format(
                object_name=_object_name(claim),
                result=_result_value(result),
                request=_value(claim.get("request_frame"), "Not available"),
                response=_value(claim.get("response_frame"), "Not available"),
            )
        )
    if len(lines) == 2:
        lines.append("| Not available | INCONCLUSIVE | Not available | Not available |")
    return "\n".join(lines)


def _render_datagram_evidence(
    title: str,
    evidence: Optional[Dict[str, Any]],
    result: Dict[str, Any],
    kind: str,
) -> List[str]:
    lines = [title]
    if not isinstance(evidence, dict):
        claim = result.get("claim") if isinstance(result.get("claim"), dict) else {}
        frame = claim.get(f"{kind}_frame", "Not available")
        lines.append(f"- Frame: INCONCLUSIVE")
        lines.append(
            f"- Reason: {_reason(result, f'{kind} frame', f'{kind} frame {frame} was not returned by TShark evidence query')}"
        )
        return lines

    lines.append(f"- Frame: {_value(evidence.get('frame_number'), 'Not available')}")
    lines.append(f"- EtherCAT Path: {_value(evidence.get('ethercat_path_role'), 'unknown')}")
    datagram = evidence.get("datagram")
    datagram = datagram if isinstance(datagram, dict) else {}
    for label, key in (
        ("Command", "cmd_name"),
        ("ADP", "adp"),
        ("ADO", "ado"),
        ("WKC", "wkc"),
    ):
        if key == "cmd_name" and datagram.get(key) is None:
            if datagram.get("cmd") is not None:
                lines.append(f"- {label}: {_value(datagram.get('cmd'))}")
            continue
        if key in datagram and datagram[key] is not None:
            lines.append(f"- {label}: {_value(datagram[key])}")

    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    if coe.get("sdo_request") not in (None, ""):
        lines.append("- CoE: SDO Request")
    elif coe.get("sdo_response") not in (None, ""):
        lines.append("- CoE: SDO Response")
    if "index" in coe or "subindex" in coe:
        subindex = _int_value(coe.get("subindex"))
        subindex_text = f"{subindex:02X}" if subindex is not None else "Not available"
        lines.append(
            f"- Index/SubIndex: {_hex(coe.get('index'), 4)}:{subindex_text}"
        )
    if kind == "request" and "data" in coe and coe.get("data") is not None:
        lines.append(f"- Data: {_value(coe.get('data'))}")
    if kind == "response" and "abort_code" in coe:
        abort = coe.get("abort_code")
        lines.append(f"- Abort Code: {_value(abort, 'None')}")
    return lines


def _render_checks(result: Dict[str, Any]) -> List[str]:
    checks = result.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    overall = _result_value(result)
    lines = ["Verification Checks"]
    labels = (
        ("request_frame", "Request frame"),
        ("station", "Station match"),
        ("index", "Index match"),
        ("subindex", "SubIndex match"),
        ("data", "Data match"),
        ("response_frame", "Response frame"),
        ("response_match", "Response match"),
    )
    for key, label in labels:
        if key in checks:
            lines.append(f"- {label}: {_check_status(checks[key], overall)}")
            if key == "data" and checks[key] is False:
                claim = result.get("claim") if isinstance(result.get("claim"), dict) else {}
                request_evidence = result.get("request_evidence")
                request_datagram = (
                    request_evidence.get("datagram")
                    if isinstance(request_evidence, dict)
                    else None
                )
                request_coe = (
                    request_datagram.get("coe")
                    if isinstance(request_datagram, dict)
                    else None
                )
                request_coe = request_coe if isinstance(request_coe, dict) else {}
                lines.append(
                    f"  Expected: {_value(claim.get('data'), 'Not available')}"
                )
                lines.append(
                    f"  Observed: {_value(request_coe.get('data'), 'Not available')}"
                )

    if "abort_detected" in checks:
        response_evidence = result.get("response_evidence")
        if isinstance(response_evidence, dict):
            abort_status = "FAIL" if checks["abort_detected"] else "PASS"
            abort_text = "Yes" if checks["abort_detected"] else "No"
            lines.append(f"- SDO Abort: {abort_status} ({abort_text})")
        else:
            lines.append("- SDO Abort: INCONCLUSIVE")
    return lines


def _render_mismatch_details(result: Dict[str, Any]) -> List[str]:
    if _result_value(result) == "PASS":
        return []
    lines: List[str] = []
    reasons = result.get("mismatch_reasons")
    if isinstance(reasons, list) and reasons:
        lines.append("Mismatch Reasons")
        lines.extend(f"- {reason}" for reason in reasons)
    return lines


def render_sdo_engineering_evidence(
    verification_results: Sequence[Dict[str, Any]],
) -> str:
    """Render compact claim, frame, datagram, check, and mismatch evidence."""
    lines: List[str] = []
    for result in verification_results:
        if not isinstance(result, dict):
            continue
        claim = result.get("claim") if isinstance(result.get("claim"), dict) else {}
        result_name = _result_value(result)
        lines.extend([f"### {_object_name(claim)} - {result_name}", "", "DLL Claim"])
        lines.extend(
            [
                f"- Station: {_hex(claim.get('station'), 4)}",
                f"- Data: {_value(claim.get('data'), 'Not available')}",
                f"- Request Frame: {_value(claim.get('request_frame'), 'Not available')}",
                f"- Response Frame: {_value(claim.get('response_frame'), 'Not available')}",
                f"- Claimed Success: {_value(claim.get('claimed_success'), 'Not available')}",
                "",
            ]
        )
        lines.extend(
            _render_datagram_evidence(
                "Request Evidence", result.get("request_evidence"), result, "request"
            )
        )
        lines.append("")
        lines.extend(
            _render_datagram_evidence(
                "Response Evidence", result.get("response_evidence"), result, "response"
            )
        )
        wkc = result.get("wkc_evidence")
        if isinstance(wkc, dict) and any(value is not None for value in wkc.values()):
            lines.extend(["", "Working Counter Evidence"])
            for key, label in (
                ("request_outgoing_wkc", "Request outgoing WKC"),
                ("request_returning_wkc", "Request returning WKC"),
                ("response_wkc", "Response WKC"),
            ):
                if wkc.get(key) is not None:
                    lines.append(f"- {label}: {wkc[key]}")
        lines.extend(["", *_render_checks(result)])
        mismatch_details = _render_mismatch_details(result)
        if mismatch_details:
            lines.extend(["", *mismatch_details])
        lines.append("")
    return "\n".join(lines).rstrip()


def _reference_provenance(reference_context: Iterable[Dict[str, Any]]) -> List[str]:
    lines = []
    for reference in reference_context:
        if not isinstance(reference, dict):
            continue
        source = reference.get("source")
        heading = reference.get("heading_path")
        query = reference.get("query")
        excerpt = " ".join(str(reference.get("excerpt", "")).split())
        parts = [str(value) for value in (source, heading) if value]
        if not parts and query:
            parts.append(str(query))
        if excerpt:
            parts.append(excerpt[:300])
        if parts:
            lines.append("- " + " - ".join(parts))
    return lines


def render_sdo_engineering_references(
    reference_context: Iterable[Dict[str, Any]],
) -> str:
    """Render fixed SDO reference wording plus deterministic provenance."""
    lines = [
        "- EtherCAT frame path: outgoing / returning is determined by ESC Source MAC U/L bit modification evidence.",
        "- Working Counter: WKC is EtherCAT Datagram execution evidence. It is independent from CoE SDO transaction success.",
        "- SDO success: determined by a matching CoE SDO response with no SDO Abort.",
    ]
    provenance = _reference_provenance(reference_context or [])
    if provenance:
        lines.extend(["", "Reference provenance", *provenance])
    return "\n".join(lines)

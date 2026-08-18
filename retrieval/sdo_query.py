"""Deterministic planning helpers for explicit SDO object capture queries."""

import re
from typing import Any, Dict, List, Optional


_SDO_OBJECT_REFERENCE = re.compile(
    r"(?<![0-9A-Za-z])0[xX]([0-9A-Fa-f]{1,4}):([0-9A-Fa-f]{1,2})(?![0-9A-Za-z])"
)
_CAPTURE_QUERY_MARKERS = (
    "查",
    "封包",
    "frame",
    "request",
    "response",
    "wkc",
    "abort",
    "寫入",
    "寫了",
    "write",
    "data",
    "sdo 操作",
    "sdo operation",
    "transaction",
)


def extract_sdo_object_reference(text: Any) -> Optional[Dict[str, int]]:
    """Extract one unambiguous hexadecimal SDO index/subindex reference."""
    if not isinstance(text, str):
        return None

    matches = list(_SDO_OBJECT_REFERENCE.finditer(text))
    if len(matches) != 1:
        return None

    index = int(matches[0].group(1), 16)
    subindex = int(matches[0].group(2), 16)
    if not 0 <= index <= 0xFFFF or not 0 <= subindex <= 0xFF:
        return None
    return {"index": index, "subindex": subindex}


def has_sdo_capture_query_intent(text: Any) -> bool:
    """Return whether the text asks for capture/evidence about an SDO object."""
    if not isinstance(text, str):
        return False
    lowered = text.casefold()
    return any(marker in lowered for marker in _CAPTURE_QUERY_MARKERS)


def is_sdo_object_capture_query(text: Any) -> bool:
    """Return whether one explicit SDO object has a capture-query request."""
    return (
        extract_sdo_object_reference(text) is not None
        and has_sdo_capture_query_intent(text)
    )


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _position(record: Dict[str, object]):
    frame_number = record.get("frame_number")
    datagram_sequence = record.get("datagram_sequence")
    return (
        frame_number if type(frame_number) is int else float("inf"),
        datagram_sequence if type(datagram_sequence) is int else float("inf"),
    )


def _counter_compatible(left: Dict[str, object], right: Dict[str, object]) -> bool:
    left_counter = left.get("mailbox_counter")
    right_counter = right.get("mailbox_counter")
    return (
        not _present(left_counter)
        or not _present(right_counter)
        or str(left_counter) == str(right_counter)
    )


def _semantic_role(frame: Dict[str, object], datagram: Dict[str, object]) -> str:
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    if _present(coe.get("abort_code")):
        return "abort"
    if _present(coe.get("sdo_request")):
        path_role = frame.get("ethercat_path_role")
        if path_role == "outgoing":
            return "request_outgoing"
        if path_role == "returning":
            return "request_returning"
        return "unknown"
    if _present(coe.get("sdo_response")):
        return "response"
    return "unknown"


def _normalize_datagram(
    frame: Dict[str, object], datagram: Dict[str, object]
) -> Dict[str, object]:
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    mailbox = datagram.get("mailbox")
    mailbox = mailbox if isinstance(mailbox, dict) else {}
    return {
        "frame_number": frame.get("frame_number"),
        "ethercat_path_role": frame.get("ethercat_path_role", "unknown"),
        "semantic_role": _semantic_role(frame, datagram),
        "cmd_name": datagram.get("cmd_name"),
        "cmd": datagram.get("cmd"),
        "adp": datagram.get("adp"),
        "ado": datagram.get("ado"),
        "wkc": datagram.get("wkc"),
        "datagram_sequence": datagram.get("datagram_sequence"),
        "mailbox_counter": mailbox.get("counter"),
        "sdo_request": coe.get("sdo_request"),
        "sdo_response": coe.get("sdo_response"),
        "index": coe.get("index"),
        "subindex": coe.get("subindex"),
        "data": coe.get("data"),
        "abort_code": coe.get("abort_code"),
        "source_mac": frame.get("source_mac"),
        "dest_mac": frame.get("dest_mac"),
    }


def _candidate_records(
    records: List[Dict[str, object]],
    semantic_roles: set[str],
    start: tuple,
    end: Optional[tuple],
    anchor: Dict[str, object],
) -> List[Dict[str, object]]:
    return [
        record
        for record in records
        if record.get("semantic_role") in semantic_roles
        and _position(record) > start
        and (end is None or _position(record) < end)
        and _counter_compatible(anchor, record)
    ]


def _pairing_status(
    outgoing: Optional[Dict[str, object]],
    returning: Optional[Dict[str, object]],
    response: Optional[Dict[str, object]],
    abort: Optional[Dict[str, object]],
    ambiguous: bool,
) -> str:
    if ambiguous:
        return "ambiguous"
    if outgoing is not None and returning is not None and (response or abort):
        return "grouped"
    return "unpaired"


def _group_transactions(
    records: List[Dict[str, object]],
    index: Any,
    subindex: Any,
) -> List[Dict[str, object]]:
    ordered = sorted(records, key=_position)
    outgoing_records = [
        record
        for record in ordered
        if record.get("semantic_role") == "request_outgoing"
    ]
    used = set()
    transactions: List[Dict[str, object]] = []

    for number, outgoing in enumerate(outgoing_records, start=1):
        outgoing_position = _position(outgoing)
        next_outgoing = (
            _position(outgoing_records[number])
            if number < len(outgoing_records)
            else None
        )
        returning_candidates = _candidate_records(
            ordered,
            {"request_returning"},
            outgoing_position,
            next_outgoing,
            outgoing,
        )
        returning = returning_candidates[0] if len(returning_candidates) == 1 else None
        ambiguous = len(returning_candidates) > 1
        if returning is not None:
            used.add(id(returning))

        response_start = _position(returning) if returning is not None else outgoing_position
        response_candidates = _candidate_records(
            ordered,
            {"response", "abort"},
            response_start,
            next_outgoing,
            outgoing,
        )
        response_record = (
            response_candidates[0] if len(response_candidates) == 1 else None
        )
        if len(response_candidates) > 1:
            ambiguous = True
        if response_record is not None:
            used.add(id(response_record))

        response = (
            response_record
            if response_record is not None
            and response_record.get("semantic_role") == "response"
            else None
        )
        abort = (
            response_record
            if response_record is not None
            and response_record.get("semantic_role") == "abort"
            else None
        )
        transactions.append(
            {
                "transaction_number": number,
                "index": index,
                "subindex": subindex,
                "written_data": (
                    outgoing.get("data") if outgoing is not None else None
                ),
                "request_outgoing": outgoing,
                "request_returning": returning,
                "response": response,
                "abort": abort,
                "pairing_status": _pairing_status(
                    outgoing, returning, response, abort, ambiguous
                ),
            }
        )

    for record in ordered:
        if id(record) in used or record.get("semantic_role") == "request_outgoing":
            continue
        transactions.append(
            {
                "transaction_number": len(transactions) + 1,
                "index": index,
                "subindex": subindex,
                "written_data": None,
                "request_outgoing": None,
                "request_returning": (
                    record if record.get("semantic_role") == "request_returning" else None
                ),
                "response": record if record.get("semantic_role") == "response" else None,
                "abort": record if record.get("semantic_role") == "abort" else None,
                "unpaired": [record],
                "pairing_status": "unpaired",
            }
        )
    return transactions


def normalize_sdo_object_query_result(
    query_result: Dict[str, object]
) -> Dict[str, object]:
    """Add deterministic CoE/path roles and conservative transaction grouping."""
    frames = query_result.get("frames")
    frames = frames if isinstance(frames, list) else []
    records: List[Dict[str, object]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        datagrams = frame.get("datagrams")
        if not isinstance(datagrams, list):
            continue
        for datagram in datagrams:
            if isinstance(datagram, dict):
                records.append(_normalize_datagram(frame, datagram))

    normalized = dict(query_result)
    normalized["semantic_frames"] = records
    normalized["transactions"] = _group_transactions(
        records,
        query_result.get("index"),
        query_result.get("subindex"),
    )
    return normalized

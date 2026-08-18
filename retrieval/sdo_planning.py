"""Small deterministic planner for SDO capture investigations."""

import re
from typing import Any, Dict, List, Optional, TypedDict


class SdoQuerySpec(TypedDict):
    index: int
    subindex: int
    frame_start: Optional[int]
    frame_end: Optional[int]
    requested_evidence: List[str]


class SdoEvidencePlan(TypedDict):
    active_capture: Optional[str]
    primary_query: str
    arguments: Dict[str, object]
    planned_tshark_scans: int
    refinement_policy: str
    query_spec: SdoQuerySpec


class SdoEvidenceAssessment(TypedDict):
    status: str
    requested_evidence: List[str]
    observed_evidence: List[str]
    missing_evidence: List[str]
    ambiguous_transactions: List[int]
    refinement: Optional[Dict[str, object]]


_SDO_OBJECT_REFERENCE = re.compile(
    r"(?<![0-9A-Za-z])0[xX]([0-9A-Fa-f]{1,4}):([0-9A-Fa-f]{1,2})(?![0-9A-Za-z])"
)
_CAPTURE_QUERY_MARKERS = (
    "frame",
    "request",
    "response",
    "wkc",
    "abort",
    "write",
    "data",
    "sdo operation",
    "transaction",
    "\u67e5",
    "\u5c01\u5305",
    "\u64cd\u4f5c",
    "\u5beb\u5165",
    "\u8acb\u5e6b\u6211\u67e5",
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


def _requested_evidence(text: str) -> List[str]:
    lowered = text.casefold()
    requested = ["transaction"]
    if any(marker in lowered for marker in ("frame", "request", "response")):
        requested.append("request_response")
    if any(marker in lowered for marker in ("write", "data", "\u5beb\u5165")):
        requested.append("data")
    if "wkc" in lowered:
        requested.append("wkc")
    if "abort" in lowered or "\u4e2d\u6b62" in lowered:
        requested.append("abort")
    if "outgoing" in lowered or "returning" in lowered:
        requested.append("path")
    return requested


def build_sdo_query_spec(text: str) -> Optional[SdoQuerySpec]:
    reference = extract_sdo_object_reference(text)
    if reference is None:
        return None
    return {
        "index": reference["index"],
        "subindex": reference["subindex"],
        "frame_start": None,
        "frame_end": None,
        "requested_evidence": _requested_evidence(text),
    }


def build_sdo_evidence_plan(
    text: str, active_capture: Optional[str]
) -> Optional[SdoEvidencePlan]:
    query_spec = build_sdo_query_spec(text)
    if query_spec is None:
        return None
    return {
        "active_capture": active_capture,
        "primary_query": "query_sdo_object",
        "arguments": {
            "capture": active_capture,
            "index": query_spec["index"],
            "subindex": query_spec["subindex"],
            "frame_start": query_spec["frame_start"],
            "frame_end": query_spec["frame_end"],
        },
        "planned_tshark_scans": 1,
        "refinement_policy": (
            "Use at most one exact query_frames refinement only when a deterministic "
            "evidence field is missing; do not broaden the capture scan."
        ),
        "query_spec": query_spec,
    }


def assess_sdo_evidence(
    normalized_result: Dict[str, object], query_spec: SdoQuerySpec
) -> SdoEvidenceAssessment:
    records = normalized_result.get("semantic_frames")
    records = records if isinstance(records, list) else []
    transactions = normalized_result.get("transactions")
    transactions = transactions if isinstance(transactions, list) else []
    observed = set()
    if any(
        isinstance(record, dict)
        and record.get("semantic_role") == "request_outgoing"
        for record in records
    ):
        observed.add("transaction")
    if any(
        isinstance(transaction, dict)
        and transaction.get("response") is not None
        for transaction in transactions
    ):
        observed.add("request_response")
    if any(
        isinstance(transaction, dict)
        and transaction.get("written_data") is not None
        for transaction in transactions
    ):
        observed.add("data")
    if records and all(
        isinstance(record, dict) and record.get("wkc") is not None
        for record in records
    ):
        observed.add("wkc")
    completion_records = [
        record for record in records
        if isinstance(record, dict)
        and record.get("semantic_role") in {"response", "abort"}
    ]
    if completion_records:
        observed.add("abort")
        observed.add("request_response")
    if any(
        isinstance(transaction, dict)
        and isinstance(transaction.get("request_exchange"), dict)
        and transaction["request_exchange"].get("returning") is not None
        for transaction in transactions
    ):
        observed.add("path")

    requested = list(query_spec["requested_evidence"])
    missing = [item for item in requested if item not in observed]
    ambiguous = [
        transaction.get("transaction_number")
        for transaction in transactions
        if isinstance(transaction, dict)
        and transaction.get("pairing_status") == "ambiguous"
    ]
    if ambiguous:
        status = "AMBIGUOUS"
    elif not records:
        status = "INSUFFICIENT"
    elif missing:
        status = "PARTIAL" if observed else "INSUFFICIENT"
    else:
        status = "COMPLETE"
    return {
        "status": status,
        "requested_evidence": requested,
        "observed_evidence": sorted(observed),
        "missing_evidence": missing,
        "ambiguous_transactions": ambiguous,
        "refinement": None,
    }

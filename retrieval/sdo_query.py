"""Deterministic planning helpers for explicit SDO object capture queries."""

import re
from typing import Any, Dict, Optional


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

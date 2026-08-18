"""Compatibility entry point for deterministic SDO query normalization."""

from typing import Dict, List

from retrieval.sdo_evidence import group_sdo_transactions, normalize_datagram
from retrieval.sdo_planning import (
    assess_sdo_evidence,
    build_sdo_evidence_plan,
    build_sdo_query_spec,
    extract_sdo_object_reference,
    has_sdo_capture_query_intent,
    is_sdo_object_capture_query,
)


def normalize_sdo_object_query_result(
    query_result: Dict[str, object]
) -> Dict[str, object]:
    """Add deterministic CoE/path roles and transaction grouping."""
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
                records.append(normalize_datagram(frame, datagram))

    normalized = dict(query_result)
    normalized["semantic_frames"] = records
    normalized["transactions"] = group_sdo_transactions(
        records,
        query_result.get("index"),
        query_result.get("subindex"),
    )
    return normalized

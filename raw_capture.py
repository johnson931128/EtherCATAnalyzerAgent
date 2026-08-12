"""Deterministic search helpers for raw TShark capture JSON."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


COE_SDO_FIELDS = (
    "ecat_mailbox.coe.sdoreq",
    "ecat_mailbox.coe.sdores",
    "ecat_mailbox.coe.sdoidx",
    "ecat_mailbox.coe.sdosub",
    "ecat_mailbox.coe.sdodata",
)


def _iter_packets(document: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(document, list):
        for item in document:
            if isinstance(item, dict):
                yield item
        return

    if isinstance(document, dict):
        packets = document.get("packets")
        if isinstance(packets, list):
            for item in packets:
                if isinstance(item, dict):
                    yield item
        else:
            yield document


def _field_name_matches(key: str, path: Sequence[str], field_name: str) -> bool:
    path_text = ".".join(path)
    return key == field_name or path_text == field_name or path_text.endswith(
        f".{field_name}"
    )


def _find_field_values(
    value: Any, field_names: Sequence[str], path: Sequence[str] = ()
) -> List[Any]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if any(_field_name_matches(key_text, child_path, name) for name in field_names):
                found.append(child)
            found.extend(_find_field_values(child, field_names, child_path))
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_field_values(child, field_names, path))
    return found


def find_first_packet_with_any_field(
    json_path: Path, field_names: Sequence[str]
) -> Optional[Dict[str, Any]]:
    """Return the first raw packet containing any requested field name."""
    document = json.loads(Path(json_path).read_text(encoding="utf-8"))
    for packet in _iter_packets(document):
        if _find_field_values(packet, field_names):
            return packet
    return None


def _first_field_value(value: Any, field_names: Sequence[str]) -> Any:
    values = _find_field_values(value, field_names)
    return values[0] if values else None


def _extract_datagram(packet: Dict[str, Any]) -> Dict[str, Any]:
    datagram_fields = {
        "Command": ("ecat.command", "ecat.cmd", "Command"),
        "ADP": ("ecat.adp", "ADP"),
        "ADO": ("ecat.ado", "ADO"),
        "Data Length": (
            "ecat.data_length",
            "ecat.length",
            "ecat.len",
            "Data Length",
        ),
        "WKC": ("ecat.wkc", "ecat.working_counter", "WKC"),
    }

    ecat_objects = _find_field_values(packet, ("ecat",))
    candidates = [value for value in ecat_objects if isinstance(value, dict)]
    candidates.append(packet)

    best_candidate = max(
        candidates,
        key=lambda candidate: sum(
            _first_field_value(candidate, names) is not None
            for names in datagram_fields.values()
        ),
    )
    return {
        label: _first_field_value(best_candidate, names)
        for label, names in datagram_fields.items()
    }


def find_first_coe_sdo_packet(json_path: Path) -> Optional[Dict[str, Any]]:
    """Find and extract the first packet containing a CoE SDO field."""
    packet = find_first_packet_with_any_field(json_path, COE_SDO_FIELDS)
    if packet is None:
        return None

    mailbox = _first_field_value(packet, ("ecat_mailbox",))
    coe_tree = _first_field_value(packet, ("ecat_mailbox.coe_tree", "coe_tree"))
    return {
        "frame_number": _first_field_value(packet, ("frame.number", "Frame Number")),
        "ecat_mailbox": mailbox,
        "coe_tree": coe_tree,
        "datagram": _extract_datagram(packet),
    }

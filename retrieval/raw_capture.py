"""Deterministic search helpers for raw TShark capture JSON."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence


COE_SDO_FIELDS = (
    "ecat_mailbox.coe.sdoreq",
    "ecat_mailbox.coe.sdores",
    "ecat_mailbox.coe.sdoidx",
    "ecat_mailbox.coe.sdosub",
    "ecat_mailbox.coe.sdodata",
)


def _iter_json_array_items(
    json_path: Path, chunk_size: int = 64 * 1024
) -> Iterator[Any]:
    decoder = json.JSONDecoder()

    with Path(json_path).open("r", encoding="utf-8") as stream:
        buffer = ""
        eof = False

        def read_more() -> None:
            nonlocal buffer, eof
            chunk = stream.read(chunk_size)
            if chunk:
                buffer += chunk
            else:
                eof = True

        while not buffer and not eof:
            read_more()

        position = 0
        while position < len(buffer) and buffer[position].isspace():
            position += 1
        if position >= len(buffer) and not eof:
            read_more()
            while position >= len(buffer) and not eof:
                read_more()
        if position >= len(buffer) or buffer[position] != "[":
            raise ValueError("Expected a top-level JSON array")
        position += 1

        expect_value = True
        while True:
            while position >= len(buffer) and not eof:
                read_more()
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            while position >= len(buffer) and not eof:
                read_more()
                while position < len(buffer) and buffer[position].isspace():
                    position += 1

            if position >= len(buffer):
                raise ValueError("Unexpected end of top-level JSON array")

            if expect_value and buffer[position] == "]":
                return
            if not expect_value and buffer[position] == "]":
                return
            if not expect_value:
                if buffer[position] != ",":
                    raise ValueError("Expected a comma between JSON array items")
                position += 1
                expect_value = True
                continue

            while True:
                try:
                    item, end_position = decoder.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ValueError("Invalid JSON array item") from exc
                    read_more()

            buffer = buffer[end_position:]
            position = 0
            expect_value = False
            yield item


def _iter_packets(json_path: Path) -> Iterable[Dict[str, Any]]:
    for item in _iter_json_array_items(json_path):
        if isinstance(item, dict):
            yield item


def _field_name_matches(key: str, path: Sequence[str], field_name: str) -> bool:
    path_text = ".".join(path)
    return key == field_name or path_text == field_name or path_text.endswith(
        f".{field_name}"
    )


def _packet_layers(packet: Dict[str, Any]) -> Dict[str, Any]:
    source = packet.get("_source")
    if not isinstance(source, dict):
        return {}
    layers = source.get("layers")
    return layers if isinstance(layers, dict) else {}


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
    for packet in _iter_packets(json_path):
        if _find_field_values(_packet_layers(packet), field_names):
            return packet
    return None


def _first_field_value(value: Any, field_names: Sequence[str]) -> Any:
    values = _find_field_values(value, field_names)
    return values[0] if values else None


def _iter_datagrams(ecat_layer: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(ecat_layer, dict):
        return

    for name, datagram in ecat_layer.items():
        if str(name).startswith("EtherCAT datagram:") and isinstance(
            datagram, dict
        ):
            yield datagram


def _extract_datagram(datagram: Dict[str, Any]) -> Dict[str, Any]:
    datagram_fields = {
        "Command": ("ecat.cmd",),
        "ADP": ("ecat.adp",),
        "ADO": ("ecat.ado",),
        "Data Length": ("ecat.subframe.length",),
        "WKC": ("ecat.cnt",),
    }
    header = datagram.get("Header")
    if not isinstance(header, (dict, list)):
        header = {}

    return {
        label: _first_field_value(header if label != "WKC" else datagram, names)
        for label, names in datagram_fields.items()
    }


def find_first_coe_sdo_packet(json_path: Path) -> Optional[Dict[str, Any]]:
    """Find and extract the first packet containing a CoE SDO field."""
    for packet in _iter_packets(json_path):
        layers = _packet_layers(packet)
        ecat_layer = layers.get("ecat")
        for datagram in _iter_datagrams(ecat_layer):
            if not _find_field_values(datagram, COE_SDO_FIELDS):
                continue

            return {
                "frame_number": _first_field_value(
                    layers, ("frame.number", "Frame Number")
                ),
                "ecat_mailbox": _first_field_value(
                    datagram, ("ecat_mailbox",)
                ),
                "coe_tree": _first_field_value(
                    datagram, ("ecat_mailbox.coe_tree",)
                ),
                "datagram": _extract_datagram(datagram),
            }
    return None

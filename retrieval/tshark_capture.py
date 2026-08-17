"""Bounded deterministic TShark capture query primitives."""

import csv
import io
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from core.config import CAPTURE_INPUT_ROOT, TSHARK_EXECUTABLE
from retrieval.raw_capture import COE_SDO_FIELDS


DEFAULT_QUERY_LIMIT = 50
MAX_QUERY_LIMIT = 200
MAX_DISPLAY_FILTER_LENGTH = 512
MAX_FIELD_COUNT = 32
MAX_BATCH_FRAME_COUNT = 50
TSHARK_TIMEOUT_SECONDS = 60
JSON_LAYER_SELECTOR = "frame eth ecat ecat_mailbox"

ECAT_COMMAND_NAMES = {
    0x00: "NOP",
    0x01: "APRD",
    0x02: "APWR",
    0x03: "APRW",
    0x04: "FPRD",
    0x05: "FPWR",
    0x06: "FPRW",
    0x07: "BRD",
    0x08: "BWR",
    0x09: "BRW",
    0x0A: "LRD",
    0x0B: "LWR",
    0x0C: "LRW",
    0x0D: "ARMW",
    0x0E: "FRMW",
}

CAPTURE_FIELD_ALLOWLIST = frozenset(
    {
        "frame.number",
        "frame.time_epoch",
        "frame.time_relative",
        "eth.src",
        "eth.dst",
        "ecat.cmd",
        "ecat.idx",
        "ecat.adp",
        "ecat.ado",
        "ecat.subframe.length",
        "ecat.cnt",
        "ecat.lad",
        "ecat.int",
        "ecat_mailbox.length",
        "ecat_mailbox.address",
        "ecat_mailbox.priority",
        "ecat_mailbox.type",
        "ecat_mailbox.counter",
        "ecat_mailbox.coe",
        "ecat_mailbox.coe.type",
        "ecat_mailbox.coe.abortcode",
        "ecat_mailbox.coe.sdolength",
        "ecat_mailbox.coe.sdoccsid",
        "ecat_mailbox.coe.sdoccsid.sizeind",
        "ecat_mailbox.coe.sdoccsid.expedited",
        "ecat_mailbox.coe.sdoccsid.size0",
        "ecat_mailbox.coe.sdoccsid.size1",
        "ecat_mailbox.coe.sdoccsid.complete",
        "ecat_mailbox.coe.sdoccsds",
        "ecat_mailbox.coe.sdoccsds.lastseg",
        "ecat_mailbox.coe.sdoccsds.size",
        "ecat_mailbox.coe.sdoccsds.toggle",
        "ecat_mailbox.coe.sdoccsiu",
        "ecat_mailbox.coe.sdoccsus",
        "ecat_mailbox.coe.sdoccsus_toggle",
        "ecat_mailbox.coe.sdoscsiu",
        "ecat_mailbox.coe.sdoscsiu_sizeind",
        "ecat_mailbox.coe.sdoscsiu_expedited",
        "ecat_mailbox.coe.sdoscsiu_size0",
        "ecat_mailbox.coe.sdoscsiu_size1",
        "ecat_mailbox.coe.sdoscsiu_complete",
        "ecat_mailbox.coe.sdoscsds",
        "ecat_mailbox.coe.sdoscsds_toggle",
        "ecat_mailbox.coe.sdoscsus",
        "ecat_mailbox.coe.sdoscsus_lastseg",
        "ecat_mailbox.coe.sdoscsus_bytes",
        "ecat_mailbox.coe.sdoscsus_toggle",
        *COE_SDO_FIELDS,
    }
)


def validate_capture_name(capture: Any) -> str:
    if not isinstance(capture, str) or not capture.strip():
        raise ValueError("capture must be a logical filename")

    normalized = capture.strip()
    candidate = Path(normalized)
    if (
        candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name != normalized
        or normalized in {".", ".."}
    ):
        raise ValueError("capture must be a filename without path components")
    if candidate.suffix.casefold() not in {".pcap", ".pcapng"}:
        raise ValueError("capture must have a .pcap or .pcapng extension")
    return normalized


def resolve_capture_path(capture: str) -> Path:
    """Resolve one capture filename inside the repository capture root."""
    normalized = validate_capture_name(capture)
    root = Path(CAPTURE_INPUT_ROOT).resolve()
    resolved = (root / normalized).resolve()
    if resolved.parent != root:
        raise ValueError("capture must resolve inside the repository capture root")
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Capture not found: {normalized}; expected under {root}"
        )
    return resolved


def validate_display_filter(display_filter: Any) -> str:
    if not isinstance(display_filter, str) or not display_filter.strip():
        raise ValueError("display_filter must be a non-empty string")
    if "\x00" in display_filter or "\r" in display_filter or "\n" in display_filter:
        raise ValueError("display_filter must not contain NUL or newline characters")
    normalized = display_filter.strip()
    if len(normalized) > MAX_DISPLAY_FILTER_LENGTH:
        raise ValueError(
            f"display_filter must not exceed {MAX_DISPLAY_FILTER_LENGTH} characters"
        )
    return normalized


def validate_fields(fields: Any) -> List[str]:
    if not isinstance(fields, list) or not fields:
        raise ValueError("fields must be a non-empty list")
    if len(fields) > MAX_FIELD_COUNT:
        raise ValueError(f"fields must contain at most {MAX_FIELD_COUNT} entries")

    normalized_fields = []
    for field in fields:
        if not isinstance(field, str) or not field:
            raise ValueError("each field must be a non-empty string")
        if field not in CAPTURE_FIELD_ALLOWLIST:
            raise ValueError(f"Unsupported capture field: {field}")
        if field not in normalized_fields:
            normalized_fields.append(field)
    return normalized_fields


def validate_limit(limit: Any) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_QUERY_LIMIT}")
    return limit


def _validate_positive_integer(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_frame_numbers(frame_numbers: Any) -> List[int]:
    if not isinstance(frame_numbers, list) or not frame_numbers:
        raise ValueError("frame_numbers must be a non-empty list")

    unique_frames: List[int] = []
    for frame_number in frame_numbers:
        _validate_positive_integer(frame_number, "each frame number")
        if frame_number not in unique_frames:
            unique_frames.append(frame_number)
    if len(unique_frames) > MAX_BATCH_FRAME_COUNT:
        raise ValueError(
            f"frame_numbers must contain at most {MAX_BATCH_FRAME_COUNT} unique frames"
        )
    return unique_frames


def validate_query_frames_arguments(arguments: Any) -> Dict[str, object]:
    expected = {"capture", "frame_numbers"}
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ValueError("query_frames expects exactly: capture, frame_numbers")
    return {
        "capture": validate_capture_name(arguments["capture"]),
        "frame_numbers": validate_frame_numbers(arguments["frame_numbers"]),
    }


def _validate_optional_positive_integer(value: Any, name: str) -> Any:
    if value is not None:
        _validate_positive_integer(value, name)
    return value


def validate_query_sdo_object_arguments(arguments: Any) -> Dict[str, object]:
    expected = {"capture", "index", "subindex", "frame_start", "frame_end"}
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ValueError(
            "query_sdo_object expects exactly: capture, index, subindex, "
            "frame_start, frame_end"
        )

    index = arguments["index"]
    if type(index) is not int or not 0 <= index <= 0xFFFF:
        raise ValueError("index must be an integer between 0x0000 and 0xFFFF")

    subindex = arguments["subindex"]
    if subindex is not None and (
        type(subindex) is not int or not 0 <= subindex <= 0xFF
    ):
        raise ValueError("subindex must be null or an integer between 0x00 and 0xFF")

    frame_start = _validate_optional_positive_integer(
        arguments["frame_start"], "frame_start"
    )
    frame_end = _validate_optional_positive_integer(
        arguments["frame_end"], "frame_end"
    )
    if frame_start is not None and frame_end is not None and frame_start > frame_end:
        raise ValueError("frame_start must be less than or equal to frame_end")

    return {
        "capture": validate_capture_name(arguments["capture"]),
        "index": index,
        "subindex": subindex,
        "frame_start": frame_start,
        "frame_end": frame_end,
    }


def validate_query_capture_arguments(arguments: Any) -> Dict[str, object]:
    expected = {"capture", "display_filter", "fields", "limit"}
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ValueError(
            "query_capture expects exactly: capture, display_filter, fields, limit"
        )
    return {
        "capture": validate_capture_name(arguments["capture"]),
        "display_filter": validate_display_filter(arguments["display_filter"]),
        "fields": validate_fields(arguments["fields"]),
        "limit": validate_limit(arguments["limit"]),
    }


def validate_export_frame_arguments(arguments: Any) -> Dict[str, object]:
    expected = {"capture", "frame_number"}
    if not isinstance(arguments, dict) or set(arguments) != expected:
        raise ValueError("export_frame_json expects exactly: capture, frame_number")
    frame_number = arguments["frame_number"]
    if type(frame_number) is not int or frame_number <= 0:
        raise ValueError("frame_number must be a positive integer")
    return {
        "capture": validate_capture_name(arguments["capture"]),
        "frame_number": frame_number,
    }


def _parse_tshark_json(stdout: str) -> List[Dict[str, Any]]:
    try:
        packets = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed TShark JSON output: {exc}") from exc

    if not isinstance(packets, list):
        raise ValueError("TShark JSON output must be a top-level packet array")
    if any(not isinstance(packet, dict) for packet in packets):
        raise ValueError("TShark JSON packet must be an object")
    return packets


def _field_values(value: Any, field_names: set[str]) -> List[Any]:
    """Find fields only within one datagram object."""
    found: List[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in field_names:
                found.append(child)
            found.extend(_field_values(child, field_names))
    elif isinstance(value, list):
        for child in value:
            found.extend(_field_values(child, field_names))
    return found


def _first_field(value: Any, *field_names: str) -> Any:
    values = _field_values(value, set(field_names))
    return values[0] if values else None


def _command_name(value: Any) -> Any:
    command_value = _as_integer(value)
    if command_value is not None:
        return ECAT_COMMAND_NAMES.get(command_value)
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in ECAT_COMMAND_NAMES.values():
            return normalized
    return None


def _datagram_evidence(
    frame_number: int, datagram_sequence: int, datagram: Dict[str, Any]
) -> Dict[str, object]:
    mailbox_fields = {
        "ecat_mailbox",
        "ecat_mailbox.length",
        "ecat_mailbox.address",
        "ecat_mailbox.priority",
        "ecat_mailbox.type",
        "ecat_mailbox.counter",
    }
    coe_fields = {
        "ecat_mailbox.coe.type",
        "ecat_mailbox.coe.sdoreq",
        "ecat_mailbox.coe.sdores",
        "ecat_mailbox.coe.sdoidx",
        "ecat_mailbox.coe.sdosub",
        "ecat_mailbox.coe.sdodata",
        "ecat_mailbox.coe.abortcode",
    }
    mailbox = None
    if _field_values(datagram, mailbox_fields) or _field_values(datagram, coe_fields):
        mailbox = {
            "type": _first_field(datagram, "ecat_mailbox.type"),
            "counter": _first_field(datagram, "ecat_mailbox.counter"),
        }

    coe = None
    if _field_values(datagram, coe_fields):
        coe = {
            "type": _first_field(datagram, "ecat_mailbox.coe.type"),
            "sdo_request": _first_field(datagram, "ecat_mailbox.coe.sdoreq"),
            "sdo_response": _first_field(datagram, "ecat_mailbox.coe.sdores"),
            "index": _first_field(datagram, "ecat_mailbox.coe.sdoidx"),
            "subindex": _first_field(datagram, "ecat_mailbox.coe.sdosub"),
            "data": _first_field(datagram, "ecat_mailbox.coe.sdodata"),
            "abort_code": _first_field(datagram, "ecat_mailbox.coe.abortcode"),
        }

    return {
        "frame_number": frame_number,
        "datagram_sequence": datagram_sequence,
        "cmd": _first_field(datagram, "ecat.cmd"),
        "cmd_name": _command_name(_first_field(datagram, "ecat.cmd")),
        "idx": _first_field(datagram, "ecat.idx"),
        "adp": _first_field(datagram, "ecat.adp"),
        "ado": _first_field(datagram, "ecat.ado"),
        "data_length": _first_field(datagram, "ecat.subframe.length"),
        "wkc": _first_field(datagram, "ecat.cnt"),
        "mailbox": mailbox,
        "coe": coe,
    }


def _iter_datagram_objects(ecat_layer: Any):
    if not isinstance(ecat_layer, dict):
        return
    for name, datagram in ecat_layer.items():
        if str(name).startswith("EtherCAT datagram:") and isinstance(datagram, dict):
            yield datagram


def _frame_number(packet: Dict[str, Any]) -> Any:
    source = packet.get("_source")
    layers = source.get("layers") if isinstance(source, dict) else None
    frame_layer = layers.get("frame") if isinstance(layers, dict) else None
    value = _first_field(frame_layer, "frame.number")
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_mac_address(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        return None
    try:
        return tuple(int(part, 16) for part in parts)
    except ValueError:
        return None


def _classify_ethercat_path_roles(frames: List[Dict[str, object]]) -> None:
    """Classify frame direction only when an original/modified MAC pair is present."""
    source_macs = {
        parsed
        for frame in frames
        for parsed in [_parse_mac_address(frame.get("source_mac"))]
        if parsed is not None
    }
    role_by_mac = {}
    for original in source_macs:
        if original[0] & 0x02:
            continue
        modified = (original[0] | 0x02, *original[1:])
        if modified in source_macs:
            role_by_mac[original] = "outgoing"
            role_by_mac[modified] = "returning"

    for frame in frames:
        parsed = _parse_mac_address(frame.get("source_mac"))
        frame["ethercat_path_role"] = role_by_mac.get(parsed, "unknown")


def _compact_packet(packet: Dict[str, Any]) -> Dict[str, object]:
    frame_number = _frame_number(packet)
    if frame_number is None:
        raise ValueError("TShark packet is missing frame.number")
    source = packet.get("_source")
    layers = source.get("layers") if isinstance(source, dict) else None
    eth_layer = layers.get("eth") if isinstance(layers, dict) else None
    ecat_layer = layers.get("ecat") if isinstance(layers, dict) else None
    return {
        "frame_number": frame_number,
        "source_mac": _first_field(eth_layer, "eth.src"),
        "dest_mac": _first_field(eth_layer, "eth.dst"),
        "ethercat_path_role": "unknown",
        "datagrams": [
            _datagram_evidence(frame_number, sequence, datagram)
            for sequence, datagram in enumerate(
                _iter_datagram_objects(ecat_layer), start=1
            )
        ],
    }


def _as_integer(value: Any) -> Any:
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


def _matches_sdo_object(
    datagram: Dict[str, object], index: int, subindex: Any
) -> bool:
    coe = datagram.get("coe")
    if not isinstance(coe, dict):
        return False
    if _as_integer(coe.get("index")) != index:
        return False
    return subindex is None or _as_integer(coe.get("subindex")) == subindex


def _build_json_query_command(capture_path: Path, display_filter: str) -> List[str]:
    command = _tshark_command_prefix(capture_path)
    command.extend(
        ["-Y", display_filter, "-T", "json", "-J", JSON_LAYER_SELECTOR]
    )
    return command


def _build_sdo_display_filter(
    index: int, subindex: Any, frame_start: Any, frame_end: Any
) -> str:
    clauses = [f"ecat_mailbox.coe.sdoidx == 0x{index:04x}"]
    if subindex is not None:
        clauses.append(f"ecat_mailbox.coe.sdosub == 0x{subindex:02x}")
    if frame_start is not None:
        clauses.append(f"frame.number >= {frame_start}")
    if frame_end is not None:
        clauses.append(f"frame.number <= {frame_end}")
    return " && ".join(clauses)


def query_frames(capture: str, frame_numbers: List[int]) -> Dict[str, object]:
    """Return compact EtherCAT datagram evidence for a bounded frame batch."""
    arguments = validate_query_frames_arguments(
        {"capture": capture, "frame_numbers": frame_numbers}
    )
    capture_name = str(arguments["capture"])
    requested_frames = list(arguments["frame_numbers"])
    capture_path = resolve_capture_path(capture_name)
    display_filter = "frame.number in {" + ",".join(
        str(frame) for frame in requested_frames
    ) + "}"
    packets = _parse_tshark_json(
        _run_tshark(_build_json_query_command(capture_path, display_filter))
    )

    compact_by_frame = {}
    for packet in packets:
        compact = _compact_packet(packet)
        compact_by_frame[compact["frame_number"]] = compact
    returned_frames = [frame for frame in requested_frames if frame in compact_by_frame]
    frames = [compact_by_frame[frame] for frame in returned_frames]
    _classify_ethercat_path_roles(frames)
    return {
        "capture": capture_name,
        "requested_frames": requested_frames,
        "returned_frames": returned_frames,
        "missing_frames": [
            frame for frame in requested_frames if frame not in compact_by_frame
        ],
        "frames": frames,
    }


def query_sdo_object(
    capture: str,
    index: int,
    subindex: Any,
    frame_start: Any,
    frame_end: Any,
) -> Dict[str, object]:
    """Return only datagrams containing the requested SDO object."""
    arguments = validate_query_sdo_object_arguments(
        {
            "capture": capture,
            "index": index,
            "subindex": subindex,
            "frame_start": frame_start,
            "frame_end": frame_end,
        }
    )
    capture_name = str(arguments["capture"])
    object_index = int(arguments["index"])
    object_subindex = arguments["subindex"]
    frame_start_value = arguments["frame_start"]
    frame_end_value = arguments["frame_end"]
    display_filter = _build_sdo_display_filter(
        object_index, object_subindex, frame_start_value, frame_end_value
    )
    capture_path = resolve_capture_path(capture_name)
    packets = _parse_tshark_json(
        _run_tshark(_build_json_query_command(capture_path, display_filter))
    )

    frames = []
    for packet in packets:
        compact = _compact_packet(packet)
        matching_datagrams = [
            datagram
            for datagram in compact["datagrams"]
            if _matches_sdo_object(datagram, object_index, object_subindex)
        ]
        if matching_datagrams:
            frames.append(
                {
                    "frame_number": compact["frame_number"],
                    "source_mac": compact["source_mac"],
                    "dest_mac": compact["dest_mac"],
                    "ethercat_path_role": "unknown",
                    "datagrams": matching_datagrams,
                }
            )
    _classify_ethercat_path_roles(frames)
    return {
        "capture": capture_name,
        "index": object_index,
        "subindex": object_subindex,
        "frame_start": frame_start_value,
        "frame_end": frame_end_value,
        "returned_frames": [frame["frame_number"] for frame in frames],
        "frames": frames,
    }


def _tshark_command_prefix(capture_path: Path) -> List[str]:
    executable = str(TSHARK_EXECUTABLE).strip()
    if not executable:
        raise FileNotFoundError("TShark executable not found: not configured")
    return [executable, "-r", str(capture_path)]


def _run_tshark(command: List[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TSHARK_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"TShark executable not found: {TSHARK_EXECUTABLE}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("TShark command timed out") from exc

    if completed.returncode != 0:
        stderr = str(completed.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"TShark command failed with exit code {completed.returncode}{detail}"
        )
    return str(completed.stdout or "")


def _parse_field_rows(stdout: str, fields: List[str], limit: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    reader = csv.reader(
        io.StringIO(stdout),
        delimiter="\t",
        quotechar='"',
        strict=True,
    )
    try:
        for values in reader:
            if not values or all(value == "" for value in values):
                continue
            if len(values) > len(fields):
                raise ValueError("TShark field output has more columns than requested")
            values.extend([""] * (len(fields) - len(values)))
            rows.append(dict(zip(fields, values)))
            if len(rows) == limit:
                break
    except csv.Error as exc:
        raise ValueError(f"Malformed TShark field output: {exc}") from exc
    return rows


def query_capture(
    capture: str,
    display_filter: str,
    fields: List[str],
    limit: int = DEFAULT_QUERY_LIMIT,
) -> Dict[str, object]:
    """Run a bounded raw TShark field query without semantic datagram pairing."""
    arguments = validate_query_capture_arguments(
        {
            "capture": capture,
            "display_filter": display_filter,
            "fields": fields,
            "limit": limit,
        }
    )
    capture_name = str(arguments["capture"])
    capture_path = resolve_capture_path(capture_name)
    requested_fields = list(arguments["fields"])
    command = _tshark_command_prefix(capture_path)
    command.extend(
        [
            "-Y",
            str(arguments["display_filter"]),
            "-T",
            "fields",
            "-E",
            "header=n",
            "-E",
            "separator=\t",
            "-E",
            "quote=d",
            "-E",
            "occurrence=a",
            "-E",
            "aggregator=,",
        ]
    )
    for field in requested_fields:
        command.extend(["-e", field])

    rows = _parse_field_rows(
        _run_tshark(command),
        requested_fields,
        int(arguments["limit"]),
    )
    return {
        "capture": capture_name,
        "display_filter": arguments["display_filter"],
        "fields": requested_fields,
        "matches": rows,
        "association": "frame-level raw fields; no EtherCAT datagram pairing",
    }


def export_frame_json(capture: str, frame_number: int) -> Dict[str, object]:
    """Export one canonical TShark protocol-tree packet for one frame."""
    arguments = validate_export_frame_arguments(
        {"capture": capture, "frame_number": frame_number}
    )
    capture_name = str(arguments["capture"])
    frame_value = int(arguments["frame_number"])
    capture_path = resolve_capture_path(capture_name)
    command = _tshark_command_prefix(capture_path)
    command.extend(
        [
            "-Y",
            f"frame.number == {frame_value}",
            "-T",
            "json",
            "-J",
            "frame eth ecat ecat_mailbox",
        ]
    )

    stdout = _run_tshark(command)
    try:
        packets = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed TShark JSON output: {exc}") from exc

    if not isinstance(packets, list):
        raise ValueError("TShark JSON output must be a top-level packet array")
    if not packets:
        raise LookupError(f"Frame {frame_value} was not found in {capture_name}")
    if len(packets) != 1:
        raise RuntimeError(
            f"Expected exactly one packet for frame {frame_value}, found {len(packets)}"
        )
    if not isinstance(packets[0], dict):
        raise ValueError("TShark JSON packet must be an object")

    return {
        "capture": capture_name,
        "frame_number": frame_value,
        "packet": packets[0],
    }

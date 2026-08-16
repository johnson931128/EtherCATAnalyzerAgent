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
TSHARK_TIMEOUT_SECONDS = 60

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
            f"Capture not found: {normalized}; expected under captures/"
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

import json
import re

from capture import derive_stage3_result
from config import CAPTURE_PATH
from state import AgentState


_VALUE = r"(?:0[xX][0-9a-fA-F]+|[0-9]+)"
_SLAVE_LINE = re.compile(
    rf"Position\s*:\s*(?P<position>{_VALUE})\s*,\s*"
    rf"Initial\s+ADP\s*:\s*(?P<initial_adp>{_VALUE})\s*,\s*"
    rf"Configured\s+Address\s*:\s*(?P<configured_address>{_VALUE})\s*,\s*"
    rf"Vendor\s+ID\s*:\s*(?P<vendor_id>{_VALUE})\s*,\s*"
    rf"Product\s+Code\s*:\s*(?P<product_code>{_VALUE})",
    re.IGNORECASE,
)
_SLAVE_COUNT = re.compile(
    rf"^\s*Slave\s+count\s*:\s*(?P<count>{_VALUE})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_value(value):
    if value.lower().startswith("0x"):
        return int(value, 16)

    return int(value, 10)


def is_result_check_task(task):
    normalized = task.casefold()
    has_stage3 = "stage 3" in normalized or "stage3" in normalized
    has_slave_discovery = "slave discovery" in normalized
    has_check_intent = any(
        marker in normalized
        for marker in ("check", "檢查", "检查", "確認", "验证", "驗證")
    )

    return has_check_intent and (has_stage3 or has_slave_discovery)


def parse_stage3_console_output(task):
    count_match = _SLAVE_COUNT.search(task)
    slave_count = (
        _parse_value(count_match.group("count"))
        if count_match
        else None
    )
    slaves = []

    for line in task.splitlines():
        match = _SLAVE_LINE.search(line)

        if match is None:
            continue

        slaves.append({
            field: _parse_value(match.group(field))
            for field in (
                "position",
                "initial_adp",
                "configured_address",
                "vendor_id",
                "product_code",
            )
        })

    return {
        "slave_count": slave_count,
        "slaves": slaves,
    }


def _format_value(field, value):
    if value is None:
        return "<missing>"

    if field in {"initial_adp", "configured_address"}:
        return f"0x{value:04X}"

    if field in {"vendor_id", "product_code"}:
        return f"0x{value:08X}"

    return str(value)


def _comparison_line(label, field, expected, actual):
    status = "PASS" if expected == actual else "FAIL"
    lines = [f"- {label}: {status}"]

    if status == "FAIL":
        lines.append(f"  Expected: {_format_value(field, expected)}")
        lines.append(f"  Actual: {_format_value(field, actual)}")

    return lines


def _format_evidence_value(field, value):
    if value is None:
        return "<missing>"

    if isinstance(value, int):
        if field in {"EepromWordAddress", "Ado"}:
            return f"0x{value:04X}"

        if field in {"EepromData", "OutgoingAdp"}:
            return f"0x{value:08X}"

    return str(value)


def _append_evidence(lines, label, evidence, fields):
    lines.append(f"- {label}")

    if evidence is None:
        lines.append("  - Evidence: <missing>")
        return

    for field in fields:
        lines.append(
            f"  - {field}: {_format_evidence_value(field, evidence.get(field))}"
        )


def _format_slave_values(lines, slaves):
    for index, slave in enumerate(slaves):
        lines.extend(["", f"Slave {index + 1}"])

        for label, field in (
            ("Topology Position", "position"),
            ("Initial ADP", "initial_adp"),
            ("Configured Address", "configured_address"),
            ("Vendor ID", "vendor_id"),
            ("Product Code", "product_code"),
        ):
            lines.append(
                f"- {label}: {_format_value(field, slave.get(field))}"
            )


def format_actual_result(parsed):
    lines = [f"- Slave count: {_format_value('slave_count', parsed['slave_count'])}"]
    _format_slave_values(lines, parsed["slaves"])
    return "\n".join(lines)


def format_capture_evidence(expected_slaves):
    lines = [f"Source: {CAPTURE_PATH}"]

    for index, slave in enumerate(expected_slaves):
        evidence = slave.get("evidence", {})
        lines.extend(["", f"Slave {index + 1}"])
        topology_evidence = evidence.get("topology")
        _append_evidence(
            lines,
            "TopologyPosition",
            topology_evidence,
            (
                "OutgoingFrame",
                "OutgoingAdp",
                "Ado",
                "CalculatedTopologyPosition",
            ),
        )
        _append_evidence(
            lines,
            "InitialAutoIncrementAddress",
            topology_evidence,
            ("OutgoingFrame", "OutgoingAdp"),
        )
        _append_evidence(
            lines,
            "ConfiguredStationAddress",
            evidence.get("configured_address"),
            (
                "OutgoingFrame",
                "ReturningFrame",
                "Ado",
                "ConfiguredStationAddressData",
                "WorkingCounterDelta",
            ),
        )
        _append_evidence(
            lines,
            "VendorId",
            evidence.get("vendor_id"),
            (
                "ControlOutgoingFrame",
                "ControlReturningFrame",
                "DataOutgoingFrame",
                "DataReturningFrame",
                "EepromWordAddress",
                "EepromData",
                "CalculatedTopologyPosition",
                "WorkingCounterDelta",
            ),
        )
        _append_evidence(
            lines,
            "ProductCode",
            evidence.get("product_code"),
            (
                "ControlOutgoingFrame",
                "ControlReturningFrame",
                "DataOutgoingFrame",
                "DataReturningFrame",
                "EepromWordAddress",
                "EepromData",
                "CalculatedTopologyPosition",
                "WorkingCounterDelta",
            ),
        )

    return "\n".join(lines)


def format_expected_result(expected_slaves):
    lines = [f"- Slave count: {len(expected_slaves)}"]
    _format_slave_values(lines, expected_slaves)
    return "\n".join(lines)


def format_verification_result(task, expected_slaves):
    actual_result = parse_stage3_console_output(task)
    actual_slaves = actual_result["slaves"]
    expected_count = len(expected_slaves)
    count_passed = actual_result["slave_count"] == expected_count
    all_passed = count_passed and len(actual_slaves) == expected_count
    lines = [
        f"Stage 3 Result Check: {'PASS' if all_passed else 'FAIL'}",
        "",
        f"Slave count: {'PASS' if count_passed else 'FAIL'}",
    ]

    if not count_passed:
        lines.append(f"Expected: {expected_count}")
        lines.append(
            f"Actual: {_format_value('slave_count', actual_result['slave_count'])}"
        )

    for index in range(max(len(expected_slaves), len(actual_slaves))):
        expected = expected_slaves[index] if index < len(expected_slaves) else None
        actual = actual_slaves[index] if index < len(actual_slaves) else None
        lines.extend(["", f"Slave {index + 1}"])

        for label, field in (
            ("Topology Position", "position"),
            ("Initial ADP", "initial_adp"),
            ("Configured Address", "configured_address"),
            ("Vendor ID", "vendor_id"),
            ("Product Code", "product_code"),
        ):
            expected_value = expected[field] if expected is not None else None
            actual_value = actual[field] if actual is not None else None
            lines.extend(
                _comparison_line(label, field, expected_value, actual_value)
            )

            if expected_value != actual_value:
                all_passed = False

    lines[0] = f"Stage 3 Result Check: {'PASS' if all_passed else 'FAIL'}"
    return "\n".join(lines)


def check_stage3_result(task, expected_slaves):
    parsed = parse_stage3_console_output(task)

    return "\n\n".join(
        (
            "### Actual Result\n" + format_actual_result(parsed),
            "### Capture Evidence\n" + format_capture_evidence(expected_slaves),
            "### Reconstructed Expected Result\n"
            + format_expected_result(expected_slaves),
            "### Verification Result\n"
            + format_verification_result(task, expected_slaves),
        )
    )


def result_check(state: AgentState):
    parsed = parse_stage3_console_output(state["task"])

    if parsed["slave_count"] is None or not parsed["slaves"]:
        return {
            "result": (
                "Stage 3 Result Check: FAIL\n\n"
                "Could not parse Slave count and Slave Discovery report lines."
            ),
            "capture_mode": "result_check",
        }

    records = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
    expected_slaves = derive_stage3_result(records)

    return {
        "result": check_stage3_result(state["task"], expected_slaves),
        "capture_mode": "result_check",
        "capture_evidence": json.dumps(
            expected_slaves,
            ensure_ascii=False,
            indent=2,
        ),
    }

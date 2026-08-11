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


def check_stage3_result(task, expected_slaves):
    actual_result = parse_stage3_console_output(task)
    actual_slaves = actual_result["slaves"]
    expected_count = len(expected_slaves)
    count_passed = actual_result["slave_count"] == expected_count
    all_passed = count_passed and len(actual_slaves) == expected_count
    lines = [f"Stage 3 Result Check: {'PASS' if all_passed else 'FAIL'}", ""]
    lines.append(f"Slave count: {'PASS' if count_passed else 'FAIL'}")

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

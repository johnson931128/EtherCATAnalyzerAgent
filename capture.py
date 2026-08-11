import json

from config import CAPTURE_PATH
from state import AgentState


def parse_number(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()

    if text.lower().startswith("0x"):
        return int(text, 16)

    return int(text)


def calculate_topology_position(initial_adp):
    distance_from_zero = (-initial_adp) & 0xFFFF
    return distance_from_zero + 1


def auto_increment_pair_key(record):
    return (
        parse_number(record.get("DatagramSequence")),
        parse_number(record.get("CommandCode")),
        parse_number(record.get("ProtocolIndex")),
        parse_number(record.get("Ado")),
        parse_number(record.get("DataLength")),
    )


def build_auto_increment_pairs(records):
    auto_increment_command_codes = {0x01, 0x02, 0x03, 0x0D}
    records_by_time = {}

    for record in records:
        command_code = parse_number(record.get("CommandCode"))

        if command_code not in auto_increment_command_codes:
            continue

        time_utc = record.get("TimeUtc")
        records_by_time.setdefault(time_utc, []).append(record)

    timestamp_groups = sorted(
        records_by_time.values(),
        key=lambda group: min(record["FrameNumber"] for record in group)
    )

    pairs = []

    for timestamp_group in timestamp_groups:
        records_by_frame = {}

        for record in timestamp_group:
            frame_number = record.get("FrameNumber")
            records_by_frame.setdefault(frame_number, []).append(record)

        frame_groups = [
            records_by_frame[frame_number]
            for frame_number in sorted(records_by_frame)
        ]

        if len(frame_groups) != 2:
            continue

        outgoing_frame = sorted(
            frame_groups[0],
            key=lambda record: record.get("DatagramSequence")
        )
        returning_frame = sorted(
            frame_groups[1],
            key=lambda record: record.get("DatagramSequence")
        )

        if not outgoing_frame or not returning_frame:
            continue

        outgoing_source = outgoing_frame[0].get("SourceMac") or ""
        returning_source = returning_frame[0].get("SourceMac") or ""

        if outgoing_source.casefold() == returning_source.casefold():
            continue

        returning_by_key = {}

        for record in returning_frame:
            key = auto_increment_pair_key(record)
            returning_by_key.setdefault(key, record)

        for outgoing in outgoing_frame:
            returning = returning_by_key.get(auto_increment_pair_key(outgoing))

            if returning is None:
                continue

            pairs.append({
                "Outgoing": outgoing,
                "Returning": returning,
            })

    return pairs


def build_pair_evidence(pair):
    outgoing = pair["Outgoing"]
    returning = pair["Returning"]
    outgoing_adp = parse_number(outgoing.get("Adp"))
    outgoing_working_counter = parse_number(outgoing.get("WorkingCounter"))
    returning_working_counter = parse_number(returning.get("WorkingCounter"))

    evidence = {
        "OutgoingFrame": outgoing.get("FrameNumber"),
        "ReturningFrame": returning.get("FrameNumber"),
        "DatagramSequence": outgoing.get("DatagramSequence"),
        "CommandCode": outgoing.get("CommandCode"),
        "OutgoingAdp": outgoing.get("Adp"),
        "ReturningAdp": returning.get("Adp"),
        "Ado": outgoing.get("Ado"),
        "OutgoingWorkingCounter": outgoing_working_counter,
        "ReturningWorkingCounter": returning_working_counter,
        "WorkingCounterDelta": (
            returning_working_counter - outgoing_working_counter
        ),
    }

    if outgoing_adp is not None:
        evidence["CalculatedTopologyPosition"] = (
            calculate_topology_position(outgoing_adp)
        )

    return evidence


def select_capture_mode(state: AgentState):
    task = state["task"].lower()

    eeprom_keywords = [
        "bindeepromidentity",
        "eeprom",
        "vendor id",
        "vendorid",
        "product code",
        "productcode",
    ]

    topology_keywords = [
        "calculatetopologyposition",
        "topology position",
        "topology",
        "拓撲位置",
        "拓樸位置",
    ]

    if any(keyword in task for keyword in eeprom_keywords):
        return {"capture_mode": "eeprom_identity"}

    if any(keyword in task for keyword in topology_keywords):
        return {"capture_mode": "topology_position"}

    return {"capture_mode": "none"}


def query_topology_capture(pairs):
    matches = []

    for pair in pairs:
        outgoing = pair["Outgoing"]
        command_code = parse_number(outgoing.get("CommandCode"))
        ado = parse_number(outgoing.get("Ado"))

        if command_code != 0x02:
            continue

        if ado != 0x0010:
            continue

        if parse_number(outgoing.get("Adp")) is None:
            continue

        evidence = build_pair_evidence(pair)
        evidence["ConfiguredStationAddressData"] = (
            outgoing.get("RegisterDataHex") or outgoing.get("DataHex")
        )
        matches.append(evidence)

    return matches[:20]


def query_eeprom_capture(pairs):
    matches = []

    for pair in pairs:
        outgoing = pair["Outgoing"]
        returning = pair["Returning"]
        command_code = parse_number(outgoing.get("CommandCode"))
        ado = parse_number(outgoing.get("Ado"))

        is_eeprom_control = command_code == 0x02 and ado == 0x0502
        is_eeprom_data = command_code == 0x01 and ado == 0x0508

        if not is_eeprom_control and not is_eeprom_data:
            continue

        if parse_number(outgoing.get("Adp")) is None:
            continue

        evidence = build_pair_evidence(pair)
        evidence["EepromControlStatus"] = outgoing.get("EepromControlStatus")
        evidence["EepromWordAddress"] = outgoing.get("EepromWordAddress")
        evidence["EepromData"] = returning.get("EepromData")
        matches.append(evidence)

    return matches[:40]


def query_capture(state: AgentState):
    records = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
    pairs = build_auto_increment_pairs(records)

    if state["capture_mode"] == "topology_position":
        matches = query_topology_capture(pairs)

    elif state["capture_mode"] == "eeprom_identity":
        matches = query_eeprom_capture(pairs)

    else:
        return {
            "capture_evidence": "No capture query was selected for this task."
        }

    capture_evidence = json.dumps(
        matches,
        ensure_ascii=False,
        indent=2
    )

    return {"capture_evidence": capture_evidence}

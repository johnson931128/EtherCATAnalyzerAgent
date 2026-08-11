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


def parse_hex_number(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()

    if text.lower().startswith("0x"):
        text = text[2:]

    return int(text, 16)


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


def derive_stage3_result(records):
    """Derive the Slave Discovery result from paired capture evidence."""
    pairs = build_auto_increment_pairs(records)
    slaves_by_position = {}

    for pair in pairs:
        outgoing = pair["Outgoing"]
        returning = pair["Returning"]
        evidence = build_pair_evidence(pair)

        if (
            outgoing is None
            or returning is None
            or parse_number(outgoing.get("Adp")) is None
            or evidence["ReturningWorkingCounter"] == 0
        ):
            continue

        initial_adp = parse_number(outgoing.get("Adp"))
        topology_position = evidence["CalculatedTopologyPosition"]

        if topology_position not in slaves_by_position:
            slaves_by_position[topology_position] = {
                "position": topology_position,
                "initial_adp": initial_adp,
                "configured_address": None,
                "vendor_id": None,
                "product_code": None,
            }

    for pair in pairs:
        outgoing = pair["Outgoing"]
        returning = pair["Returning"]

        if (
            outgoing is None
            or returning is None
            or parse_number(outgoing.get("Adp")) is None
            or parse_number(outgoing.get("Ado")) != 0x0010
            or parse_number(outgoing.get("CommandCode")) != 0x02
            or parse_number(outgoing.get("DataLength")) != 2
            or (
                parse_number(returning.get("WorkingCounter"))
                - parse_number(outgoing.get("WorkingCounter"))
                != 1
            )
        ):
            continue

        configured_address = outgoing.get("RegisterDataHex")
        if configured_address is None:
            configured_address = outgoing.get("DataHex")

        if configured_address is None:
            continue

        try:
            configured_address = parse_hex_number(configured_address)
        except (TypeError, ValueError):
            continue

        topology_position = calculate_topology_position(
            parse_number(outgoing.get("Adp"))
        )
        slave = slaves_by_position.get(topology_position)

        if slave is not None:
            slave["configured_address"] = configured_address

    pending_eeprom_reads = {}

    for pair in pairs:
        outgoing = pair["Outgoing"]
        returning = pair["Returning"]

        if outgoing is None or parse_number(outgoing.get("Adp")) is None:
            continue

        topology_position = calculate_topology_position(
            parse_number(outgoing.get("Adp"))
        )
        command_code = parse_number(outgoing.get("CommandCode"))
        ado = parse_number(outgoing.get("Ado"))

        if command_code == 0x02 and ado == 0x0502:
            control_status = parse_number(outgoing.get("EepromControlStatus"))
            word_address = parse_number(outgoing.get("EepromWordAddress"))

            if control_status is None or word_address is None:
                continue

            if control_status & 0x0700 != 0x0100:
                continue

            if (
                parse_number(returning.get("WorkingCounter"))
                == parse_number(outgoing.get("WorkingCounter")) + 1
            ):
                pending_eeprom_reads[topology_position] = word_address

            continue

        if (
            command_code != 0x01
            or ado != 0x0508
            or parse_number(returning.get("EepromData")) is None
            or parse_number(returning.get("WorkingCounter"))
            != parse_number(outgoing.get("WorkingCounter")) + 1
        ):
            continue

        word_address = pending_eeprom_reads.get(topology_position)
        slave = slaves_by_position.get(topology_position)

        if word_address is None or slave is None:
            continue

        eeprom_data = parse_number(returning.get("EepromData"))

        if word_address == 0x0008:
            slave["vendor_id"] = eeprom_data
        elif word_address == 0x000A:
            slave["product_code"] = eeprom_data

        pending_eeprom_reads.pop(topology_position, None)

    return [
        slaves_by_position[position]
        for position in sorted(slaves_by_position)
    ]


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

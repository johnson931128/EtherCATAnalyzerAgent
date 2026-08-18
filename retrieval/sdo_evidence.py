"""Deterministic semantic fields for one EtherCAT SDO datagram."""

from typing import Any, Dict, List, Optional, TypedDict


class SdoEvidenceRecord(TypedDict, total=False):
    """A JSON-serializable record whose protocol fields share one datagram."""

    frame_number: Any
    datagram_sequence: Any
    source_mac: Any
    dest_mac: Any
    ethercat_path_role: str
    semantic_role: str
    cmd: Any
    cmd_name: Any
    idx: Any
    adp: Any
    ado: Any
    data_length: Any
    wkc: Any
    mailbox_type: Any
    mailbox_counter: Any
    coe_type: Any
    sdo_request: Any
    sdo_response: Any
    index: Any
    subindex: Any
    data: Any
    abort_code: Any


class RequestExchange(TypedDict, total=False):
    outgoing: SdoEvidenceRecord
    returning: Optional[SdoEvidenceRecord]
    pairing_status: str
    unpaired: List[SdoEvidenceRecord]


class SdoTransactionEvidence(TypedDict, total=False):
    transaction_number: int
    index: Any
    subindex: Any
    written_data: Any
    request_exchange: RequestExchange
    request_outgoing: SdoEvidenceRecord
    request_returning: Optional[SdoEvidenceRecord]
    response: Optional[SdoEvidenceRecord]
    abort: Optional[SdoEvidenceRecord]
    completion_role: Optional[str]
    pairing_status: str
    unpaired: List[SdoEvidenceRecord]


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def semantic_role(frame: Dict[str, object], datagram: Dict[str, object]) -> str:
    """Classify CoE meaning after retaining the datagram's path role."""
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    if _present(coe.get("abort_code")):
        return "abort"
    if _present(coe.get("sdo_request")):
        path_role = frame.get("ethercat_path_role")
        if path_role == "outgoing":
            return "request_outgoing"
        if path_role == "returning":
            return "request_returning"
        return "unknown"
    if _present(coe.get("sdo_response")):
        return "response"
    return "unknown"


def normalize_datagram(
    frame: Dict[str, object], datagram: Dict[str, object]
) -> SdoEvidenceRecord:
    """Normalize one compact datagram without combining it with another."""
    coe = datagram.get("coe")
    coe = coe if isinstance(coe, dict) else {}
    mailbox = datagram.get("mailbox")
    mailbox = mailbox if isinstance(mailbox, dict) else {}
    return {
        "frame_number": frame.get("frame_number"),
        "datagram_sequence": datagram.get("datagram_sequence"),
        "source_mac": frame.get("source_mac"),
        "dest_mac": frame.get("dest_mac"),
        "ethercat_path_role": frame.get("ethercat_path_role", "unknown"),
        "semantic_role": semantic_role(frame, datagram),
        "cmd": datagram.get("cmd"),
        "cmd_name": datagram.get("cmd_name"),
        "idx": datagram.get("idx"),
        "adp": datagram.get("adp"),
        "ado": datagram.get("ado"),
        "data_length": datagram.get("data_length"),
        "wkc": datagram.get("wkc"),
        "mailbox_type": mailbox.get("type"),
        "mailbox_counter": mailbox.get("counter"),
        "coe_type": coe.get("type"),
        "sdo_request": coe.get("sdo_request"),
        "sdo_response": coe.get("sdo_response"),
        "index": coe.get("index"),
        "subindex": coe.get("subindex"),
        "data": coe.get("data"),
        "abort_code": coe.get("abort_code"),
    }


def _position(record: SdoEvidenceRecord):
    frame_number = record.get("frame_number")
    datagram_sequence = record.get("datagram_sequence")
    return (
        frame_number if type(frame_number) is int else float("inf"),
        datagram_sequence if type(datagram_sequence) is int else float("inf"),
    )


def _present_record_value(record: SdoEvidenceRecord, field: str) -> bool:
    return _present(record.get(field))


def _canonical(value: Any) -> Any:
    if type(value) is int:
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 0)
        except ValueError:
            try:
                return int(text, 10)
            except ValueError:
                return text.casefold()
    return value


def _same_value(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _same_request_exchange_copy(
    outgoing: SdoEvidenceRecord, returning: SdoEvidenceRecord
) -> bool:
    """Match two path copies without using WKC or frame adjacency alone."""
    required_fields = (
        "cmd_name",
        "adp",
        "ado",
        "sdo_request",
        "index",
        "subindex",
    )
    if any(
        not _present_record_value(outgoing, field)
        or not _present_record_value(returning, field)
        or not _same_value(outgoing.get(field), returning.get(field))
        for field in required_fields
    ):
        return False

    optional_fields = ("idx", "mailbox_type", "coe_type", "data")
    for field in optional_fields:
        left = outgoing.get(field)
        right = returning.get(field)
        if _present(left) and _present(right) and not _same_value(left, right):
            return False

    left_counter = outgoing.get("mailbox_counter")
    right_counter = returning.get("mailbox_counter")
    if _present(left_counter) and _present(right_counter):
        return _same_value(left_counter, right_counter)
    return True


def group_request_exchanges(
    records: List[SdoEvidenceRecord],
) -> tuple[List[RequestExchange], set[int]]:
    """Group EtherCAT outgoing/returning copies, independently of CoE completion."""
    ordered = sorted(records, key=_position)
    outgoing_records = [
        record for record in ordered if record.get("semantic_role") == "request_outgoing"
    ]
    exchanges: List[RequestExchange] = []
    used_returning: set[int] = set()

    for number, outgoing in enumerate(outgoing_records):
        next_outgoing = (
            _position(outgoing_records[number + 1])
            if number + 1 < len(outgoing_records)
            else None
        )
        candidates = [
            record
            for record in ordered
            if record.get("semantic_role") == "request_returning"
            and id(record) not in used_returning
            and _position(record) > _position(outgoing)
            and (next_outgoing is None or _position(record) < next_outgoing)
            and _same_request_exchange_copy(outgoing, record)
        ]
        exchange: RequestExchange = {
            "outgoing": outgoing,
            "returning": None,
            "pairing_status": "unpaired",
        }
        if len(candidates) == 1:
            exchange["returning"] = candidates[0]
            exchange["pairing_status"] = "grouped"
            used_returning.add(id(candidates[0]))
        elif len(candidates) > 1:
            exchange["pairing_status"] = "ambiguous"
            exchange["unpaired"] = candidates
        exchanges.append(exchange)
    return exchanges, used_returning


def _same_transaction_key(
    request: SdoEvidenceRecord, completion: SdoEvidenceRecord
) -> bool:
    required_fields = ("adp", "index", "subindex")
    return all(
        _present_record_value(request, field)
        and _present_record_value(completion, field)
        and _same_value(request.get(field), completion.get(field))
        for field in required_fields
    )


def _compatible_completion(
    request: SdoEvidenceRecord, completion: SdoEvidenceRecord
) -> bool:
    # CoE request/response semantic roles are already classified independently.
    # The authoritative DLL matcher uses only ADP/index/subindex here; CoE type
    # remains retained evidence, not an additional transaction-key constraint.
    return _same_transaction_key(request, completion)


def _pairing_status(
    exchange: RequestExchange,
    completion: Optional[SdoEvidenceRecord],
) -> str:
    if exchange.get("pairing_status") == "ambiguous":
        return "ambiguous"
    if exchange.get("returning") is not None and completion is not None:
        return "grouped"
    return "unpaired"


def group_sdo_transactions(
    records: List[SdoEvidenceRecord], index: Any, subindex: Any
) -> List[SdoTransactionEvidence]:
    """Match request exchanges to CoE response/abort evidence in capture order."""
    ordered = sorted(records, key=_position)
    exchanges, used_returning = group_request_exchanges(ordered)
    exchange_by_outgoing = {
        id(exchange["outgoing"]): exchange for exchange in exchanges
    }
    transactions: List[SdoTransactionEvidence] = []
    pending: List[SdoTransactionEvidence] = []

    for record in ordered:
        role = record.get("semantic_role")
        if role == "request_outgoing":
            exchange = exchange_by_outgoing[id(record)]
            transaction: SdoTransactionEvidence = {
                "transaction_number": len(transactions) + 1,
                "index": index,
                "subindex": subindex,
                "written_data": record.get("data"),
                "request_exchange": exchange,
                "request_outgoing": record,
                "request_returning": exchange.get("returning"),
                "response": None,
                "abort": None,
                "completion_role": None,
                "pairing_status": "unpaired",
            }
            transactions.append(transaction)
            pending.append(transaction)
            continue

        if role not in {"response", "abort"}:
            continue

        candidates = [
            transaction
            for transaction in pending
            if _compatible_completion(transaction["request_outgoing"], record)
        ]
        if not candidates:
            transactions.append(
                {
                    "transaction_number": len(transactions) + 1,
                    "index": index,
                    "subindex": subindex,
                    "written_data": None,
                    "request_exchange": {
                        "pairing_status": "unpaired",
                    },
                    "response": record if role == "response" else None,
                    "abort": record if role == "abort" else None,
                    "completion_role": role,
                    "pairing_status": "unpaired",
                    "unpaired": [record],
                }
            )
            continue

        # This is deliberate DLL-compatible FIFO matching: matching is based on
        # ADP/index/subindex and capture order, never mailbox-counter equality.
        transaction = candidates[0]
        pending.remove(transaction)
        if role == "response":
            transaction["response"] = record
        else:
            transaction["abort"] = record
        transaction["completion_role"] = role
        transaction["pairing_status"] = _pairing_status(
            transaction["request_exchange"], record
        )

    for transaction in transactions:
        if transaction.get("completion_role") is None:
            transaction["pairing_status"] = _pairing_status(
                transaction["request_exchange"], None
            )

    for record in ordered:
        if record.get("semantic_role") != "request_returning":
            continue
        if id(record) in used_returning:
            continue
        if any(
            record in transaction.get("request_exchange", {}).get("unpaired", [])
            for transaction in transactions
        ):
            continue
        transactions.append(
            {
                "transaction_number": len(transactions) + 1,
                "index": index,
                "subindex": subindex,
                "written_data": None,
                "request_exchange": {
                    "returning": record,
                    "pairing_status": "unpaired",
                },
                "request_outgoing": None,
                "request_returning": record,
                "response": None,
                "abort": None,
                "completion_role": None,
                "pairing_status": "unpaired",
                "unpaired": [record],
            }
        )
    return transactions

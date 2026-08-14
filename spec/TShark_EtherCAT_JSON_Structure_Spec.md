# TShark EtherCAT JSON Structure Specification

## 1. Purpose

本規格定義 `EtherCATAnalyzer` 使用 TShark 將 EtherCAT capture 轉換成 JSON 後，Agent / Analyzer 應如何辨識：

- Packet
- EtherCAT layer
- 單一 EtherCAT Datagram
- Datagram Header
- Working Counter
- EtherCAT Mailbox
- CoE SDO 欄位

本規格的主要目的，是避免 Parser 依靠錯誤的遞迴推測方式辨識 Datagram，並建立可供 `raw_capture.py`、`EtherCatDatagramExtractor.cs` 與後續 Agent Capture Retrieval 共用的結構契約。

---

## 2. Authority and Scope

本規格同時依據：

1. Wireshark / TShark 官方文件。
2. Wireshark EtherCAT dissector 官方 Display Filter Reference。
3. Wireshark EtherCAT protocol tree 官方範例。
4. EtherCATAnalyzer 專案目前使用的 TShark command。
5. 專案目前實際觀察到的 `output.json` 結構。

本規格描述的是 **TShark `-T json` 解碼輸出結構**，不是 EtherCAT wire-format specification。

EtherCAT protocol semantics 仍應由 ET1100 / EtherCAT specification 等權威來源決定。

---

## 3. Current TShark Export Contract

目前 `EtherCATAnalyzer` 的 Stage 1 使用等價於：

```text
tshark -r "<pcap>" -Y "<display-filter>" -T json -J "frame eth ecat ecat_mailbox"
```

其中目前 display filter 至少包含：

```text
ecat
```

### TSHARK-001 JSON output mode

TShark SHALL 使用：

```text
-T json
```

輸出 decoded packet details。

`output.json` 的 root SHALL 視為 packet array。

概念結構：

```json
[
  {
    "_source": {
      "layers": {
        "frame": {},
        "eth": {},
        "ecat": {}
      }
    }
  }
]
```

Wireshark User's Guide 的 JSON export 範例亦使用：

```text
_source
└── layers
    ├── frame
    ├── eth
    └── ...
```

### TSHARK-002 `-J` behavior

目前 command 使用：

```text
-J "frame eth ecat ecat_mailbox"
```

依 TShark manual，`-J` 為 protocol top-level filter：

- 指定 protocol 的 parent node 與所有 child nodes 會包含在輸出。
- lower-level protocol 若需要輸出，必須明確指定。

因此 `ecat_mailbox` 必須保留在 `-J` 清單中，才能將 Mailbox / CoE subtree 作為解析依據。

### TSHARK-003 Do not substitute `-j` semantics

`-j` 與 `-J` 不同。

`-j` 只保留指定 protocol parent node；child nodes 必須另外明確指定。

本專案目前依賴完整 EtherCAT / Mailbox subtree，因此 Parser specification 以 `-J` 輸出為準。

---

## 4. Packet Structure

### JSON-001 Packet root

每一個 packet SHALL 從下列位置取得 protocol layers：

```text
packet["_source"]["layers"]
```

### JSON-002 Frame Number

Frame Number SHALL 從：

```text
_source.layers.frame["frame.number"]
```

取得。

Example:

```json
"frame": {
  "frame.number": "41394"
}
```

Frame Number 屬於 packet-level metadata，不屬於單一 EtherCAT Datagram。

---

## 5. EtherCAT Layer Structure

### ECAT-001 EtherCAT layer

EtherCAT decoded tree SHALL 從：

```text
_source.layers.ecat
```

取得。

一個 EtherCAT frame MAY 包含多個 EtherCAT Datagram。

Wireshark 官方 EtherCAT protocol tree 範例明確顯示：

```text
EtherCAT frame header
EtherCAT datagram(s)
    EtherCAT datagram: ...
        Header
        Data
        Working Cnt
```

因此 Analyzer SHALL NOT 假設：

```text
1 packet == 1 EtherCAT datagram
```

---

## 6. EtherCAT Datagram Identification

### ECAT-010 Canonical Datagram node

在目前 TShark JSON output contract 中，`ecat` layer 底下名稱以下列文字開頭的 object SHALL 視為一個完整 EtherCAT Datagram：

```text
EtherCAT datagram:
```

Conceptual example:

```json
"ecat": {
  "EtherCAT datagram: Cmd: ...": {
    "Header": {
      "...": "..."
    },
    "... datagram payload ...": "...",
    "ecat.cnt": "1"
  }
}
```

### ECAT-011 Datagram identity SHALL be based on the complete node

Parser SHALL 將：

```text
"EtherCAT datagram: ..." -> complete object
```

作為 Datagram boundary。

Parser SHALL NOT 因為在 nested child 中找到：

```text
ecat.cmd
```

就將該 child 判定成完整 Datagram。

### ECAT-012 Reason

`ecat.cmd` 位於 Datagram 的 `Header` subtree。

Mailbox / CoE data 則可位於同一 Datagram 的其他 subtree。

因此以下錯誤 traversal：

```text
recursive search
→ child contains ecat.cmd
→ treat child as datagram
```

可能只取得：

```text
Header
```

而遺失 sibling：

```text
ecat_mailbox
ecat.cnt
```

造成 CoE SDO 搜尋失敗或 WKC 無法取得。

---

## 7. Datagram Header Fields

Wireshark 官方 EtherCAT Display Filter Reference 定義下列 canonical field names。

### ECAT-020 Command

```text
ecat.cmd
```

Type:

```text
Unsigned integer, 8 bits
```

目前 JSON hierarchy：

```text
EtherCAT datagram
└── Header
    └── ecat.cmd
```

### ECAT-021 Index

```text
ecat.idx
```

Type:

```text
Unsigned integer, 8 bits
```

### ECAT-022 ADP

```text
ecat.adp
```

Description:

```text
Slave Addr
```

Type:

```text
Unsigned integer, 16 bits
```

### ECAT-023 ADO

```text
ecat.ado
```

Description:

```text
Offset Addr
```

Type:

```text
Unsigned integer, 16 bits
```

### ECAT-024 Logical Address

Logical addressing command MAY expose：

```text
ecat.lad
```

Type:

```text
Unsigned integer, 32 bits
```

ADP / ADO and Logical Address SHALL NOT be assumed to have identical semantics.

### ECAT-025 Data Length

Canonical decoded Data Length field SHALL be:

```text
ecat.subframe.length
```

Wireshark Display Filter Reference defines it as:

```text
Length
Unsigned integer, 16 bits
```

In the current JSON hierarchy it is located beneath the Datagram Header subtree.

Parser SHALL NOT substitute unverified names such as:

```text
ecat.data_length
ecat.length
```

for the current TShark output contract.

### ECAT-026 Interrupt

Datagram Header MAY contain:

```text
ecat.int
```

Type:

```text
Unsigned integer, 16 bits
```

---

## 8. Working Counter

### ECAT-030 WKC field

Working Counter SHALL be read from:

```text
ecat.cnt
```

Wireshark Display Filter Reference identifies this field as:

```text
Working Cnt
Unsigned integer, 16 bits
```

In the current decoded tree, WKC belongs to the complete Datagram node and is not required to be inside `Header`.

Conceptual structure:

```text
EtherCAT datagram
├── Header
│   ├── ecat.cmd
│   ├── ecat.adp / ecat.ado
│   └── ecat.subframe.length
├── Data / decoded payload
└── ecat.cnt
```

Parser SHALL extract `ecat.cnt` from the **same complete Datagram object** that contains the target payload.

---

## 9. EtherCAT Mailbox Structure

Wireshark registers EtherCAT Mailbox protocol under:

```text
ecat_mailbox
```

Official registered mailbox fields include:

```text
ecat_mailbox.length
ecat_mailbox.address
ecat_mailbox.priority
ecat_mailbox.type
ecat_mailbox.counter
ecat_mailbox.coe
```

### MBX-001 Mailbox association

When mailbox data is decoded for an EtherCAT Datagram, Parser SHALL associate the complete `ecat_mailbox` subtree with the Datagram that contains it.

Parser SHALL NOT search the entire packet for one mailbox and separately choose another Datagram for Header/WKC information.

### MBX-002 Same-Datagram rule

All of the following SHALL come from the same EtherCAT Datagram:

```text
Command
ADP
ADO
Data Length
WKC
ecat_mailbox
ecat_mailbox.coe_tree
```

Frame Number is the only required value taken from the containing packet.

---

## 10. CoE SDO Structure

Wireshark officially registers the following CoE SDO fields.

### COE-001 SDO request marker

```text
ecat_mailbox.coe.sdoreq
```

Description:

```text
SDO Req
```

Type:

```text
Unsigned integer, 8 bits
```

### COE-002 SDO response marker

```text
ecat_mailbox.coe.sdores
```

Description:

```text
SDO Res
```

Type:

```text
Unsigned integer, 8 bits
```

### COE-003 SDO Index

```text
ecat_mailbox.coe.sdoidx
```

Description:

```text
Index
```

Type:

```text
Unsigned integer, 16 bits
```

### COE-004 SDO SubIndex

```text
ecat_mailbox.coe.sdosub
```

Description:

```text
SubIndex
```

Type:

```text
Unsigned integer, 8 bits
```

### COE-005 SDO Data

```text
ecat_mailbox.coe.sdodata
```

Description:

```text
Data
```

Type:

```text
Unsigned integer, 32 bits
```

### COE-006 Additional CoE fields

Wireshark also registers additional CoE / SDO fields such as:

```text
ecat_mailbox.coe.abortcode
ecat_mailbox.coe.sdolength
ecat_mailbox.coe.sdoccsid
ecat_mailbox.coe.sdoscsiu
...
```

Parser MAY retain the complete `coe_tree` to avoid losing information not yet mapped into Analyzer models.

---

## 11. Observed CoE SDO JSON Shape

目前專案實際 capture 已觀察到類似：

```json
"ecat_mailbox": {
  "Header": {
    "ecat_mailbox.length": "10",
    "ecat_mailbox.address": "0x0000",
    "ecat_mailbox.priority": "0",
    "ecat_mailbox.type": "3",
    "ecat_mailbox.counter": "0"
  },
  "ecat_mailbox.coe": "00:20:2f:12:1c:00:00:00:00:00",
  "ecat_mailbox.coe_tree": {
    "ecat_mailbox.coe.number": "0",
    "ecat_mailbox.coe.type": "2",
    "ecat_mailbox.coe.sdoreq": "1",
    "ecat_mailbox.coe.sdoidx": "0x1c12",
    "ecat_mailbox.coe.sdosub": "0x00",
    "ecat_mailbox.coe.sdodata": "0x00"
  }
}
```

此 shape 與 Wireshark 官方註冊的 `ecat_mailbox.*` / `ecat_mailbox.coe.*` fields 一致。

`Header`、`ecat_mailbox.coe_tree` 等 JSON object labels 是 dissector tree serialization 的結構節點；正式技術欄位應以 registered field names 為主要契約。

---

## 12. Raw CoE SDO Search Algorithm

### SEARCH-001 Input

Input:

```text
D:\EtherCATAnalyzer\Data\Json\output.json
```

### SEARCH-002 Target fields

CoE SDO presence SHALL be identified when a complete EtherCAT Datagram contains any of:

```text
ecat_mailbox.coe.sdoreq
ecat_mailbox.coe.sdores
ecat_mailbox.coe.sdoidx
ecat_mailbox.coe.sdosub
ecat_mailbox.coe.sdodata
```

### SEARCH-003 Search order

Parser SHALL search in capture order:

```text
Packet 1
  Datagram 1
  Datagram 2
  ...

Packet 2
  Datagram 1
  ...
```

### SEARCH-004 Find-first semantics

Upon the first matching Datagram:

```text
STOP
```

Parser SHALL NOT continue to search later Datagram or Packet unless the caller explicitly requests multiple results.

### SEARCH-005 Required result

Result SHALL contain:

```text
Frame Number
Complete ecat_mailbox JSON
Complete ecat_mailbox.coe_tree JSON
Command
ADP
ADO
Data Length
WKC
```

### SEARCH-006 Exact association

The result SHALL obey:

```text
Packet Frame Number
        +
Matched complete EtherCAT Datagram
        ├── Header → Command / ADP / ADO / Data Length
        ├── Mailbox → ecat_mailbox / coe_tree
        └── ecat.cnt → WKC
```

It SHALL NOT combine values from different Datagram objects in the same frame.

---

## 13. Recommended Traversal

Conceptual traversal:

```text
output.json root array
│
├─ packet
│  └─ _source
│     └─ layers
│        ├─ frame
│        │  └─ frame.number
│        │
│        └─ ecat
│           ├─ EtherCAT datagram: ...
│           │  ├─ Header
│           │  │  ├─ ecat.cmd
│           │  │  ├─ ecat.idx
│           │  │  ├─ ecat.adp / ecat.ado or ecat.lad
│           │  │  └─ ecat.subframe.length
│           │  ├─ decoded payload
│           │  │  └─ ecat_mailbox
│           │  │     └─ ecat_mailbox.coe_tree
│           │  └─ ecat.cnt
│           │
│           └─ EtherCAT datagram: ...
│              └─ ...
```

Recommended algorithm:

```text
for each packet:
    read frame.number

    get layers.ecat

    for each direct child whose name starts with "EtherCAT datagram:":
        datagram = complete child object

        if datagram contains any target CoE SDO field:
            extract all fields from this same datagram
            return result
```

---

## 14. Forbidden Parser Assumptions

### PARSE-001

Parser SHALL NOT assume:

```text
one packet == one datagram
```

### PARSE-002

Parser SHALL NOT recursively find the first object containing `ecat.cmd` and treat it as a complete Datagram.

Reason:

```text
Header contains ecat.cmd
but Header does not contain all Datagram sibling payload/WKC nodes.
```

### PARSE-003

Parser SHALL NOT search:

```text
mailbox from whole packet
+
header from another independently selected datagram
```

### PARSE-004

Parser SHALL NOT infer Data Length using undocumented aliases when canonical:

```text
ecat.subframe.length
```

is present.

### PARSE-005

Parser SHALL NOT infer WKC using undocumented aliases when canonical:

```text
ecat.cnt
```

is present.

### PARSE-006

Parser SHALL NOT treat human-readable tree labels as EtherCAT protocol facts.

For example:

```text
"EtherCAT datagram: Cmd: ..."
"Header"
```

are tree-serialization structure labels.

Fields such as:

```text
ecat.cmd
ecat.adp
ecat.ado
ecat.cnt
ecat_mailbox.coe.sdoidx
```

are Wireshark registered fields and are the stronger field-level contract.

---

## 15. Versioning Requirements

Wireshark Display Filter Reference currently lists the main EtherCAT fields in this specification as available across a broad Wireshark version range, including current 4.x releases.

However, JSON tree labels and nesting are produced from the dissector protocol tree and MAY change between Wireshark versions even when registered field names remain stable.

Therefore:

### VERSION-001

The Analyzer SHOULD record or expose the actual TShark version used to produce `output.json`.

### VERSION-002

When upgrading TShark, the following SHALL be regression-checked:

```text
_source.layers
frame.number
ecat layer
EtherCAT datagram node discovery
Header placement
ecat.cmd
ecat.adp
ecat.ado
ecat.subframe.length
ecat.cnt
ecat_mailbox
ecat_mailbox.coe_tree
CoE SDO target fields
```

### VERSION-003

If the human-readable Datagram object label changes, the parser MAY require a version adapter.

Such adaptation SHALL preserve the rule:

```text
identify the complete Datagram boundary first,
then extract Header + payload + WKC from that same object.
```

---

## 16. Performance Requirement

### PERF-001

Large `output.json` files SHOULD be processed incrementally.

The implementation SHOULD avoid:

```text
read entire file
→ json.loads entire capture
→ search
```

for find-first operations.

### PERF-002

For a find-first query, the desired behavior is:

```text
parse one packet
→ inspect its datagrams
→ discard packet if unmatched
→ continue
→ stop immediately on first match
```

This prevents unnecessary parsing of packets after the first match and substantially reduces peak memory usage.

Streaming implementation details are outside the structural contract of this specification.

---

## 17. Current Project Mapping

Current `EtherCatDatagramExtractor.cs` already follows the intended full-Datagram boundary approach:

```text
packet["_source"]["layers"]["ecat"]
→ enumerate properties named "EtherCAT datagram:"
→ pass complete property object into CreateDatagramRecord()
```

Its current raw field mapping includes:

```text
Command      → Header["ecat.cmd"]
Protocol Idx → Header["ecat.idx"]
ADP          → Header["ecat.adp"]
ADO          → Header["ecat.ado"]
Logical Addr → Header["ecat.lad"]
Data Length  → Header subtree "ecat.subframe.length"
WKC          → datagram["ecat.cnt"]
```

`raw_capture.py` SHOULD use the same structural contract rather than inventing a separate Datagram discovery rule.

---

## 18. Acceptance Criteria

Raw TShark JSON parser is conformant when all following tests pass:

1. Can read `frame.number`.
2. Can enumerate multiple EtherCAT Datagram objects in one packet.
3. Does not confuse nested `Header` with complete Datagram.
4. Can extract `ecat.cmd`.
5. Can extract `ecat.adp` / `ecat.ado` when applicable.
6. Can extract `ecat.subframe.length`.
7. Can extract `ecat.cnt`.
8. Can retain complete `ecat_mailbox`.
9. Can retain complete `ecat_mailbox.coe_tree`.
10. Can identify a Datagram containing any configured CoE SDO field.
11. All reported Datagram fields come from the exact Datagram containing the matched mailbox.
12. Find-first mode stops after the first matched Datagram.
13. No file is modified during raw search.
14. No LLM is required for deterministic raw search.

---

## 19. References

### Wireshark / TShark official documentation

**W1 — TShark Manual Page**

https://www.wireshark.org/docs/man-pages/tshark.html

Relevant topics:

```text
-T json
-j
-J
-e
-G fields
```

**W2 — Wireshark User's Guide: Exporting Data**

https://www.wireshark.org/docs/wsug_html_chunked/ChIOExportSection.html

Provides the official JSON example with:

```text
_source.layers
```

**W3 — Display Filter Reference: EtherCAT datagram(s)**

https://www.wireshark.org/docs/dfref/e/ecat.html

Authoritative registered fields include:

```text
ecat.cmd
ecat.idx
ecat.adp
ecat.ado
ecat.lad
ecat.cnt
ecat.subframe.length
```

**W4 — Display Filter Reference: EtherCAT Mailbox Protocol**

https://www.wireshark.org/docs/dfref/e/ecat_mailbox.html

Authoritative registered fields include:

```text
ecat_mailbox.*
ecat_mailbox.coe.sdoreq
ecat_mailbox.coe.sdores
ecat_mailbox.coe.sdoidx
ecat_mailbox.coe.sdosub
ecat_mailbox.coe.sdodata
```

**W5 — Wireshark Wiki: EtherCAT**

https://wiki.wireshark.org/Protocols/ethercat

Shows the protocol tree:

```text
EtherCAT frame header
EtherCAT datagram(s)
    EtherCAT datagram
        Header
        Data
        Working Cnt
```

### Current project source

**P1**

```text
EtherCATAnalyzer_net472/
AnalyzerDll/EtherCATAnalyzer/Tshark/TsharkRunner.cs
```

**P2**

```text
EtherCATAnalyzer_net472/
AnalyzerDll/EtherCATAnalyzer/Extraction/EtherCatDatagramExtractor.cs
```

---

## 20. Summary Contract

The core parsing rule is:

```text
Packet
→ _source.layers.ecat
→ identify COMPLETE "EtherCAT datagram:" object
→ search CoE inside that complete Datagram
→ if matched:
     Header → cmd / adp / ado / length
     same Datagram → mailbox / coe_tree / ecat.cnt
     Packet → frame.number
→ return
```

Do not use:

```text
recursive ecat.cmd discovery
```

as a Datagram-boundary detector.

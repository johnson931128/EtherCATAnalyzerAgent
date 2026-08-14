# TShark EtherCAT / CoE SDO Search Commands

## 1. Purpose

本文件整理 EtherCATAnalyzer 開發期間使用的 TShark / PowerShell 查詢指令，目標是讓人工、Codex 或自製 Agent 能快速從大型 PCAP 中定位 EtherCAT Mailbox / CoE / SDO 封包，而不需要掃描完整 `output.json`。

主要用途：

- 查詢本機 TShark 版本。
- 查詢 Wireshark 已註冊的 EtherCAT / CoE / SDO fields。
- 從 PCAP 找出包含 SDO Request / Response 的 frame。
- 匯出單一 frame 為小型 JSON。
- 找特定 Object Dictionary Index / SubIndex。
- 找 PDO Mapping，例如 `0x1A00:01 -> 0x604X0010`。
- 提供後續 Agent Tool 可直接包裝的 deterministic command。

---

## 2. Recommended PowerShell Variables

```powershell
$TS = "C:\WiresharkPortable64\App\Wireshark\tshark.exe"
$PCAP = "D:\EtherCATAnalyzer\Data\Pcap\<capture>.pcapng"
$JSON_DIR = "D:\EtherCATAnalyzer\Data\Json"
```

後續指令盡量使用 `$TS` 與 `$PCAP`，避免重複寫完整路徑。

---

## 3. Check TShark Version

```powershell
& $TS -v
```

目前開發環境已確認：

```text
TShark (Wireshark) 4.6.6
```

注意：

```text
-v
```

代表查版本。

```text
-V
```

代表輸出 verbose packet decode；如果沒有指定 `-r <capture>`，TShark 可能嘗試進行 live capture。

---

## 4. Query Registered CoE / SDO Fields

查詢目前 TShark 版本實際註冊的所有 CoE fields：

```powershell
& $TS -G "fields,ecat_mailbox.coe"
```

只顯示 SDO 相關 fields：

```powershell
& $TS -G "fields,ecat_mailbox.coe" | Select-String "sdo"
```

目前 TShark 4.6.6 已觀察到的重要 fields：

```text
ecat_mailbox.coe.type

ecat_mailbox.coe.sdoreq
ecat_mailbox.coe.sdores

ecat_mailbox.coe.sdoidx
ecat_mailbox.coe.sdosub
ecat_mailbox.coe.sdodata
ecat_mailbox.coe.abortcode
ecat_mailbox.coe.sdolength

ecat_mailbox.coe.sdoccsid
ecat_mailbox.coe.sdoccsid.sizeind
ecat_mailbox.coe.sdoccsid.expedited
ecat_mailbox.coe.sdoccsid.size0
ecat_mailbox.coe.sdoccsid.size1
ecat_mailbox.coe.sdoccsid.complete

ecat_mailbox.coe.sdoccsds
ecat_mailbox.coe.sdoccsds.lastseg
ecat_mailbox.coe.sdoccsds.size
ecat_mailbox.coe.sdoccsds.toggle

ecat_mailbox.coe.sdoccsiu
ecat_mailbox.coe.sdoccsus
ecat_mailbox.coe.sdoccsus_toggle

ecat_mailbox.coe.sdoscsiu
ecat_mailbox.coe.sdoscsiu_sizeind
ecat_mailbox.coe.sdoscsiu_expedited
ecat_mailbox.coe.sdoscsiu_size0
ecat_mailbox.coe.sdoscsiu_size1
ecat_mailbox.coe.sdoscsiu_complete

ecat_mailbox.coe.sdoscsds
ecat_mailbox.coe.sdoscsds_toggle

ecat_mailbox.coe.sdoscsus
ecat_mailbox.coe.sdoscsus_lastseg
ecat_mailbox.coe.sdoscsus_bytes
ecat_mailbox.coe.sdoscsus_toggle
```

這類查詢應優先於掃描大型 TShark JSON，因為它直接反映目前安裝版本的 dissector registry。

---

## 5. Find Frames Containing SDO Request / Response

只列出 frame number：

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq || ecat_mailbox.coe.sdores" -T fields -e frame.number | Select-Object -First 20
```

若要同時查看基本 SDO 欄位：

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq || ecat_mailbox.coe.sdores" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.counter `
-e ecat_mailbox.coe.type `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata `
-e ecat_mailbox.coe.abortcode
```

注意：`-T fields` 適合定位與搜尋；若一個 EtherCAT frame 內有多個 Datagram，不應把 flat field output 當成完整 Datagram 結構證據。

---

## 6. Export One Frame as Small JSON

找到目標 frame 後，例如：

```powershell
$FRAME = 41394
```

只匯出該 frame：

```powershell
& $TS -r $PCAP -Y "frame.number == $FRAME" -T json -J "frame eth ecat ecat_mailbox" > "$JSON_DIR\sdo-frame-$FRAME.json"
```

用途：

```text
大型 PCAP
↓
TShark display filter
↓
單一 frame
↓
小型 JSON
```

單一 frame JSON 可保留：

```text
frame
eth
ecat
ecat_mailbox
ecat_mailbox.coe_tree
ecat.cnt
```

適合人工檢查、Codex 靜態分析與 Agent evidence retrieval。

---

## 7. Find SDO Responses After a Known Request

已知 request frame，例如：

```powershell
$REQUEST_FRAME = 41394
```

先在後方小範圍找 SDO Response：

```powershell
& $TS -r $PCAP -Y "frame.number >= $REQUEST_FRAME && frame.number <= ($REQUEST_FRAME + 60) && ecat_mailbox.coe.sdores" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.counter `
-e ecat_mailbox.coe.type `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.abortcode
```

找到候選 response 後，再用上一節的單 frame JSON export 做完整確認。

---

## 8. Find a Specific Object Dictionary Access

### Example: find any access to `0x1A00:01`

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoidx == 0x1a00 && ecat_mailbox.coe.sdosub == 0x01" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.type `
-e ecat_mailbox.coe.sdoreq `
-e ecat_mailbox.coe.sdores `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

### Example: only SDO Initiate Download Request

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq && ecat_mailbox.coe.sdoccsid && ecat_mailbox.coe.sdoidx == 0x1a00 && ecat_mailbox.coe.sdosub == 0x01" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.counter `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

### Example: only Expedited Initiate Download

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq && ecat_mailbox.coe.sdoccsid && ecat_mailbox.coe.sdoccsid.expedited == 1 && ecat_mailbox.coe.sdoidx == 0x1a00 && ecat_mailbox.coe.sdosub == 0x01" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.counter `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

---

## 9. Find PDO Mapping Values Like `0x604X0010`

目標例子：

```text
0x1A00:01 -> 0x60410010
```

其中 mapping value：

```text
0x6041  Object Index
0x00    SubIndex
0x10    Bit Length = 16 bit
```

先鎖定 `0x1A00:01`，再用 PowerShell regex 篩選：

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq && ecat_mailbox.coe.sdoccsid && ecat_mailbox.coe.sdoccsid.expedited == 1 && ecat_mailbox.coe.sdoidx == 0x1a00 && ecat_mailbox.coe.sdosub == 0x01" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.sdodata | Select-String -Pattern "0x604[0-9A-Fa-f]0010"
```

此 regex 可匹配：

```text
0x60400010
0x60410010
0x60420010
...
0x604F0010
```

找到 frame number 後，再匯出單一 frame JSON：

```powershell
$FRAME = <frame-number>

& $TS -r $PCAP -Y "frame.number == $FRAME" -T json -J "frame eth ecat ecat_mailbox" > "$JSON_DIR\sdo-frame-$FRAME.json"
```

---

## 10. Generic PDO Mapping Search

查所有 TxPDO Mapping Objects：

```text
0x1A00 ~ 0x1BFF
```

可先用：

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq && ecat_mailbox.coe.sdoccsid && ecat_mailbox.coe.sdoidx >= 0x1a00 && ecat_mailbox.coe.sdoidx <= 0x1bff" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

查所有 RxPDO Mapping Objects：

```text
0x1600 ~ 0x17FF
```

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoreq && ecat_mailbox.coe.sdoccsid && ecat_mailbox.coe.sdoidx >= 0x1600 && ecat_mailbox.coe.sdoidx <= 0x17ff" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.sdoidx `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

---

## 11. Find SM Assignment Objects

RxPDO assignment：

```text
0x1C12
```

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoidx == 0x1c12" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.sdoreq `
-e ecat_mailbox.coe.sdores `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

TxPDO assignment：

```text
0x1C13
```

```powershell
& $TS -r $PCAP -Y "ecat_mailbox.coe.sdoidx == 0x1c13" -T fields `
-e frame.number `
-e ecat.adp `
-e ecat_mailbox.coe.sdoreq `
-e ecat_mailbox.coe.sdores `
-e ecat_mailbox.coe.sdosub `
-e ecat_mailbox.coe.sdodata
```

---

## 12. Useful Search Patterns for Agent Tools

後續自製 Agent 可將下列操作包成 deterministic tools。

### Tool: `list_registered_coe_fields`

Input：

```text
tshark_path
```

Command：

```powershell
& $TS -G "fields,ecat_mailbox.coe"
```

Output：

```text
registered field names
```

### Tool: `find_sdo_frames`

Input：

```text
pcap_path
limit
```

Command concept：

```text
-Y "ecat_mailbox.coe.sdoreq || ecat_mailbox.coe.sdores"
-T fields
-e frame.number
```

Output：

```text
frame numbers
```

### Tool: `find_sdo_object_access`

Input：

```text
pcap_path
index
subindex optional
request/response optional
```

Output：

```text
frame
ADP
Index
SubIndex
Data
```

### Tool: `export_frame_json`

Input：

```text
pcap_path
frame_number
output_path
```

Command concept：

```text
-Y "frame.number == N"
-T json
-J "frame eth ecat ecat_mailbox"
```

Output：

```text
small JSON artifact
```

### Tool: `find_pdo_mapping`

Input：

```text
pcap_path
mapping_index
mapping_subindex
optional data regex
```

Example：

```text
mapping_index = 0x1A00
mapping_subindex = 0x01
data_regex = 0x604[0-9A-Fa-f]0010
```

Output：

```text
matching frame
station address
mapping value
```

---

## 13. Important Structural Rule

`-T fields` 適合：

```text
find
filter
locate
quick inspection
```

但完整 EtherCAT Datagram evidence 應使用：

```text
-T json -J "frame eth ecat ecat_mailbox"
```

並遵守：

```text
Packet
→ complete EtherCAT Datagram
   ├─ Header
   ├─ ecat_mailbox
   │  └─ ecat_mailbox.coe_tree
   └─ ecat.cnt
```

不要把同一 frame 中不同 Datagram 的 fields 混在一起。

---

## 14. Current Development Workflow

推薦目前 EtherCATAnalyzer 開發使用：

```text
1. TShark field registry
   ↓
2. TShark display filter 查 PCAP
   ↓
3. 取得少量候選 frame
   ↓
4. 匯出單 frame JSON
   ↓
5. 驗證 Datagram / Mailbox / CoE / SDO facts
   ↓
6. 更新 EtherCATAnalyzer parser / analyzer
```

避免：

```text
讀取完整超大型 output.json
→ Agent 全文搜尋
```

因為大部分 deterministic capture retrieval 都可以先由 TShark 完成。

---

## 15. Related Project Contract

本文件應搭配：

```text
TShark_EtherCAT_JSON_Structure_Spec.md
```

其中定義：

```text
_source.layers
complete EtherCAT Datagram boundary
ecat.cmd
ecat.adp
ecat.ado
ecat.subframe.length
ecat.cnt
ecat_mailbox
ecat_mailbox.coe_tree
```

本文件負責「如何查」，JSON Structure Spec 負責「查到後如何解析」。

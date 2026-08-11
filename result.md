# EtherCAT Analyzer Agent Result

## Task
請根據 ET1100 Spec 建立 EtherCAT EEPROM 文件。

內容包含：
- EEPROM 基本用途
- 0x0502 EEPROM Control / Status
- 0x0504 EEPROM Address
- 0x0508 EEPROM Data
- EEPROM Read Procedure
- Vendor ID
- Product Code
- 對 EtherCAT Analyzer 實作有用的重點

## Routing
- Selected docs:
EtherCAT_ESC_Architecture.md
EtherCAT_Field_Mapping.md
- Selected source: slave_discovery
- Capture mode: eeprom_identity

## Result
# EtherCAT EEPROM 分析文件 (基於 ET1100 與 EtherCATAnalyzer 專案)

## 1. 文件來源與權威性聲明

本文件內容嚴格區分以下四類來源，並遵循 `AGENTS.md` 規則：

1.  **Source Code**: `EtherCATAnalyzer/Analysis/SlaveDiscoveryAnalyzer.cs` 中的實際邏輯。
2.  **Capture Evidence**: 本次 `eeprom_identity` 查詢從 `ethercat-datagrams.json` 提取的實際觀察數據。
3.  **docs/read**: `EtherCAT_ESC_Architecture.md` 等整理過的參考筆記。
4.  **Full Specification**: `D:\DATA\SPEC\EtherCAT_ET1100_Datasheet_all_v1i8.pdf`。
    *   **重要聲明**：目前尚未從完整 PDF 中提取具體的位元定義或時序細節。本文件中關於 "Protocol Behavior" 的描述若未標註為 Source Code 或 Capture Evidence，均基於 `docs/read` 的摘要或 EtherCAT 通用標準，**並非**已驗證的 ET1100 完整規範細節。若需精確的位元定義（如 `0x0502` 的具體位元功能），需查閱完整 PDF。

---

## 2. EEPROM 基本用途

### 來源：docs/read & 通用 EtherCAT 知識
*   **功能**：EEPROM (Electrically Erasable Programmable Read-Only Memory) 用於儲存 Slave 裝置的靜態識別資訊與啟動配置。
*   **內容**：包含 Vendor ID、Product Code、Revision Number、Serial Number、ESI (EtherCAT Slave Information) 描述檔等。
*   **存取方式**：Master 無法直接讀取 EEPROM 內容。必須透過 ESC 的特定寄存器（`0x0502`, `0x0504`, `0x0508`）進行間接讀寫操作。
*   **架構定位**：屬於 ESC Address Space 的一部分，位於 `0x0000` 起始的 Register 區域。

---

## 3. 關鍵寄存器定義

### 3.1 0x0502: EEPROM Control / Status
*   **Source Code 實作**:
    *   常數定義：`EepromControlStatusRegister = 0x0502`
    *   讀取命令遮罩：`EepromReadCommandMask = 0x0700`
    *   讀取命令值：`EepromReadCommandValue = 0x0100`
    *   邏輯：程式檢查 `EepromControlStatus` 是否包含 `0x0100` 以判斷是否為讀取操作。
*   **Capture Evidence 觀察**:
    *   在 `Outgoing` 封包中，`Ado` 為 `0x0502`。
    *   `EepromControlStatus` 欄位值為 `0x0100` (例如 Frame 133, 137)。
    *   `EepromWordAddress` 欄位同時存在於此封包中（見下文 3.2）。
*   **Protocol Behavior (基於 docs/read)**:
    *   此寄存器用於啟動 EEPROM 操作（讀/寫）並回報狀態。
    *   寫入特定命令碼（如 `0x0100` 代表讀取）並指定地址後，ESC 會開始從 EEPROM 讀取資料。

### 3.2 0x0504: EEPROM Address
*   **Source Code 實作**:
    *   程式中未直接定義 `0x0504` 常數。
    *   **關鍵發現**：在 `SlaveDiscoveryAnalyzer.cs` 的 `BindEepromIdentity` 方法中，當 `Ado == 0x0502` 時，程式直接從 `pair.Outgoing.EepromWordAddress` 讀取地址。
    *   **推論**：在目前的 JSON 數據結構 (`ethercat-datagrams.json`) 中，`EepromWordAddress` 似乎被解析並附帶在 `0x0502` 的封包記錄中，或者解析器將 `0x0502` 和 `0x0504` 的寫入操作合併處理了。
*   **Capture Evidence 觀察**:
    *   當 `Ado` 為 `0x0502` 且 `CommandCode` 為 `0x02` (APwr) 時，`EepromWordAddress` 欄位有值。
    *   例如 Frame 133: `EepromWordAddress` = `0x00000008` (Vendor ID 位置)。
    *   例如 Frame 137: `EepromWordAddress` = `0x0000000A` (Product Code 位置)。
    *   **注意**：Capture Evidence 顯示地址是 32-bit (`0x00000008`)，這可能代表 Word Address 的 16-bit 值被擴展或包含在數據結構中。
*   **Protocol Behavior (基於 docs/read)**:
    *   通常 `0x0504` 用於指定要讀取的 EEPROM Word 地址。
    *   在 ET1100 中，寫入 `0x0502` 時通常會同時包含控制位元和地址資訊，或者需要連續寫入 `0x0504`。目前的 Capture Evidence 顯示地址資訊直接伴隨在 `0x0502` 的寫入操作中。

### 3.3 0x0508: EEPROM Data
*   **Source Code 實作**:
    *   常數定義：`EepromDataRegister = 0x0508`
    *   邏輯：當 `Ado == 0x0508` 且 `CommandCode == 0x01` (APrd) 時，讀取 `pair.Returning.EepromData`。
*   **Capture Evidence 觀察**:
    *   在 `Returning` 封包中，`Ado` 為 `0x0508`。
    *   `EepromData` 欄位包含實際讀取的資料。
    *   Frame 136 (回應 Frame 133/135): `EepromData` = `0x000001DD` (對應 Vendor ID 0x0008)。
    *   Frame 140 (回應 Frame 137/139): `EepromData` = `0x1041000F` (對應 Product Code 0x000A)。
*   **Protocol Behavior (基於 docs/read)**:
    *   此寄存器用於讀取或寫入 EEPROM 的實際資料內容。
    *   讀取操作：Master 發送讀取命令到 `0x0508`，Slave 在回應中填入 EEPROM 內容。

---

## 4. EEPROM Read Procedure (讀取流程)

根據 **Source Code** 與 **Capture Evidence** 的對應關係，標準讀取流程如下：

### 步驟 1: 設定讀取命令與地址 (Write to 0x0502)
*   **動作**: Master 發送 `APwr` (0x02) 命令。
*   **目標**: `Ado` = `0x0502`。
*   **內容**:
    *   設定控制位元為讀取模式 (`0x0100`)。
    *   設定目標 EEPROM Word 地址 (例如 `0x0008` 或 `0x000A`)。
*   **Capture Evidence 驗證**:
    *   Frame 133: `CommandCode`="0x02", `Ado`="0x0502", `EepromControlStatus`="0x0100", `EepromWordAddress`="0x00000008"。
    *   Frame 137: `CommandCode`="0x02", `Ado`="0x0502", `EepromControlStatus`="0x0100", `EepromWordAddress`="0x0000000A"。

### 步驟 2: 讀取資料 (Read from 0x0508)
*   **動作**: Master 發送 `APrd` (0x01) 命令。
*   **目標**: `Ado` = `0x0508`。
*   **內容**: 請求讀取之前設定的地址對應的資料。
*   **Capture Evidence 驗證**:
    *   Frame 135: `CommandCode`="0x01", `Ado`="0x0508"。
    *   Frame 139: `CommandCode`="0x01", `Ado`="0x0508"。

### 步驟 3: 獲取回應 (Returning Frame)
*   **動作**: Slave 回應讀取請求。
*   **內容**: `Returning` 封包的 `Ado` 為 `0x0508`，且 `EepromData` 欄位包含資料。
*   **Capture Evidence 驗證**:
    *   Frame 136 (回應 135): `EepromData`="0x000001DD"。
    *   Frame 140 (回應 139): `EepromData`="0x1041000F"。

### 步驟 4: Working Counter 檢查
*   **Source Code 邏輯**: `pair.Returning.WorkingCounter == pair.Outgoing.WorkingCounter + 1`。
*   **Capture Evidence 驗證**:
    *   所有配對的封包 `WorkingCounterDelta` 均為 1。
    *   這確認了資料交換成功且無遺漏。

---

## 5. 識別資訊 (Vendor ID & Product Code)

### 5.1 Vendor ID
*   **EEPROM 地址**: `0x0008` (Word Address)
*   **Source Code 常數**: `VendorIdEepromWordAddress = 0x0008`
*   **Capture Evidence 結果**:
    *   地址 `0x0008` 的讀取結果為 `0x000001DD`。
    *   對應的 `CalculatedTopologyPosition` 為 1 和 2 (兩顆 Slave 均回報相同 Vendor ID)。
*   **解析**: `0x01DD` 是 Beckhoff Automation GmbH 的 Vendor ID (十進位 477)。

### 5.2 Product Code
*   **EEPROM 地址**: `0x000A` (Word Address)
*   **Source Code 常數**: `ProductCodeEepromWordAddress = 0x000A`
*   **Capture Evidence 結果**:
    *   地址 `0x000A` 的讀取結果為 `0x1041000F`。
    *   對應的 `CalculatedTopologyPosition` 為 1 和 2。
*   **解析**: `0x1041000F` 是該特定 EtherCAT Slave 的產品代碼。

---

## 6. 對 EtherCAT Analyzer 實作有用的重點

### 6.1 地址映射邏輯 (Topology Position)
*   **Source Code 邏輯**: `CalculateTopologyPosition` 使用 `0 - initialAdp` 的 16-bit 無符號運算。
    *   公式：`distanceFromZero = unchecked((ushort)(0 - initialAdp))`
    *   結果：`topologyPosition = distanceFromZero + 1`
*   **Capture Evidence 驗證**:
    *   Frame 133: `OutgoingAdp` = `0x0000` -> `CalculatedTopologyPosition` = 1。
    *   Frame 133 (第二個 datagram): `OutgoingAdp` = `0xFFFF` -> `CalculatedTopologyPosition` = 2。
    *   這確認了 `0x0000` 是第一個 Slave，`0xFFFF` 是第二個 Slave (在 Auto Increment 模式下，地址遞增，但這裡顯示的是初始地址)。
    *   **注意**: `ReturningAdp` 在 Capture Evidence 中變化 (`0x0002`, `0x0001`)，這是 EtherCAT 自動遞增地址的特性，**不可**用於計算拓樸位置。Source Code 正確地僅使用 `Outgoing.Adp`。

### 6.2 配對邏輯 (Pairing)
*   **Source Code 邏輯**: `BuildPairs` 方法依賴 `TimeUtc` 和 `FrameNumber` 將 Outgoing 和 Returning 封包配對。
*   **Capture Evidence 驗證**:
    *   Python 已經完成了配對 (`OutgoingFrame` 133 對應 `ReturningFrame` 134)。
    *   分析器不需要重新解析方向，只需信任 `CalculatedTopologyPosition` 和配對結果。

### 6.3 數據解析的邊界條件
*   **Source Code 限制**:
    *   僅處理 `CommandCode` 為 `0x01` (APrd), `0x02` (APwr), `0x03` (APrw), `0x0D` (ARMw) 的封包。
    *   僅當 `EepromControlStatus` 包含 `0x0100` 時才視為讀取操作。
    *   僅當 `WorkingCounter` 增加 1 時才視為成功。
*   **潛在風險**:
    *   如果 Capture 中缺少 `0x0502` 的寫入封包，或者 `0x0508` 的讀取封包，`BindEepromIdentity` 將無法提取資料。
    *   目前的 Capture Evidence 顯示流程完整，但需確保在更複雜的場景（如多筆連續讀取）中，`pendingEepromReads` 字典能正確處理狀態。

### 6.4 數據類型與格式
*   **Source Code**: 使用 `ushort` 處理地址，`uint` 處理 Vendor/Product Code。
*   **Capture Evidence**:
    *   `EepromWordAddress` 在 JSON 中顯示為 32-bit 字串 (`0x00000008`)。
    *   `EepromData` 在 JSON 中顯示為 32-bit 字串 (`0x000001DD`)。
    *   **實作建議**: 在解析 JSON 時，需確保將這些 Hex 字串正確轉換為 `uint`，並注意大小端序 (Little Endian 是 EtherCAT 標準，但 JSON 中的字串通常已按標準順序排列，需確認 `TryParseHexUShort` 或類似函數的處理方式)。

---

## 7. 未確認事項與下一步建議

由於尚未接入完整 `EtherCAT_ET1100_Datasheet_all_v1i8.pdf`，以下細節需進一步確認：

1.  **0x0504 寄存器的具體行為**:
    *   在 Capture Evidence 中，地址資訊似乎直接附帶在 `0x0502` 的寫入操作中，而非獨立的 `0x0504` 寫入。
    *   **假設**: ET1100 可能允許在寫入 `0x0502` 時同時指定地址，或者解析器將連續的 `0x0502` 和 `0x0504` 寫入合併為單一邏輯記錄。
    *   **行動**: 需查閱 PDF 確認 `0x0502` 的位元定義是否包含地址欄位，或確認 `0x0504` 是否為必經步驟。

2.  **EEPROM 讀取時序**:
    *   目前證據顯示 `APwr` (設定) 和 `APrd` (讀取) 是連續的。
    *   **行動**: 確認 PDF 中關於 EEPROM 操作完成時間 (Busy Flag) 的定義，以確保 Analyzer 在讀取 `0x0508` 前不需要等待特定的時序或檢查狀態位。

3.  **錯誤處理**:
    *   目前 Source Code 僅在 `WorkingCounter` 不匹配時跳過。
    *   **行動**: 需確認 PDF 中 `0x0502` 的 Status 位元定義，以在 Analyzer 中實現更精確的錯誤檢測（如 EEPROM 讀取失敗、地址越界等）。

**結論**: 目前的 `SlaveDiscoveryAnalyzer` 實作與 Capture Evidence 高度一致，能正確識別 Vendor ID 和 Product Code。主要風險在於對 `0x0504` 寄存器的處理方式與完整規範的差異，建議在後續開發中對照完整 PDF 進行驗證。

---

# Generated ET1100 Documentation Draft

# EtherCAT EEPROM

## Source
ET1100 Datasheet, Section I - Technology, Version 1.9 (2010-05-03).

## Overview
The ET1100 ESC (EtherCAT Slave Controller) includes an integrated ESI (EtherCAT Slave Information) EEPROM interface. This interface allows the EtherCAT Master to read and write configuration data stored in an external EEPROM connected to the ESC via the I²C interface. The ESC manages the low-level I²C timing and protocol, exposing a register-based interface (0x0500–0x050F) for the Master to control access.

- **Spec fact:** The ESI EEPROM interface supports three commands: write to one EEPROM address, read from one EEPROM address, and reload the EEPROM content into the ESC registers (0x0500–0x050F) (Page 95, 98).
- **Engineering explanation:** The Master does not drive the I²C lines directly. Instead, it writes commands and data to specific ESC registers, and the ESC hardware handles the serial communication with the external EEPROM chip.
- **Analyzer note:** When analyzing captures, look for sequences of writes to 0x0502, 0x0504, and 0x0508 followed by a read of 0x0508 to reconstruct EEPROM transactions.

## EEPROM Interface
The ESC provides a dedicated register block for EEPROM access. Access is generally blocked if the EEPROM interface is busy (0x0502.15=1).

### 0x0502 EEPROM Control / Status
This 16-bit register (extended to 0x0503) controls the operation and reports the status of the EEPROM interface.

- **Spec fact:** Bit 15 (Busy) indicates if the EEPROM interface is busy. The Master must check if this bit is cleared (0) before initiating a new command (Page 98, 169).
- **Spec fact:** Bit 0 (ECAT Write Enable) enables write requests. If a write command is issued without this bit set, an error occurs (Page 96, 169).
- **Spec fact:** The Write Enable bit is self-clearing at the Start of Frame (SOF) of the next frame (Page 170).
- **Engineering explanation:** The "Busy" bit acts as a semaphore. The Master must poll this bit or wait for the previous operation to complete before issuing a new command to avoid data corruption or command rejection.
- **Analyzer note:** In `EtherCatDatagramRecord`, the `EepromControlStatus` property maps to this register. A non-zero value in Bit 15 during a command sequence indicates the ESC is still processing a previous I²C transaction.

### 0x0504 EEPROM Address
This 32-bit register (0x0504–0x0507) specifies the target address in the external EEPROM.

- **Spec fact:** The register reflects the address used for the I²C transaction. The PDF states the EEPROM interface supports byte-addressing, but the ESC adds `A[0]` internally (Page 99).
- **Spec fact:** The register is 32 bits wide (Page 171).
- **Engineering explanation:** Although the external EEPROM might be byte-addressable, the EtherCAT protocol and the ESC interface typically operate on word boundaries (16-bit or 32-bit). The ESC handles the internal bit manipulation (e.g., setting the LSB) to align with the I²C device's addressing scheme.
- **Analyzer note:** **Crucial Distinction:** The ET1100 PDF describes the address in terms of **byte addressing** (where the LSB is handled internally). However, the `EEPROM_Field_Mapping.md` context defines the analyzer's convention as **Word Addressing** (0x0008 for Vendor ID).
    - When parsing 0x0504, the analyzer must interpret the value as a **Word Address** (e.g., 0x0008) to match the ESI standard, even if the raw register value in the PDF context implies a byte offset.
    - The analyzer combines 0x0504 (Low) and 0x0506 (High) into a 32-bit `EepromWordAddress`.

### 0x0508 EEPROM Data
This register block (0x0508–0x050F) holds the data to be written or the data read from the EEPROM.

- **Spec fact:** The register is 32 bits wide (0x0508–0x050B) for the ET1100 (Page 171).
- **Spec fact:** Data access is generally blocked if the EEPROM interface is busy (0x0502.15=1) (Page 171).
- **Engineering explanation:** For a read operation, the Master writes the command and address, waits for the Busy bit to clear, and then reads this register to retrieve the data. For a write, the Master writes the data here before or during the command execution.
- **Analyzer note:** The `EepromData` property in the analyzer combines 0x0508 and 0x050A. This field contains the actual payload (e.g., Vendor ID value) after a successful read transaction.

## EEPROM Read Procedure
The ET1100 specifies a strict sequence for accessing the EEPROM to ensure data integrity.

- **Spec fact:** The procedure requires checking if the Busy bit (0x0502.15) is cleared before starting (Page 98).
- **Spec fact:** If a write command is issued without the Write Enable bit set, the ESC retries or reports an error (Page 96, 98).
- **Spec fact:** The ESC retries reading the EEPROM if a failure occurs (e.g., Missing Acknowledge) (Page 96, 97).
- **Engineering explanation:** The "Missing Acknowledge" error (Page 97) occurs if the external EEPROM does not respond. The ESC hardware automatically retries the operation for several milliseconds before setting an error flag.
- **Analyzer note:** When reconstructing a read transaction:
    1. Identify the write to 0x0502 (Command: Read, Enable Write if needed).
    2. Identify the write to 0x0504 (Target Address).
    3. Wait for 0x0502.15 to become 0 (Busy cleared).
    4. Read 0x0508 for the result.
    - If the analyzer sees a "Busy" bit set immediately after a command, it indicates the ESC is still processing the I²C cycle.

## Identity Information
The ESI EEPROM contains standard identity fields defined by the EtherCAT specification.

### Vendor ID
- **Spec fact:** The Vendor ID is located at EEPROM word addresses 0x0008 and 0x0009 (Page 95, 197).
- **Spec fact:** The register mapping in the ESC (0x0E08:0x0E0F) reflects the Vendor ID loaded from the EEPROM (Page 197).
- **Engineering explanation:** This 32-bit value uniquely identifies the manufacturer of the slave device. It is the first critical field read during device enumeration.
- **Analyzer note:** According to `EEPROM_Field_Mapping.md`, the analyzer expects the **Word Address** 0x0008. When the 0x0504 register contains `0x0008`, the subsequent read from 0x0508 should yield the Vendor ID.

### Product Code
- **Spec fact:** The Product Code is located at EEPROM word addresses 0x000A and 0x000B (Page 95, 197).
- **Spec fact:** This field follows the Vendor ID in the EEPROM map (Page 95).
- **Engineering explanation:** This 32-bit value identifies the specific product model. Combined with the Vendor ID, it allows the Master to load the correct ESI XML file.
- **Analyzer note:** The analyzer should look for a read sequence targeting Word Address 0x000A (0x0504 = 0x000A) to extract the Product Code.

## Analyzer-Relevant Notes
- **Addressing Convention Mismatch:** The ET1100 PDF (Page 99) mentions "byte addressing" where `A[0]` is added internally. However, the ESI standard and the `EEPROM_Field_Mapping.md` use **Word Addressing** (0x0008, 0x000A).
    - **Action:** The analyzer must treat the value in 0x0504 as a **Word Address**. Do not shift or multiply by 2. If the PDF implies a byte offset, the ESC hardware has already handled the conversion. The value `0x0008` in 0x0504 corresponds to the Vendor ID.
- **Transaction Pairing:** The current implementation extracts fields but does not pair the command (0x0502/0x0504) with the data (0x0508).
    - **Action:** Implement logic to match a "Read Command" (0x0502) + "Address" (0x0504) with the subsequent "Data Read" (0x0508) once the Busy bit clears.
- **Error Handling:** If the analyzer detects a "Missing Acknowledge" or "Write Enable" error in the status register (0x0502), it should flag the transaction as failed and not attempt to parse the data in 0x0508 as valid identity information.
- **Data Width:** The ET1100 supports 32-bit data access (0x0508–0x050B). Ensure the analyzer reads both 0x0508 and 0x050A to reconstruct the full 32-bit Vendor ID or Product Code.

## Source References
- ET1100 Datasheet, Section I - Technology, Version 1.9 (2010-05-03).
- Pages referenced: 94, 95, 96, 97, 98, 99, 128, 130, 133, 168, 169, 170, 171, 197, 220.
- Context: `EEPROM_Field_Mapping.md` (Repository implementation context).
- Context: `EtherCAT_Datagram_Addressing_WKC.md` (Datagram structure).

### Evidence Used

- Topic: EEPROM
  - PDF page: 94
  - Excerpt: ESI EEPROM I-72 Slave Controller – Technology 11.1 ESI EEPROM Content ias. ration data is secured wit...
- Topic: EEPROM
  - PDF page: 95
  - Excerpt: ESI EEPROM Slave Controller – Technology I-73 An excerpt of the ESI EEPROM For more information, refer to t...
- Topic: EEPROM
  - PDF page: 96
  - Excerpt: ESI EEPROM I-74 Slave Controller – Technology 11.2.1 ESI EEPROM Errors The ESC retries reading the EEP...
- Topic: EEPROM
  - PDF page: 97
  - Excerpt: ESI EEPROM Slave Controller – Technology I-75 11.2.1.1 Missing Acknowledge : o several ms). and bit is ...
- Topic: EEPROM
  - PDF page: 98
  - Excerpt: ESI EEPROM I-76 Slave Controller – Technology 11.2.3 Read/Write/Reload Example The following steps hav...
- Topic: 0x0502
  - PDF page: 95
  - Excerpt: ...PDI. Register Address Description 0x0500 EEPROM Configuration 0x0501 EEPROM PDI Access State 0x0502:0x0503 EEPROM Control/Status 0x0504:0x0507 EEPROM Address 0x0508:0x050F EEPROM Data The EEP...
- Topic: 0x0502
  - PDF page: 96
  - Excerpt: ...te without Write Enable (ECAT Rea te command without Write Enable son: ECAT issued a wri bit set (0x0502.0) Solu able bit in the same frame as the write tion: Set Write En command
- Topic: 0x0502
  - PDF page: 98
  - Excerpt: ...SI EEPROM read or write access: 1. Check if the Busy bit of the EEPROM Status register is cleared (0x0502.15==0) and the EEPROM interface is not busy, otherwise wait until the EEPROM interface is not busy...
- Topic: 0x0502
  - PDF page: 128
  - Excerpt: ...PDI ESI EEPROM Interface 0x0500 1 EEPROM Configuration 0x0501 1 EEPROM PDI Access State 0x0502:0x0503 2 EEPROM Control/Status 0x0504:0x0507 4 EEPROM Address 0x0508:0x050F 4/8 EEPROM Data...
- Topic: 0x0502
  - PDF page: 169
  - Excerpt: ESI EEPROM Interface (0x0500:0x050F) Table 65: Register EEPROM Control/Status (0x0502:0x0503) ESC20 ET1100 ET1200 IP Core [7] Bit Description ECAT PDI Reset Value 0 EC...
- Topic: 0x0504
  - PDF page: 95
  - Excerpt: ...x0500 EEPROM Configuration 0x0501 EEPROM PDI Access State 0x0502:0x0503 EEPROM Control/Status 0x0504:0x0507 EEPROM Address 0x0508:0x050F EEPROM Data The EEPROM interface supports three commands:...
- Topic: 0x0504
  - PDF page: 99
  - Excerpt: ...ugh the I²C interface A[0] is added internally by the EEPROM I.e., the EEPROM address register (0x0504:0x0507) reflects the d with the 11.3.1 Word Addressing EtherCAT and ESC actually uses byte add...
- Topic: 0x0504
  - PDF page: 128
  - Excerpt: ... EEPROM Configuration 0x0501 1 EEPROM PDI Access State 0x0502:0x0503 2 EEPROM Control/Status 0x0504:0x0507 4 EEPROM Address 0x0508:0x050F 4/8 EEPROM Data MII Management Interface 0x0510:0x...
- Topic: 0x0504
  - PDF page: 168
  - Excerpt: ... EEPROM Configuration 0x0501 1 EEPROM PDI Access State 0x0502:0x0503 2 EEPROM Control/Status 0x0504:0x0507 4 EEPROM Address 0x0508:0x050F 4/8 EEPROM Data EtherCAT controls the ESI EEPROM inte...
- Topic: 0x0504
  - PDF page: 171
  - Excerpt: ESI EEPROM Interface (0x0500:0x050F) Table 66: Register EEPROM Address (0x0504:0x0507) ESC20 ET1100 ET1200 IP Core Bit Description ECAT PDI Reset Value 31:0 EEPROM Add...
- Topic: 0x0508
  - PDF page: 95
  - Excerpt: ...0501 EEPROM PDI Access State 0x0502:0x0503 EEPROM Control/Status 0x0504:0x0507 EEPROM Address 0x0508:0x050F EEPROM Data The EEPROM interface supports three commands: write to one EEPROM address (1...
- Topic: 0x0508
  - PDF page: 128
  - Excerpt: ...EEPROM PDI Access State 0x0502:0x0503 2 EEPROM Control/Status 0x0504:0x0507 4 EEPROM Address 0x0508:0x050F 4/8 EEPROM Data MII Management Interface 0x0510:0x0511 2 MII Management Control/St...
- Topic: 0x0508
  - PDF page: 168
  - Excerpt: ...EEPROM PDI Access State 0x0502:0x0503 2 EEPROM Control/Status 0x0504:0x0507 4 EEPROM Address 0x0508:0x050F 4/8 EEPROM Data EtherCAT controls the ESI EEPROM interface if EEPROM configuration regi...
- Topic: 0x0508
  - PDF page: 171
  - Excerpt: ...is generally blocked if EEPROM interface is busy (0x0502.15=1). Table 67: Register EEPROM Data (0x0508:0x050F [0x0508:0x050B]) ESC20 ET1100 ET1200 IP Core [63:32] [63:32] Bit Description EC...
- Topic: Vendor ID
  - PDF page: 95
  - Excerpt: ... 0x19 Standard Receive Mailbox Size 0x7 Checksum 0x1A Standard Send Mailbox Offset 0x8:0x9 Vendor ID 0x1B Standard Send Mailbox Size 0xA:0xB Product Code 0x1C Mailbox Protocol 0xC:0xD Revi...
- Topic: Vendor ID
  - PDF page: 130
  - Excerpt: ... ESC specific 0x0E00:0x0EFF 256 ESC specific registers (e.g., Power-On Values / Product and Vendor ID) Digital Input/Output 0x0F00:0x0F03 4 Digital I/O Output Data 0x0F10:0x0F17 1-8 General ...
- Topic: Vendor ID
  - PDF page: 133
  - Excerpt: ...s/l c c dc - 0x0E00:0x0EFF 256 ESC specific registers (e.g., Power-On Values / Product and Vendor ID) x x x x x x 0x0F00:0x0F03 4 Digital I/O Output Data x x io io io x 0x0F10:0x0F17 ...
- Topic: Vendor ID
  - PDF page: 197
  - Excerpt: ... ECAT PDI Reset Value 63:0 Product ID r/- r/- Depends on configuration Table 132: Register Vendor ID (0x0E08:0x0E0F) ESC20 ET1100 ET1200 IP Core Bit Description ECAT PDI Reset Value 31:0 Ve...
- Topic: Vendor ID
  - PDF page: 220
  - Excerpt: ...set filters after writing filter depth - ESC Specific Registers (0x0E00:0x0EFF) Product and Vendor ID - POR Values x FPGA Update (online) - Process RAM and User RAM Process RAM (0x1000 f...
- Topic: Product Code
  - PDF page: 95
  - Excerpt: ...x1A Standard Send Mailbox Offset 0x8:0x9 Vendor ID 0x1B Standard Send Mailbox Size 0xA:0xB Product Code 0x1C Mailbox Protocol 0xC:0xD Revision Number 0x1D:0x3D Reserved 0xE:0xF Serial Number ...
- Topic: EEPROM read procedure
  - PDF page: 96
  - Excerpt: ... failure. Invalid nd error is automatically comma sup terface. ported by the EEPROM in 14 Error Write Enable Wri control only): te without Write Enable (ECAT Rea te command without Write Enable son: ECAT...
- Topic: EEPROM read procedure
  - PDF page: 98
  - Excerpt: ... – Technology 11.2.3 Read/Write/Reload Example The following steps have to be performed for a ESI EEPROM read or write access: 1. Check if the Busy bit of the EEPROM Status register is cleared (0x0502.15==0) and the EEPROM ...
- Topic: EEPROM read procedure
  - PDF page: 169
  - Excerpt: ...0503) ESC20 ET1100 ET1200 IP Core [7] Bit Description ECAT PDI Reset Value 0 ECAT write enable*2: 0: Write requests are disabled 1: Write requests are enabled This bit is always 1 if PDI ha...
- Topic: EEPROM read procedure
  - PDF page: 170
  - Excerpt: ...st 0x0220[5]. *1 ESC20: configurable with pin EEPROM SIZE, but not readable in this register. *2 Write Enable bit 0 is self-clearing at the SOF of the next frame, Command bits [10:8] are self-clearing after th...

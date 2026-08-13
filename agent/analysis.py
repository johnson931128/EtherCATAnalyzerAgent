from core.config import SPEC_ORIGINAL_ROOT
from core.llm import llm
from core.state import AgentState


def analyze(state: AgentState):
    prompt = f"""
以下是 EtherCATAnalyzer 專案規則：

{state["context"]}

以下是從 docs/read 選出的相關專案筆記：

{state["docs_content"]}

注意：

docs/read 是整理過的參考資料，不代表完整 EtherCAT protocol specification。
如果 docs/read 沒有足夠資訊支持 protocol fact，不得使用一般模型知識補完。
應明確說明需要查完整 ET1100 specification。

完整 ET1100 specification 目錄為：

{SPEC_ORIGINAL_ROOT / "ET1100"}

目前尚未把完整 PDF evidence 接入這個 Graph，因此不能假裝已經查過完整 ET1100 specification。

以下是目前分析的 source code：

Source context may contain multiple complete selected C# files.
{state["source_code"]}

Capture query mode：

{state["capture_mode"]}

以下是 Python 從 ethercat-datagrams.json 實際查詢得到的 capture evidence：

{state["capture_evidence"]}

Capture evidence contract:

- Python has already paired Outgoing and Returning datagrams deterministically.
- Do not infer packet direction or reconstruct pairs.
- CalculatedTopologyPosition is calculated only from OutgoingAdp.
- ReturningAdp must never be treated as a topology address.
- EepromControlStatus and EepromWordAddress come from Outgoing.
- EepromData comes from Returning.
- ConfiguredStationAddressData comes from Outgoing.

如果 evidence 中存在 CalculatedTopologyPosition：

該值是 Python 依照目前 C# CalculateTopologyPosition 的 16-bit unchecked arithmetic
預先計算出的 deterministic evidence。

不得自行重新計算或覆寫 CalculatedTopologyPosition。

任務：

{state["task"]}

回答時必須嚴格區分：

1. Source Code：目前程式實際實作的行為。
2. Capture Evidence：目前 JSON 實際觀察到的行為。
3. docs/read：整理過的參考資料。
4. Full Specification：目前尚未由 Python 擷取的完整 ET1100 PDF。

不得把 docs/read、Agent prompt 或模型一般知識誤稱為 AGENTS.md 規則。

不得因為目前查詢結果沒有某種封包，就推論整份 capture 不存在該封包。
只能描述本次 capture query 實際查到的內容。

如果一般模型知識與 Source Code 或 Capture Evidence 衝突，描述本專案時以實際 evidence 為準。
"""

    response = llm.invoke(prompt)

    return {"result": response.content}

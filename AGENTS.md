# 規則

- 只允許執行 prompt 明確要求的操作與修改，其餘一律不要做。
- 修改範圍保持最小，只處理目前任務需要的檔案與功能。
- 不主動延伸功能、不重構無關程式碼、不新增額外 abstraction。
- 不修改 EtherCATAnalyzer DLL 專案，除非 prompt 明確要求。
- 不安裝套件、不修改系統環境、不修改開發環境設定。

## 執行與驗證

- 除非 prompt 明確要求，禁止執行程式、啟動服務或進行 runtime verification。
- 禁止自行執行 `run.ps1`、`main.py`、`HermesProxy.py` 或啟動 Qwen / Agent。
- 禁止自行呼叫外部 API 或模型進行驗證。
- 禁止自行執行 pytest、unittest、build、compile 或其他完整測試流程。
- 可以新增或修改小範圍 test code，但不要自行執行。

## 修改完成後

- 只檢查 source diff 與修改範圍。
- 不因為驗證方便而建立 temporary script、temporary file 或額外工具。
- 若 prompt 要求 commit / push，完成修改後才進行。
- 若遇到無法在不執行程式的情況下確認的事項，直接在回報中說明，不要自行嘗試 runtime verification。

# Contract: CLI 變更（feature 005）

> **2026-10-22 稽核補記：規則 3.0.0 沒有採用。** 2026-09-26 的驗證組判定中，`sweet-price` 3.0.0 沒有通過換版的硬門檻
> （spec FR-015：c = 20、每月重新評估，平均淨效益差距 +1.7 [−0.7, +4.2]，區間含 0），使用者決定不換版
> （[validation.md](../validation.md) 第 2 節；005 T030–T032 跳過、005 T033）。現行規則是 2.1.0（feature 006；
> `src/sweetspot/decision/rule.py` 的 `CURRENT_RULE`）。3.0.0 與 006 加的 3.1.0 只留在程式中，供預覽
> （`sweetspot report --rule`）與回測（`sweetspot backtest-rule --rule/--wait-cost`、`sweetspot compare-rule`）；
> 偏好 `wait_cost_twd` 只在這些情況使用。下文「規則 3.0.0 時頁首顯示等待成本」只出現在預覽報告。

延伸 [004 的 CLI 契約](../../004-deeper-discount-model/contracts/cli.md)。共用規則不變：

- 進度寫到 stderr，摘要寫到 stdout。
- 唯讀指令不取寫入鎖。
- `--json` 輸出 JSON 摘要。

## `steamsage backtest-rule`

| 參數 | 預設 | 說明 |
|---|---|---|
| `--rule` | 現行規則 | 新增 `3.0.0` |
| `--wait-cost N[,N…]` | 設定檔的 `wait_cost_twd` | 只對 3.0.0 有效。多個值時，每個分析時點只預測一次，每個 c 各寫一份結果檔 |

- 結果檔名：`…_sweet-price-3.0.0-c20_…json`。2.0.0 的檔名不變。
- 摘要新增：
  - `follow_advice_monthly`（全體）
  - 兩種模式在規則本身的 c 下的淨效益平均
  - `longer_horizon`
- 多個 c 時，摘要是清單，每個 c 一筆。
- **拒絕**（結束代碼 1）：
  - `--wait-cost` 搭配 `--rule 2.0.0`／`1.0.0`：「規則 2.0.0 不使用等待成本」
  - 值不是 0–10,000 的整數

## `steamsage compare-rule`

```text
steamsage compare-rule 基準.json 候選.json [候選2.json …] [--record] [--attempt N] [--change "說明"]
                       [--decision "文字"] [--no-wishlist]
```

- **一致性**（不符時結束代碼 1，說明哪裡不同）：
  - 所有結果的資料集識別、截止時間、切分、模型與參數必須相同。
    （2026-10-22 稽核補記：程式不檢查模型與參數，只檢查資料集識別、截止時間，以及雙方都有的偏好；切分包含在資料集識別中。
    `src/sweetspot/decision/compare_rule.py` 的 `compare_rule_results`。008 T027 依賴「同一規則、不同模型」可以並列，
    這時不算規則的驗證組次數（`tests/unit/decision/test_compare_rule.py`）。）
  - 偏好只比較雙方都有的鍵。
- **輸出**：
  - 004 的指標表，每個候選一欄。
  - 淨效益表：research R7，兩種模式，每個候選以它自己的 c 計算差距與 95% 區間。
  - 每個評估成本下的淨效益。
  - 判定（只在符合判定條件時）：「通過硬門檻：每月重新評估、c = 20、差距 +x [lo, hi]」或「未通過硬門檻」。
  - `longer_horizon`。（2026-10-22：使用者決定不做；程式只在 `backtest-rule` 的摘要輸出 `longer_horizon`，
    `compare-rule` 輸出願望清單的 `longer_24`／`longer_60`。）
- **願望清單差異**（沒有 `--no-wishlist` 時）：
  - 依每份結果記錄的規則、模型與 c，對現在的願望清單各做一次決策。
  - 列出各組款數、改變分組的遊戲、甜蜜價與甜蜜時點的變化，以及兩邊的期望淨效益（research R7）。
  - 列出放寬範圍時，最晚一場選到 12 個月以後的款數。
- **`--attempt N`**：所有結果都是驗證組、而且有 `--record` 或 `--decision` 時必填，1–3。
  - 第 2、3 次必須有 `--change`。
  - 比較文件中同一候選規則版本已有第 N 次紀錄時拒絕。
    （2026-10-22 稽核補記：程式依確切的規則版本比對標題，`3.1.0` 和 `3.0.0` 的次數分開，3.1.0 從第 1 次算起；
    006 所說 3.1.0「沿用 3.0.0 的 1/3」要人工判斷，程式不會擋（`src/sweetspot/decision/compare_rule.py` 的 `check_rule_attempt`）。
    基準和候選是同一個規則版本時，視為模型並列，不需要 `--attempt`（008 T027）。）
    （2026-10-22 稽核補記：第 N 次已記錄、這次又加 `--decision` 與同一個 `--attempt N` 時，程式不拒絕，
    只在比較文件附加一筆「日期 · 使用者的決定：規則驗證組比較（sweet-price 版本）第 N 次」，結束代碼 0；
    `src/sweetspot/commands.py` 的 `compare_rule_command`，README 也有寫。）
  - 紀錄標題：「規則驗證組比較（sweet-price 3.0.0）第 N 次」。
- **結束代碼**：0 完成；1 失敗或拒絕。判定未通過不算失敗，由使用者決定。

## `steamsage report`、`run`（一鍵更新）

- 使用現行規則與設定檔的偏好。規則 3.0.0 時頁首顯示等待成本（contracts/report-html-v005.md）。
- **新增 `--rule 版本`（預覽）**：用非現行規則產生報告，供換版前檢查（quickstart B）。
  - 預覽不是正式執行：不寫預測紀錄、不和前一天比較，`official = false`。
  - 預設輸出 `data/reports/preview-<版本>.html`，不覆蓋 `latest.html`。
  - 頁首註明「預覽：非現行規則」。
  - 指定的就是現行規則時，等於一般的 `report`。
- 設定檔的 `wait_cost_twd` 無效時，結束代碼 1，並說明原因。不會默默改用預設值。

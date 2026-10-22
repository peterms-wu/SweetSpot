# Contract: CLI 與報告的變更（feature 006）

延伸 [005 的 CLI 契約](../../005-waiting-cost/contracts/cli.md) 與 [005 的報告契約](../../005-waiting-cost/contracts/report-html-v005.md)。
共用規則不變：進度寫到 stderr、摘要寫到 stdout、唯讀指令不取寫入鎖。

## `steamsage update`

- 新步驟「版本」：在「現價」之後、「歷史價格」之前。進度文字：`版本 n/N`。
- 歷史價格改抓每款遊戲目前版本的 ITAD 商品；換過版本的遊戲不再抓舊商品。
- 第一次在 v2 資料庫上執行任何寫入指令時自動遷移到 v3，stderr 印出「資料庫升級到 v3：已備份 steamsage.db.bak-v2，補上 N 列的 ITAD 商品 id（x 秒）」。
- 摘要新增 `versions`：

```json
"versions": {
  "checked": 66, "unchanged": 64, "changed": [{"app_id": 239140, "name": "Dying Light",
      "from": "Dying Light", "to": "Dying Light: Essentials Edition"}],
  "rejected": [{"app_id": 9500003, "name": "範例分季作品 - Season 1", "reason": "bundle", "detail": "bundle/99003"}],
  "stopped": [], "fallback_own": {"ambiguous": 0, "not-in-itad": 0}, "no_option": 2, "source_error": false,
  "seconds": 1.2
}
```

（2026-10-22 稽核補記）版本步驟只處理這次現價結果是 priced、free、not-purchasable、delisted 的遊戲（`pipeline/daily.py` 的 `HISTORY_OUTCOMES`）。
`no_option` 只數其中沒有台灣區售價的遊戲（免費、不能購買、下架）；尚未發售（以及 unsupported、not-found、現價查詢失敗）的遊戲不寫 `app_versions` 列、不計入任何一項，
沒有任何版本紀錄時它們的 `version.basis_reason` 是 `no-record`。

- 版本更換、驗證失敗與停止追蹤也加入 `alerts`（FR-015），例如「Dying Light：Steam 換了預設購買選項，改用 Dying Light: Essentials Edition 的價格歷史」。
- 版本步驟的來源錯誤只寫 alert，不讓整次更新失敗；各款沿用上一筆版本（FR-011）。
- `--no-history` 或沒有 `ITAD_API_KEY`：跳過版本步驟，不寫版本紀錄；摘要 `versions` 為 `{"skipped": "no-history"}` 或 `{"skipped": "no-itad-key"}`，
  沒有金鑰時另加 alert「未設定 ITAD_API_KEY：版本步驟略過，沿用上一次的版本」。
- （2026-10-22 稽核補記）ITAD 對應查詢（001 的 mapping）失敗時，版本步驟不執行，摘要**完全沒有** `versions` 鍵，只有一條 alert「ITAD 對應查詢失敗，本次略過歷史：…」。
  來源不支援版本查詢時摘要為 `{"skipped": "unsupported-source"}`（實務上只有測試用的人工來源會走到）（`pipeline/daily.py`）。

## `steamsage report`

- 唯讀指令開啟 v2 以下的資料庫時結束代碼 1，訊息「資料庫是舊版（v2），請先執行 steamsage update 升級」；不自動遷移（唯讀指令不取寫入鎖）。

- 不新增參數。`--as-of` 使用 as-of 以前的版本紀錄（research R7）。
- 每款遊戲的名稱下方：
  - 追蹤的版本名稱和 App 名稱不同時，一直顯示：`追蹤 Dying Light Essentials Edition · 歷史從 2025-06-26 起 · 2026-09-27 偵測到版本更換`。
    （2026-10-22 稽核補記：已被 006 T039 取代，見 [outputs-version.md](outputs-version.md) 開頭）實際條件是 `basis = version`、有 `package_name`，而且 `itad_id ≠ own_itad_id`（真的換了 ITAD 商品）；只是名稱不同、商品相同時不顯示（`report/html.py` 的 `version_text`）。
  - `tracking = stopped`：`價格歷史停止更新（最後確認 2025-01-27）`。
  - `basis = own` 且原因不是 `no-record`：`無法確認 Steam 目前賣的版本，沿用 App 本身的價格歷史`。
  - `basis = own` 且原因是 `no-record`（例如 `--as-of` 早於第一筆版本紀錄）：`這個時點沒有版本紀錄，沿用 App 本身的價格歷史`。
- 變動欄：`version` 變動顯示 `版本更換：Dying Light → Dying Light: Essentials Edition（偵測於 2026-09-27）`，只在偵測後的第一份報告出現。
- 「無法預測」組中驗證失敗的遊戲，原因顯示 `status_reason`。
- 報告只讀決策輸出的 `version` 與 `change`，不自行判斷版本（憲章 VII）。
- 390px 寬度不得水平捲動（沿用 005 的檢查）。

## `steamsage backtest`、`backtest-rule`、`compare-rule`

- 不新增參數。資料讀取依版本紀錄選 ITAD 商品（research R4）；截止時間早於第一筆版本紀錄時，結果和本 feature 之前完全相同（FR-016）。

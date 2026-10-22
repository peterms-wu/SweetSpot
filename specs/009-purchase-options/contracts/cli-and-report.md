# Contract: 設定、CLI 與報告的變更（feature 009）

延伸 [006 的 CLI 與報告契約](../../006-version-tracking/contracts/cli-and-report.md)。
共用規則不變：進度寫到 stderr、摘要寫到 stdout、唯讀指令不取寫入鎖。

## 設定檔 `steamsage.toml`

- 新區段 `[purchase_options]`（選用）：`<App 編號> = "sub/<數字>"` 或 `"bundle/<數字>"`。範本（`DEFAULT_TOML`）只放註解與範例。
- 讀取時的警告（指令照常執行，stderr 印出）：
  - `purchase_options.<鍵>：鍵必須是 App 編號（正整數），已忽略`
  - `purchase_options.<App>：值必須是 "sub/<數字>" 或 "bundle/<數字>"，已忽略`
  - `purchase_options.<App>：同一 App 出現多次（"0123" 與 "123"），全部忽略`（括號內是實際的寫法）
  - 完全相同的鍵重複是 TOML 語法錯誤：照現行規則整個設定檔讀取失敗並說明位置（spec FR-008，plan 決定 D3）。

## `steamsage update`

- 新步驟「購買選項」：在「版本」之後、「歷史價格」之前。進度文字：`購買選項 n/N`。
- 「歷史價格」另外抓通過驗證的版本：台灣區每天；美國區只抓指定生效的版本（research R8 D2）。進度文字沿用 `歷史價格 n/N`（N 含版本）。
  （2026-10-22 稽核補記）實際上版本的歷史是另一個進度步驟 `版本歷史 n/N`，跑在「歷史價格」之後（`歷史價格` 的 N 不含版本）；
  摘要 `purchase_options.history` 除了 `tw`、`aux`、`skipped_fresh`，還有 `failed` 與 `seconds`（`pipeline/daily.py` 的 `_edition_histories`）。
- 第一次在 v3 資料庫上執行寫入指令時自動遷移到 v4，stderr 印出「資料庫升級到 v4：已備份 steamsage.db.bak-v3（x 秒）」。
- 摘要新增 `purchase_options`：

```json
"purchase_options": {
  "apps": 66, "options": 231, "editions": 32, "editions_verified": 32, "rejected": [
      {"app_id": 239140, "name": "Dying Light", "option": "sub/1265945", "reason": "bundle", "detail": "bundle/47759"}],
  "specified": {"active": [{"app_id": 1091500, "name": "Cyberpunk 2077", "option": "bundle/32470"}],
                "fallback": [], "ignored": []},
  "history": {"tw": 32, "aux": 1, "skipped_fresh": 0},
  "source_error": false, "seconds": 18.7
}
```

- 指定不能用、被忽略的設定、版本驗證失敗（第一次出現時）加入 `alerts`（FR-017），例如
  「Cyberpunk 2077：指定的版本（bundle/32470）目前不在購買選項中，改用 Steam 預設版本」。
- 來源錯誤只寫 alert，不讓整次更新失敗；不寫購買選項紀錄，讀取時沿用上一次（FR-009）。
- `--no-history` 或沒有 `ITAD_API_KEY`：和版本步驟一起略過；摘要 `purchase_options` 為 `{"skipped": "no-history"}` 或 `{"skipped": "no-itad-key"}`。
- （2026-10-22 稽核補記）另外兩種略過（`pipeline/daily.py`）：版本步驟沒有取得購買選項（它的來源錯誤）時，摘要為 `{"skipped": "no-purchase-options", "source_error": true}`，
  並加 alert「購買選項步驟略過：版本步驟沒有取得購買選項，沿用上一次的紀錄」；ITAD 對應查詢失敗時，摘要**完全沒有** `purchase_options` 鍵（只有「ITAD 對應查詢失敗…」的 alert）。
  來源不支援時為 `{"skipped": "unsupported-source"}`（實務上只有測試用的人工來源）。

## `steamsage report`

- 唯讀指令開啟 v3 以下的資料庫時結束代碼 1，訊息「資料庫是舊版（v3），請先執行 steamsage update 升級」。
- 不新增參數。指定依**目前的設定**；`--as-of` 搭配 as-of 以前的購買選項紀錄（research R4，決定 D1）。
- 設定中有不在追蹤範圍的 App：摘要與 stderr 警告 `purchase_options.<App>：不在願望清單的追蹤範圍，已忽略`（決策輸出另有批次層級的 `warnings`；實作時新增）。
  （2026-10-22，014 T074）「追蹤範圍」和每日更新相同：願望清單上的遊戲，加上移除後仍在追蹤期間的遊戲（spec Edge Case「指定設定照常生效」）。
  以前 `report` 只算願望清單上的遊戲，對移除後仍在追蹤的遊戲也警告「已忽略」，和 `update` 的摘要（列為生效）不一致。這類遊戲不在報告裡，但它的指定不再被說成忽略；015 的本機程式也照這個範圍。
- 每款遊戲：
  - 摘要行：`editions` 不為空時顯示「另有 N 個版本」。
  - 名稱下方的版本行：
    - `source = user`：`追蹤 《電馭叛客 2077：終極版》（使用者指定）· 歷史從 2024-12-11 起`。
    - `source = user-fallback`：`指定的版本（bundle/32470）目前不在購買選項中，改用 Steam 預設版本`（`fallback` 的文字）。
    - 其他情況照 006。
    - （2026-10-22，014 T073）上面以 `source` 判斷。以前程式看的是 `basis = user`：指定的是 Steam 預設本身、或和預設同一個 ITAD 商品的版本時，`basis` 仍是 `version`／`own`，版本行因此不顯示「（使用者指定）」。
      這種指定的版本行另外加「和 Steam 預設的價格歷史相同；刪掉設定檔中的這一行即可取消指定」：預設那一列就是追蹤中的版本，不列在「其他版本」，那裡的取消指定提示不會出現。
      `source = user-fallback` 只顯示 `fallback` 的文字，不顯示「（使用者指定）」。
  - 展開內容的「其他版本」表格（依 `editions` 的順序）：名稱、現價（折扣）、原價、台灣區歷史最低價（日期）、歷史起點、
    設定行（`config_line`，附複製按鈕）或未通過的原因；`unset_hint` 的那一列顯示「刪掉設定檔中的這一行即可取消指定」。
    沒有歷史時顯示「—（還沒有價格歷史）」，不顯示 0。
  - 變動欄：`change.version.cause` 對應的文字（contracts/outputs-options.md）。
- 複製按鈕是報告內的 JavaScript（寫入剪貼簿），不寫任何檔案；瀏覽器不允許時仍可手動選取文字。
- 報告只讀決策輸出的 `version`、`editions` 與 `change`，不自行判斷版本或計算價格（憲章 VII）。
- 390px 寬度不得水平捲動；設定行可換行。

## `steamsage backtest`、`backtest-rule`、`compare-rule`、`grid`、`ns-backtest`

- 不變。回測不讀 `[purchase_options]`，也不讀版本的價格歷史（`itad-option-history`）；資料集識別碼不變（FR-012、SC-007）。

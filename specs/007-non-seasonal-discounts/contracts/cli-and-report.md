# Contract: 指令與報告

## `steamsage ns-backtest`

非季節預測的回測，輸出 `steamsage.ns-backtest/1`（[data-model](../data-model.md)），存到 `data/backtests/`。

```text
steamsage ns-backtest [--model non-seasonal] [--param K=V ...] [--split all|tuning|validation]
                      [--cutoff YYYY-MM-DD] [--no-earlier] [--apps-limit N] [--json]
```

| 選項 | 說明 |
|---|---|
| `--model`、`--param` | 預設為 `CURRENT_NS_MODEL`；未採用且沒有 `--param` 時，以預設參數 `smoothing=2, history=TW+US, clock=true`（[ns-model-api](ns-model-api.md)）執行並在摘要註明 |
| `--split` | 同季節回測；切分與鹽相同 |
| `--no-earlier` | 不計算「更早到價」的命中率（省下季節模型與規則的決策，約 35 秒） |
| `--cutoff` | （2026-10-22 稽核補記）沒有給時預設為**最新的資料已知時間**（`ns-backtest`、`ns-grid` 相同，`commands.py` 的 `_ns_setup`），每次更新後都會變；要重現結果一定要給 `--cutoff`（2026-09-26 網格誤用預設截止時間的更正，記在 `docs/model/comparisons.md`） |

- **檔名**：`<started>_ns-<name>-<version>_<params6>_TW_<ns_dataset_id8>.json`。
- **摘要**：結果檔路徑、模型、切分、遊戲數、分析時點數、依 h 的計分與不計分數、Brier、參照分數、錯誤數、秒數。
- **結束碼**：同 `backtest`，有錯誤時為 `EXIT_PARTIAL`。

## `steamsage ns-grid`

```text
steamsage ns-grid --grid smoothing=1,2,5 --grid history=TW,TW+US --grid clock=true,false
                  [--param K=V ...] [--split tuning|all] [--record | --record-to PATH] [--json]
```

- （2026-10-22 稽核補記）`ns-grid` 也接受 `--cutoff YYYY-MM-DD`、`--no-earlier`（和 `ns-backtest` 相同）與 `--model`（預設 `non-seasonal`）（`cli.py`）。
  `--cutoff` 預設同樣是最新的資料已知時間，要重現一定要給。
- 不接受 `--split validation`（同 004 FR-011）。
- 季節模型與規則的決策只算一次，每組共用（R7）。
- **摘要**：每組的 Brier（全體、依 h）、和參照分數的差距與 95% 區間、選定的參數與原因（R3 的選擇規則）。
- **`--record`**：附加一筆「non-seasonal 調參組網格」到 `docs/model/comparisons.md`。

## `steamsage ns-compare`

```text
steamsage ns-compare RESULT [--against OTHER] [--record | --record-to PATH] [--attempt N] [--change TEXT] [--json]
```

- **只給 `RESULT`**：比較模型和它自己的參照分數（整體比例）。
- **給 `--against`**：比較兩個結果。兩者的 `ns_dataset_id` 與切分必須相同，否則拒絕執行。
- **方法**：依遊戲成對重抽樣 2,000 次，種子由 `ns_dataset_id` 決定；只用兩邊都有的遊戲。
  （2026-10-22 稽核補記）給 `--against` 時，實際上只要有任何一款遊戲只在一邊計分、或兩邊的計分單位數不同，就整個拒絕執行（「評分單位不同：遊戲 N」，結束代碼 1），
  不會只取共同的遊戲（`forecast/nonseasonal/backtest.py` 的 `compare_ns`）。
- **判定**：只看 `RESULT` 的切分。
  - 驗證組：全體 Brier 差距 < 0，而且 95% 區間不含 0 → 「優於」；否則「未優於」（spec FR-010）。
  - 其他切分只報告，不判定。
- **`--record`**：驗證組時必須給 `--attempt`（1–3）。
  - 第 2 次以後必須給 `--change`，說明改了什麼、為什麼改。
  - 同一個模型版本已有 3 次紀錄時拒絕執行。
  - 次數和 004 的模型比較、005 的規則比較分開計算。
- **紀錄內容**：日期（UTC）、模型與參數、切分、`ns_dataset_id`、兩者的 Brier（全體與依 h）、差距與區間、判定、更早到價在門檻 50% 的次數與命中率。
- **結束碼**：優於時 `EXIT_OK`，否則 `EXIT_PARTIAL`。

## 使用者的決定

驗證組比較之後，使用者的決定（採用或不採用）以一段文字附加到比較文件，只附加，寫法同 005。
採用時同時修改 `CURRENT_NS_MODEL`（spec FR-009、FR-010）。

## 報告（`steamsage report`）

只讀決策輸出（憲章 VII）。沒有 `non_seasonal` 的舊紀錄照常產生報告。

**頁首**：
- 模型那一行多一段「· 非季節 non-seasonal 1.0.0」。未採用時寫「· 非季節預測：只顯示過去紀錄」。
- 從未採用變成採用的第一份正式報告，加一條註記（[outputs](outputs-non-seasonal.md)）。

**摘要列**：`earlier` 不是 null 時，在標籤區加「可能提早」。

**展開的內容**：原因清單的最後加一段「季節特賣以外」。

| 顯示 | 條件 |
|---|---|
| 依據（[措辭](ns-model-api.md)） | 每款可決策的遊戲 |
| 機率：30／60／90 天內季節特賣以外降到甜蜜價以下 | `status = ok` |
| 更早到價的一句，附命中率 | `earlier` 不是 null |
| 「非季節預測暫時無法計算：原因」 | `status = model-error` |

**版面**：390px 寬度不得出現水平捲動。用 `specs/006-version-tracking/prototype/check_390.py` 檢查。

## 效率

`report` 增加的時間在 5 秒以內（R7），一鍵更新全部仍在 30 秒以內（spec SC-008）。

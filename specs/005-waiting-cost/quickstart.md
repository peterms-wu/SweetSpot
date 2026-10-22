# Quickstart：驗收情境（feature 005）

**前提**：

- 真實資料庫 `data/steamsage.db`，資料截止 2026-09-25，和 002 的回測資料集相同（識別碼 `d547c29d…`）。
- 指令都在專案根目錄執行；在 Bash 中印中文前先設 `PYTHONIOENCODING=utf-8`。
- `steamsage.toml` 的 `[preferences]` 有 `wait_cost_twd = 20`。

**功能測試通過不代表新規則較好**：新規則好不好，只看情境 D、E 的結果（spec SC-008）。

## A 自動測試

```text
uv run pytest
```

**預期**：全部通過，不連網。004 結束時 646 項，本 feature 新增：

- 規則 3.0.0 在人工曲線上的期望值、選擇與甜蜜時點。
  - 以分為單位和手算完全相同（SC-001）。
  - c 單調：c 提高，等待不增加（SC-002）。
- 偏好：驗證、依規則分組。
- 決策輸出 `/2`：契約保證；`/1` 紀錄仍可讀取與比較。
- 每月重新評估與淨效益在人工價格路徑上逐案手算（SC-003）。
- `compare-rule` 的成對差距、區間、判定與次數限制。
- 報告：3.0.0 的頁首、摘要列與對照表逐一比對；2.0.0 的報告不變。
- 洩漏：3.0.0 規則，以及每月重新評估不影響決策。

## B 願望清單的 3.0.0 決策（US1、US3）

先不換版，產生預覽報告 `data/reports/preview-3.0.0.html`。預覽不寫紀錄、不和前一天比較（contracts/cli.md）：

```text
uv run steamsage report --rule 3.0.0
```

**預期**（和 research R0.6 對照，c = 20）：

| 項目 | 預期 |
|---|---|
| 各組款數 | 大約現在買 18、即將到價 41、繼續等 4、低信心 2，另有無法預測 3 |
| NEKOPARA After | 2026 秋特 -20%，即將到價 |
| Cyberpunk 2077 | 2026 秋特 -65%（約 93%），最晚 2027 夏特 |
| 真・三國無雙 起源 | 現在買（只在現價仍為 -30% 時） |

另外要確認：

- 每一款都有期望多省、等待成本、淨效益與機率，等待對照表恰好一列標示「建議」。
- 原因的特殊情況逐一抽查措辭：現價未知、從沒打折過（PRAGMATA）、低信心（龍之劍:覺醒）、原價不一致（Dying Light）、
  現價已低於所有選項（戰國無雙５）、現價過舊。
- 耗時 < 30 秒（SC-007）。

## C c 單調（SC-002）

```text
uv run python scripts/wait_cost_monotonic.py
```

**預期**：c = 0、10、20、30、50、80、120 時，每款遊戲的期望等待都不增加；c = 0 時選中的是期望多省最高的選項。

## D 調參組的並列（US2，spec FR-012）

```text
uv run steamsage backtest-rule --rule 2.0.0 --split tuning
uv run steamsage backtest-rule --rule 3.0.0 --wait-cost 0,10,20,30,50,80 --split tuning
uv run steamsage compare-rule <2.0.0 結果> <3.0.0 c0> <c10> <c20> <c30> <c50> <c80> --record
```

**預期**：

- 數字和 research R0.1 的原型相近，平均淨效益差距在 ±1 以內。
- 比較文件多一筆「規則回測並列」。
- 耗時：兩個 `backtest-rule` 合計 < 1 分鐘，`compare-rule` < 1 分鐘。

**checkpoint**：向使用者報告調參組的結果。

## E 驗證組的判定（US2，spec FR-014、FR-015）

```text
uv run steamsage backtest-rule --rule 2.0.0 --split validation
uv run steamsage backtest-rule --rule 3.0.0 --wait-cost 0,10,20,30,50,80 --split validation
uv run steamsage compare-rule <2.0.0 結果> <3.0.0 各 c 的結果…> --record --attempt 1
```

**預期**：

- 比較文件多一筆「規則驗證組比較（sweet-price 3.0.0）第 1 次」。
- 判定只看 c = 20、每月重新評估：3.0.0 的平均淨效益比 2.0.0 高，而且 95% 區間下限 > 0。

**checkpoint**：把判定、並列表與願望清單差異交給使用者決定換不換（FR-015）。

## F 換版（US4，只有 E 通過而且使用者同意時）

```text
uv run steamsage backtest-rule --rule 3.0.0
uv run steamsage report --open
```

**預期**：

- 完整資料集的規則回測數字寫進 `RULE_BACKTESTS` 與模型定義的「規則回測」一節；一致性測試通過（SC-006）。
- 報告頁首是 `sweet-price` 3.0.0 與「等待成本 NT$20／月（使用者偏好）」。
- 比較基準註明「規則 sweet-price 2.0.0 → 3.0.0」。
- 把真實報告交給使用者（`SendUserFile data/reports/latest.html`）。

## G 改 c 之後（spec FR-020、FR-023）

把設定檔暫時改成 `wait_cost_twd = 30`，再執行 `uv run steamsage report`：

- 頁首比較基準列出「等待成本從 NT$20 改成 NT$30」。
- 不引用到價率，改顯示「規則回測是以等待成本 NT$20 算的……」。

檢查完改回 20。

## H 不換版時

如果 E 未通過或使用者不同意：

- 現行規則維持 2.0.0，報告和 004 相同。
- 比較文件記錄結果與使用者的決定；模型定義記錄 3.0.0 的設計、原型與判定。

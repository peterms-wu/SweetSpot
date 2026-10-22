# Quickstart：驗收情境（feature 004）

**前提**：

- 真實資料庫 `data/steamsage.db`，資料截止 2026-09-25（和 002 的回測資料集相同）。
- 指令都在專案根目錄執行；在 Bash 中印中文前先設 `PYTHONIOENCODING=utf-8`。

**功能測試通過不代表預測準確**：準確度只看情境 C、D、E 的結果（spec SC-010）。

## A 自動測試

```text
uv run pytest
```

**預期**：全部通過，不連網。003 結束時 545 項，本 feature 新增：

- 模型：人工資料上的單調、交界、退化、共用倒推表、原因。
- 切分與資料集識別。
- `deeper_than_past` 與 `by_own_sales`。
- 網格的選參數規則。
- 比較次數限制。
- 照建議買的評分。
- `notes` 與 RuleBacktestFigures。
- 洩漏測試（新模型與偷看的變體）。

## B 新模型的預測（US1）

```text
uv run steamsage forecast --model seasonal-record --param min_sales=1 --param half_life=2 --param hazard_history=TW+US --app 1091500
```

（2026-10-22 稽核補記：已被 008 contracts/cli.md 的「模型版本」取代。不帶版本的 `--model seasonal-record` 現在解析成現行的 1.1.0，
並併入現行參數 `low_base=new-split`、`shrink=0.5`；要重現 004 的結果，寫 `--model seasonal-record@1.0.0`。
本文件的 C、D、E 同理；「現行模型」現在也是 `seasonal-record` 1.1.0，不是 004 當時的 `seasonal-freq`。指令名稱現在是 `sweetspot`。）

**預期**：Cyberpunk 2077（1091500）是一般信心。

- 下一場 ≥ -75% 的機率大於 0。
- 原因寫出上一次創新低的特賣與創新低機率的樣本數。
- 同一指令加 `--as-of 2025-06-01`，只用當時的資料。

## C 調參組網格（US2，FR-011）

```text
uv run steamsage grid --model seasonal-record --grid min_sales=1,2 --grid half_life=0,2,4 --grid hazard_history=TW,TW+US --split tuning --record
```

（2026-10-22 稽核補記：`grid` 不帶版本時同樣解析成 1.1.0，但不併入現行參數，用類別預設 `low_base=population`、`shrink=0`；
這樣每個設定都會被 008 FR-003 排除（`fr-003`），結束代碼 2。要重現 004 的網格，寫 `--model seasonal-record@1.0.0`；網格的對照基準一律是程式中的現行模型（現在是 1.1.0）。
`src/sweetspot/forecast/backtest/grid.py`。）

**預期**：

- 12 個設定加上現行模型。
- 美國區只跑 6 次，因為 `hazard_history` 只影響台灣區。
- 約 4–5 分鐘。
- 比較文件多一筆「調參組網格」。
- research R0 的預期：選中 `min_sales=1, half_life=2, hazard_history=TW+US`；如果正式網格選出不同的設定，照實記錄原因。

## D 驗證組比較（US2，FR-012、FR-013）

```text
uv run steamsage backtest --split validation                     # 現行模型
uv run steamsage backtest --split validation --model seasonal-record --param …（C 選中的參數）
uv run steamsage compare <現行>.json <候選>.json --record --attempt 1
```

（2026-10-22 稽核補記：重現 004 時，候選寫 `--model seasonal-record@1.0.0`，基準寫 `--model seasonal-freq`；見 B 的註記。）

**預期**：比較文件多一筆「驗證組 · 第 1 次」，含兩區 Brier、差距、區間、判定，以及「更深」分組的 Brier。

- **第一次看到驗證組的結果**，在這一步之前都沒有看過。
- 判定「未優於」時：記錄原因，最多再修改兩次（`--attempt 2 --change "…"`）。

## E 規則回測並列（US3，FR-015–FR-021）

```text
uv run steamsage backtest-rule --split validation --rule 1.0.0                                   # 現行模型＋現行規則
uv run steamsage backtest-rule --split validation --rule 2.0.0 --model seasonal-record --param …  # 候選
uv run steamsage compare-rule <現行>.json <候選>.json --record
```

（2026-10-22 稽核補記：重現 004 時，候選寫 `--model seasonal-record@1.0.0`，基準寫 `--model seasonal-freq`；見 B 的註記。）

**預期**：

- 並列列出各組到價率、時間誤差、甜蜜時點分布、現在買的後續、照建議買、事後最低價，以及差距。
- 列出願望清單的分組差異。
- 比較文件多一筆「規則回測並列」。
- 另外可以跑「候選＋規則 1.0.0」與「現行＋規則 2.0.0」，分開看模型與規則各自的影響。
- **使用者看過之後決定換不換**：`compare-rule … --decision "…"`。

## F 換版（US4，FR-023–FR-027；只有 D 判定「優於」而且使用者同意時）

1. `CURRENT_MODEL` 改成 `seasonal-record 1.0.0 {…}`，`CURRENT_RULE` 改成 `2.0.0`。
2. `uv run steamsage backtest-rule`：完整資料集、現行組合。把數字寫進 RuleBacktestFigures 與模型定義的「規則回測」一節。
3. `uv run steamsage report --open`。

**預期**：

- 頁首顯示新模型與規則 2.0.0。
- 提示是新模型的 `notes`，不再出現「目前的模型無法預測比過去更深的折扣」。
- 變動標示註明版本改變。
- `pytest` 的一致性檢查通過。

## G 切回舊模型（FR-026）

暫時把 `CURRENT_MODEL` 改回 `seasonal-freq`，然後產生報告。

**預期**：報告恢復舊模型的提示。規則 2.0.0 沒有舊模型的回測數字時，顯示「規則尚未以現行模型回測」。檢查完改回來。

（2026-10-22 稽核補記：實際顯示的是報告自己寫的「甜蜜價規則尚未以現行模型與規則回測：本報告不引用任何準確率。」，
這句不在 `notes` 裡；`seasonal-freq` 的提示不需要數字，照舊放在 `notes`。`src/sweetspot/report/html.py` 的 `_backtest_note`。）

## H 效能（SC-009）

`uv run steamsage backtest --model seasonal-record …`：兩區完整回測在 10 分鐘內完成（預期約 2 分鐘）；`report` 仍在 30 秒內。
實測值寫進 validation.md。

## I 洩漏（SC-001）

仿 002 的實機抽查：資料庫副本中，把 2025-06-01 之後的觀測改成 -99%，再以 `--as-of 2025-06-01` 用新模型預測全部遊戲。

**預期**：結果完全相同。

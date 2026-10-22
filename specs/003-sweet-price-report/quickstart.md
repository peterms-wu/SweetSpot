# Quickstart: 甜蜜價決策與 HTML 報告（feature 003）驗收情境

在真實資料庫上逐一執行，結果寫進 `validation.md`。**功能正確不代表預測準確**：準確度只看情境 G 的規則回測與 002 的回測。

前提：

- 已跑過 `uv run steamsage update`，所以 `data/steamsage.db` 有今天的現價。
- 在 Git Bash 印中文前，先設 `PYTHONIOENCODING=utf-8`。

## A 自動測試

```powershell
uv run pytest
```

預期：002 的 411 項加上本 feature 的測試，全部通過，不連網。

## B 願望清單報告（US1、US2）

```powershell
uv run steamsage report --open
```

預期：

- 瀏覽器開啟 `data/reports/latest.html`。
- 68 款每款恰好在一組；有曲線的 65 款都有甜蜜價、時點與原因（SC-002）。
- 分組大致和 research R0 的原型相同：現在買 16、即將到價 27、繼續等 11、低信心 11、無法預測 3。現價隨時間變動，數字可能不同。
- 抽查：
  - **Dying Light**：原價不一致的標籤、低信心。
  - **PRAGMATA**：改用無本身歷史曲線；原因列出 2026-09-07 的 -20%。
  - **活俠傳**：「即將到價」，不是現在買。
  - **Devil May Cry 5**：等待對照表有 5 列。
- 頁首有版本、偏好、「長期最低價可能更低」「價格指標準版本」的提示，以及規則回測的到價率。
- 耗時 ≤ 30 秒（SC-006）。實測值寫入 validation。

## C 紀錄與變動標示（US3）

1. 情境 B 完成後，`data/forecasts/` 多一份 `.json.gz`。
2. 同一天再跑一次 `uv run steamsage report`：比較基準與第一次相同（前一天或更早的紀錄），變動標示相同。
3. 第一次執行（沒有任何紀錄）：頁首顯示「沒有前一天或更早的紀錄，無法比較」。
4. 用測試資料製造一份「前一天」的紀錄，把某款遊戲的分組、時點、甜蜜價改掉；再跑一次，那款遊戲標出 3 種變動和上次的值（SC-005）。

## D 過去時點

```powershell
uv run steamsage report --as-of 2025-06-01
```

預期：

- 寫出 `data/reports/asof-2025-06-01.html`。
- `data/forecasts/` 沒有新檔。
- 不顯示變動。

## E 中斷

用測試讓寫紀錄的步驟在改名前失敗：

- 不會留下 `.json.gz`。
- 下一次執行的比較基準不變。
- 報告註明「本次紀錄未保存」，結束代碼 2（SC-004）。

## F 一鍵執行（US4）

1. 雙擊 `更新資料.cmd`：先更新，再開啟報告。報告的資料更新狀態顯示 0。
2. `update` 正在跑時，另開一個再雙擊：顯示「另一個更新正在執行」，報告仍以既有資料產生並開啟。
3. 暫時移除 `ITAD_API_KEY` 或斷網再執行：update 結束代碼 2 或 1，報告頁首醒目標示「本次資料更新未完成」。

## G 規則回測（US5）

```powershell
uv run steamsage backtest-rule
```

預期：

- 結果檔寫到 `data/backtests/`。
- 到價率依分組與信心列出，數字應該接近 research R0：一般信心約 93%、低信心約 20%。
- 資料集識別碼和 `steamsage backtest --region TW` 在同一截止時間下相同。
- 耗時約 10–30 秒。
- 數字寫入 `docs/model/model-definition.md` 的決策規則章節，以及程式常數 `RULE_BACKTEST`（測試檢查兩者一致）。

## H 偏好設定

在 `steamsage.toml` 加上：

```toml
[preferences]
tolerance_min_twd = 0
```

再跑一次 `report`：

- Dying Light 這類便宜遊戲的目標折扣改變。
- 頁首與比較說明顯示偏好改變（FR-021、FR-036）。

改回預設值後，結果恢復。

## I 安全

用測試資料放一款名稱為 `<script>alert(1)</script>` 的遊戲：

- 報告只顯示文字。
- 報告中沒有任何外部資源（FR-027、FR-028）。

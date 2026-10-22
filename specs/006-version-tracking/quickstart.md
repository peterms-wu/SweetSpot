# Quickstart: 版本追蹤的驗收

實作完成後，照順序執行。在 Bash 印中文前先設 `PYTHONIOENCODING=utf-8`。

## 1 測試

```bash
uv run pytest
```

- 預期：005 的 748 個測試全部通過，加上本 feature 新增的測試。
- 功能測試通過不代表預測變準（SC-008）；本 feature 不宣稱提升準確度。

## 2 遷移

先確認資料庫是 v2，再執行一次每日更新（會自動遷移）：

```bash
uv run steamsage update
```

- stderr 出現「資料庫升級到 v3…」，`data/steamsage.db.bak-v2` 存在。
- 遷移耗時寫進驗收文件（research R8 估計 10 秒以內）。
- 再執行一次 `update`：不再遷移。

## 3 版本（真實願望清單，SC-001、SC-003）

`update` 的摘要 `versions`：

| 項目 | 預期 |
|---|---|
| `changed` | Dying Light：Dying Light → Dying Light: Essentials Edition |
| `rejected` | 範例分季作品 - Season 1，`bundle`（`bundle/99003`） |
| `unchanged` | 其他有價格的遊戲 |
| `no_option` | 尚未發售、沒有價格的遊戲。（2026-10-22 稽核補記）實際只數免費、不能購買、下架的遊戲；尚未發售的遊戲不進版本步驟、不計入（`pipeline/daily.py`） |
| 版本步驟耗時 | 第一次 < 10 秒，之後每天 < 3 秒（SC-007 的上限是 30 秒） |

隔天再執行 `update`：`changed` 為空（沒有重複記錄更換）。

## 4 報告（SC-001、SC-002、SC-005）

```bash
uv run steamsage report --open
```

- Dying Light：
  - 名稱下方顯示「追蹤 Dying Light Essentials Edition · 歷史從 2025-06-26 起 · 偵測到版本更換」。
  - 原價 NT$670，不再有「原價不一致」；決策依 Essentials Edition 的歷史（原型 P3：即將到價，2026 秋特 NT$101）。
  - 變動欄顯示「版本更換」（只在這一份報告）。
- 範例分季作品 - Season 1：「無法預測」，原因寫出組合包。
- 其他遊戲：和遷移前最後一份正式紀錄相比，除了 Dying Light，沒有任何組別、甜蜜價或甜蜜時點的變化（SC-002）。
  頁首出現「規則 sweet-price 2.0.0 → 2.1.0」。
- 390px 寬度沒有水平捲動：`uv run --with playwright python 腳本`。

## 5 回測資料集不變（SC-006、FR-016）

```bash
uv run steamsage backtest --cutoff 2026-09-25 --region TW
```

- 台灣區資料集識別碼仍是 `d547c29d…`。
- 規則 2.1.0：`uv run steamsage backtest-rule --cutoff 2026-09-25` 的每個決策和 2.0.0 的結果檔逐案相同（只差規則版本）。

## 6 停止追蹤（SC-004）

真實資料目前沒有「沒有其他版本可用」的停止追蹤遊戲，所以用測試驗收（人工資料：版本紀錄的 ITAD Steam 現價筆數為 0）。
另外在資料庫複本上重跑原型 P3 的 stopped 版本，確認報告顯示「價格歷史停止更新（最後確認 2025-01-27）」與低信心。

## 7 驗收文件

寫 `specs/006-version-tracking/validation.md`：

- 上面各步驟的實際結果與耗時。
- FR-017：回測資料集中停止追蹤、混了多個商品的序列數與款數（原型 P4：停止追蹤 1 款、ITAD 多筆現價 2 款、原價來回切換 9 款），以及是否建議之後建立新版資料集。
- 決策原因的措辭抽查（Dying Light、範例分季作品、停止追蹤的複本）。

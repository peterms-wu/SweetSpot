# Quickstart: 特賣日期自動更新（驗證指南）

**Feature**: 012-sale-calendar-sync。在 worktree `〈專案資料夾〉-012` 開發；主資料夾留在 master（秋特期間的每日背景更新）。

## 前置

- worktree 沒有 `data/steamsage.db` 與 `steamsage.toml`（不進版控）。測試用暫存資料庫；真實資料的檢查**複製**主資料夾的資料庫到
  `specs/012-sale-calendar-sync/prototype/out/`（schema 會升到 v6，不能直接用主資料夾的檔案）。
- 測試不連網：官方頁面用 `tests/fixtures/partner/` 的精簡副本（2026-09-27 的頁面與 Wayback 上 3 種日期寫法各一份，只留「Dates」一節）。

## 1. 自動測試

```powershell
uv run pytest -o addopts="" -q                      # 全部；1217 + 本 feature 的新測試
uv run pytest -o addopts="" -q tests/unit/test_steam_partner.py tests/unit/test_calendar_sync.py
node --test "tests/extension/*.test.js"             # 31 passed（擴充功能不變）
uv run --with playwright python tests/extension/e2e.py   # 68/68
```

## 2. 對照 spec 的成功標準

| SC | 怎麼驗證 | 預期 |
|---|---|---|
| SC-001 | 解析 2026-09-27 的頁面副本並和 `data/steam_sales.toml` 比對 | 4/4 一致，新增 0、不一致 0、提醒 0 |
| SC-002 | 整合測試：頁面副本多一場 2027 秋特 → 每日更新的行事曆步驟 | 行事曆有這一場（官方）、推估被取代、決策標示官方；toml 不變 |
| SC-003 | 整合測試：逾時、403、429、空白頁、格式改變 | 每種都完成其他步驟，行事曆＝只讀檔案時，各 1 行提醒 |
| SC-004 | 洩漏測試（含反向測試）；在同一份資料庫副本上跑本分支與 master：`uv run steamsage backtest --cutoff 2026-09-25 --split tuning`（master 用 git worktree 執行） | 結果相同 |
| SC-005 | 資料庫副本上跑 `update`（真的抓 1 次官方頁面）與 `report`，和 master 在同一份資料上逐款比對 | 68/68 相同；報告與擴充功能資料檔只差新增的摘要欄位 |
| SC-006 | 資料庫副本上跑 `update` 5 次，看 `official_page.seconds` 與 `http_usage` | 中位數 ≤ 3 秒；`steam-partner` 1 個請求，沒有其他新網站 |
| SC-007 | `calendar --sync --write` 在測試用的行事曆副本上 | 驗證通過；原有位元組不變；沒有差異時修改時間不變 |
| SC-008 | 頁面副本冬特 +1 天 → 更新 → `calendar --sync --write` → 再更新 | 提醒兩邊日期、預測用檔案的日期；寫回後一致 |

## 3. 手動看一次

```powershell
uv run steamsage calendar --fetch --check        # 1 個請求；列出比對結果
uv run steamsage calendar --sync                 # 今天應為「已一致」
```

## 4. 合併前

- 合併後第一次在主資料夾執行 `update` 會把資料庫升到 v6（自動備份 `data/steamsage.db.bak-v5`，約 160 MB）；每日背景更新本來就先跑 `update`。
- 在秋特結束（10/9 01:00 台北）之前不合併，除非使用者決定。

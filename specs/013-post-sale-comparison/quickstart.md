# Quickstart: 事後對照（驗證指南）

**Feature**: 013-post-sale-comparison。在 worktree `〈專案資料夾〉-013` 開發；主資料夾留在 master（每天 02:30 的背景更新）。

## 前置

- worktree 沒有 `data/` 與 `steamsage.toml`。指令唯讀，真實資料的檢查直接用主資料夾的檔案：
  `--config 〈專案資料夾〉\steamsage.toml`（資料庫與 `data/forecasts/` 由設定檔的 `data_dir` 決定）。
  預設的 `--out` 也在那個 `data_dir` 底下，所以開發期間一律明確給 `--out`，不寫入主資料夾。
- 測試不連網、不用真實資料庫：小型測試資料庫＋測試紀錄（3–5 款，結果事先手算）。

## 1. 自動測試

```powershell
uv run pytest -o addopts="" -q                                   # 全部
uv run pytest -o addopts="" -q tests/unit/test_review*.py tests/contract/test_cli_review.py
node --test "tests/extension/*.test.js"                         # 擴充功能不變
```

## 2. 真實資料

```powershell
$cfg = "〈專案資料夾〉\steamsage.toml"
$out = "specs/013-post-sale-comparison/prototype/out"
uv run steamsage review --config $cfg --sale autumn-2026 --out "$out/review-a.json"
uv run steamsage review --config $cfg --sale autumn-2026 --out "$out/review-b.json"   # SC-004：去掉 run 後逐位元組相同
uv run steamsage review --config $cfg --sale autumn-2026 --today 2026-11-01 --no-recompute --out "$out/review-nov.json"   # SC-005
uv run steamsage review --config $cfg --sale autumn-2026 --doc                     # comparisons.md 草稿
```

## 3. 對照 spec 的成功標準

| SC | 怎麼驗證 | 預期 |
|---|---|---|
| SC-001 | 真實資料的 `summary.counts` 與各組款數 | 68/68 都有結果或原因；現在買 9、即將到價 26、繼續等 28、低信心 2、無法預測 3 |
| SC-002 | 單元測試：4 部分＋5 種「無法對照」＋3 種提早到價 | 和手算相同；無法對照不進分母 |
| SC-003 | 真實資料的 `mismatches`；使用者抽看不一致與一致各 3 款 | 劍星列為依每日紀錄補正；Cyberpunk 2077（指定的組合包）一致 |
| SC-004 | 兩次輸出去掉 `run` 後比較；執行前後主資料夾的資料庫、`data/forecasts/`、`data/steam_sales.toml`、`steamsage.toml` 的 SHA-256 | 相同；雜湊不變 |
| SC-005 | `--today 2026-10-12` 與 `--today 2026-11-01` | 前者 0 個非季節單位計分並列出 10/30；後者 30 天的單位計入，60／90 天仍未到期 |
| SC-006 | 洩漏測試（含反向測試） | 分析時點之後的假資料不影響重算；移到之前會影響 |
| SC-007 | `uv run steamsage backtest --cutoff 2026-09-25 --split tuning` 在本分支與 master（git worktree、同一份資料）；`report --as-of` 與擴充功能資料檔 | 相同 |
| SC-008 | 真實資料的 `run.seconds` | 不含重算 ≤ 60 秒；含重算 ≤ 300 秒（原型：重算約 12 秒） |
| SC-009 | `comparisons.md` 新節的每個數字 | 都能在結果 JSON 找到同一個值 |

## 4. 合併前

- `docs/model/comparisons.md` 新增「事後對照」一節（由 `--doc` 的草稿整理）；HANDOFF §3 加上候選（D1 的附帶發現、R0.2 的 10/7 現象）。
- README 的指令列表加上 `review`。

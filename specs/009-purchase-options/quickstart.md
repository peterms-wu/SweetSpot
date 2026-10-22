# Quickstart: 驗收使用者指定版本、列出其他購買選項

前提：在 `009-purchase-options` 分支；`ITAD_API_KEY`、`STEAM_WEB_API_KEY` 已設定；Bash 中先 `export PYTHONIOENCODING=utf-8`。
回測指令一律明確給 `--cutoff 2026-09-25`。

## 1 測試

```bash
uv run pytest            # 本 feature 之前 1011 passed；全部通過
```

## 2 不指定：結果和之前相同（SC-001）

1. 比對方法沿用原型 P3（tasks T031）：本分支用完整的 v4 資料庫；master 用一份副本，副本刪掉 `itad-option-history`／`itad-option` 的列與
   `purchase_options` 表（只在副本上移除只新增的觸發器）。master 沒有讀取修正，不能直接讀含版本歷史的資料庫。
2. 在本分支執行 `uv run steamsage update`：
   - 第一次升級到 v4 並備份 `steamsage.db.bak-v3`。
   - 摘要的 `purchase_options` 顯示約 66 款、231 個選項、32 個版本；耗時寫入 validation（SC-008：比之前多 ≤ 30 秒）。
3. `uv run steamsage report`：68 款的組別、甜蜜價、甜蜜時點、機率、原因和步驟 1 的 master 結果相同；只多了版本清單與選用欄位。
   兩邊用同一次更新的資料（006 的教訓：更新後資料會變）。

## 3 列出其他版本（SC-003）

- 報告中有「另有 N 個版本」的遊戲數與版本數等於當天的清點（2026-09-27 為 26 款、33 個，其中可指定的 25 款、32 個）。
- 抽查：AC Odyssey「另有 3 個版本」；MiSide 沒有版本提示；Dying Light 十週年完整版列出價格與拒絕原因、沒有設定行。
- 瀏覽器檢查 390px 寬度（`uv run --with playwright python specs/006-version-tracking/prototype/check_390.py data/reports/latest.html`）。

## 4 指定一款（SC-002、SC-005）

1. 把報告中 Cyberpunk 2077 終極版的設定行複製到 `steamsage.toml` 的 `[purchase_options]`。
2. `uv run steamsage report`（可以不先 update；美國區歷史下一次更新才有，原因會寫出）：
   - Cyberpunk 2077 的原價 NT$2,206、甜蜜價依終極版計算，版本行顯示「（使用者指定）」，變動欄「版本更換（使用者指定）」。
   - 其他 67 款的結果和指定前逐款相同（validation 附比對結果）。
3. 再產生一次報告：變動欄不再有版本更換，版本行仍在。
4. 刪掉設定行再產生報告：變動欄「版本更換（取消指定）」。

## 5 指定不能用（SC-004）

- 設定一個不存在的選項（例如 `1091500 = "sub/1"`）、一個含其他遊戲的組合包、一個格式錯誤的值、一個不在願望清單的 App：
  前兩者退回預設並附原因；後兩者被忽略並警告；其他遊戲不受影響。

## 6 回測不變（SC-007）

```bash
uv run steamsage backtest-rule --cutoff 2026-09-25        # 資料集識別碼仍是 d493ac02…，決策逐案相同
```

## 7 驗收文件

`specs/009-purchase-options/validation.md`：SC-001～SC-009 的結果、實測耗時、指定前後的逐款比對、真實願望清單的原因措辭抽查。

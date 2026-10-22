# Quickstart: Chrome 擴充功能（feature 011）驗收

## 1. 測試

```powershell
uv run pytest -o addopts="" -q                       # 既有 1180 個＋本 feature 的 Python 測試
node --test "tests/extension/*.test.js"                         # JS 單元測試（格式化、過舊、對應、靜態網路檢查、manifest）
uv run --with playwright python tests/extension/e2e.py          # 端對端，只用測試頁（不連 Steam）
uv run --with playwright python tests/extension/e2e.py --live   # 另外在真實 Steam 頁面上檢查並截圖（未登入）
```

預期：全部通過；e2e 印出「擴充功能發出的請求 0」與「改寫資料檔後讀到新檔（未重新載入）」。

## 2. 產生資料檔（真實資料）

```powershell
uv run steamsage report
```

預期：`extension/data/steamsage-extension.json` 更新（≤ 500 KB）；`report` 多花 ≤ 0.5 秒（和改版前比較，各跑 3 次）；
`data/reports/latest.html` 和改版前在同一份資料上逐位元組相同（validation 用 git worktree 的 master 比對）。
`uv run steamsage report --as-of 2026-09-26` 與 `--rule 3.0.0` 不改資料檔的修改時間。

## 3. 安裝（使用者的 Chrome，一次）

1. Chrome 網址列輸入 `chrome://extensions`，右上角打開「開發人員模式」。
2. 「載入未封裝項目」→ 選 `〈專案資料夾〉\extension`。
3. 工具列的拼圖圖示 → 把 SteamSage2 釘選到工具列。

## 4. 使用者的 Chrome 上實測（登入 Steam）

| # | 步驟 | 預期 |
|---|---|---|
| 1 | 點工具列圖示 | 1 秒內出現；五組款數和 `latest.html` 相同；圖示數字＝「現在買」款數 |
| 2 | 打開「光與影：33號遠征隊」、Cyberpunk 2077、一款無法預測的遊戲 | 面板在購買區正上方；數字和報告相同；Cyberpunk 註明使用者指定的版本、頁面現價取終極版 |
| 3 | 打開自己的願望清單，從頭捲到尾 | 每一列都有一行（包含未登入時看不到的 9 款）；沒有重複；名稱與 Steam 原本的內容都在 |
| 4 | 執行 `uv run steamsage report`，**不重新載入擴充功能** | 重開彈出視窗、重新整理頁面就看到新的報告時間（SC-004） |
| 5 | 開發人員工具 → Network，重新整理遊戲頁 | 沒有 SteamSage2 發出的請求（面板出現前後的請求和停用擴充功能時相同） |

## 5. 排程（10/1）

```powershell
Get-ScheduledTask -TaskName "SteamSage2 每日背景更新" | Get-ScheduledTaskInfo   # NextRunTime 為 02:30
(Get-ScheduledTask -TaskName "SteamSage2 每日背景更新").Triggers                # 每天 02:30，其他設定不變
```

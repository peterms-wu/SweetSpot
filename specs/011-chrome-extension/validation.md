# Validation: Chrome 擴充功能（feature 011）

2026-09-27，分支 `011-chrome-extension`。真實資料：最新正式紀錄 `20260927T070813Z`（68 款、6 個組合包）。
瀏覽器：Playwright 1.63 的 Chromium（品牌版 Chrome 137 以後不接受 `--load-extension`），Steam **未登入**。
使用者的 Chrome 154（已登入）上的試用結果見 §3。

## 1. 測試

| 測試 | 結果 |
|---|---|
| `uv run pytest -o addopts="" -q` | **1217 passed**（原 1180＋本 feature 37：golden 14、純文字函式 4、資料檔 10、契約 3、`report` 6） |
| `node --test "tests/extension/*.test.js"` | **31 passed**（lib 23、manifest 4、靜態檢查 4） |
| `tests/extension/e2e.py`（測試頁） | **68/68** |
| `tests/extension/e2e.py --live` | **106/106**（含測試頁 68 項＋真實頁面） |

## 2. Success Criteria

| SC | 實測 | 結果 |
|---|---|---|
| SC-001 彈出視窗＝報告 | 真實資料：五組款數 11／24／28／2／3＝`summary`＝報告；每款連到自己的 Steam 頁面；組合包 6 個；圖示「11」 | ✅ |
| SC-002 遊戲頁面板＝報告 | 16 款真實頁面（原型的抽樣，含使用者指定的 Cyberpunk 2077 終極版、2 款無法預測）：分組、甜蜜價、時點、機率、最低價、組合包指引都等於資料檔（資料檔＝報告的句子由同一段函式產生，pytest 比對）；頁面現價＝紀錄現價 **14/14** | ✅ |
| SC-003 願望清單 | 真實頁面從頭捲到尾：**59 列，每列恰好一行，0 重複，0 列超過 1 秒**（最慢 6 ms）；列高 174 px 不變（1280／700 px）；改版的測試頁 0 行、沒有頁面錯誤。未登入時 Steam 不列出的 9 款，使用者登入後確認也有那一行 | ✅ |
| SC-004 不重新載入就讀到新資料 | Chromium：暫存檔再改名、直接覆寫、Service Worker 被停止後都讀到新檔；遊戲頁重新整理讀到新的資料時間；alarm 的處理在沒有頁面時也更新圖示。使用者的 Chrome：執行 `更新資料.cmd` 後不重新載入就看到新資料 | ✅ |
| SC-005 對外請求 0 | 所有 e2e（含 16 個真實遊戲頁與真實願望清單）中由擴充功能發出的請求 **0**；Service Worker 連外被 CSP 擋下；資料檔不含金鑰（pytest） | ✅ |
| SC-006 1 秒內出現 | 彈出視窗 47–134 ms；遊戲頁面板在 DOMContentLoaded 後 218–318 ms；願望清單新列 ≤ 242 ms | ✅ |
| SC-007 報告多花 ≤ 0.5 秒、檔案 ≤ 500 KB | 產生＋轉 JSON＋寫檔中位數 **1.5 ms**（最慢 7.5 ms，20 次）；檔案 **140 KB**。沒有重複執行正式 `report` 來量：每次都會多寫一筆正式紀錄 | ✅ |
| SC-008 秋特前安裝並確認 | 2026-09-27 使用者安裝並確認可用；排程下一次執行 2026-09-28 02:30 | ✅ |
| SC-009 決策、紀錄、HTML 不變 | 分析核心（`decision`、`forecast`、`store`、`pipeline`）和 master 沒有差異；28 份正式紀錄用 master（git worktree）與本分支 render 的 HTML **逐位元組相同**；另有 14 份 golden 測試 | ✅ |

## 3. 使用者的 Chrome（2026-09-27）

| 項目 | 結果 |
|---|---|
| 安裝（載入未封裝項目） | ✅ |
| 登入後的願望清單：未登入看不到的 9 款也有那一行 | ✅ 使用者確認「正常」 |
| `更新資料.cmd` 後不重新載入就看到新資料 | ✅ 使用者確認「正常」 |
| 使用者回饋與修正 | 沒有需要修正的項目 |

## 3.1 排程（FR-017）

2026-09-27 經使用者同意，以 `Set-ScheduledTask … -Trigger (New-ScheduledTaskTrigger -Daily -At 02:30)` 只改觸發時間。改前後比對：
動作（`conhost.exe --headless cmd.exe /d /c "…\背景更新.cmd"`）、工作目錄、`StartWhenAvailable = True`、電池設定、執行時間上限 1 小時、
帳戶（互動式、一般權限）都不變；`NextRunTime` 2026-09-28 02:30。

## 4. 發現並修正的問題

| 問題 | 發現方式 | 處理 |
|---|---|---|
| 願望清單的行插在名稱後面：擠壓名稱；讓名稱容器換行則把名稱擠出可視範圍 | plan 原型的截圖 | 改插在 grid 的 `mid` 區（research R0.2） |
| clarify 寫的資料時間欄位 `observed_at` 語意不對 | plan 原型 | 改用 `confirmed_at`（spec 已改） |
| e2e 的真實願望清單只看到 16 列卻判為通過（捲動太快，列表沒有跟上） | 看輸出的列數 | 捲動前等 1.5 秒、每步等 1 秒（和原型相同），並加上「至少 50 列」的檢查 |
| e2e 的請求計數把擴充功能自己的檔案算進去 | 輸出 18 個 `chrome-extension://` 網址 | 只計外部網址 |
| `node --test tests/extension/` 在 Node 24 不接受資料夾 | 執行失敗 | 改用 `"tests/extension/*.test.js"`（文件已改） |

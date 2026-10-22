# Quickstart: 在 Steam 遊戲頁直接指定追蹤版本（驗收步驟）

**Feature**: 015 | [spec.md](spec.md) | [plan.md](plan.md) | 契約：[native-host.md](contracts/native-host.md)、[extension-ui.md](contracts/extension-ui.md)

## 0. 前提

- 在 015 的 worktree（`〈專案資料夾〉-015`）開發與跑自動測試；**使用者的 Chrome 驗收在合併到 master 之後**做
  （Chrome 載入的是 `〈專案資料夾〉\extension`，背景更新也在 master 執行）。
- 自動測試不碰真的設定檔、資料庫與使用者的 Chrome 登錄（research R9）。

## 1. 自動測試

```
uv run pytest
node --test "tests/extension/*.test.js"
uv run --with playwright==1.63.0 python tests/extension/e2e.py
```

預期：全部通過。e2e 的結尾印出「擴充功能發出的網路請求：0」，並確認 `Software\Chromium\NativeMessagingHosts\` 下沒有留下測試用的鍵。

分項對照：

| 項目 | 在哪裡驗 |
|---|---|
| SC-002 ≥ 20 種錯誤或惡意請求全部拒絕、檔案逐位元組不變、日誌無金鑰 | pytest：本機程式的安全測試 |
| SC-003 只差一行 | pytest：設定檔逐行編輯（含註解、空行、CRLF、其他區段與其他指定） |
| SC-004 每一步注入失敗後還原 | pytest：處理流程的失敗注入 |
| SC-005 和手動寫同一行再 `report` 相同 | pytest：兩條路徑的輸出比對（除了產生時間） |
| SC-006 沒有本機程式時 011 的端對端照常、請求為 0 | e2e |
| SC-007 背景更新進行中 1 秒內拒絕 | pytest（鎖被占用）＋ e2e（假的本機程式回覆 `busy-update`） |
| SC-008 單按一次、頁面程式觸發（≥ 5 種）送出 0 次 | node --test（狀態）＋ e2e（實際觸發） |

## 2. 安裝本機程式（合併到 master 之後，使用者的電腦）

```
cd 〈專案資料夾〉
uv run steamsage report
uv run steamsage host install
uv run steamsage host status
```

`report` 先產生一次新格式的擴充功能資料檔（含 `versions`）；合併前 02:30 產生的資料檔沒有這個欄位，「版本」一節不會出現
（2026-10-14 驗收時漏了這一步；之後面板會顯示「資料檔是舊版…」）。

預期：印出這個程式能做與不能做的事；`status` 顯示已登記、允許的擴充功能編號和 `chrome://extensions` 上 SweetSpot 的編號相同。

第一次安裝時：先在 `chrome://extensions` 對 SweetSpot 按「重新載入」（編號會改成固定的那一個），再看編號。

## 3. 使用者的 Chrome：指定與改回（SC-001、US1）

1. 先備份：`copy steamsage.toml data\steamsage.toml.before-015`（不放在本機程式自己的 `data\host\`）。
2. 打開 Cyberpunk 2077 的遊戲頁（`/app/1091500/`），面板最下面「版本（2）」→ 展開。
   - 預期：終極版「追蹤中（使用者指定）」、本體「Steam 預設」與「改回 Steam 預設」。
3. 按「改回 Steam 預設」→ 按鈕變成「確定改回 Steam 預設？再按一次」→ 再按一次。
   - 預期：進度提示；30 秒內面板換成本體的數字（現價 -70% 那一個），版本一節本體為「追蹤中」，終極版有「追蹤這個版本」。
   - `steamsage.toml` 和備份相比只少了 `1091500 = …` 那一行（`git diff --no-index data\steamsage.toml.before-015 steamsage.toml` 比對；PowerShell 的 `fc` 是 `Format-Custom`，不能用）。
4. 對終極版按「追蹤這個版本」並確認。
   - 預期：面板回到終極版的數字；設定檔多了一行 `1091500 = "bundle/32470"   # 《電馭叛客 2077：終極版》（…從 Steam 頁面指定）`
     （決定 D7），其他內容和備份相同。
5. 在 Steam 的購買框：終極版的框顯示「SweetSpot：追蹤中」，本體的框有「SweetSpot：改回 Steam 預設」（指定的是終極版，所以選本體＝改回），
   原聲帶等框沒有東西（US4）。按本體框的捷徑兩下：結果和第 3 步相同，本體的框變成「追蹤中」、終極版的框變成「SweetSpot：追蹤這個版本」；再用捷徑指定回終極版。
6. 看 `data\logs\steamsage-<今天>.log`：每次指定一行 `host choose …`，沒有金鑰。

## 4. 沒有安裝時（US2）

```
uv run steamsage host uninstall
```

重新整理 Cyberpunk 2077 的頁面，展開「版本」一節。預期：顯示「安裝本機程式後可在這裡指定」與可以手動貼的設定行；面板其他內容、彈出視窗、願望清單都和平常相同。
（2026-10-22 稽核補記：commit 5925272 起）預期改為：一節最上面是安裝說明（「要在這裡直接指定版本：在 … 開啟命令列，執行 uv run sweetspot host install，然後重新整理這一頁。…」），
每個可指定的版本是手動步驟加可選取的設定行；文字見 [contracts/extension-ui.md](contracts/extension-ui.md)「版本」一節。
驗收完再執行一次 `uv run steamsage host install`。

## 5. 背景更新期間（US3 情境 3）

不需要等 02:30：在另一個視窗執行 `uv run steamsage update`（約 2 分鐘），期間在面板按指定並確認。預期：1 秒內顯示「背景更新進行中，請稍後再試」，設定檔不變。

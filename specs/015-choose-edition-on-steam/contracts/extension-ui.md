# Contract: 擴充功能的變更（015）

**Feature**: 015 | spec FR-001–FR-006b、FR-010、FR-011、FR-021、FR-023–FR-025 | 延伸 [011 extension-ui.md](../../011-chrome-extension/contracts/extension-ui.md)

## manifest

- `permissions`：`["alarms", "nativeMessaging"]`（FR-021：只多這一項）。
- 新增 `key`（決定 D1；擴充功能編號因此固定，第一次要在 `chrome://extensions` 重新載入）。
- `content_security_policy` 不變（`connect-src 'self'`）；網路請求仍為 0。
- `version` 改為 `1.1.0`；`description` 改為「…只讀本機資料檔，不連外；安裝本機程式後可在遊戲頁指定追蹤版本」。

## 訊息（內容腳本 → Service Worker）

011 的 `{type: "data"}` 不變。新增：

```js
{type: "host", cmd: "status", app: 1091500}
{type: "host", cmd: "choose", app: 1091500, option: "bundle/32470"}
{type: "host", cmd: "reset",  app: 1091500}
```

Service Worker 轉送前檢查（第一道，本機程式仍會以資料庫重新檢查）：

- `sender.url` 是 `https://store.steampowered.com/app/<app>/…`，且 `<app>` 與訊息的 `app` 相同；
- 資料檔讀得到，`app` 在 `games` 中；`choose` 的 `option` 是這款遊戲 `versions` 中 `action` 為 `choose` 或 `reset` 的那一項；`reset` 要有 `action: "reset"` 的項目。

不符合 → 回覆 `{ok: false, code: "refused"}`，不呼叫本機程式。符合 → `chrome.runtime.sendNativeMessage("com.sweetspot.edition", {v: 1, cmd, app[, option]})`：

- `chrome.runtime.lastError` 為 `Specified native messaging host not found.` → `{ok: false, code: "not-installed"}`；其他錯誤 → `{ok: false, code: "unavailable", message}`。
- 本機程式的回覆原樣轉給內容腳本；`choose`／`reset` 成功且 `changed: true` 時，先重新讀資料檔、更新圖示，回覆中附上新的 `data`。

## 遊戲頁面板：「版本」一節（FR-001–FR-003、FR-023）

位置：面板內容的最後（原因之後），用 `<details>`，標題「版本（N）」，預設收合；`versions` 少於兩項時不顯示。已擁有時跟著面板收合（spec Edge Cases）。

展開時查詢一次 `status`（FR-023a），之後同一頁沿用。每個版本一列：

```
《電馭叛客 2077：終極版》  NT$882 -60%   追蹤中（使用者指定）
Cyberpunk 2077            NT$479 -70%   Steam 預設  [改回 Steam 預設]
```

| 本機程式狀態 | `action: "choose"` | `action: "reset"` | 其他 |
|---|---|---|---|
| 可用 | 「追蹤這個版本」按鈕 | 「改回 Steam 預設」按鈕 | 追蹤中：「追蹤中」；不可指定：`reason` |
| 未安裝 | 手動步驟「手動指定：用記事本打開 SweetSpot 資料夾的 steamsage.toml，在 [purchase_options] 那一行的下面加上下面這一行…存檔後執行 更新資料.cmd，再重新整理這一頁。」＋`manual`（可選取的設定行） | 「手動改回：…找到以「<app> =」開頭的那一行，整行刪掉…」（沒有要複製的東西） | 同上 |
| 無法使用 | 同上 | 同上 | 同上 |
| 查詢中 | 「檢查本機程式…」 | 同左 | 同上 |

未安裝與無法使用時，一節最上面另有一段說明（2026-10-14 使用者驗收時指出原本的「安裝本機程式後可在這裡指定」沒有說怎麼裝、手動要改哪個檔案）：

- 未安裝：「要在這裡直接指定版本：在 SweetSpot 資料夾（extension 資料夾的上一層）開啟命令列，執行 uv run steamsage host install，然後重新整理這一頁。在那之前，可以照下面各版本的步驟手動指定。」
- 無法使用：「本機程式無法使用（Chrome：message）：在 SweetSpot 資料夾重新執行 uv run steamsage host install（專案資料夾搬家後會這樣），然後重新整理這一頁。」＋同一句「在那之前…」。

**完整路徑（2026-10-14 使用者選定提案 A）**：資料檔的 `config_path`（報告用的設定檔絕對路徑）存在時，「SweetSpot 資料夾（extension 資料夾的上一層）」
換成它的資料夾（例如「在 `〈專案資料夾〉` 開啟命令列」），「SweetSpot 資料夾的 steamsage.toml」換成完整路徑。資料夾、指令
`uv run steamsage host install` 與設定檔路徑以可選取的程式碼格式顯示（`.vcode`）。舊資料檔沒有 `config_path` 時沿用上面的文字。
路徑只在未安裝與無法使用時出現；面板是 open shadow DOM，Steam 頁面的程式技術上讀得到這段文字（提案時已說明）。

> 2026-10-22 稽核補記：「查詢中」那一列原本在上表裡，2026-10-14（commit 5925272）在表格後面加說明時被擠到說明的後面、表格因此斷開；已搬回表格，文字沒改。

`status.choice` 和資料檔的追蹤中版本不一致時（research R5），在一節最上面顯示「設定檔已指定《…》，報告還沒重新產生」。
（2026-10-22 稽核補記）`status.choice` 是 null（設定檔沒有指定）而資料檔追蹤的是使用者指定的版本時，顯示「設定檔已改回 Steam 預設，報告還沒重新產生」；`choice` 指向不能選的版本時不顯示（報告會說明）。
（2026-10-22，014 T081）本機程式回 `unavailable` 時，面板的說明「本機程式無法使用（Chrome：…）」只包 Chrome 或本機程式的原始訊息一次；以前包的是已經組好的整句，畫面上出現兩層（`lib.js` 的 `hostState`）。
（2026-10-22，014 T068）`config_ok` 是 false 時不比較、不顯示這兩句：本機程式讀不到設定檔，`choice` 是 null 不代表改回了預設（以前會誤說「已改回」）。設定檔的問題照常顯示在狀態列。

## 按兩下確認（FR-006、FR-006a、FR-006b）

- 只處理 `event.isTrusted` 的點擊（research R7）。
- 第一次按：按鈕文字變成「確定追蹤《名稱》？再按一次」／「確定改回 Steam 預設？再按一次」；5 秒內再按才送出；逾時或按了面板其他地方就恢復。
- 送出後：這一節最上面顯示「正在指定《名稱》並重新產生報告…」（改回時「正在改回 Steam 預設並重新產生報告…」），這款遊戲的所有按鈕（面板與購買框）停用。
- 成功（`changed: true`）：用回覆中的新資料重畫整個面板與購買框的按鈕（FR-011），一節最上面顯示「已改為追蹤《名稱》」。`changed: false`：「設定已經是這樣，不需要重新產生」。
- 失敗：顯示 `message`，按鈕恢復可用。
- 60 秒還沒有回覆：顯示「報告仍在產生，完成後重新整理頁面即可看到」，按鈕維持停用到這一頁重新整理（FR-010）。

> 2026-10-22 稽核補記：送出後（60 秒內有回覆）一節最上面的文字由 `extension/lib.js` 的 `replyText` 決定，照程式的字串：
>
> | 回覆 | 文字 |
> |---|---|
> | 沒有回覆 | 本機程式沒有回覆 |
> | `ok`，`changed: false` | 設定已經是這樣，不需要重新產生報告 |
> | `ok`，`changed: true`，`choose` | 已改為追蹤《名稱》（名稱本身已有《》時不再加） |
> | `ok`，`changed: true`，`reset` | 已改回 Steam 預設 |
> | `code: "refused"` | 這個請求不符合目前的資料，沒有送出（請重新整理頁面） |
> | `code: "not-installed"` | 找不到本機程式（可能已經移除），沒有改任何設定；這一頁的本機程式狀態同時改成「未安裝」（顯示安裝說明與手動步驟） |
> | `code: "unavailable"` | 本機程式無法使用（Chrome：`message`，沒有時「未知的錯誤」）：在 SweetSpot 資料夾重新執行 uv run sweetspot host install（專案資料夾搬家後會這樣），然後重新整理這一頁。 |
> | 其他失敗 | 本機程式回覆的 `message` 原樣顯示；沒有 `message` 時「本機程式回覆錯誤（`code`）」 |
>
> 上面「`changed: false`」一句的程式字串比本節原文多「報告」兩字；「失敗：顯示 `message`」只適用於最後一列。

## Steam 購買框的捷徑（FR-004、US4）

- 讀購買框的方式和 011 `readBlocks` 相同；每個框以 `subid`／`bundleid` 對應 `versions`。
- 有任何一個框讀不到 `subid` 與 `bundleid` → 一個捷徑都不放（不猜）。
- 對應到 `action` 為 `choose`／`reset` 的框：在框內的購買按鈕區前加一個小的 shadow DOM 節點「SweetSpot：追蹤這個版本」（`reset` 為「SweetSpot：改回 Steam 預設」）；
  對應到追蹤中的框：「SweetSpot：追蹤中」（沒有按鈕）。其他框不放。不改 Steam 自己的任何節點。
- 捷徑的確認方式與面板相同；第一次按下時才查詢 `status`；未安裝或無法使用時捷徑變成「需要安裝本機程式（見 SweetSpot 面板）」並展開面板的「版本」一節。
- 進度與結果都顯示在面板的「版本」一節（並自動展開）。

## 舊版資料檔（合併後補上，2026-10-14）

資料檔有任何一款遊戲缺少 `lib.js` 的 `GAME_FIELDS`（目前只有 `versions`）時，是更新擴充功能之前的報告寫的：面板頂端顯示
「資料檔是舊版，部分功能不會顯示：請執行 更新資料.cmd 重新產生」，「版本」一節與捷徑不出現。之後的 feature 開始讀新的每款遊戲欄位時加進 `GAME_FIELDS`。

## 不變的部分

- 願望清單頁、彈出視窗：沒有任何按鈕；行為與 2026-10-14 相同（FR-005）。
- 資料檔讀不到時：不顯示任何東西（011 FR-007）。
- 錯誤只影響自己的節點（011 FR-008）。

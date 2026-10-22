# Data Model: 在 Steam 遊戲頁直接指定追蹤版本

**Feature**: 015-choose-edition-on-steam | **Date**: 2026-10-14 | **Plan**: [plan.md](plan.md)

資料庫結構**不變**（仍是 v7）；正式紀錄、決策契約、HTML 報告都不變。新增或改變的是：擴充功能資料檔的一個欄位、本機程式的訊息、
本機程式的安裝檔案與登錄、執行期狀態。訊息的完整格式見 [contracts/native-host.md](contracts/native-host.md)。

## 1. 擴充功能資料檔：每款遊戲的 `versions`（spec FR-024）

和 spec FR-024 的對應：「是否可指定」是 `action`（不是 null 就有按鈕），「設定行」是 `manual`（`choose` 時就是報告的設定行）。

`steamsage.extension/1` 的 `games[]` 每一項新增 `versions`（陣列）。格式識別不變；舊版擴充功能忽略這個欄位。

| 欄位 | 型別 | 來源（決策字典） | 說明 |
|---|---|---|---|
| `kind` | `"sub"` \| `"bundle"` | `version.option.kind`／`editions[].kind` | |
| `id` | int | `version.option.id`／`editions[].id` | 和 Steam 購買框 form 的 `subid`／`bundleid` 比對（011 頁面現價並列） |
| `name` | string \| null | `version.option.name`／`editions[].name` | 只當文字顯示（FR-025） |
| `price_twd` | int \| null | 追蹤中：`current.price_twd`；其他：`editions[].price_twd` | 未知為 null（憲章 I） |
| `cut_pct` | int \| null | 追蹤中：`current.cut_pct`；其他：`editions[].cut_pct` | |
| `is_default` | bool | 見下 | 是不是 Steam 預設的購買選項 |
| `tracked` | bool | 第一項為 true，其他為 false | |
| `action` | `"choose"` \| `"reset"` \| null | 見下 | 按鈕要做什麼；null 表示沒有按鈕 |
| `reason` | string \| null | `html.edition_refusal_text(editions[])` | 不可指定的原因：和報告「其他版本」表的同一句（011 D1） |
| `manual` | string \| null | 見下 | 沒有本機程式時顯示的手動做法（句子由 Python 產生，011 D1） |

組成規則（`report/extension.py`，不重算）：

- 第一項是**追蹤中**的版本（`version.option`）；沒有 `version.option`（沒有購買選項紀錄）時 `versions` 為 `[]`。
- 接著是 `editions` 的每一項，順序不變（Steam 商店的順序）。
- 追蹤中的 `is_default`：`version.basis` 不是 `user`，或 `editions` 中沒有任何 `is_default` 的項目（使用者指定的就是預設版本）。其他項目照 `editions[].is_default`。
- `action`：
  - 追蹤中 → null（顯示「追蹤中」，使用者指定時加「（使用者指定）」）。
  - `editions` 中 `unset_hint` 為 true 的 Steam 預設 → `"reset"`（spec FR-003：對預設版本按下等同改回）。
  - `config_line` 不是 null（009 驗證通過）→ `"choose"`。
  - 其他 → null，`reason` 寫出原因（報告的同一句：核對未通過的原因，或「沒有 ITAD 的價格歷史，不能指定」）。
- `manual`：`choose` 為 `config_line`（例如 `1091500 = "bundle/32470"`）；`reset` 為「刪掉設定檔 [purchase_options] 中 1091500 那一行」；其他為 null。
- 「版本」一節只在 `versions` 至少兩項時顯示（spec FR-001）。

真實資料（2026-10-14 最新正式紀錄，實作時實測）：69 款中 24 款有「版本」一節，其他版本共 31 個（30 個 `choose`、1 個 `reset`）；資料檔 147 KB → 165 KB（+18 KB，原本預估 10 KB；011 plan 的目標 ≤ 200 KB、spec 上限 500 KB）。

## 2. 本機程式的請求與回覆（spec FR-014–FR-018）

只存在於一次 `sendNativeMessage`（一問一答）中；結果寫進日誌（§4）。

**請求**（三種，欄位固定，多一個或少一個都拒絕）：

| `cmd` | 其他欄位 | 說明 |
|---|---|---|
| `status` | `app`（int） | 本機程式是否可用；設定檔是否可讀；這款遊戲在設定檔中的指定 |
| `choose` | `app`（int）、`option`（`"sub/N"` 或 `"bundle/N"`） | 指定版本；選的是 Steam 預設時等同 `reset`（FR-003） |
| `reset` | `app`（int） | 改回 Steam 預設：刪除那一行 |

每個請求都帶 `v: 1`（訊息格式版本）。整個請求 ≤ 512 位元組；`app` 為 1 到 2³¹−1；`option` 的數字部分同樣範圍。

**驗證**（以本機程式當下讀到的設定檔與資料庫為準，FR-016）：

- `app` 在追蹤範圍：`store.wishlist_apps()`（和 009 FR-008 的範圍相同）。
- `choose` 的 `option` 是這款遊戲最新購買選項紀錄中的一項，且 `choices.resolve_choice` 判定可用（`role` 為 `edition` 且 ITAD 核對通過，或就是 Steam 預設）。
- 設定檔可以解析；`[purchase_options]` 中這款遊戲的寫法可以安全修改（research R3）。

**處理狀態**（一次請求）：

```
收到 → 格式檢查 ─失敗→ 拒絕（bad-request）
     → 取處理鎖 ─占用→ 拒絕（busy-host）
     → 取寫入鎖 ─占用→ 拒絕（busy-update）
     → 讀設定檔、資料庫並驗證 ─失敗→ 拒絕（not-tracked／not-choosable／config-invalid／config-unsafe）
     → 沒有要改的（已經是這個設定）→ 成功（changed: false，不重新產生報告）
     → 保存原始內容（設定檔、報告、資料檔）
     → 寫設定檔 → 執行 report → 檢查結果 ─失敗→ 還原設定檔、報告、資料檔（正式紀錄保留，research R5）→ 失敗（step）
     → 成功（changed: true）
     → 釋放兩個鎖、回覆、結束
```

## 3. 本機程式的安裝（spec FR-022）

`uv run steamsage host install` 建立，`uv run steamsage host uninstall` 移除。只影響目前使用者，不需要系統管理員權限。

| 項目 | 位置 | 內容 |
|---|---|---|
| 啟動檔 | `data/host/sweetspot-host.bat` | 一行：專案 `.venv` 的 python、`-m steamsage.host`、`--config` 設定檔的絕對路徑、`%*`（research R2）；OEM 字碼頁 |
| 登記檔 | `data/host/com.sweetspot.edition.json` | `name`、`description`、`path`（啟動檔）、`type: "stdio"`、`allowed_origins: ["chrome-extension://<編號>/"]` |
| 登錄 | `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.sweetspot.edition` | 預設值 = 登記檔的絕對路徑 |

- 擴充功能編號：由 `extension/manifest.json` 的 `key` 算出（決定 D1）。
- `data/host/` 加進 `.gitignore`（含這台電腦的絕對路徑）。
- 移除時刪除登錄的鍵、啟動檔與登記檔；`data/host/` 沒有其他檔案時一併刪除，其他都不動。
  **實作時修正（2026-10-14，使用者選定）**：原本寫「刪除 `data/host/`」，但設定檔還原失敗時原本的內容存在 `data/host/restore-*.toml`（contracts/native-host.md、決定 D5），
  那可能是唯一的一份；所以只刪安裝寫的檔案，留下的檔案列在訊息中。
- 專案資料夾搬家後要重新執行安裝（啟動檔與登記檔是絕對路徑）。

## 4. 日誌（spec FR-020）

寫進現有的 `data/logs/steamsage-YYYYMMDD.log`（`logs.setup_logging`，有金鑰遮蔽）。每個請求一行，只記錄**驗證過**的欄位：

```
host choose app=1091500 option=bundle/32470 result=ok changed=true seconds=7.1
host choose app=1091500 option=sub/123 result=rejected code=not-choosable
host request result=rejected code=bad-request bytes=731
```

格式不對的請求不記錄內容，只記錄長度。`report` 自己的日誌照舊。

## 5. 鎖

| 鎖檔 | 誰取 | 被占用時 |
|---|---|---|
| `data/.host.lock`（新） | 本機程式，處理 `choose`／`reset` 的全程 | 「上一個指定還在處理」（busy-host） |
| `data/.lock`（既有） | `update`、`reference`、`import-legacy`、`calendar`，以及本機程式處理 `choose`／`reset` 的全程 | 本機程式回覆「背景更新進行中，請稍後再試」（busy-update） |

`status` 不取任何鎖。正式 `report` 照舊不取鎖（決定 D4，research R4）。

## 6. 擴充功能的執行期狀態（不保存）

每個遊戲頁一份，在內容腳本中：

| 狀態 | 值 |
|---|---|
| 版本一節 | 收合／展開；展開時查詢一次 `status`，同一頁沿用（FR-023a） |
| 本機程式 | 未查詢／可用／未安裝（`Specified native messaging host not found.`）／無法使用（其他錯誤） |
| 每個按鈕 | `idle` → `confirm`（5 秒）→ `sending` → `idle`；`sending` 時這款遊戲的所有按鈕停用（FR-006b） |
| 等待 | 送出後計時 60 秒；逾時顯示「報告仍在產生，完成後重新整理頁面即可看到」（FR-010） |

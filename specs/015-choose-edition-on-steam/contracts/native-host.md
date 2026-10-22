# Contract: 本機程式 `com.sweetspot.edition` 與 `steamsage host` 指令

**Feature**: 015 | spec FR-007–FR-022 | research R2–R6 | [data-model.md](../data-model.md) §2–§5

## 啟動

Chrome 依登記檔啟動 `data/host/sweetspot-host.bat`，參數為 `chrome-extension://<編號>/ --parent-window=0`（research R0 H）。
`.bat` 執行 `<.venv>\Scripts\python.exe -m steamsage.host --config <設定檔絕對路徑> %*`。

- 第一個 Chrome 參數不是登記的來源 → 不讀訊息，記錄一行日誌後以代碼 1 結束。
- （2026-10-22，014 T067）設定檔讀不到（不存在、不是 TOML、不是 UTF-8、有 BOM、驗證不過）時**照樣讀訊息並回覆**：`status` 回 `config_ok: false` 與說明，其他指令回 `config-invalid`（FR-017）。
  資料夾取自設定檔的 `[storage] data_dir`；設定檔連 TOML 都不是時，用設定檔旁的預設 `data`。允許的來源照樣從那裡的登記檔讀。
  以前在讀訊息之前就以 1 結束、不回覆，擴充功能因此說「本機程式無法使用…重新執行 host install」，重新安裝修不好。
  自訂了 `data_dir`、而設定檔又壞到連 TOML 都不是時，找不到登記檔，仍然不回覆。
- 啟動後先把標準輸出留給通道（research R2），之後任何 `print` 都不會進入通道。
- 每個程序只讀**一則**訊息、回覆一則、結束（`sendNativeMessage`，research R6）。

## 訊息格式

每則訊息：4 位元組長度（本機位元組順序，無號 32 位元）＋ UTF-8 JSON 物件。

- 請求長度 > 512 位元組、不是 JSON 物件、不是 UTF-8 → `bad-request`（不讀其餘內容）。
- 回覆一律 ≤ 4 KB（Chrome 上限 1 MB）。

### 請求

```json
{"v": 1, "cmd": "status", "app": 1091500}
{"v": 1, "cmd": "choose", "app": 1091500, "option": "bundle/32470"}
{"v": 1, "cmd": "reset",  "app": 1091500}
```

- 欄位剛好是上面列的（不多、不少）；`v` 必須是 1；`app` 是 int（不是布林、不是字串），1 ≤ app ≤ 2147483647；
  `option` 符合 `^(sub|bundle)/[1-9][0-9]{0,9}$` 且數字 ≤ 2147483647。
- 不接受路徑、指令、設定內容等任何其他欄位（FR-015）。

### 回覆

成功：

```json
{"v": 1, "ok": true, "cmd": "status", "app": 1091500, "choice": "bundle/32470", "config_ok": true, "host": "0.2.0"}
{"v": 1, "ok": true, "cmd": "choose", "app": 1091500, "option": "sub/367653", "changed": true, "seconds": 7.1, "partial": false}
{"v": 1, "ok": true, "cmd": "reset",  "app": 1091500, "changed": false}
```

- `status.choice`：設定檔中這款遊戲的指定（`"sub/N"`／`"bundle/N"`），沒有指定為 null；`config_ok` 為 false 時 `choice` 為 null，另附 `message`。
- `choose` 選到 Steam 預設時，回覆的 `cmd` 仍是 `choose`，效果等同 `reset`（FR-003）。
- `changed: false`：設定檔本來就是這樣，沒有重新產生報告。
- `partial: true`：報告完成，但有個別遊戲的決策錯誤（不是失敗，research R5）；面板照樣更新。

失敗：

```json
{"v": 1, "ok": false, "code": "busy-update", "message": "背景更新進行中，請稍後再試"}
{"v": 1, "ok": false, "code": "report", "step": "report", "message": "報告產生失敗（…），設定檔與報告已還原"}
```

| `code` | 何時 | `message`（面板直接顯示） | 有沒有改任何檔案 |
|---|---|---|---|
| `bad-request` | 格式不符 | 請求格式不正確 | 沒有 |
| `wrong-origin` | 來源不是登記的擴充功能（只記日誌，不回覆） | — | 沒有 |
| `busy-host` | 處理鎖被占用 | 上一個指定還在處理 | 沒有 |
| `busy-update` | 寫入鎖被占用 | 背景更新進行中，請稍後再試 | 沒有 |
| `config-invalid` | 設定檔無法解析 | 設定檔有錯誤，請先修正 steamsage.toml（…） | 沒有 |
| `config-unsafe` | 這款遊戲的寫法無法安全修改（research R3） | 設定檔中這款遊戲的寫法無法自動修改（…），請手動修改 | 沒有 |
| `not-tracked` | 遊戲不在追蹤範圍（2026-10-22，014 T074：願望清單上的遊戲，加上移除後仍在追蹤期間的，和每日更新相同；以前只算願望清單上的） | 這款遊戲不在願望清單的追蹤範圍 | 沒有 |
| `not-choosable` | 版本不是可指定的購買選項 | 這個版本不能指定（009 的原因） | 沒有 |
| `config-write` | 寫設定檔失敗 | 設定檔寫入失敗（…） | 沒有（寫入是暫存檔再改名） |
| `report` | `report` 結束代碼 1 | 報告產生失敗（…），設定檔與報告已還原 | 設定檔、報告、資料檔已還原；已保存的正式紀錄保留 |
| `record` | 正式紀錄沒有保存 | 正式紀錄沒有保存（…），設定檔與報告已還原 | 設定檔、報告、資料檔已還原；已保存的正式紀錄保留 |
| `extension-data` | 擴充功能資料檔沒有寫入 | 擴充功能資料沒有寫入（…），設定檔與報告已還原 | 設定檔、報告、資料檔已還原；已保存的正式紀錄保留 |
| `restore` | 還原本身失敗 | 還原失敗：請手動檢查 steamsage.toml（備份在 data/host/restore-…） | 備份另存，見訊息 |
| `internal` | 其他例外 | 本機程式發生錯誤（例外類型） | 設定檔、報告、資料檔已還原；已保存的正式紀錄保留 |

`message` 中的「…」是例外類型與訊息，經過金鑰遮蔽（`RedactingFilter.redact`），不含完整路徑以外的系統資訊。
還原失敗時（`restore`），本機程式把原始設定檔另存到 `data/host/restore-<時間>.toml`，不刪除，讓使用者手動處理。

## 處理順序（`choose`／`reset`）

照 [data-model.md](../data-model.md) §2 的狀態圖。報告用和命令列相同的程式執行：同一個程序內呼叫 `steamsage.cli.main(["report", "--config", <設定檔>, "--json"])`，
讀它的結束代碼與 JSON 摘要（spec FR-007、FR-012：和手動執行 `report` 是同一條路徑）。

## `steamsage host` 指令（spec FR-022）

```
uv run steamsage host install      # 安裝：寫 data/host/ 的兩個檔案、登記 HKCU
uv run steamsage host uninstall    # 移除：刪除登錄的鍵與 data/host/ 的兩個檔案；資料夾空了才刪（restore-*.toml 等其他檔案保留並列出）
uv run steamsage host status       # 顯示：是否已登記、登記檔與啟動檔是否存在、允許的擴充功能編號、啟動檔指向的 python 是否存在
```

- 不需要 API 金鑰、不取寫入鎖、不讀寫資料庫。
- `install` 重複執行會覆寫成目前的路徑與編號（例如專案資料夾搬家之後）。
- `install` 成功時印出：這個程式能做的事（三種指令、只改 `[purchase_options]` 的一行、重新產生報告）與不能做的事（其他設定、任意檔案或指令、連網）。
- 結束代碼：0 成功；1 失敗（例如不是 Windows、路徑無法用 OEM 字碼頁表示、登錄寫入失敗）。

## 安全不變式（spec SC-002 要逐條測）

1. 請求只決定「哪款遊戲、哪個版本、哪種指令」；檔案、路徑、要執行的程式都是安裝時固定的。
2. 驗證失敗、鎖被占用時，設定檔、資料庫、報告、資料檔、正式紀錄都逐位元組不變。
3. 回覆、日誌、錯誤訊息都不含 API 金鑰（`ITAD_API_KEY`、`STEAM_WEB_API_KEY` 的值）。
4. 本機程式不開網路連接埠；它執行的 `report` 不連網（`report` 本來就只讀資料庫）。

---

description: "Task list for feature 015: choose the tracked edition on the Steam page"
---

# Tasks: 在 Steam 遊戲頁直接指定追蹤版本

**Input**：`specs/015-choose-edition-on-steam/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求測試先行。本機程式、設定檔編輯、資料檔先寫 pytest；擴充功能的純函式先寫 `node --test`；頁面行為用端對端（`tests/extension/e2e.py`）。
每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational（訊息格式、設定檔編輯、資料檔 `versions`、`lib.js` 純函式）→ US1（指定與改回，MVP）→ US2（沒有本機程式）
→ US3（安全邊界的對抗測試）→ US4（購買框捷徑）→ Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 在遊戲頁面板指定或改回版本，立即生效 | P1 |
| US2 | 沒有安裝本機程式時，其他功能照常並告訴使用者怎麼做 | P1 |
| US3 | 本機程式只做被允許的事 | P1 |
| US4 | 在 Steam 自己的購買框直接按 | P3 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄（worktree `〈專案資料夾〉-015`）

## 共用約定（每個任務都適用）

- **名稱與常數**：本機程式名稱 `com.sweetspot.edition`；請求 ≤ 512 位元組；回覆 ≤ 4 KB；確認時間 5 秒；面板等待 60 秒；設定檔註解中的名稱 ≤ 80 字；
  `app` 與 `option` 的數字 1 ≤ n ≤ 2147483647；`option` 符合 `^(sub|bundle)/[1-9][0-9]{0,9}$`（contracts/native-host.md）。
  JS 的常數集中在 `extension/lib.js`（`HOST_NAME`、`CONFIRM_MS = 5000`、`WAIT_MS = 60000`），端對端測試在暫存副本中替換它們。
- **訊息文字**：照 contracts/native-host.md 的錯誤代碼表與 contracts/extension-ui.md；面板直接顯示回覆的 `message`，不在 JS 另組句子（011 D1）。
- **檔案是固定的**（spec FR-015）：本機程式只讀寫安裝時寫死的設定檔，以及由它推出的 `data/`、`data/reports/latest.html`、`extension/data/steamsage-extension.json`、
  `data/forecasts/`；請求中沒有任何路徑。
- **兩個鎖**（plan D4）：`data/.host.lock`（被占用 → `busy-host`）、`data/.lock`（被占用 → `busy-update`），都用 `steamsage.lock.WriterLock`，持有到回覆為止；`status` 不取鎖。
  正式 `report` 照舊不取鎖。
- **失敗與還原**（plan D5，research R5）：失敗 = `report` 結束代碼 1、或摘要 `record` 以「未保存」開頭、或 `extension` 為 null 或以「未寫入」開頭。
  失敗時設定檔、`latest.html`、擴充功能資料檔寫回原始內容（暫存檔再改名）；`report` 已經保存的正式紀錄**保留，不刪除**（憲章 IV，analyze C1）。個別遊戲的決策錯誤不是失敗（`partial: true`）。
- **報告的執行**：同一個程序內呼叫 `steamsage.cli.main(["report", "--config", <設定檔>, "--json"], stdout=StringIO(), stderr=StringIO())`，讀結束代碼與 JSON 摘要（FR-007、FR-012）。
- **測試的暫存環境**：暫存設定檔旁邊一定要有 `extension/manifest.json`（複製 `extension/manifest.json`），否則 `report` 不寫擴充功能資料檔，摘要的 `extension` 為 null，會被判為失敗（analyze U2）。
- **金鑰**：回覆、日誌、錯誤訊息都經過 `logs.RedactingFilter.redact`；測試用假的金鑰值（`monkeypatch.setenv`）搜尋所有輸出，必須找不到。
- **不碰使用者的環境**：pytest 的登錄操作一律經過可替換的介面（不寫真的登錄）；端對端只用假的本機程式（回覆帶 `fake: true`，否則中止），登記在
  `HKCU\Software\Chromium\NativeMessagingHosts\com.sweetspot.edition.test`，結束時刪除它和自己建立的空上層鍵（research R0）；從不讀寫 `〈專案資料夾〉\steamsage.toml`。
- **不連外**：擴充功能的權限只有 `alarms`、`nativeMessaging`；CSP 不變；`sendNativeMessage` 只出現在 `sw.js`；外部字串用 `textContent`。
- **改檔案**：多行修改用 Edit 工具或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）；`.bat` 與要逐位元組比對的內容一律用 bytes 寫。
- **Checkpoint**：每完成一個，就跑 `uv run pytest -o addopts="" -q` 與 `node --test "tests/extension/*.test.js"`（有改頁面行為時加跑 e2e）、commit（附 attribution trailer），並向使用者報告。

---

## Phase 1: Setup

- [X] T001 在 `.gitignore` 的 SweetSpot 區塊加 `data/host/` 與 `data/.host.lock`；建立 `src/steamsage/host/__init__.py`（模組說明：015 本機程式，contracts/native-host.md）與
  `tests/unit/host/__init__.py`。
- [X] T002 [P] 擴充功能 manifest（contracts/extension-ui.md）：在 scratchpad 用 openssl 產生一次 RSA 2048 金鑰，把公鑰 DER 的 base64 寫進 `extension/manifest.json` 的 `key`，
  **刪除私鑰**（不保存、不進版控）；`permissions` 改為 `["alarms", "nativeMessaging"]`；`version` 改為 `1.1.0`；`description` 改為「…只讀本機資料檔，不連外；安裝本機程式後可在遊戲頁指定追蹤版本」。
  先改 `tests/extension/manifest.test.js`：權限恰好這兩項、`key` 存在且是合法的 base64、CSP 不變。

---

## Phase 2: Foundational（所有情境共用）

**⚠️ 這一階段完成前不開始任何情境**

- [X] T003 [P] 先寫 `tests/unit/host/test_protocol.py`（contracts/native-host.md「訊息格式」）：
  - 讀寫：4 位元組長度（`struct` 的 `=I`）＋ UTF-8 JSON；EOF（不足 4 位元組）→ None；長度 > 512 → `bad-request` 且不讀其餘內容；不是 UTF-8、不是 JSON 物件 → `bad-request`；
    回覆超過 4 KB → 例外（程式錯誤）。
  - `validate(obj)`：三種 `cmd` 的欄位集合**恰好**是 `{v, cmd, app}`（status、reset）與 `{v, cmd, app, option}`（choose）；`v` 必須是 1；`app` 是 int 且不是 bool、
    1 ≤ app ≤ 2147483647；`option` 符合 `^(sub|bundle)/[1-9][0-9]{0,9}$` 且數字 ≤ 2147483647；回傳 `(cmd, app, (kind, id) | None)`。
- [X] T004 實作 `src/steamsage/host/protocol.py`：`read_message(stream)`、`write_message(stream, obj)`、`validate(obj)`、`BadRequest`（帶位元組數，供日誌）。只用標準函式庫。
- [X] T005 [P] 先寫 `tests/unit/host/test_toml_edit.py`（research R3、spec SC-003），每個案例比對**逐位元組**結果：
  - 新增：區段中已有其他指定 → 加在最後一筆指定之後（尾端註解留在最後）；區段只有註解 → 加在註解之後；沒有 `[purchase_options]` → 檔尾空一行後加區段與那一行。
  - 改寫：鍵有引號（`"1091500" = …`）與沒有引號；原本的行尾註解被新註解取代；只有那一行改變。
  - 刪除：只刪那一行（含行尾註解），前後的空行與註解不變。
  - 保留：LF 與 CRLF、有沒有檔尾換行、其他區段的註解與空行。UTF-8 BOM → `ConfigInvalid`（`tomllib` 與 `load_config` 都讀不了；實作時查證）。
  - 拒絕（`ConfigInvalid`）：tomllib 解析失敗。拒絕（`ConfigUnsafe`）：同一款遊戲在區段中出現兩次（含 `"0123"` 與 `"123"`）；以 `purchase_options.<app> = …` 或 inline table 寫在區段外；
    那一行的值跨多行；修改後的 tomllib 解析結果除了這款遊戲之外和原本不同。
  - 寫入的行（plan D7）：`1091500 = "bundle/32470"   # 《電馭叛客 2077：終極版》（2026-10-14 從 Steam 頁面指定）`；名稱移除控制字元與換行、超過 80 字截斷；名稱為 null 時只寫 `# 2026-10-14 從 Steam 頁面指定`。
  - `current_choice(text, app)` 讀出目前的指定（和 `config.load_config` 的解析一致）。
  - 用 `config.DEFAULT_TOML` 加上使用者現在那一行（`1091500 = "bundle/32470"   # Cyberpunk 2077 → …`）當作接近真實的案例。
- [X] T006 實作 `src/steamsage/host/toml_edit.py`：`current_choice(text, app) -> tuple[str, int] | None`、`set_choice(text, app, choice: tuple[str, int] | None, *, name, today) -> str`、
  `ConfigInvalid`、`ConfigUnsafe`。逐行處理，寫入前用 `tomllib` 驗證（research R3）；不新增套件（plan D3）。
- [X] T007 [P] 先寫資料檔 `versions` 的測試（data-model §1）於 `tests/unit/report/test_extension_data.py`，並在 `tests/contract/test_extension_contract.py` 加欄位檢查：
  - 第一項是 `version.option`（`tracked: true`），價格來自 `current.price_twd`／`current.cut_pct`；接著是 `editions` 的每一項，順序不變。
  - 追蹤中的 `is_default`：`version.basis` 不是 `user`，或 `editions` 中沒有 `is_default` 的項目；其他項目照 `editions[].is_default`。
  - `action`：追蹤中 → null；`unset_hint` 為 true → `"reset"`；`config_line` 不是 null → `"choose"`；其他 → null 並帶 `reason`（`editions[].reason_text`）。
  - `manual`：`choose` 為 `config_line`；`reset` 為「刪掉設定檔 [purchase_options] 中 <app> 那一行」；其他為 null。
  - 沒有 `version.option` → `[]`；`format` 仍是 `steamsage.extension/1`；既有欄位與 HTML 報告不變（既有的 golden 測試照常通過）。
- [X] T008 實作 `src/steamsage/report/extension.py` 的 `_versions(d)` 並加進 `_game`；`reset` 的手動句子放在 Python（011 D1）。
- [X] T009 [P] 先寫 `tests/extension/lib.test.js` 的新測試：
  - `versionsModel(game, host)`：少於兩項 → null（不顯示一節）；標題「版本（N）」；每列的名稱、價格（`money`／`off`）、標示（追蹤中／追蹤中（使用者指定）／Steam 預設）；
    依 `host`（`unknown`／`checking`／`ready`／`not-installed`／`unavailable`）決定按鈕或說明（contracts/extension-ui.md 的表）；`status.choice` 與追蹤中不一致時的提示。
  - `confirmStep(state, event, now)`：`idle` → 按下 → `confirm`（記錄時間）；`confirm` 5 秒內按同一個 → `send`；超過 5 秒或按了別處 → `idle`；`sending` 時一律忽略；
    不是 `isTrusted` 的事件 → 狀態不變。
  - `relayCheck(data, senderUrl, msg)`：分頁網址必須是 `https://store.steampowered.com/app/<app>/…` 且 `<app>` 等於 `msg.app`；`app` 在 `games`；`choose` 的 `option` 是 `versions` 中
    `action` 為 `choose` 或 `reset` 的項目；`reset` 要有 `action: "reset"` 的項目；`status` 只要求前兩項；回傳要送給本機程式的物件 `{v: 1, cmd, app[, option]}` 或 `null`。
- [X] T010 實作 `extension/lib.js` 的 `HOST_NAME`、`CONFIRM_MS`、`WAIT_MS`、`versionsModel`、`confirmStep`、`relayCheck`（純函式，加進 `SteamSage` 匯出）。

**Checkpoint**：pytest 與 `node --test` 全部通過；`report` 在測試資料上產生的資料檔帶 `versions`。

---

## Phase 3: User Story 1 - 在遊戲頁面板指定或改回版本，立即生效（P1）🎯 MVP

**Goal**：安裝本機程式後，在面板的「版本」一節按兩下就改追蹤版本，面板自動換成新數字。

**Independent Test**：在人工資料與暫存設定檔上，從本機程式的處理流程指定一個版本、再改回預設，檢查設定檔的變化、報告與資料檔；端對端用假的本機程式檢查面板。

### Tests for User Story 1（先寫，確認會失敗）

- [X] T011 [P] [US1] `tests/integration/test_host_service.py`（spec US1 情境 1–4、FR-003、FR-007、FR-008、FR-020）：用 `tests/forecast_builders.build_db` 建一款有本體（Steam 預設 `sub`）、
  已驗證的終極版（`bundle`）、未驗證的版本與原聲帶（`role` 非 edition）的遊戲，暫存設定檔用 `DEFAULT_TOML`，`commands.NOW` 固定：
  - `choose` 終極版 → 設定檔只多那一行（逐位元組比對）、正式紀錄多一份、`latest.html` 與資料檔更新、資料檔中這款遊戲的追蹤中是終極版、回覆 `changed: true`。
  - 再 `reset` → 那一行刪除、設定檔和最初逐位元組相同；`choose` 另一個版本 → 改寫而不是多一行；`choose` Steam 預設 → 效果等同 `reset`（FR-003）。
  - 設定檔已經是這樣 → `changed: false`，沒有新的正式紀錄、報告不重寫。
  - `status` → `choice` 為設定檔中的指定（沒有為 null）、`config_ok: true`。
  - 變動標示（FR-007）：`choose` 後這款遊戲決策的 `change.version.cause` 為 `user`，`reset` 後為 `unset`（`decision/changes.py` 的現行規則）。
  - 日誌：每個請求一行 `host <cmd> app=… option=… result=… …`（data-model §4）。
- [X] T012 [P] [US1] `tests/integration/test_host_equivalence.py`（spec FR-012、SC-005）：同一份資料庫複製兩份；A 由本機程式 `choose`，B 手動寫同一行（報告「指定」欄的 `config_line`，不含註解）
  再執行 `cli.main(["report", …])`；兩邊的擴充功能資料檔與正式紀錄除了 `generated_at`（與紀錄檔名的時間）之外相同；`reset` 也比一次。
- [X] T013 [P] [US1] `tests/integration/test_host_rollback.py`（spec FR-009、SC-004；plan D5）：在每一步注入失敗——設定檔改名（`os.replace` 例外）、`report` 結束代碼 1
  （`run_decisions` 丟例外）、正式紀錄沒有保存（`records.write_record` 丟例外）、HTML 已寫但資料檔沒有寫入（`extension_data.build` 丟例外）、還原本身失敗——檢查：
  設定檔、`latest.html`、資料檔逐位元組回到之前；`report` 已經保存的正式紀錄保留（不刪除任何紀錄，憲章 IV），之前的紀錄不變；回覆的 `code`／`step` 與 contracts/native-host.md 相同；
  還原失敗時原始設定檔另存為 `data/host/restore-<時間>.toml`、`code: "restore"`。另外：個別遊戲的決策錯誤 → 成功且 `partial: true`，不還原。
- [X] T014 [P] [US1] `tests/unit/host/test_install.py` 與 `tests/contract/test_cli_host.py`（data-model §3、contracts/native-host.md「steamsage host 指令」），登錄用假的介面：
  - 擴充功能編號由 manifest `key` 算出：SHA-256（公鑰 DER）前 32 個十六進位字元換成 a–p（用一組固定的測試金鑰與預期編號）。
  - `install`：`data/host/sweetspot-host.bat` 為一行 `@"<sys.executable>" -m steamsage.host --config "<設定檔絕對路徑>" %*`＋CRLF，以 OEM 字碼頁編碼；
    `data/host/com.sweetspot.edition.json` 的 `name`、`description`、`path`、`type: "stdio"`、`allowed_origins: ["chrome-extension://<編號>/"]`；
    登錄 `Software\Google\Chrome\NativeMessagingHosts\com.sweetspot.edition` 的預設值是登記檔的絕對路徑；印出能做與不能做的事；重複執行會覆寫。
  - 路徑無法用 OEM 字碼頁表示、不是 Windows、登錄寫入失敗 → 結束代碼 1 並說明，不留下半套檔案。
  - `uninstall`：刪除登錄鍵與 `data/host/` 的啟動檔、登記檔，資料夾空了才刪（**2026-10-14 使用者選定的修正**：還原失敗留下的 `restore-*.toml` 等其他檔案保留並列出），其他不動；沒有安裝時也成功。`status`：顯示是否登記、檔案是否存在、允許的編號、啟動檔指向的 python 是否存在。
  - `host` 指令不取寫入鎖、不開資料庫、不需要金鑰。

### Implementation for User Story 1

- [X] T015 [US1] 實作 `src/steamsage/host/service.py`（data-model §2 的狀態圖、contracts/native-host.md 的處理順序與錯誤表）：`handle(request, *, config_path, now) -> reply`；
  兩個鎖；用 `PriceStore` 讀 `wishlist_apps()` 與 `purchase_options([app], now)`、以 `choices.resolve_choice` 判定可指定（FR-016）；名稱取自資料庫的購買選項紀錄；
  修改前保存設定檔、`latest.html`、資料檔的原始內容（不動 `data/forecasts/`）；`toml_edit.set_choice` → 暫存檔再改名 → 同程序執行 `report` → 依共用約定判斷失敗 → 還原；
  每個請求一行日誌（`logging.getLogger("steamsage.host")`），訊息經過金鑰遮蔽。
- [X] T016 [US1] 實作 `src/steamsage/host/__main__.py`（contracts/native-host.md「啟動」）：解析 `--config` 與 Chrome 傳入的來源；**先**用 `os.dup(1)` 把真正的標準輸出留給通道，
  再把檔案描述元 1 與 `sys.stdout` 改指向 `sys.stderr`；來源不在 `<設定的 data_dir>/host/com.sweetspot.edition.json`（由 `--config` 載入的設定推出）的 `allowed_origins` → 記錄一行後以代碼 1 結束、不讀訊息；
  `setup_logging`；讀一則訊息 → `protocol.validate` → `service.handle` → 回覆 → 結束。
- [X] T017 [US1] 實作 `src/steamsage/host/install.py`（登錄操作包成可替換的類別，預設用 `winreg`）與 `src/steamsage/cli.py`／`src/steamsage/commands.py` 的 `host` 子指令
  （`install`／`uninstall`／`status`；加進 `READ_ONLY_COMMANDS`，不開 `StoreWriter`、不取鎖）。
- [X] T018 [P] [US1] 測試頁 `tests/extension/fixtures/game_editions.html`（Cyberpunk 2077 的結構：本體 `subid=367653`、終極版 `bundleid=32470`、原聲帶 `subid` 不在版本中）；
  `tests/extension/fixtures/data.json` 的 1091500 加 `versions`（追蹤終極版、本體 `action: "reset"`），另一款加一個 `action: null` 帶 `reason` 的版本。
- [X] T019 [US1] 實作 `extension/sw.js` 的 `{type: "host"}` 轉送（contracts/extension-ui.md「訊息」）：讀資料檔 → `relayCheck` → `chrome.runtime.sendNativeMessage(HOST_NAME, …)`；
  `Specified native messaging host not found.` → `{ok: false, code: "not-installed"}`，其他 `lastError` → `unavailable`；`choose`／`reset` 成功且 `changed: true` 時先 `refresh()` 再回覆並附上新的 `data`。
  同時更新 `tests/extension/static.test.js`：`sendNativeMessage` 只出現在 `sw.js`、不使用 `connectNative`、仍然只 fetch 自己的資料檔。
- [X] T020 [US1] 實作 `extension/content.js` 的「版本」一節（contracts/extension-ui.md）：面板內容最後的 `<details>`（預設收合，已擁有時跟著收合）；展開時查詢一次 `status`；
  按鈕的點擊先檢查 `event.isTrusted`，狀態用 `confirmStep`；送出後顯示進度並停用這款遊戲的所有按鈕；`WAIT_MS` 逾時顯示「報告仍在產生，完成後重新整理頁面即可看到」；
  成功時用回覆的新資料重畫整個面板（把 `gamePage` 改成可以重畫：移除舊的 `.steamsage-panel` 再建立），一節保持展開並顯示結果；失敗時顯示 `message`。
- [X] T021 [US1] 端對端（`tests/extension/fake_host.py`＋`tests/extension/e2e.py` 新增 `check_editions`）：把 `extension/` 複製到暫存資料夾，替換 `HOST_NAME` 為 `com.sweetspot.edition.test`、
  `WAIT_MS` 為 2000；`fake_host.py` 把收到的請求逐行寫進暫存檔，依情境回覆（`status` 可用；`choose` 先改寫副本的資料檔再回 `changed: true`；`busy-update`；不回覆讓面板逾時），每個回覆帶 `fake: true`。檢查：
  一節預設收合、展開前沒有任何請求、展開後恰好一個 `status`；按一次不送出、5 秒後恢復；頁面程式的模擬點擊（research R0 T 的 6 種：`click()`、`dispatchEvent` 滑鼠與指標事件、`HTMLElement.prototype.click.call`、模擬 Enter 按鍵、`<label>` 轉送）在面板的按鈕上送出 0 個請求（US1 情境 7、FR-006a、SC-008）；確認後送出 `choose` 並顯示進度；成功後面板換成新資料；`busy-update` 顯示訊息；逾時說明；已擁有的頁面（`game_owned.html` 的結構，遊戲帶 `versions`）「版本」一節跟著面板收合、展開面板後可以使用；
  擴充功能發出的網路請求為 0；登錄清理後沒有留下鍵。
  **實作時擴大（2026-10-14）**：e2e 的**所有**檢查（含 011 原有的）都改用暫存副本。manifest `key` 讓副本和 `extension/` 編號相同，而這個 Chromium 也讀 `Software\Google\Chrome` 的登錄，直接載入 `extension/` 在使用者安裝真的本機程式之後就可能呼叫到它；副本的本機程式名稱是測試名稱，所以不可能。副帶效果：e2e 不再讀寫真的 `extension/data/`（結尾檢查它沒有被改動）。

**Checkpoint**：MVP。pytest、`node --test`、e2e 全部通過；在 worktree 的暫存資料上手動跑一次 `python -m steamsage.host`（用 protocol 的格式餵一則 `status`）確認回覆。向使用者報告。

---

## Phase 4: User Story 2 - 沒有安裝本機程式時，其他功能照常並告訴使用者怎麼做（P1）

**Goal**：沒有安裝或本機程式壞掉時，擴充功能和現在一樣，「版本」一節改成安裝說明與手動設定行。

**Independent Test**：不登記任何本機程式，011 的端對端檢查全部通過，「版本」一節顯示說明與設定行。

- [X] T022 [P] [US2] 在 `tests/extension/lib.test.js` 加：`versionsModel` 在 `not-installed` 時每個 `choose`／`reset` 列顯示「安裝本機程式後可在這裡指定」與 `manual`；`unavailable` 時顯示
  「本機程式無法使用，請重新執行 `uv run steamsage host install`（Chrome：message）」與 `manual`（專案資料夾搬家後的情況，spec Edge Cases）；`action: null` 的列兩種情況都只顯示 `reason`。
- [X] T023 [US2] `extension/content.js`：未安裝與無法使用時的顯示（`manual` 是可以選取的文字，用 `textContent`）；同一頁沿用第一次查詢的結果（FR-023a）。
- [X] T024 [US2] `tests/extension/e2e.py` 新增 `check_no_host`：不登記本機程式時，011 原有的檢查（遊戲頁、彈出視窗、願望清單、過舊）全部照常；展開「版本」一節顯示說明與設定行；
  彈出視窗與願望清單沒有任何指定按鈕（FR-005）；網路請求為 0（SC-006）。另外在 `check_editions` 確認：已登記但沒有展開、也沒有按捷徑時，假的本機程式沒有收到任何請求（US2 情境 3）。

**Checkpoint**：pytest、`node --test`、e2e 全部通過，commit，向使用者報告。

---

## Phase 5: User Story 3 - 本機程式只做被允許的事（P1）

**Goal**：錯誤或惡意的請求一律被拒絕，而且不留下任何變更、不洩漏金鑰。

**Independent Test**：對本機程式直接送一組錯誤或惡意的請求，每個都被拒絕，檔案逐位元組不變，日誌有原因、沒有金鑰。

- [X] T025 [P] [US3] `tests/integration/test_host_security.py`（spec SC-002，至少 20 種，一個參數化表）：未知 `cmd`；多一個 `path` 欄位；少 `app`；`v: 2`；`app` 為字串、布林、0、負數、2147483648；
  `option` 為 `sub/0`、`bundle/01`、`sub/1/../x`、`pkg/1`、`sub/ 1`、`sub/99999999999`；請求 513 位元組；不是 UTF-8；JSON 陣列；不在追蹤範圍的遊戲；不在購買選項紀錄中的版本；
  ITAD 核對未通過的版本；`role` 不是 edition 的購買選項；設定檔無法解析（`config-invalid`）；這款遊戲寫了兩次（`config-unsafe`）。每一種：拒絕、`code` 正確；設定檔、資料庫、
  `latest.html`、資料檔、`data/forecasts/` 的雜湊不變；日誌有拒絕原因，格式不對的請求只記位元組數；設定假的 `ITAD_API_KEY`／`STEAM_WEB_API_KEY` 後，回覆、日誌、stderr 都找不到它們。
- [X] T026 [P] [US3] `tests/integration/test_host_locks.py`（spec US3 情境 3、FR-018、FR-019、SC-007）：`data/.lock` 被存活的程序持有 → `busy-update`，1 秒內回覆，所有檔案不變；
  `data/.host.lock` 被持有 → `busy-host`；擁有者已結束的鎖可以接手；處理期間兩個鎖都被持有、回覆後都釋放（也在失敗時釋放）。
- [X] T027 [P] [US3] `tests/unit/host/test_main.py`（contracts/native-host.md「啟動」）：用子程序執行 `python -m steamsage.host`：來源不是登記的擴充功能 → 代碼 1、沒有讀訊息、日誌一行；
  處理過程中有程式 `print` 到標準輸出時，通道收到的仍然只有一則格式正確的回覆；EOF → 正常結束。另加靜態檢查：`src/steamsage/host/` 不 import `socket`、`http`、`httpx`、`urllib`（FR-013）。
- [X] T028 [P] [US3] 在 `tests/extension/lib.test.js` 加 `relayCheck` 的對抗案例：別的遊戲頁、別的網站、沒有分頁網址、`app` 與網址不同、不在資料中的遊戲、不在 `versions` 的版本、
  `action: null` 的版本、`reset` 但沒有可改回的項目、多餘欄位（只轉送允許的欄位）——全部回傳 `null`。
- [X] T029 [US3] 依 T025–T028 補齊 `src/steamsage/host/service.py`、`src/steamsage/host/__main__.py`、`extension/lib.js` 中沒有通過的部分（預期 T015、T016、T010 已涵蓋；若需要修改，在 commit 訊息說明是哪個案例）。

**Checkpoint**：pytest、`node --test` 全部通過，commit，向使用者報告（附 SC-002 的案例數）。

---

## Phase 6: User Story 4 - 在 Steam 自己的購買框直接按（P3）

**Goal**：Steam 的購買框中，對應到可指定版本的框有 SweetSpot 的小按鈕，效果和面板相同。

**Independent Test**：測試頁上可指定版本的購買框有按鈕、DLC 與原聲帶沒有、結構不符時一個都不放。

- [X] T030 [P] [US4] 在 `tests/extension/lib.test.js` 加 `shortcutPlan(blocks, versions)`：每個框以 `subid`／`bundleid` 對應 `versions`；任何一個框兩者都讀不到 → 全部不放；
  對應到 `choose`／`reset` → 按鈕文字「SweetSpot：追蹤這個版本」／「SweetSpot：改回 Steam 預設」；對應到追蹤中 → 「SweetSpot：追蹤中」；其他框不放。
- [X] T031 [US4] 實作 `extension/lib.js` 的 `shortcutPlan` 與 `extension/content.js` 的捷徑：在每個對應的 `.game_area_purchase_game` 內、購買按鈕區之前插入自己的 shadow DOM 節點（不改 Steam 的節點）；
  確認方式與面板相同；第一次按下才查詢 `status`；未安裝或無法使用 → 捷徑文字改為「需要安裝本機程式（見 SweetSpot 面板）」並展開面板的「版本」一節；進度與結果顯示在面板（自動展開）。
- [X] T032 [US4] `tests/extension/e2e.py` 的 `check_editions` 加：`game_editions.html` 的本體框有「追蹤這個版本」、終極版框「追蹤中」、原聲帶框沒有；`wishlist_restyled.html` 式的改版購買框
  （新增 `tests/extension/fixtures/game_editions_restyled.html`，購買框沒有 `subid`／`bundleid`）一個都不放；捷徑按兩下送出的請求與面板相同；頁面程式的模擬點擊（同 T021 的 6 種）
  在捷徑上也不送出（面板的部分在 T021；SC-008）。
  **實作時的細節（2026-10-14）**：(1) 測試資料中 1091500 追蹤的是終極版，所以 `game_editions.html` 的本體框是「SweetSpot：改回 Steam 預設」、終極版框「追蹤中」；「追蹤這個版本」改用改回預設後的資料（`default_data()`）檢查，兩種都測。(2) `shortcutPlan` 另外在版本少於兩個時、或對應到的框沒有購買按鈕區（`.game_purchase_action`）時一個都不放（不猜）。(3) 頁面程式的模擬點擊連 `status` 查詢都不會觸發（不只是不送出）。

**Checkpoint**：pytest、`node --test`、e2e 全部通過，commit，向使用者報告。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T033 [P] `README.md`：安裝與移除（`uv run steamsage host install|uninstall|status`）、第一次要在 `chrome://extensions` 重新載入 SweetSpot、這個程式能做與不能做的事（FR-022）、
  沒有安裝時的手動做法、專案資料夾搬家後要重新安裝。
- [X] T034 [P] `specs/011-chrome-extension/contracts/extension-ui.md` 的 manifest 一節加一行指向 015 的契約（權限多了 `nativeMessaging`）；`HANDOFF.md` 更新 015 的狀態、測試數量、合併後的驗收步驟。
- [X] T035 全部測試：`uv run pytest`、`node --test "tests/extension/*.test.js"`、`uv run --with playwright==1.63.0 python tests/extension/e2e.py`；在 worktree 的資料庫**副本**上量一次
  `choose` 的總時間（SC-001，預期約 7 秒）與資料檔大小的增加（預期約 10 KB），記錄到 HANDOFF。
  **結果（2026-10-14）**：`status` 0.3 秒；改回本體 9.5 秒、指定終極版 11.2 秒（MVP 時 7.7／8.2 秒，都在 30 秒內）；資料檔 147,179 → 165,513 位元組（+18 KB，比預估多，仍在 011 的 200 KB 內）。
- [X] T036 列出值得重構的點（重複、過長函式、命名不一致），不擅自修改範圍外的部分；準備合併：squash merge 到 master 的說明（使用者確認後才合併與 push）。
- [X] T037 合併到 master 之後由使用者在自己的 Chrome 執行 `quickstart.md` §2–§5（安裝、指定與改回、沒有安裝、背景更新期間），結果記錄到 HANDOFF。
  **結果（2026-10-14～15，使用者在自己的 Chrome）**：§2–§5 全部和預期相同。改回本體 7.0 秒、指定回終極版 7.5 秒（日誌），設定檔和備份只差那一行的註解；未安裝時的說明與手動步驟（含完整路徑）；背景更新期間 `busy-update` 拒絕、設定檔不變；金鑰不在日誌中。驗收中修正：合併後要先跑 `report`（d1814db 加「資料檔是舊版」提示）、未安裝時的說明（5925272）、完整路徑（0a09388）、標籤與按鈕的間距（a8b7105）、quickstart 的比對指令（818bef5）。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：沒有依賴。
- **Foundational（Phase 2）**：依賴 Setup；完成前不開始任何情境。
- **US1（Phase 3）**：依賴 Foundational。
- **US2（Phase 4）**：依賴 Foundational 與 T019、T020（同一個 `content.js`／`sw.js`）。
- **US3（Phase 5）**：依賴 T015、T016（測試對象是本機程式）；T028 只依賴 T010。
- **US4（Phase 6）**：依賴 T020（共用面板的確認與進度）。
- **Polish（Phase 7）**：依賴所有情境；T037 在合併之後。

### Within Each User Story

- 測試先寫並確認失敗，再實作。
- `protocol.py`、`toml_edit.py` → `service.py` → `__main__.py`；`install.py` 獨立。
- `lib.js` 純函式 → `sw.js` → `content.js` → e2e。

### Parallel Opportunities

- Setup：T002 與 T001 並行。
- Foundational：T003、T005、T007、T009 四個測試並行；實作 T004、T006、T008、T010 分別在不同檔案，也可並行。
- US1：T011、T012、T013、T014、T018 並行；T017 與 T015 可並行（不同檔案）。
- US3：T025、T026、T027、T028 並行。

---

## Parallel Example: User Story 1

```bash
# 先寫的測試（不同檔案）：
Task: "T011 tests/integration/test_host_service.py"
Task: "T012 tests/integration/test_host_equivalence.py"
Task: "T013 tests/integration/test_host_rollback.py"
Task: "T014 tests/unit/host/test_install.py + tests/contract/test_cli_host.py"
Task: "T018 tests/extension/fixtures/game_editions.html + data.json"

# 之後可並行的實作：
Task: "T015 src/steamsage/host/service.py"
Task: "T017 src/steamsage/host/install.py + cli host 子指令"
```

---

## Implementation Strategy

### MVP First（US1）

1. Phase 1 → Phase 2 → Phase 3。
2. **停下來驗證**：pytest、`node --test`、e2e 全部通過；用 `python -m steamsage.host` 在暫存資料上送一則 `status` 與 `choose`。
3. 向使用者報告；使用者的 Chrome 驗收要等合併到 master（Chrome 載入的是 master 的 `extension/`）。

### Incremental Delivery

1. US1（指定與改回）→ US2（沒有本機程式時照常）→ US3（安全對抗測試）→ US4（購買框捷徑）。
2. 每個情境完成都 commit 並報告；US3 的對抗測試在合併前必須全部通過（spec「本機程式只做被允許的事」是安裝的前提）。

---

## Notes

- 本機程式的任何測試都不寫真的登錄、不碰 `〈專案資料夾〉` 的設定檔與資料庫。
- e2e 的暫存副本只替換 `HOST_NAME` 與 `WAIT_MS` 兩個常數；其餘程式和 `extension/` 相同。
- 實作偏離 plan／tasks 時停下說明，不要默默調整。

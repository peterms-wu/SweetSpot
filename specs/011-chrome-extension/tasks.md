---

description: "Task list for feature 011: Chrome extension for the 2026 autumn sale"
---

# Tasks: Chrome 擴充功能

**Input**：`specs/011-chrome-extension/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求測試先行。Python 的匯出與 `report` 變更先寫 pytest；擴充功能的純函式先寫 `node --test`；頁面行為用端對端（`tests/extension/e2e.py`）。
每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational（資料檔＋擴充功能骨架）→ US1（遊戲頁面板）→ US2（彈出視窗）→ **MVP 試用** → US3（願望清單）→ US4（資料時間與排程）→ Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 在遊戲頁面看到這款遊戲的甜蜜價 | P1 |
| US2 | 點工具列圖示看整份清單 | P1 |
| US3 | 在願望清單頁每一列看到分組與甜蜜價 | P2 |
| US4 | 知道資料是什麼時候的（過舊提示、排程 02:30） | P2 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **資料檔**：`steamsage.extension/1`（contracts/extension-data.md）。路徑 `<設定檔所在資料夾>/extension/data/steamsage-extension.json`；
  只在 `report` 的 `official`（沒有 `--as-of`、不是 `--rule` 預覽）而且 `extension/manifest.json` 存在時寫；用 `commands.write_text_atomic`（暫存檔再改名）。
- **未知是 null**（憲章 I）：`price_twd`、`sweet_twd`、`probability`… 未知時為 `null`；`data_time` 全部未知時為 `null`，擴充功能視為過舊。
- **資料時間**：`data_time` = 所有非 null 的 `decisions[].current.confirmed_at` 的 `median_low`（research R0.3，不是 `observed_at`）。
- **句子只有一個來源**（plan D1）：擴充功能顯示的句子由 `report/html.py` 的純文字函式產生；HTML 報告**逐位元組不變**（SC-009）。
- **擴充功能只格式化**（FR-005）：千分位 `NT$1,063`、百分比四捨五入到整數 `83%`、台北時間 UTC+8 `YYYY-MM-DD HH:MM`；唯一的比較是「現在 − `data_time` > `stale_hours` 小時」。
  不判斷「已到價」、不排序（`games` 已依報告排序）。
- **不連外**（FR-004、research R0.4）：manifest 權限只有 `alarms`；CSP `connect-src 'self'`；內容腳本與 `lib.js` 不含網路 API；外部字串用 `textContent` 或先跳脫。
- **不動 Steam**（FR-008、FR-016）：只新增自己的節點（shadow root，`:host { all: initial }`）；不改 Steam 元素的樣式或屬性；找不到結構就不顯示。
- **分組**：`now` 現在買／`soon` 即將到價／`wait` 繼續等／`low` 低信心／`na` 無法預測；顏色 綠 `#1e7d32`／藍 `#1a73e8`／灰 `#6b6b70`／橘 `#8a4b00`／紅 `#a1261b`。
- **JS 模組**：`extension/lib.js` 是一般 script（`globalThis.SteamSage = {...}`），結尾 `if (typeof module !== 'undefined') module.exports = SteamSage;`，
  內容腳本 `["lib.js", "content.js"]`、彈出視窗 `<script src="lib.js">`、Service Worker `importScripts('lib.js')` 都載入它；DOM 的讀取留在 `content.js`／`popup.js`，
  `lib.js` 只收純資料（方便 `node --test`）。
- **改檔案**：多行修改用 Edit 工具或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）；需要專案套件的一次性腳本用 `uv run python`。
- **Checkpoint**：每完成一個，就跑 `uv run pytest -o addopts="" -q` 與 `node --test "tests/extension/*.test.js"`、commit（附 attribution trailer），並向使用者報告。
  要在真實資料與真實頁面上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 在 `.gitignore` 的 SteamSage2 區塊加 `extension/data/`；建立 `extension/`、`extension/icons/`、`tests/extension/fixtures/`、`tests/fixtures/report/`。
  `extension/data/` 整個被排除，不放 `.gitkeep`；`report` 寫檔時由 `write_text_atomic` 建立資料夾。
- [X] T002 [P] 新增 `scripts/make_extension_icons.py`：只用標準函式庫（`zlib`、`struct`）畫 16／32／48／128 px 的 PNG（深藍底 `#1b2838`、綠色 `#a4d007` 的「S」字形或價格標籤形狀），
  輸出到 `extension/icons/icon-<n>.png`；執行一次並把 PNG 納入版控。
- [X] T003 [P] 新增測試頁 `tests/extension/fixtures/`（從 `specs/011-chrome-extension/prototype/out/p2_probe.json` 與原型的觀察精簡，不含願望清單以外的個人資料）：
  - `game_twd.html`：`#game_area_purchase` 內兩個 `.game_area_purchase_game`，一個 `form input[name=subid][value=685434]`＋`.game_purchase_price[data-price-final="79000"]` 文字 `NT$ 790`，
    一個 `input[name=bundleid][value=32470]`＋`.discount_block[data-price-final="220600"]`＋`.discount_final_price` 文字 `NT$ 2,206`。
  - `game_owned.html`：同上再加 `.game_area_already_owned`。
  - `game_usd.html`：價格文字為 `$29.99`（非新台幣）。
  - `game_no_purchase.html`：沒有 `#game_area_purchase`。
  - `wishlist.html`：3 列 `[data-index]`，每列是 `display:grid; grid-template-areas: "capsule title" "capsule mid" "capsule lower"` 的容器，
    子元素：圖片連結（含 `img`）、`style="grid-area:title"` 的 `div` 內只有文字的名稱連結、`style="grid-area:mid"` 的空 `div`、`style="grid-area:lower"` 的價格連結（含 `div`）；
    App 1903340、1091500、730（不在資料中）。
  - `wishlist_restyled.html`：名稱連結內有 `span`（原型 P3 的改版頁）。
  - `data.json`：小型、符合 `steamsage.extension/1`（contracts/extension-data.md）的資料檔：1903340 `now`（`option` sub/685434、`bundle_hints` 一則）、
    1091500 `wait`（`option` bundle/32470、`user: true`、`version_text`）、一款 `na`（`status_reason`）、一個組合包；`data_time` 在 e2e 執行時改寫成「現在」或指定的時間。
    T017、T021、T026、T030、T033 都用它。

---

## Phase 2: Foundational（資料檔與擴充功能骨架，所有情境都依賴）

**Purpose**：正式 `report` 寫出 `steamsage.extension/1`；擴充功能能讀檔、回覆訊息、更新圖示。

### 報告句子拆成純文字函式（HTML 不變）

- [X] T004 在 `tests/unit/report/test_html_golden.py` 寫逐位元組比對測試：
  用 `tests/unit/report/test_html.py` 的 `sample()`、`v3_sample()`，加上一份含組合包（`tests.decision_builders.e33_dispatch()`、`dave_miside()` 組出的批次）
  與使用者指定版本（`version.basis == "user"`）的資料，**在改 `html.py` 之前**產生 `tests/fixtures/report/golden_*.html`（一次性產生程式寫在測試檔的 `if __name__ == "__main__"`），
  測試斷言 `render(data)` 與 golden 完全相同。先確認測試在現行程式上通過。
- [X] T005 [P] 在 `tests/unit/report/test_html.py` 新增純文字函式的測試（先失敗）：`version_text(d)` 回傳 `_version` 的內容去掉 HTML（沒有時 `None`）；
  `bundle_hint_texts(d, by_id)` 回傳 `[{"id", "text"}]`，`text` 等於報告的指引句（「可和 X 一起買：組合包 −10%（另含其他內容）；組合包含的是 Steam 預設的版本…」，不含「見〈組合包〉」連結字樣）；
  `bundle_card_texts(b)` 回傳 `{"grade_text", "discount_text", "lines", "advice_text", "advice_low", "check_text"}`，和 `_bundle_card` 顯示的各行相同；
  `tag_labels(tags)`；`sorted_games(group, games)` 等於 `_sorted`；`lowest_label(data)` 等於 `_lowest`。
- [X] T006 修改 `src/steamsage/report/html.py`：把 `_version`、`_bundle_hints`、`_bundle_card`、`_tags`、`_sorted`、`_lowest` 中組字串的部分拆成 T005 的公開函式，原本的 HTML 函式改呼叫它們。
  T004 的 golden 測試與既有 `test_html.py` 全部通過（輸出逐位元組不變）。

### 資料檔的產生

- [X] T007 [P] 寫 `tests/unit/report/test_extension_data.py`（先失敗），測 `steamsage.report.extension.build(data, record=None)`：
  - 檔頭：`format == "steamsage.extension/1"`、`generated_at`、`as_of`、`stale_hours == 26`、`refresh_note == data["data_refresh"]["note"]`、
    `record`：傳入 `{"saved": True, "file": ".../20260927T050639Z.json.gz"}` → 檔名 `"20260927T050639Z.json.gz"`；`{"saved": False, ...}` 或 `None` → `null`；
    `lowest_label == html.lowest_label(data)`（規則有 `p_min_months` → 「12 個月內最低」，否則「長期最低」，兩種都測）；
    `versions == {"model": "<name> <version>", "rule": "<name> <version>"}`、`summary` 只有 now／soon／wait／low／na 五個鍵且等於各組 `games` 數。
  - `data_time`：三款 `confirmed_at` 為 05:00、06:00、07:00 → 06:00；兩款 05:00、07:00 → 05:00（`median_low`）；全部 `current` 為 None → `null`。
  - 遊戲欄位（contracts/extension-data.md）：`now`／`soon`／`wait`／`low` 的數字取自決策（`price_twd`＝`current.price_twd`、`cut_pct`、`stale`、`sweet_twd`、`sweet_pct`、
    `point` 的 label／status／start／end、`probability`＝`sweet_probability`、`p_min_twd`、`p_min_pct`）；`na` 的數字欄位為 `null`、`status_reason` 等於決策；
    `option` 由 `version.option` 與 `version.basis == "user"` 組成，`version.option` 為 None 時為 `null`；`editions` = `len(editions)`；`ns_reasons` = `non_seasonal.reasons`（沒有時 `[]`）；
    `reasons` 順序不變；`tags`、`version_text`、`bundle_hints` 等於 T005 的函式在同一個決策上的輸出。
  - 排序：`games` 依 now → soon → wait → low → na，組內等於 `html.sorted_games`。
  - 組合包：`id`、`name`、`price_twd`、`contents`（名稱，未知時 `App <id>`）、`owned_note`，其餘等於 `bundle_card_texts`；沒有組合包時 `[]`。
  - 不含：`curve`、`probabilities`、`itad_id`、`comparison`；JSON 字串中不出現測試用的假金鑰（把 `Secrets` 的值放進環境也不會出現）。
  - 大小：`len(json.dumps(build(data), ensure_ascii=False, separators=(",", ":")).encode()) ≤ 500_000`，用 150 款、每款 12 個原因的資料。
- [X] T008 實作 `src/steamsage/report/extension.py`：`FORMAT = "steamsage.extension/1"`、`STALE_HOURS = 26`、`build(data: dict, record: dict | None = None) -> dict`、
  `dumps(payload) -> str`（`ensure_ascii=False, separators=(",", ":")`）。只 import `steamsage.report.html` 與標準函式庫（不 import 分析核心，憲章 VII；
  在 `tests/unit/report/test_html.py::test_report_module_does_not_import_the_core` 的精神下，新增同樣的檢查到 T007）。T007 通過。
- [X] T009 [P] 寫 `tests/contract/test_extension_contract.py`（先失敗）：用真實形狀的批次（`tests.decision_builders` 的 now／soon／wait／low／na 各一款＋`e33_dispatch()` 組合包）
  檢查每款遊戲依分組的必要鍵齊全、型別正確（整數元、0–1 機率、UTC `Z` 時間字串）、`games` 的 `app_id` 不重複、`bundle_hints[].id` 都在 `bundles[].id` 中。
- [X] T010 [P] 在 `tests/contract/test_cli_report.py` 新增（先失敗；沿用 `config_path`、`db` fixture）：
  - `config_path.parent / "extension" / "manifest.json"` 存在時，`report --json` 寫出 `extension/data/steamsage-extension.json`，摘要 `extension` 為該路徑，檔案 `format` 正確，目錄中沒有 `.tmp`。
  - manifest 不存在時不建立 `extension/`，摘要 `extension` 為 `null`。
  - `--as-of 2026-09-24` 與 `--rule 3.0.0` 不改資料檔（mtime 與內容不變）。
  - 寫檔失敗（monkeypatch `steamsage.report.extension.dumps` 丟 `OSError`）：HTML 報告與正式紀錄照常寫出、結束代碼 `cli.EXIT_PARTIAL`、摘要 `extension` 以「未寫入：」開頭、stderr 有「擴充功能資料未寫入」。
  - `latest.html` 的內容和沒有 manifest 時相同（SC-009）。
- [X] T011 實作：`src/steamsage/config.py` 的 `Config.extension_dir` property（`self.path.parent / "extension"`）；
  `src/steamsage/commands.py` 的 `report_command` 在 HTML 寫完之後，`official and (extension_dir / "manifest.json").exists()` 時 `write_text_atomic(extension_dir / "data" / "steamsage-extension.json", dumps(build(data)))`，
  `build(data, record=record_status)`；例外時記錄 `f"未寫入：{type(exc).__name__}: {exc}"`、`ctx.progress.note("擴充功能資料未寫入：…")`，並讓 `attention` 為真；摘要加 `extension`。T010 通過。

### 擴充功能骨架

- [X] T012 [P] 寫 `tests/extension/lib.test.js`（`node:test`、`node:assert`，先失敗）的共用部分：
  `money(1063) === "NT$1,063"`、`money(null) === "未知"`；`pct(0.825835) === "83%"`、`pct(null) === "—"`；`off(0) === "原價"`、`off(20) === "-20%"`；
  `taipei("2026-09-27T05:06:12Z") === "2026-09-27 13:06"`、`taipei(null) === "未知"`；
  `isStale(data, now)`：`data_time` 為 `now − 26h` → false，`now − 26h − 1s` → true，`null` → true；
  `checkData(obj)`：`format` 不同 → `{ok:false, why:"format"}`，缺 `games` 或 `data_time` 鍵 → `format`，正確 → `{ok:true}`；
  `badge(result, now)`：正常 3 款 → `{text:"3", color:"#1e7d32"}`、0 款 → `{text:"", ...綠}`、過舊 → 橘 `#b06000`（0 款時文字 `!`）、讀不到 → `{text:"!", color:"#a1261b"}`；
  `esc('<a href="x">&\'')` 跳脫五個字元。
- [X] T013 實作 `extension/lib.js` 的上述函式（JS 模組約定見上）。T012 通過。
- [X] T014 [P] 寫 `tests/extension/manifest.test.js`（先失敗）：讀 `extension/manifest.json`，斷言 `manifest_version === 3`、`permissions` 恰為 `["alarms"]`、
  沒有 `host_permissions`／`optional_permissions`／`web_accessible_resources`、CSP 字串等於 contracts/extension-ui.md、
  `content_scripts[0].matches` 恰為 `https://store.steampowered.com/app/*`、`https://store.steampowered.com/wishlist/*`，`js` 為 `["lib.js", "content.js"]`、
  `action.default_popup === "popup.html"`、`background.service_worker === "sw.js"`、四個 icon 檔存在。
- [X] T015 [P] 寫 `tests/extension/static.test.js`（先失敗）：`extension/content.js`、`extension/lib.js`、`extension/popup.js` 不含
  `fetch(`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`importScripts(`（`sw.js` 除外）、`http://`、`https://` 以外的網址字面
  （允許的只有 `https://store.steampowered.com/app/`、`https://store.steampowered.com/bundle/` 兩個前綴，用於連結）；`sw.js` 唯一的 `fetch(` 參數是 `chrome.runtime.getURL(`；
  所有檔案不含 `innerHTML =` 除非同一行有 `esc(`（或改用 `textContent`）；不含 `document.cookie`、`chrome.cookies`。
- [X] T016 實作 `extension/manifest.json`（contracts/extension-ui.md；`name` "SteamSage2"、`version` "1.0.0"、`description` 繁中、icons）與 `extension/sw.js`：
  `importScripts('lib.js')`；`readData()` 用 `fetch(chrome.runtime.getURL('data/steamsage-extension.json'), {cache: 'no-store'})`，不存在 → `missing`、JSON 錯誤 → `broken`、`checkData` 不過 → `format`；
  `refresh()` 讀檔並 `chrome.action.setBadgeText`／`setBadgeBackgroundColor`（`SteamSage.badge`）；`onInstalled` 與 `onStartup` 建立 `refresh` alarm（`periodInMinutes: 30`）並 `refresh()`；
  `onAlarm` → `refresh()`；`onMessage({type:"data"})` → `refresh()` 後回覆 `{ok, data, stale}` 或 `{ok:false, why}`（`return true` 非同步回覆）。T014、T015 通過。
- [X] T017 端對端骨架 `tests/extension/e2e.py`（`uv run --with playwright python tests/extension/e2e.py [--live]`）：
  Playwright Chromium 以 `--disable-extensions-except`／`--load-extension=extension` 啟動（暫存 profile、`ignore_cleanup_errors=True`）；
  把資料檔備份、測試結束還原；`store.steampowered.com` 的測試網址用 `context.route` 回傳 `tests/extension/fixtures/*.html`，其他請求 abort 並記錄；
  每個頁面開 CDP `Network.enable`，記錄 initiator 含 `chrome-extension://` 的請求；Service Worker 嘗試 `fetch('https://example.com/')` 必須被擋下。
  第一組檢查（原型 P1，research R0.1）：寫 v1 → 彈出視窗讀到 v1；暫存檔再改名寫 v2，不重新載入 → 彈出視窗與遊戲測試頁讀到 v2；`ServiceWorker.stopAllWorkers` 後寫 v3 → 讀到 v3；
  寫一半 → `broken`；刪除 → `missing`；`chrome.alarms.getAll()` 恰為一個 `refresh`、`periodInMinutes === 30`；直接覆寫資料檔後在 Service Worker 執行 alarm 的處理函式（沒有任何頁面）→ 圖示更新；
  最後印出「擴充功能發出的請求 N」，N 必須為 0。結束代碼：全部通過 0，否則 1。

**Checkpoint（Foundational）**：pytest、node 測試、e2e 全部通過；在真實資料執行 `uv run steamsage report`，確認寫出資料檔（大小、耗時和 research R0.3 對照）；
HTML 和改版前在同一份資料上逐位元組相同（先用 `git stash`／worktree 的 master 對同一個 `data/forecasts` 紀錄 render 比對）；commit、報告。

---

## Phase 3: User Story 1 — 在遊戲頁面看到這款遊戲的甜蜜價（P1）

**Goal**：資料中的遊戲頁，購買區正上方出現面板；頁面現價取追蹤的購買選項並列；已擁有時縮成一行。

**Independent Test**：真實 Steam 上 10 款以上遊戲的面板數字和報告相同、頁面現價 = 同一購買選項在頁面上的價格；不在資料中的遊戲頁不變（SC-002）。

- [X] T018 [P] [US1] 在 `tests/extension/lib.test.js` 新增（先失敗）：
  `matchOption(blocks, option)`：`blocks` 為 `[{subid, bundleid, priceFinal, text}]`（字串，來自頁面）；`{kind:"sub", id:685434}` 對到 `subid "685434"` → `{cents:79000, text:"NT$ 790"}`；
  `kind:"bundle"` 對 `bundleid`；找不到 → `{why:"頁面上找不到追蹤的購買選項"}`；`priceFinal` 為 null → `{why:"頁面上沒有這個選項的價格"}`；文字不含 `NT$` → `{why:"頁面不是新台幣，不並列"}`；
  `option` 為 null → `{why:"沒有追蹤的購買選項"}`。
  `panelModel(game, live, owned, data, now)`：回傳 `{group, groupName, color, header, stale, refreshNote, cells: [[label, value]...], notes: [...], reasons, owned, collapsedText}`；
  `cells` 依序為「頁面現價」（`live.text` 或 `—`）、「甜蜜價」`NT$790 -20%`、「甜蜜時點」`2026 秋特（官方）`（`status` announced→官方、estimated→預估）、「到價機率」`83%`、
  `data.lowest_label`（例如「12 個月內最低」，不寫死）`NT$692 -30%`；
  `notes` 依序為 `live.why`、`version_text`、`另有 N 個版本`（N > 0）、每個 `bundle_hints[].text`、每個 `ns_reasons`；`na` → `cells` 為空、`notes` 為 `[status_reason]`；
  `owned` → `collapsedText === "你已擁有這款遊戲；以下是購買前（資料時間 2026-09-27 13:06）的建議"`；`header` 含「資料時間 …（台北）」；過舊時 `stale === "資料超過 26 小時，請先執行更新"`。
- [X] T019 [US1] 實作 `extension/lib.js` 的 `matchOption`、`panelModel`。T018 通過。
- [X] T020 [US1] 實作 `extension/content.js` 的遊戲頁部分：網址 `^/app/(\d+)` → 向 Service Worker 要資料 → 遊戲不在資料中或沒有 `#game_area_purchase` 就結束；
  從 `#game_area_purchase .game_area_purchase_game` 讀出 blocks（`form input[name=subid|bundleid]`、`[data-price-final]`、`.discount_final_price, .game_purchase_price` 的文字）；
  `owned = !!document.querySelector('.game_area_already_owned')`；用 `panelModel` 的結果建立 `div.steamsage-panel`（shadow root，樣式配合 Steam 深色：底 `#1f2a38`、左框分組顏色），
  插在 `#game_area_purchase` 前面；原因用 `<details>` 展開；已擁有時只顯示 `collapsedText` 與「展開」按鈕，按下後顯示完整內容。
  一頁只插一次（已有 `.steamsage-panel` 就不插）；全部包在 `try/catch`。所有字串用 `textContent` 設定。
- [X] T021 [US1] 在 `tests/extension/e2e.py` 新增遊戲頁檢查（測試頁）：`game_twd.html` 以 `/app/1903340/` 提供 → 一個面板、`nextElementSibling.id === "game_area_purchase"`、面板文字含 `NT$ 790` 與資料中的甜蜜價；
  以 `/app/1091500/` 提供（資料中為 `bundle/32470`）→ 頁面現價 `NT$ 2,206` 並註明使用者指定；`game_usd.html` → 不並列並顯示「頁面不是新台幣，不並列」；
  `game_owned.html` → 顯示已擁有的一行、按「展開」後出現完整內容；`game_no_purchase.html` → 沒有面板；以 `/agecheck/app/1903340/` 提供 `game_twd.html` → 沒有面板（FR-012）；`/app/730/`（不在資料中）→ 沒有面板、`document.body.innerHTML` 和停用擴充功能時相同。
  測試用資料檔由 e2e 從 `tests/extension/fixtures/data.json`（T003）寫入。
- [X] T022 [US1] 在 `tests/extension/e2e.py --live` 新增真實遊戲頁檢查（原型 `p3_live.py` 的邏輯，未登入、年齡 cookie）：用真實資料檔（`uv run steamsage report` 產生），
  抽原型的 16 款：面板在購買區前、頁面現價 = 資料檔 `price_twd × 100`（有現價的款）、
  **面板文字包含由資料檔格式化出的分組名稱、甜蜜價與折扣、甜蜜時點、機率、`lowest_label` 與最低價、每則 `bundle_hints[].text`**（資料檔＝報告由 T007 保證，合起來就是 SC-002）；
  `na` 的面板只有 `status_reason`；面板在 DOMContentLoaded 後的毫秒數（SC-006 ≤ 1000）、擴充功能發出的請求 0；
  截圖 `specs/011-chrome-extension/prototype/out/e2e-panel-<app>.png`（1903340、1091500、9500003）。

**Checkpoint（US1）**：測試與 e2e（含 `--live`）通過；看截圖確認面板沒有遮住或擠壓 Steam 的內容；commit、報告。

---

## Phase 4: User Story 2 — 點工具列圖示看整份清單（P1）

**Goal**：彈出視窗依分組列出遊戲與組合包，圖示顯示「現在買」款數。

**Independent Test**：用真實資料打開彈出視窗，每組款數和報告相同，圖示數字 = 現在買款數；資料檔不存在時顯示如何產生資料（SC-001）。

- [X] T023 [P] [US2] 在 `tests/extension/lib.test.js` 新增（先失敗）`popupModel(result, now)`：
  - `ok` → `{header: ["資料時間 2026-09-27 13:06（台北）· 報告 2026-09-27 13:06"], stale, refreshNote, hint: "買完遊戲後可執行 更新資料.cmd 立即更新",
    groups: [{key, title: "現在買（11）", open: true|false, rows: [...]}] ×5, bundles: [...]}`；`now`、`soon` 的 `open` 為 true，其他 false；
    每組 `rows` 的順序等於 `games` 中該組的順序；一般列 `{appId, name, url: "https://store.steampowered.com/app/<id>/", price: "NT$790 -20%", sweet: "NT$790 -20%", point: "2026 秋特", probability: "83%"}`；
    `na` 列 `{appId, name, url, reason}`；現價未知 → `price: "未知"`。
  - 組合包列 `{name, url: "https://store.steampowered.com/bundle/<id>/", grade, discount, text}`，`text` = `advice_text`（低信心加「（低信心）」）或 `lines` 的最後一行。
  - `{ok:false, why}` → `{error: "還沒有資料：請先執行 更新資料.cmd"}`（missing）／「資料檔損壞或正在寫入，請稍後再開」（broken）／
    「資料格式不認得（需要 steamsage.extension/1），請更新擴充功能或重新產生報告」（format），而且沒有 `groups`。
- [X] T024 [US2] 實作 `extension/lib.js` 的 `popupModel`。T023 通過。
- [X] T025 [US2] 實作 `extension/popup.html`、`extension/popup.css`、`extension/popup.js`：寬 400 px、最大高 600 px 可捲動；
  打開時 `chrome.runtime.sendMessage({type:"data"})` → `popupModel` → 用 DOM API 建立頂端資訊、五個 `<details>` 分組（每列為表格式的兩行：名稱連結／數字）與組合包一節；
  連結 `target="_blank" rel="noopener"`；讀不到時只顯示 `error`。深色與淺色都可讀（`prefers-color-scheme`）。
- [X] T026 [US2] 在 `tests/extension/e2e.py` 新增彈出視窗檢查：用 `fixtures/data.json` 打開 `chrome-extension://<id>/popup.html` → 各組標題款數等於資料 `summary`、
  列數等於各組 `games` 數、組合包數、連結網址；`sw.evaluate("chrome.action.getBadgeText({})")` 等於 now 款數，0 款為空字串；missing／broken／format 三種訊息；
  打開到內容出現 < 1000 ms（SC-006）。`--live` 時再用真實資料檔檢查款數等於資料檔 `summary`，並截圖 `prototype/out/e2e-popup.png`。

**Checkpoint（US2）＝ MVP**：測試與 e2e 通過；真實資料截圖（彈出視窗、遊戲頁面板）；寫試用說明（安裝三步驟、要看什麼、怎麼回報），
用 `SendUserFile` 傳給使用者：`prototype/out/e2e-popup.png`、`e2e-panel-1903340.png`、`e2e-panel-1091500.png` 與試用說明；commit、報告，等使用者試用回饋。

---

## Phase 5: User Story 3 — 在願望清單頁每一列看到分組與甜蜜價（P2）

**Goal**：願望清單每列名稱下方一行；捲動時新列 1 秒內出現；Steam 改版時不顯示、不出錯。

**Independent Test**：從頭捲到尾，資料中的每一列恰好一行、不在資料中的 0 行；改版測試頁 0 行（SC-003）。

- [X] T027 [P] [US3] 在 `tests/extension/lib.test.js` 新增（先失敗）：
  `pickNameLink(links)`：`links` 為 `[{childCount, text}]`，回傳第一個 `childCount === 0` 且 `text.trim()` 非空的索引；圖片連結（childCount 1、text ""）與價格連結（childCount 2）不選；都不符合 → -1。
  `pickMid(children)`：`children` 為 `[{gridRowStart}]`，回傳第一個 `gridRowStart === "mid"` 的索引，沒有 → -1。
  `rowAction(lineApp, rowApp, inData)`：同一款 → `"keep"`；不同款且 `inData` → `"replace"`；不同款且不在資料中 → `"remove"`；沒有行且 `inData` → `"add"`；沒有行且不在資料中 → `"none"`。
  `lineModel(game, data, now)`：`{groupName, color, text: "甜蜜價 NT$141 -25% · 2026 冬特 · 71%", bundle: bool, title: 前三個原因以 "\n" 連接, stale: bool}`；`na` → `text` = `status_reason`、`title` = `status_reason`。
- [X] T028 [US3] 實作 `extension/lib.js` 的 `pickNameLink`、`pickMid`、`rowAction`、`lineModel`。T027 通過。
- [X] T029 [US3] 實作 `extension/content.js` 的願望清單部分（research R0.2）：網址以 `/wishlist/` 開頭 → 要資料 → `handle()` 掃描 `[data-index]`：
  列的 App 編號 = 第一個 `a[href*="/app/"]` 的 `/app/(\d+)`；名稱連結 = `pickNameLink`；grid = 名稱連結的 `parentElement.parentElement`；
  插入點 = `pickMid(getComputedStyle(child).gridRowStart)` 的子元素；依 `rowAction` 新增、保留、替換或移除 `span.steamsage-line[data-app]`（shadow root，`display:block`，`title` 為原因），放在插入點最前面；
  找不到名稱或 mid → 跳過該列。載入時 `handle()` 一次，之後 `MutationObserver(document.body, {childList, subtree})` 以 `requestAnimationFrame` 合併、每個畫面最多一次；
  忽略只由自己的節點引起的變動（避免無限迴圈）。每列 `try/catch`。
- [X] T030 [US3] 在 `tests/extension/e2e.py` 新增願望清單檢查（測試頁）：`wishlist.html` → 1903340、1091500 各一行、730 沒有；把第一列的連結改成另一款（模擬 Steam 重複使用列）→ 1 秒內那一行被替換；
  連續觸發 50 次變動後每列仍最多一行；`wishlist_restyled.html` → 0 行、沒有 pageerror。
  `--live`：原型 `p4_wishlist.py` 的捲動（滑鼠滾輪 350 px、每步 1 秒）從頭到尾，產生的每列資料中遊戲恰好一行、0 重複、0 列超過 1 秒；列高與停用擴充功能時相同；
  記錄每一步 `handle()` 的處理時間（最大值與平均，寫進 validation；目前只能驗證到 68 款）；
  截圖 `prototype/out/e2e-wishlist-1280.png`、`e2e-wishlist-700.png`，看截圖確認名稱沒有被擠壓或遮住。

**Checkpoint（US3）**：測試與 e2e（含 `--live`）通過；截圖確認；commit、報告。

---

## Phase 6: User Story 4 — 知道資料是什麼時候的（P2）

**Goal**：三個位置都顯示資料時間；超過 26 小時與更新失敗時提示；每日排程 02:30。

**Independent Test**：資料時間 26 小時內沒有提示、超過時三個位置都有；排程下一次執行 02:30。

- [X] T031 [P] [US4] 在 `tests/extension/lib.test.js` 新增（先失敗）：`popupModel`、`panelModel`、`lineModel` 在 `data_time = now − 27h` 時都帶 `stale: "資料超過 26 小時，請先執行更新"`（line 為 true 並在 `text` 前加「資料過舊 · 」），
  `now − 25h` 時沒有；`refresh_note` 非 null 時 `popupModel`、`panelModel` 帶 `refreshNote`（原句），`lineModel` 的 `title` 第一行為該句。
- [X] T032 [US4] 實作 T031（`extension/lib.js`），並讓 `popup.js`、`content.js` 顯示：彈出視窗頂端橘色提示列、面板標題下一行橘色提示、願望清單行前的「資料過舊」字樣與橘色標籤。
- [X] T033 [US4] 在 `tests/extension/e2e.py` 新增：資料檔 `data_time` 改為 27 小時前 → 彈出視窗、遊戲測試頁、願望清單測試頁都有提示，圖示底色橘；`refresh_note` 有值 → 彈出視窗與面板顯示原句。
- [X] T034 [US4] **10/1，先向使用者確認再執行**：把 Windows 工作排程器「SteamSage2 每日背景更新」的觸發時間改為每天 02:30（research R6）：
  先 `Get-ScheduledTask … | Select-Object -ExpandProperty Actions, Triggers, Settings` 存到 scratchpad，
  `Set-ScheduledTask -TaskName "SteamSage2 每日背景更新" -Trigger (New-ScheduledTaskTrigger -Daily -At 02:30)`，再讀一次比對動作、`conhost.exe --headless`、`StartWhenAvailable`、使用者帳戶不變，
  `Get-ScheduledTaskInfo` 的 `NextRunTime` 為 02:30；同步修改 `README.md` 的排程說明（00:00 → 02:30，理由：Steam 特賣在台北 01:00／02:00 開始或換日）。

**Checkpoint（US4）**：測試與 e2e 通過；commit、報告。

---

## Phase 7: Polish & Cross-Cutting

- [X] T035 [P] `README.md` 新增「Chrome 擴充功能」一節：安裝三步驟（quickstart §3）、三個位置的內容、資料何時更新（每次 `report`；背景排程 02:30；買完可執行 `更新資料.cmd`）、
  26 小時過舊提示、隱私（不連外、不讀 Cookie 與登入資料、只讀自己的資料檔）、Chrome 提醒開發人員模式時選擇保留、Steam 改版時願望清單的行可能消失而彈出視窗不受影響、
  測試指令（`node --test "tests/extension/*.test.js"`、`e2e.py [--live]`）。
- [X] T036 [P] 新增 `specs/011-chrome-extension/validation.md`：SC-001–SC-009 逐條的實測結果與數字（款數比對、10 款以上的面板比對、願望清單捲動結果、
  重新產生報告後讀到新資料的實測、請求 0、彈出視窗與面板的時間、`report` 耗時（改版前後各 3 次）與資料檔大小、HTML 在同一份紀錄上和 master 逐位元組相同（git worktree）、決策與正式紀錄不變）。
- [X] T037 使用者在自己的 Chrome 上試用（quickstart §4）：登入後願望清單的 68 款（含未登入看不到的 9 款）都有那一行、SC-004 在品牌版 Chrome 實測、Network 面板沒有擴充功能的請求；
  依回饋修正，並把結果補進 `validation.md`。
- [X] T038 更新 `HANDOFF.md`：011 的狀態、做了什麼、擴充功能資料夾與測試指令、已知限制（Steam 改版、開發人員模式提醒、登入後才看得到的遊戲）、下一步 012（事後對照）；
  更新記憶（`feature011-direction.md`）。
- [X] T039 **10/1，使用者確認後**合併到 master（plan D3，排程在工作目錄執行）：跑全部測試、`git merge --squash` 或依使用者指示；確認合併後 `uv run steamsage report` 仍寫出資料檔，
  Chrome 載入的仍是 `〈專案資料夾〉\extension`。

---

## Dependencies & Execution Order

```text
Setup (T001–T003)
  └─▶ Foundational (T004–T017)            # 資料檔 + 擴充功能骨架；T004 必須在 T006 之前
        ├─▶ US1 (T018–T022)               # 遊戲頁面板
        ├─▶ US2 (T023–T026)               # 彈出視窗 ── US1 + US2 = MVP，給使用者試用
        ├─▶ US3 (T027–T030)               # 願望清單（可和 US1／US2 並行，但 content.js 與 US1 同檔，依序做）
        └─▶ US4 (T031–T034)               # 依賴 US1–US3 的顯示位置；T034 在 10/1
              └─▶ Polish (T035–T039)      # T037 使用者試用、T039 合併在 10/1
```

- `extension/lib.js` 與 `tests/extension/lib.test.js` 被每個情境修改：同一個檔案的任務依序做。
- `extension/content.js`：US1（T020）→ US3（T029）→ US4（T032）依序。

## Parallel Opportunities

- Setup：T002（圖示）、T003（測試頁）可同時做。
- Foundational：T005、T007、T009、T010（Python 測試）與 T012、T014、T015（JS 測試）彼此不同檔，可同時寫；實作 T006 → T008 → T011 依序，T013、T016 可和 Python 實作並行。
- US1 的 T018 與 US2 的 T023 都改 `lib.test.js`：依序。US2 的 T025（popup 檔案）可和 US1 的 T020（content.js）並行。
- Polish：T035、T036 可同時做。

## Implementation Strategy

1. **9/28**：Setup＋Foundational（T001–T017）。Checkpoint：真實 `report` 寫出資料檔、HTML 逐位元組不變。
2. **9/29**：US1＋US2（T018–T026）→ **MVP**：真實資料截圖與試用說明給使用者（`SendUserFile`）。
3. **9/30**：US3（T027–T030）、US4 的顯示部分（T031–T033）、README、validation。
4. **10/1**：依試用回饋修正（T037）；排程改 02:30（T034，先確認）；合併到 master（T039，先確認）。
5. **10/2 01:00 前**：使用者確認可用（SC-008）。

每個 checkpoint 都在真實資料與真實 Steam 頁面上驗證，不只看測試（HANDOFF §5）。

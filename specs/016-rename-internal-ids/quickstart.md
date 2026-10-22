# Quickstart: 驗證 016 內部識別碼改名

指令都在 PowerShell 執行。比較檔案用 `git diff --no-index`，不用 `fc`（PowerShell 的 `fc` 是 Format-Custom）。

## 原則

**A 與 B 兩段完全不碰**主資料夾 `〈專案資料夾〉` 的設定檔、資料庫、登錄與排程工作，只用暫存副本。C 段才是真正的搬家，由使用者在合併後執行。

## A. 自動測試（worktree `〈專案資料夾〉-016`）

```powershell
uv run pytest
node --test tests/extension/
uv run python tests/extension/e2e.py
uv run python scripts/scan_names.py
```

預期：

- pytest、node 全部通過，數量不少於改名前：pytest 1597、node 55（SC-001）。
- e2e 全部通過。
- 掃描印出各類別次數，「未允許」為 0，結束代碼 0（SC-005）。

## B. 真實資料的副本（SC-002、SC-003、SC-004、SC-007）

1. **建立副本**：暫存資料夾 `$T`，複製以下內容：
   - 主資料夾的 `steamsage.toml`；
   - `data\steamsage.db`：用 SQLite 備份 API，或在背景更新以外的時間直接複製；
   - `data\steam_sales.toml`、`data\forecasts\`；
   - `extension\` 整個資料夾。
2. **舊程式產生基準**：用主資料夾（master）的程式對副本產生報告，得到正式紀錄 A 與擴充功能資料檔 A。

   ```powershell
   uv run --project 〈專案資料夾〉 steamsage report --config $T\steamsage.toml
   ```

3. **只有舊名稱時，新程式拒絕**（SC-004）：在 worktree 執行下面的指令。

   ```powershell
   uv run sweetspot update --config $T\sweetspot.toml
   ```

   預期：
   - 結束代碼 4；
   - stderr 提示先執行搬家；
   - `$T` 沒有出現 `sweetspot.toml` 或 `data\sweetspot.db`，舊檔雜湊不變。
4. **模擬失敗**（SC-003）：先記下 `$T` 全部檔案的清單與雜湊。另開一個 Python 唯讀開著 `$T\data\steamsage.db`，再執行：

   ```powershell
   uv run sweetspot migrate --config $T\sweetspot.toml
   ```

   預期：
   - 結束代碼 1，說明停在哪一步；
   - 關掉那個 Python 後，`$T` 的檔案清單與雜湊和搬家前相同，備份資料夾除外。
5. **搬家**（SC-003）：

   ```powershell
   uv run sweetspot migrate --config $T\sweetspot.toml --dry-run
   uv run sweetspot migrate --config $T\sweetspot.toml
   ```

   預期：
   - 1 分鐘內完成；
   - 三個檔案改成新名稱，SHA-256 與搬家前相同；
   - 備份資料夾裡有三份副本，資料庫的 quick_check 結果為 ok；
   - 環境段的本機程式與排程工作都是 `skipped`，因為 `$T` 不是登記的資料夾。到工作排程器確認「SteamSage2 每日背景更新」仍在、沒有新工作。
6. **再搬一次**（FR-009b）：預期顯示「已經是新名稱」，什麼都沒改，結束代碼 0。
7. **新程式產生報告**：

   ```powershell
   uv run sweetspot report --config $T\sweetspot.toml
   ```

   得到紀錄 B 與 `$T\extension\data\sweetspot-extension.json`。用比對腳本確認：
   - 69 款的決策、格式名稱（`steamsage.decision/2`）、規則版本逐款相同（SC-002）；
   - 擴充功能資料檔除了 `generated_at` 與 `config_path` 以外相同，`config_path` 指向 `$T\sweetspot.toml`；
   - HTML 報告（`$T\data\reports\latest.html`，第 2 步執行後先複製一份）除了產生時間與路徑以外相同。
8. **回測資料集識別碼**：分別用舊程式與新程式對副本執行下面的指令，資料集識別碼相同。

   ```powershell
   backtest-rule --cutoff 2026-09-25 --apps-limit 200
   ```

9. **金鑰**（SC-007）：用只印布林值的腳本，確認以下輸出與檔案中都沒有 `ITAD_API_KEY`、`STEAM_WEB_API_KEY` 的值：
   - 步驟 3–8 的輸出；
   - `$T\data\logs\`；
   - 備份資料夾的 `migration.json`。
10. 刪除 `$T`。
11. **真正的工作排程器**（research R6，用暫時的測試工作）：
    - 先讀一次「SteamSage2 每日背景更新」的設定並記下。
    - 建立「SweetSpot 搬家測試（舊）」，以測試名稱執行排程工作步驟。
    - 確認改名結果：舊的已刪除，「SweetSpot 搬家測試（新）」的觸發、動作、工作目錄、`StartWhenAvailable`、`LogonType`、`RunLevel` 都和舊的相同，`<URI>` 是新名稱。
    - 刪除新的。
    - 再讀一次「SteamSage2 每日背景更新」，確認和開始時完全相同。

## 實測紀錄（2026-10-15，016 T039–T043）

**A 自動測試**：
- pytest 1743 passed（改名前 1597）；node 56 passed（改名前 55）。
- e2e 124/124：要用 `PYTHONUTF8=1` 和 `playwright==1.63.0`，見 HANDOFF §6。
- 掃描：1936 處、646 個文字檔、略過 4 個二進位檔，未允許 0。

**B 真實資料副本**：
- **建立副本**：資料庫以 SQLite 備份 API 複製，`quick_check` ok；主資料夾的設定檔與資料庫雜湊前後相同。
- **舊程式產生基準**：master 的 `steamsage report` 8 秒，紀錄 A。
- **只有舊名稱時**：新程式的 `update`、`report` 都以 4 結束，提示「找到舊名稱的檔案（steamsage.toml），請先執行搬家：uv run sweetspot migrate」；副本 77 個檔案完全不變（SC-004）。
- **模擬失敗**：
  - (a) 另一個程序只開著資料庫：資料庫改名失敗（WinError 32），全部改回；原有檔案的清單與雜湊相同。
  - (b) 另一個程序持有讀取交易：WAL 是空的，checkpoint 沒有回報忙碌，同樣在改名時失敗並改回。checkpoint 忙碌那條路由 `test_busy_checkpoint_is_refused` 覆蓋。
  - 唯一不同的是 `steamsage.db-shm`：SQLite 的共用記憶體索引，任何連線都會改寫，不是資料。
  - 試跑時發現改名順序和 research R4 不同：原本是設定檔先，已改為資料庫先，有 `test_the_database_is_renamed_first` 守著。
- **搬家**：
  - 3.6 秒（SC-003 上限 1 分鐘）；三個檔案的 SHA-256 與搬家前相同。
  - 備份資料夾有三份副本與 `migration.json`，資料庫副本 `quick_check` ok；`-wal`（0 位元組）、`-shm` 跟著改名。
  - 本機程式、排程工作都是 `skipped`；「SteamSage2 每日背景更新」的 XML 前後相同，沒有新工作。
- **再搬一次**：「已經是新名稱，什麼都沒改」，結束代碼 0，檔案不變。
- **新程式產生報告（紀錄 B）**：
  - 69 款的甜蜜價、時點與分組都相同。
  - 65 款的非季節機率不同，因為兩次分析時間差了 3 分鐘（非季節預測是「從現在起 30／60／90 天」）。以同一個 `--as-of 2026-10-14` 重跑，HTML 只差 3 行「把設定行加進 steamsage.toml／sweetspot.toml」，非季節機率也相同（SC-002）。
  - 擴充功能資料檔只差 `as_of`、`generated_at`、`record`、`config_path`（指向 `sweetspot.toml`）；格式仍是 `steamsage.extension/1`。
- **回測資料集識別碼**：`backtest-rule --cutoff 2026-09-25 --apps-limit 200` 新舊程式都是 `6e5e15d7…`；結果檔只差 `run.started_at`、`finished_at`、`seconds`；`steamsage_version` 欄位照舊。
- **金鑰**（SC-007）：39 個輸出與檔案（日誌 3 個、`migration.json` 3 個）中，含金鑰的檔案 0 個。檢查腳本只印布林值。
- **真正的工作排程器**（B 第 11 步，016 T045）：
  - 「SweetSpot 搬家測試（舊）」設定為 2030 年觸發、`Interactive`、`Limited`、`StartWhenAvailable`，經 `task_step` 重建為「（新）」；結果 `done`；
  - 舊的已刪除，新的 7 個欄位都相同，`<URI>` 是新名稱；測試工作沒有執行過；
  - 兩個測試工作都已刪除；「SteamSage2 每日背景更新」前後的欄位與匯出 XML 相同。

**D 改名前的雲端備份**（016 T044）：
- 備份是 `sweetspot-db-2026-10-15.zip`（43 MB），內容是 `data/steamsage.db`、`steamsage.toml`、`data/forecasts/`。
- zip 不含 `data/steam_sales.toml`：它在版控裡，還原到專案資料夾時本來就在，所以暫存資料夾從 worktree 補一份。
- 還原步驟：
  1. `update` 以 4 拒絕並提示先搬家；
  2. `migrate` 搬好設定檔與資料庫（擴充功能資料檔不在備份裡，略過），環境段 `skipped`；
  3. `report` 正常寫出紀錄。
- README 的步驟不用改。

## C. 合併後的真正搬家（使用者執行；SC-006）

1. 在主資料夾合併。避開 02:30，也不要在 `更新資料.cmd` 執行中合併。合併後執行 `uv sync`，並刪除只剩 `__pycache__` 的 `src/steamsage/`：`uv run` 不會移除舊套件（research 前提表的更正）。2026-10-15 合併 `a9d9560` 時已做。
2. 先看計畫，確認列出的三個檔案、本機程式、排程工作都正確：

   ```powershell
   uv run sweetspot migrate --dry-run
   ```

   第一次 `uv run` 會花幾秒同步開發環境。
3. 搬家：

   ```powershell
   uv run sweetspot migrate
   ```

   預期結束代碼 0，並列出接下來要做的事。
4. **Chrome**：`chrome://extensions` → SweetSpot → 重新載入，版本顯示 1.2.0。開一個遊戲頁，確認以下都和搬家前相同：
   - 面板；
   - 版本一節；
   - 指定一次再改回 Steam 預設（015 的本機程式）。
5. **排程工作**：工作排程器中只剩「SweetSpot 每日背景更新」，觸發時間 02:30，動作是 `conhost.exe --headless … 背景更新.cmd`。
6. 執行一次 `更新資料.cmd`，或等 02:30。之後 `data\logs\` 會出現 `sweetspot-YYYYMMDD.log`，`background-update.log` 的結束行整體代碼為 0 或 2。
7. 連續 3 個晚上的背景更新整體代碼為 0 或 2（SC-006），之後刪除 `data\pre-016-backup-…` 資料夾，再開始 014。

## D. 從改名前的雲端備份還原（FR-012，抽查）

在暫存資料夾解開任一份改名前的 `sweetspot-<tag>.zip`：裡面是 `data/steamsage.db` 與 `steamsage.toml`。

1. 執行 `uv run sweetspot update --config <暫存>\sweetspot.toml`。預期結束代碼 4，並提示先搬家。
2. 執行 `uv run sweetspot migrate --config <暫存>\sweetspot.toml`。之後 `report` 正常。

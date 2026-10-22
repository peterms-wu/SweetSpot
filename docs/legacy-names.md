# 舊名稱與例外清單

> 這份檔案由 `uv run python scripts/scan_names.py --write` 產生，不要手改（feature 016，[contracts/scan.md](../specs/016-rename-internal-ids/contracts/scan.md)）。

專案的舊名是 SteamSage2（2026-09-28 改名為 SweetSpot）；feature 016 之前，程式的指令、套件、設定檔、資料庫、日誌與擴充功能內部仍用舊名 `steamsage`，016 起全部改為 `sweetspot`（對照見 [contracts/names.md](../specs/016-rename-internal-ids/contracts/names.md)）。

版本控制中的檔案只有下列地方允許留下舊名；其他地方一出現，`tests/unit/test_scan_names.py` 就會失敗。寫在已保存紀錄裡的資料識別碼（格式名稱、004 的分組依據、紀錄欄位）刻意保留舊名：改了，舊紀錄就讀不懂、回測資料集也會改變。

每一處依下列規則由上而下歸類，取第一條符合的。各類的出現次數每次執行掃描時當場計算，不寫在這裡。

## 1. 歷史文件

- 規則：路徑在 `specs/` 下
- 理由：過去 feature 的 spec、plan、原型腳本是當時的紀錄，不改寫（016 spec Assumptions）
- 檔案：整個路徑都是例外，不逐檔列出

## 2. 交接紀錄

- 規則：路徑是 `HANDOFF.md`
- 理由：歷史段落保留當時的名稱；操作步驟由 016 改成新名稱（FR-005）；014 不公開這份檔案
- 檔案：整個路徑都是例外，不逐檔列出

## 3. 只附加的比較紀錄

- 規則：路徑是 `docs/model/comparisons.md`
- 理由：「只附加、不修改」（003 FR-030）；舊紀錄中的指令是當時實際執行的指令
- 檔案：整個路徑都是例外，不逐檔列出

## 4. 掃描本身

- 規則：路徑是 `scripts/scan_names.py`、`docs/legacy-names.md`、`tests/unit/test_scan_names.py`
- 理由：規則與樣本本身必須寫出舊名
- 檔案：
  - `docs/legacy-names.md`
  - `scripts/scan_names.py`
  - `tests/unit/test_scan_names.py`

## 5. 搬家與舊名稱保護

- 規則：路徑是 `src/sweetspot/legacy.py`、`src/sweetspot/migrate.py`，或 `tests/` 下檔名含 `migrate` 或 `legacy_names`
- 理由：要認得舊檔名才能搬家，以及在只有舊檔時拒絕執行
- 檔案：
  - `src/sweetspot/legacy.py`
  - `tests/contract/test_cli_migrate.py`
  - `tests/contract/test_cli_migrate_guard.py`
  - `tests/integration/test_migrate.py`
  - `tests/unit/test_legacy_names.py`

## 6. 忽略舊名稱的檔案

- 規則：路徑是 `.gitignore`
- 理由：舊名的設定檔與資料庫在搬家前後都不能被誤加進版控
- 檔案：
  - `.gitignore`

## 7. 資料識別碼

- 規則：該處是格式名稱 `steamsage.<名稱>/<版本>`、分組依據 `steamsage-004-split` 或紀錄欄位 `steamsage_version`
- 理由：寫在只新增不修改的紀錄裡，或決定回測資料集（016 FR-006、contracts/names.md §2）
- 檔案：
  - `README.md`
  - `docs/model/model-definition.md`
  - `extension/lib.js`
  - `src/sweetspot/cli.py`
  - `src/sweetspot/commands.py`
  - `src/sweetspot/decision/backtest.py`
  - `src/sweetspot/decision/compare_rule.py`
  - `src/sweetspot/decision/contract.py`
  - `src/sweetspot/decision/records.py`
  - `src/sweetspot/forecast/backtest/runner.py`
  - `src/sweetspot/forecast/backtest/split.py`
  - `src/sweetspot/forecast/contract.py`
  - `src/sweetspot/forecast/nonseasonal/backtest.py`
  - `src/sweetspot/report/__init__.py`
  - `src/sweetspot/report/extension.py`
  - `src/sweetspot/report/html.py`
  - `src/sweetspot/review/__init__.py`
  - `src/sweetspot/review/contract.py`
  - `src/sweetspot/review/run.py`
  - `src/sweetspot/review/score.py`
  - `tests/contract/test_cli_backtest_rule.py`
  - `tests/contract/test_cli_forecast.py`
  - `tests/contract/test_cli_ns.py`
  - `tests/contract/test_cli_report.py`
  - `tests/contract/test_cli_review.py`
  - `tests/contract/test_decision_contract.py`
  - `tests/contract/test_extension_contract.py`
  - `tests/contract/test_forecast_contract.py`
  - `tests/extension/e2e.py`
  - `tests/extension/fixtures/data.json`
  - `tests/extension/lib.test.js`
  - `tests/integration/test_backtest_runner.py`
  - `tests/integration/test_report_flow.py`
  - `tests/review_builders.py`
  - `tests/unit/decision/test_records.py`
  - `tests/unit/forecast/test_compare.py`
  - `tests/unit/forecast/test_ns_backtest.py`
  - `tests/unit/forecast/test_ns_compare.py`
  - `tests/unit/forecast/test_split.py`
  - `tests/unit/report/test_extension_data.py`
  - `tests/unit/report/test_html.py`

## 8. 舊名稱說明

- 規則：該行含「舊名」或「formerly」
- 理由：README、憲章、套件說明中說明舊名稱（016 FR-005）
- 檔案：
  - `.specify/memory/constitution.md`
  - `README.md`
  - `src/sweetspot/__init__.py`

## 9. 前身專案

- 規則：大小寫相同的 `SteamSage`、後面不是 `2`，而且該行含「前身」「舊專案」「legacy」之一，或後面接一或兩個 `\`／`/` 再接英文字母（路徑的一段）
- 理由：前身專案 SteamSage 的名稱與它的快取路徑，不是本專案的識別碼；正規表示式的跳脫 `SteamSage\.` 不算路徑
- 檔案：
  - `.specify/memory/constitution.md`
  - `README.md`
  - `src/sweetspot/commands.py`
  - `src/sweetspot/config.py`
  - `src/sweetspot/pipeline/legacy_import.py`
  - `src/sweetspot/sources/legacy_cache.py`
  - `tests/unit/test_legacy_import.py`

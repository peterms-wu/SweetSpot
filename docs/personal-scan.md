# 個人資訊掃描的例外清單

> 這份檔案由 `uv run python scripts/scan_personal.py --write` 產生，不要手改（feature 014，[contracts/scan-personal.md](../specs/014-publish-github/contracts/scan-personal.md)）。

公開的檔案不能有任何人的 SteamID、本機資料夾、使用者資料夾、私人信箱、對話連結或私鑰；帳號名只能出現在授權的著作權行。這些只有下列地方允許；其他地方一出現，`tests/unit/test_scan_personal.py` 就會失敗。`HANDOFF.md` 不公開，不掃描。

需要金鑰、本機資料庫或網路的檢查（金鑰的值、本人的 SteamID、願望清單的加入日期、NSFW 遊戲）只在發佈時執行，不在這份清單裡；它們沒有例外。

每一處依下列規則由上而下歸類，取第一條符合的。各類的出現次數每次執行掃描時當場計算，不寫在這裡。

## 1. 虛構的 SteamID

- 適用：steamid
- 規則：數值不大於帳號 0 的 SteamID64（`76561197960265728`）
- 理由：帳號 0 與更小的值 Steam 不會分給任何人；測試與文件用它當例子（014 research R8）
- 檔案：
  - `docs/personal-scan.md`
  - `scripts/scan_personal.py`
  - `specs/014-publish-github/contracts/scan-personal.md`
  - `specs/014-publish-github/plan.md`
  - `specs/014-publish-github/redact_tool.py`
  - `specs/014-publish-github/research.md`
  - `specs/014-publish-github/tasks.md`
  - `tests/config_builders.py`
  - `tests/fixtures/community/profile_friendsonly.xml`
  - `tests/fixtures/community/profile_private.xml`
  - `tests/fixtures/community/profile_public.xml`
  - `tests/unit/test_config.py`
  - `tests/unit/test_record_fixtures.py`
  - `tests/unit/test_scan_personal.py`
  - `tests/unit/test_setup.py`

## 2. 規則說明

- 適用：path、userdir、email、session
- 規則：路徑是掃描本身、它的測試（`tests/unit/test_scan_personal.py`）、它的契約、`docs/personal-scan.md`，或 `specs/014-publish-github/inventory/` 底下的檔案
- 理由：規則與樣本本身必須寫出這些形狀；SteamID 不在此列，樣本一律在執行時組出
- 檔案：
  - `docs/personal-scan.md`
  - `scripts/scan_personal.py`
  - `specs/014-publish-github/contracts/scan-personal.md`
  - `tests/unit/test_scan_personal.py`

## 3. 系統路徑

- 適用：path
- 規則：任何磁碟的 `X:\Windows`、`X:\Program Files`（路徑在空白處截斷，所以比對的是 `X:\Program`）、`X:\ProgramData` 底下，或磁碟根目錄本身（含 `\\` 跳脫寫法），而且不在本機的專案上層資料夾或使用者資料夾
- 理由：每台 Windows 都有的位置（例如排程用的 `conhost.exe`），不透露任何人的資訊
- 檔案：
  - `.specify/scripts/powershell/common.ps1`
  - `specs/014-publish-github/audit-2026-10-22.md`
  - `specs/014-publish-github/tasks.md`
  - `specs/015-choose-edition-on-steam/prototype/p1_native.py`
  - `src/sweetspot/schedule.py`
  - `tests/integration/test_host_security.py`
  - `tests/integration/test_migrate.py`

## 4. 測試用的虛構路徑

- 適用：path
- 規則：路徑在 `tests/` 下，而且不在本機的專案上層資料夾或使用者資料夾
- 理由：測試需要 Windows 路徑的形狀；真實的資料夾（本機專案的上層、使用者資料夾）仍然不允許
- 檔案：
  - `tests/contract/test_extension_contract.py`
  - `tests/extension/e2e.py`
  - `tests/extension/fixtures/data.json`
  - `tests/extension/lib.test.js`
  - `tests/integration/test_migrate.py`
  - `tests/unit/host/test_install.py`
  - `tests/unit/host/test_protocol.py`
  - `tests/unit/report/test_extension_data.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_scan_names.py`

## 5. 公開的地址

- 適用：email
- 規則：`git@github.com`（ssh remote 的寫法）、`…@users.noreply.github.com`、`noreply@anthropic.com`、`example.com／org／net`
- 理由：不是任何人的私人信箱
- 檔案：
  - `specs/014-publish-github/contracts/publish.md`
  - `specs/014-publish-github/research.md`
  - `tests/integration/test_publish.py`
  - `tests/unit/test_backup_db.py`

## 6. 授權的著作權人

- 適用：account
- 規則：路徑是 `LICENSE`，而且該行以 `Copyright` 開頭
- 理由：MIT 授權必須寫出著作權人；使用者 2026-10-18 選定用 GitHub 帳號名（014 FR-015）
- 檔案：
  - `LICENSE`

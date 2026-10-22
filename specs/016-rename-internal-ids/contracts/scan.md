# Contract: 舊名稱掃描與例外清單（016）

## 1. 指令

```text
uv run python scripts/scan_names.py [--write]
```

- 讀 `git ls-files` 列出的每個檔案（以 UTF-8 解碼；解不開的視為二進位檔，略過並計數），逐行找 `steamsage`（不分大小寫）。
- 每一處依下面的規則表，**由上而下取第一條符合的**，歸到一個類別；都不符合就是「未允許」。
- 有「未允許」：每處印一行 `<檔案>:<行號>: <該行內容>`，最後印出總數，結束代碼 1。
- 沒有：印出每個類別的出現次數與檔案數（當場計算），以及略過的二進位檔數，結束代碼 0。
- `--write`：重新產生 `docs/legacy-names.md`（§3）。

## 2. 規則表

| 順序 | 類別 | 規則 | 理由 |
|---|---|---|---|
| 1 | 歷史文件 | 路徑在 `specs/` 下 | 過去 feature 的 spec、plan、原型腳本是當時的紀錄，不改寫（spec Assumptions） |
| 2 | 交接紀錄 | 路徑是 `HANDOFF.md` | 歷史段落保留當時的名稱；操作步驟由 016 手動改成新名稱（FR-005），014 不公開這份檔案 |
| 3 | 只附加的比較紀錄 | 路徑是 `docs/model/comparisons.md` | 「只附加、不修改」（003 FR-030）；舊紀錄中的指令是當時的實際指令 |
| 4 | 掃描本身 | 路徑是 `scripts/scan_names.py`、`docs/legacy-names.md`、`tests/unit/test_scan_names.py` | 規則與樣本本身必須寫出舊名稱 |
| 5 | 搬家與舊名稱保護 | 路徑是 `src/sweetspot/legacy.py`、`src/sweetspot/migrate.py`，或 `tests/` 下檔名含 `migrate` 或 `legacy_names` 的檔案 | 要認得舊檔名才能搬家與拒絕 |
| 6 | 忽略舊名稱的檔案 | 路徑是 `.gitignore` | 舊名稱的設定檔與資料庫在搬家前後都不能被誤加進版控 |
| 7 | 資料識別碼 | 該處符合 contracts/names.md §2 三條規則之一 | 寫在已保存的紀錄裡，或決定回測資料集（FR-006） |
| 8 | 舊名稱說明 | 該行含「舊名」或「formerly」 | README、憲章、套件說明中說明舊名稱（FR-005） |
| 9 | 前身專案 | 該處是大小寫完全相同的 `SteamSage`，後面不是 `2`；而且該行含「前身」「舊專案」「legacy」（不分大小寫）之一，或 `SteamSage` 後面緊接一或兩個 `\`／`/` 再接英文字母（路徑的一段，例如 `SteamSage\\state`） | 前身專案 SteamSage 的名稱與它的快取路徑，不是本專案的識別碼。正規表示式的跳脫 `SteamSage\.`（`\` 後面是 `.`）不算路徑：016 T002 試跑時發現 `tests/extension/static.test.js` 的 `/sendNativeMessage\(SteamSage\.HOST_NAME…/` 被誤判為前身專案，2026-10-15 收緊這條規則 |

**一處**：類別 7 與 9 以該處的比對結果判斷，其餘以檔案或整行判斷。同一行有兩處時，各自歸類，有一處未允許就算未允許。

**例**：
- `globalThis.SteamSage`、`uv run steamsage update`、`data/steamsage.db` 出現在 README 的操作步驟中 → 未允許。
- `〈前身專案資料夾〉\state\cache` → 前身專案。
- `/sendNativeMessage\(SteamSage\.HOST_NAME, request,/`（測試中的正規表示式）→ 未允許。
- `steamsage.decision/2` → 資料識別碼。

## 3. `docs/legacy-names.md`

由 `--write` 產生，不手改。內容：

1. 開頭固定說明三件事：
   - 這份檔案由掃描產生；
   - 舊名稱 `steamsage`、`SteamSage2` 是什麼；
   - 保留的資料識別碼為什麼不改（contracts/names.md §2）。
2. 每個類別一節：規則、理由，以及有命中的檔案清單（依路徑排序）。整個路徑都是例外的類別（1、2、3）只寫規則，不逐檔列出。不寫次數，次數由執行掃描時印出。

測試確認：
- 這份檔案和重新產生的內容逐字相同；
- 規則表的每一條在檔案中都有對應的一節。

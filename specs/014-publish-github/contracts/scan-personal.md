# Contract: 個人資訊掃描（014 FR-005、FR-008b、FR-016b）

```
uv run python scripts/scan_personal.py                # 離線類別：列出不允許的命中（結束代碼 1）或每類的數量（0）
uv run python scripts/scan_personal.py --write        # 同上，並由掃描重新產生 docs/personal-scan.md
uv run python scripts/scan_personal.py --publish DIR  # 發佈用：對 DIR 的檔案跑離線＋發佈時的類別（需要網路）
```

架構照 016 的 `scripts/scan_names.py`：規則表，第一條符合的規則決定類別；沒有規則允許的命中就是違規。`tests/unit/test_scan_personal.py` 在 repo 上跑離線類別（結果必須是 0 個不允許），並對每條規則各放一個該中、一個不該中的樣本。

## 1. 掃描範圍

- 預設：`git ls-files` 的文字檔扣掉排除清單（`HANDOFF.md`）；二進位檔（圖示等）只檢查私鑰標頭。
- `--publish DIR`：DIR 這個 git repo 的 clone 會有的檔案：`git ls-files --cached --others --exclude-standard`（已 stage 或還沒 stage、但不被 `.gitignore` 排除的），不含 `.git/`；排除清單不適用，`HANDOFF.md` 萬一出現在 DIR 也照掃。
  - （2026-10-22，014 T055）原本是「DIR 裡的全部檔案」：發佈的測試步驟 `uv sync` 會在公開資料夾留下 `.venv/`，它的 `pyvenv.cfg` 有本機路徑，所以第二次發佈起一定不通過。被忽略的檔案不會進公開 commit，不用掃。

## 2. 類別與規則

### 離線類別（自動測試）

| 類別（輸出的代號） | 找什麼 | 允許的情況（規則） |
|---|---|---|
| SteamID（`steamid`） | `7656119` 開頭的 17 位數字 | 虛構值：不大於帳號 0（`76561197960265728`）的值 |
| 本機路徑（`path`） | Windows 絕對路徑（`X:\…`、`X:/…`，含 `\\` 跳脫；在空白處截斷） | 系統路徑：任何磁碟的 `X:\Windows`、`X:\Program…`（`Program Files` 截斷後的樣子）、`X:\ProgramData` 底下，或磁碟根目錄本身；`tests/` 底下的任何路徑。兩者都要不在本機的專案上層資料夾或使用者資料夾。代稱（`〈…〉`）不是路徑 |
| 使用者資料夾（`userdir`） | `\Users\<名稱>`、`/Users/<名稱>` | 無 |
| email（`email`） | `名稱@網域.頂級網域` | `git@github.com`（ssh remote 形式）；`@users.noreply.github.com`；`noreply@anthropic.com`；`example.com`／`example.org`／`example.net` |
| 對話連結（`session`） | `claude.ai/code/session_…`、`claude.ai/chat/…` | 無 |
| 私鑰（`private_key`） | `-----BEGIN … PRIVATE KEY-----`；`.pem`、`.key` 檔名 | 無 |
| 帳號名（`account`） | repo 本身 github.com 的 git remote 的擁有者名稱（只讀 git 設定，不需要網路或使用者資料；沒有這種 remote 時這一類略過） | `LICENSE` 的著作權行 |

掃描腳本自己（`scripts/scan_personal.py`）、它的測試（`tests/unit/test_scan_personal.py`）、本契約、`docs/personal-scan.md`、`specs/014-publish-github/inventory/` 底下的檔案裡的規則樣本與正規表示式，列為例外類別「規則說明」（照 016 `scan_names.py` 的做法；SteamID 不適用，樣本在執行時組出）。

> 2026-10-22 稽核補記（014 T061）：上面的表改成程式實際的規則。以前寫的是：SteamID 只允許帳號 0 本身；`tests/` 的虛構路徑是一份清單；系統路徑只列 C 槽，沒有 `ProgramData` 與磁碟根目錄；email 沒有 `example.net`；
> 使用者資料夾另外找 `%USERPROFILE%` 展開後的值（程式只用它判斷「不在使用者資料夾」，搜尋靠 `\Users\`）；規則說明沒有測試檔與 `docs/personal-scan.md`。
> 「不在本機的專案上層資料夾或使用者資料夾」這個排除條款以前沒有測試，現在有了。另外，含空白的真實路徑（例如 `X:\Program Files\<名稱>`）在空白處就被截斷，排除條款看不到後半段；這種位置的專案資料夾掃描判斷不了。

### 發佈時的類別（`--publish`，不進自動測試：需要真實金鑰、網路或使用者本機的設定檔與資料庫）

| 類別（輸出的代號） | 找什麼 | 允許 |
|---|---|---|
| 金鑰（`key`） | `ITAD_API_KEY`、`STEAM_WEB_API_KEY` 的值（從環境與 HKCU 讀） | 無；只報檔案與行號，命中內容印 `***` |
| 本人的 SteamID（`own_steamid`） | 使用者 `sweetspot.toml` 的 SteamID（另一層保險；離線類別本來就會抓到） | 無 |
| 願望清單的加入日期（`wishlist_date`） | 本機資料庫裡使用者願望清單的 `date_added`：10 位數的 Unix 時間，以及資料庫裡的 ISO 字串（前 19 個字）。和別的數字撞到的機會極小 | 無 |
| NSFW 遊戲（`nsfw`） | 公開檔案裡出現的 app id（JSON 鍵、商店網址、`app_id=` 等）與本機資料庫商品名稱對照出的 app id；以 `IStoreBrowseService/GetItems` 查內容描述，編號 3 或 4。名稱只用不會是一般用字的：全是 ASCII 的名稱至少 8 個字元且前後不接英數字；含任何非 ASCII 字元（中日韓文字、é、™ 等）的至少 3 個字，不檢查前後（2026-10-18 用真實資料庫試跑，「Mirror」「Put in」這種名稱撞到一般英文）。命中內容印 `app <id>`，不印名稱。GetItems 沒有回傳的 app（例如台灣區不販售）當作沒有內容描述 | 無 |

願望清單的**排序**（`priority`）是 1、2、3 這種小整數，到處都會出現，掃描判斷不了；它只在錄製時改寫（FR-008a、`record_fixtures.py`）。2026-10-18 實作時發現，原本寫的「`priority`＋app id 成對出現」改成只查日期（014 T017）。

> 2026-10-22 稽核補記：ISO 字串、「任何非 ASCII 字元」（比「中日韓文字」寬，比對較嚴的一側）、命中內容的寫法、GetItems 沒回傳的 app 怎麼算，以前都沒寫。
> 其中「任何非 ASCII 字元」與 GetItems 沒回傳的 app，使用者 2026-10-22 同意維持程式現在的做法。
> 公開的檔案本來就不放願望清單的遊戲名稱，所以台灣區查不到的 app 放行不影響這一層。

## 3. 輸出

- 不允許的命中：`<檔案>:<行號>: <代號>: <命中內容>`（代號見 §2 的表；金鑰的命中內容是 `***`），最後一行「不允許的個人資訊：N 處」。
- 通過時的摘要：離線掃描印每條規則允許的處數與檔案數，再印總處數、掃描的檔案數與其中的二進位檔數；`--publish` 印「發佈檢查：N 個檔案，不允許 0」。
- `docs/personal-scan.md`：每條規則的適用類別、規則、理由與檔案清單（由 `--write` 產生，不手寫；照 016 `docs/legacy-names.md`）。出現次數每次執行時當場計算，不寫進檔案。
- （2026-10-22 稽核補記：以前寫的「每類的命中數與允許數」與「允許的命中數」不是程式的輸出，改成上面實際的格式。）

## 4. 結束代碼

0：沒有不允許的命中；1：有；2：`--publish` 不能判定（DIR 不是 git repo、讀不到本機的值，或線上查詢失敗；發佈步驟視同不通過）。

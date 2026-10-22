# Contract: 新增與改變的指令（014）

既有指令的行為以 001 起的各 feature 契約為準；這裡只列 014 的新增與改變。所有輸出、日誌不含 API 金鑰（FR-019）。

## 1. `sweetspot setup`

互動設定願望清單，建立 `sweetspot.toml`。

```
uv run sweetspot setup [--config 路徑] [--change]
```

1. 設定檔已存在 → 印出目前的網址，說明「已經設定過；要換清單請加 --change」，結束代碼 0，不改檔案。`--change`：照下面 4–6 詢問與檢查，只改寫設定檔裡 `[wishlist] url` 那一行，其餘內容與註解不動。
2. 不能互動（標準輸入不是終端機，或 `SWEETSPOT_BACKGROUND=1`）→ 說明「請在視窗中執行 sweetspot setup」，結束代碼 5。
3. 檢查 `ITAD_API_KEY`：沒有 → 說明申請網址、設成使用者層級環境變數的方法、「設定後關掉視窗重開」，結束代碼 5，不建立檔案（FR-014）。
4. 詢問網址（可重試；直接按 Enter 或輸入空白 → 結束代碼 5，不建立檔案）。接受：
   - `https://store.steampowered.com/wishlist/profiles/<17 位數字>/`
   - `https://store.steampowered.com/wishlist/id/<名稱>/`
   - `https://steamcommunity.com/profiles/<17 位數字>`、`https://steamcommunity.com/id/<名稱>`（結尾斜線可有可無）
5. 自訂網址 → 查個人檔案 XML 換成數字形式；印出「已記成這個帳號：<個人檔案名稱>（<數字>）」。
6. 讀願望清單（research R3 的四種結果）；格式錯、找不到帳號、不公開 → 說明後重新詢問；0 款且個人檔案公開 → 問「要用這份空的清單嗎？(y/N)」。
7. 寫入設定檔（數字形式網址），印出下一步（執行更新、註冊排程）。結束代碼 0。
8. （2026-10-22，014 T050）建立或改寫了設定檔時（第 7 步、`--change`、以及第 2 節由其他指令先進入的設定），在當天的 `data/logs/sweetspot-YYYYMMDD.log`
   寫一行「`setup 結束：代碼 0，N 秒；…`」（N 含等候輸入的時間；摘要是 `settings=created` 或 `settings=changed`，不含網址）。沒有建立檔案的結束（代碼 5、已經設定過）不寫，維持「什麼都不建立」。
> 2026-10-22 稽核補記（程式從 2026-10-18 起就是這樣，以前沒寫）：
> - 第 1 步的實際文字是「已經設定過：<網址>」與「要換願望清單請執行：uv run sweetspot setup --change」；第 2 步是「請在視窗中執行 sweetspot setup（雙擊「更新資料.cmd」也會詢問）；什麼都沒建立。」
> - `--change` 也照第 2、3 步檢查（不能互動 → 5；沒有 `ITAD_API_KEY` → 5）：換清單之後的更新一樣需要金鑰。
> - 第 4 步的四種形式結尾斜線都可有可無，也接受後面接 `?…`、`#…`（例如從瀏覽器複製的 `?l=tchinese`）。
> - 第 5 步的「已記成這個帳號」在第 6 步讀到願望清單之後才印；清單不公開時只看到隱私說明。
> - 第 5、6 步連不上 Steam（個人檔案或願望清單的來源錯誤，不是「找不到」或「不公開」）→ 「暫時連不上 Steam／暫時讀不到願望清單（原因），請稍後再試；什麼都沒建立。」，結束代碼 1。
9. （2026-10-22，014 T060）第 4–6 步之間按 Ctrl+C（在詢問時，或查詢 Steam 時）→ 「已取消；什麼都沒建立。」，結束代碼 5，不建立檔案；以前會印 traceback。
   （2026-10-22，014 T066）`--change` 的「只改寫 `[wishlist] url` 那一行」：那一行可以是任何單行的 TOML 寫法（單引號或雙引號、`=` 兩邊有沒有空白、行尾有註解，註解保留），只在 `[wishlist]` 這一段裡找；
   這一段沒有 url 就加在段首，沒有這一段就加在檔尾。改完讀回確認；檔案本身不是有效的 TOML 時不改，說明要手動改成的網址，結束代碼 1。以前只認 `url = "…"`，其他寫法會印 traceback；
   `[wishlist]` 沒有 url 時，還會改到後面別段的 url 那一行。
   第 4 步的 `<17 位數字>` 指 SteamID64（`7656119` 開頭）：其他 17 位數字算格式不對，列出接受的形式後重新詢問（以前會說成「自訂名稱只能有…」）。

## 2. 沒有設定檔時的其他指令

- `migrate`、`setup`、`--help`、`--version` 不受影響。
- 其他指令：可以互動 → 先進入 `setup` 的流程，成功後繼續原本的指令；不能互動 → 在 stderr 印出「還沒設定願望清單：請先在視窗中執行 uv run sweetspot setup（或雙擊「更新資料.cmd」）」，結束代碼 5。
  （2026-10-22 稽核補記：括號那一段程式從 2026-10-18 起就有。）
  - Python 端不建立設定檔、資料庫、`data/` 或當天的 `sweetspot-*.log`；
  - 背景執行時，這段說明由 `背景更新.cmd` 寫進 `data\logs\background-update.log`（資料夾由 .cmd 自己建立），spec US1 情境 4 的「日誌寫明原因」指的是這個檔。
- 016 的舊名稱保護（結束代碼 4）先於這一條判斷。

## 3. `sweetspot schedule`

```
uv run sweetspot schedule install   [--name 名稱] [--replace] [--dry-run]
uv run sweetspot schedule uninstall [--name 名稱]
uv run sweetspot schedule status    [--name 名稱]
```

| 情況 | install | uninstall | status |
|---|---|---|---|
| 沒有同名工作 | 建立（data-model「排程工作」），0 | 「沒有這個工作」，0 | 「沒有註冊」，0 |
| 同名、指向這個資料夾 | 「已註冊」，不改，0；`--replace` 重建，0 | 移除，0 | 列出觸發時間、上次執行時間與結果，0 |
| 同名、指向別的資料夾 | 說明指向哪裡，**拒絕**，1；`--replace` 取代，0 | 拒絕，1（不移除別的資料夾的工作） | 列出並說明指向別的資料夾，0 |
| PowerShell 失敗 | 說明原因與手動步驟，1 | 說明原因，1 | 說明原因，1 |

- `--dry-run` 只印出會建立的設定，不呼叫寫入。
- 2026-10-22 稽核補記（PowerShell 失敗那一列改成程式實際的行為；使用者 2026-10-22 同意改 contract，不改程式）：
  - 查詢工作失敗（三個動作都是）→ 「讀不到排程工作「<名稱>」：<原因>」，1。
  - `install` 註冊失敗 → 原因，加上在工作排程器手動建立的步驟，1。手動步驟只在這裡給：移除與查看在工作排程器裡本來就能直接做。
  - `uninstall` 移除失敗 → 「移除「<名稱>」失敗：<原因>」，1。
  - `status` 查到工作、但讀不到執行紀錄 → 照常列出工作，再加一行「讀不到執行紀錄：<原因>」，0。
  - `status` 沒有上次執行時間（空的）時，不論結果碼都寫「上次：還沒執行過」。
- （2026-10-22，014 T056）`--dry-run`、`--replace` 只用於 `install`：`uninstall`、`status` 收到時說明並以 1 結束，不查詢、不改任何東西。
  （parser 讓三個動作都接受這兩個旗標，以前 `uninstall --dry-run` 會真的移除工作。）
- （2026-10-22，014 T056）`status` 的觸發時間取自工作本身的觸發條件（`StartBoundary` 的時:分），不是 install 寫入的 02:30；使用者在工作排程器改過時間也照實顯示。
- （2026-10-22，014 T051）`status` 的上次結果：工作排程器回報 267011（`SCHED_S_TASK_HAS_NOT_RUN`）時寫「上次：還沒執行過」，不印它附帶的 1999-11-30 日期；
  267009（`SCHED_S_TASK_RUNNING`）寫「執行中」；其他值照原樣印出。
- 不需要系統管理員權限（目前使用者的工作）。

## 4. `scripts/backup_db.py` 的改變

> 2026-10-22 稽核補記：基準行為（014 以前的維運修補，從來沒有 contract；名稱是 016 改名後的；照 scripts/backup_db.py 的 docstring 與程式）：
> - 用法：`uv run python scripts/backup_db.py [--dry-run]`。上傳到名為 `private` 的 git remote 指向的 GitHub repo（程式裡不寫 repo 名稱），用 `gh`。
> - zip `sweetspot-db-YYYY-MM-DD.zip` 的內容：`data/sweetspot.db`（以 SQLite backup API 從唯讀連線複製，別的程式開著資料庫時也一致）、`sweetspot.toml`（存在時）、`data/forecasts/` 第一層的所有檔案。
>   報告與回測可以重新產生，不放。路徑固定是〈專案資料夾〉的 `data/`，不看設定檔的 `data_dir`。
> - 每天一個 release，tag 與標題是 `db-YYYY-MM-DD`（本機日期）。同一天的 tag 已存在時用 `--clobber` 換掉附件（「備份已更新：…」），否則建立新 release（「備份已上傳：…」）。
> - 保留規則：`db-YYYY-MM-DD` 形狀的 tag 留最新 14 個，再加上有備份的最近 12 個月各自最早的一個；其餘以 `gh release delete --cleanup-tag` 刪掉（「已刪除舊備份：<tag>」）。不是這個形狀的 tag 一律保留。
> - `--dry-run`：照樣建立 zip（暫存資料夾）並查詢 release 清單，只印「[dry-run] <zip> <MB> MB -> <repo> <tag>」與每個會刪的「[dry-run] would delete <tag>」；不上傳、不刪除、不寫日誌結果行。
> - 結束代碼：0 完成；1 失敗（任何錯誤，stderr 印「備份失敗：<訊息>」，例如 `gh` 失敗、remote 不是 GitHub、資料庫打不開）；
>   4（016 起）只有改名前的資料庫或設定檔，印出搬家提示，不建立 zip、不上傳、不寫日誌。參數錯誤是 argparse 預設的 2（這支不經過 `sweetspot` 的參數解析，014 T069 不適用）。
> - 不是 `--dry-run` 時，結束時在當天日誌 `data/logs/sweetspot-<YYYYMMDD>.log` 留一行「backup 結束：代碼 N，…」，附印出的每一句。
>
> 下面只列 014 改了什麼。

- 找不到名為 `private` 的 git remote → 印出「略過雲端備份：沒有名為 private 的 git remote（只有原作者的環境有私人備份 repo）」，結束代碼 0；日誌結果行附這一句。其餘不變。
  （2026-10-22 稽核補記：引號裡的文字照程式。）

## 5. `更新資料.cmd`、`背景更新.cmd`

> 2026-10-22 稽核補記：`背景更新.cmd` 的基準行為（014 沒有改的部分；排程工作每天 02:30 執行的就是它；從來沒有 contract；照 .cmd 本身）：
> - 在 .cmd 所在的資料夾執行；不開瀏覽器、不暫停。
> - 所有輸出（三個步驟的 stdout 與 stderr）寫到 `data\logs\background-update.log`，**每次覆寫**；詳細的每日日誌照常在 `data\logs\sweetspot-<YYYYMMDD>.log`。
> - 開始寫一行「===== 開始 <日期> <時間> =====」。找不到 `uv` 時再寫一行「找不到 uv，請先安裝：https://docs.astral.sh/uv/」並以 1 結束，沒有結束行。
> - 依序執行 `uv run sweetspot update`、`uv run sweetspot report --update-exit <update 的代碼>`、`uv run python scripts\backup_db.py`；前一步失敗也照樣執行下一步。
> - 結束寫一行「===== 結束 <日期> <時間>：update X，report Y，backup Z，整體 N =====」，並以整體代碼 N 結束。
> - 整體代碼取 update 與 report 中較嚴重的，現在的順序是 1 > 5 > 4 > 3 > 2 > 0（data-model「結束代碼」；不在 0–5 的 update 代碼算 1，見下面的 014 T069）；report 的 3 不算。
>   **backup 的代碼不算進整體**，只寫在結束行。

- `更新資料.cmd`：沒有 `sweetspot.toml` 時先執行 `uv run sweetspot setup`，代碼不是 0 就暫停並結束；其餘不變。
- `背景更新.cmd`：開頭 `set "SWEETSPOT_BACKGROUND=1"`；整體代碼加入 5（data-model「結束代碼」）。
  - （2026-10-22，014 T059）update 回 5（還沒設定）時略過雲端備份，結束行寫「backup 略過（還沒設定）」：沒有資料可以備份，`backup_db.py` 也會留下當天的 `sweetspot-*.log`，違反 §2。
- （2026-10-22，014 T069）update 的結束代碼不是 0–5（例如被中止時的 Windows 狀態碼）時，兩支 .cmd 的整體代碼算 1（以前沒有一行符合，算成 0）；
  `更新資料.cmd` 另外印「資料更新沒有正常結束（代碼 N），報告使用既有資料並已開啟。」。代碼照樣傳給 `report --update-exit`。
- （2026-10-22，014 T059）兩支 .cmd 的 `rem` 只用 ASCII：`chcp 65001` 之後，cmd.exe 有時會從含中文的 `rem` 的下一行中間開始讀，把後半段當成指令執行，哪一行出錯取決於資料夾路徑的長度。
  實測時，`背景更新.cmd` 開頭第三行被當成指令執行（以前每晚都可能發生，剛好無害）；中文 `rem` 之後的 `set "bcode=略過…"` 也會失去值。
  `rem` 改成 ASCII 後，在 120 種路徑長度下都沒有讀錯。echo 與 set 的中文保留。`tests/integration/test_cmd_run.py` 用假的 uv.exe 實際執行兩支 .cmd，`tests/unit/test_cmd_scripts.py` 檢查 `rem` 都是 ASCII。

## 6. 參考資料集提示（FR-014a）

- HTML 報告頁首（在既有的資料時間、更新失敗說明之後）與擴充功能（彈出視窗頂端、遊戲頁面板的說明列）在 `reference_notice` 存在時顯示：
  - `sampling` 不是 `complete`（含沒有這個欄位的舊紀錄）：
    「參考資料集目前 340 款（建議至少 2,000 款），預測的依據還不完整。補完：執行 uv run sweetspot reference（約 2～3 小時，可以中斷，下次接著做），或讓每日更新慢慢累積。」
    時間是 014 T045 從零安裝的實測（約 2 小時 18 分，願望清單 69 款、有 STEAM_WEB_API_KEY）。
  - `sampling` 是 `complete`（2026-10-22，014 T048）：
    「參考資料集已補完：共 1,659 款，少於原作者驗證模型時的 2,000 款（Steam 上符合抽樣條件的遊戲不夠多），預測的依據比較少。」
  - `broad_sample` 為 `disabled` 時加一句「沒有設定 STEAM_WEB_API_KEY，廣泛樣本停用，可能到不了 2,000 款」（這時 `sampling` 一定不是 `complete`）。
- 數字以 `reference_notice` 為準；兩個呈現層的文字相同。

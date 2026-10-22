# Data Model: 公開到 GitHub（014）

本 feature 不改資料庫結構、預測紀錄格式或模型；只動設定檔的預設值、一個選用的輸出欄位，以及發佈用的檔案與紀錄。

## 設定檔 `sweetspot.toml`

| 欄位 | 改變 | 規則 |
|---|---|---|
| `[wishlist] url` | 預設值改成空字串（原本是使用者本人的網址） | 只接受 `https://store.steampowered.com/wishlist/profiles/<17 位數字>/`；由 `sweetspot setup` 寫入（自訂網址在設定時換算成數字形式，FR-002）。空字串 → 「還沒設定」 |
| `[legacy] cache_path` | 預設值改成空字串（原本是〈前身專案資料夾〉） | 空字串 → `import-legacy` 說明用途並以 1 結束，摘要 `{"status": "not_configured"}`（FR-010）；其他指令不受影響 |
| 其餘 | 不變 | 使用者本人的設定檔裡已有的值優先，行為不變（FR-004） |

> 2026-10-22 稽核補記：「空字串 → 還沒設定」指的是 `DEFAULT_TOML` 這個樣板，也就是 `setup` 寫入網址之前的樣子。設定檔**存在**、網址卻是空字串時（例如手改過），
> 設定的驗證把它當成設定錯誤（`wishlist.url` 不能是空的），結束代碼 1，不是 5；`setup` 在這種檔案上說「已經設定過：（空的）」，要用 `--change` 改。使用者 2026-10-22 同意維持這個行為。
> `import-legacy` 的 `not_configured` 以前沒寫。

- 設定檔**不再自動建立**：只有 `sweetspot setup`（或可以互動時由其他指令帶入同一流程）會建立它（FR-001）。
- `setup` 寫出的檔案 = 現在的 `DEFAULT_TOML`（去掉個人值）＋使用者的網址；檔案開頭註明「由 sweetspot setup 建立」與日期。

## 結束代碼

| 代碼 | 意義 | 來源 |
|---|---|---|
| 0、1、2、3 | 不變 | 001 contracts/cli.md |
| 4 | 只有改名前的檔案，要先搬家 | 016 |
| **5** | **還沒設定**：沒有設定檔、而且不能互動（背景執行、標準輸入不是終端機） | 014 FR-001 |

`更新資料.cmd`、`背景更新.cmd` 的整體代碼嚴重度順序加入 5：1 > 5 > 4 > 3 > 2 > 0（「還沒設定」比「要先搬家」更早一步）。

## 決策紀錄的選用欄位 `reference_notice`（FR-014a）

- 位置：正式紀錄（`steamsage.decision/2`）與擴充功能資料檔（`steamsage.extension/1`）各多一個選用欄位；依 011 契約「新增選用欄位不升版」。
- 值：參考資料集達到門檻時省略（或 `null`）；未達時
  ```json
  {"dataset_size": 340, "threshold": 2000, "broad_sample": "disabled"}
  ```
  `broad_sample` 是 `ok` 或 `disabled`（沒有 `STEAM_WEB_API_KEY`）。文字由呈現層依這些值組成，兩個呈現層數字相同（憲章 VII）。
  - 2026-10-22 稽核補記：上面的物件在正式紀錄裡。擴充功能資料檔的 `reference_notice` 是 `report/html.py` 依這個物件組好的**文字**
    （011 contracts/extension-data.md 寫的就是字串；HTML 報告與擴充功能因此顯示同一段文字）。
- （2026-10-22，014 T048）多一個值 `sampling`：`complete` 或 `incomplete`，例如 `{"dataset_size": 1659, "threshold": 2000, "broad_sample": "ok", "sampling": "complete"}`。
  `complete` = 有 `STEAM_WEB_API_KEY`，現在願望清單上每家發行商與開發商的商店目錄都翻完（`catalog_progress.complete`）且該公司的候選沒有 `pending`／`accepted`，
  而且廣泛樣本各分層都滿、或 Steam 遊戲清單（`steam_app_list`，扣掉願望清單）每一款都有目前抽樣版本的廣泛樣本判定（不是 `accepted`）。
  報告產生時從資料庫唯讀算出；沒有這個值的舊紀錄當作 `incomplete`。達到門檻時整個欄位照舊省略，紀錄逐位元組不變。
  - 2026-10-22 稽核補記（判斷的細節，已記在 tasks.md 014 T048）：「該公司的候選沒有 `pending`／`accepted`」不算願望清單上的遊戲（含移除後追蹤中的）：
    每家公司的目錄都會列出願望清單上的那款，樣本從不收它，所以它永遠是 `pending`。`steam_app_list` 是空的（還沒抓過清單）時一律算 `incomplete`，即使各分層都滿。
- `dataset_size` 與 `update` 摘要的同名欄位同一個定義（願望清單以外、有台灣區價格歷史的參考遊戲數）。門檻 2,000 來自 001 SC-006（research R6）。

## 排程工作（FR-012、FR-012a）

由 `sweetspot schedule install` 產生的工作：

| 項目 | 值 |
|---|---|
| 名稱 | 預設「SweetSpot 每日背景更新」；`--name` 可改 |
| 觸發 | 每天 02:30（本機時間） |
| 動作 | `conhost.exe --headless cmd.exe /d /c "<資料夾>\背景更新.cmd"`，工作目錄 = 資料夾 |
| 執行身分 | 目前的使用者、只在登入時執行（LogonType `Interactive`）、最低權限（RunLevel `Limited`）；2026-10-18 核對使用者現在的工作也是這樣。不需要密碼、不需要系統管理員 |
| 設定 | 錯過時補跑、執行上限 1 小時、已在執行時不再啟動、電池時也執行 |
| 說明 | 「每天 02:30 在背景執行 SweetSpot 的 update、report 與雲端備份；錯過時在電腦可用時補跑。輸出：data\logs\background-update.log」 |

「同一個工作」的判斷：名稱相同，且工作目錄是這個資料夾，**或**動作的引數裡有這個資料夾的 `背景更新.cmd` 路徑（沿用 016 `migrate.py` 的 `_runs_here`）。
「這個資料夾」是設定檔（`--config`，預設 `sweetspot.toml`）所在的資料夾；不檢查那裡有沒有 `背景更新.cmd`。

> 2026-10-22 稽核補記：說明文字照程式（`schedule.DESCRIPTION`）；「同一個工作」以前只寫了引數那一半；「這個資料夾」的定義以前沒寫。

## 掃描規則（FR-005、FR-016b）

詳見 [contracts/scan-personal.md](contracts/scan-personal.md)。實體：

- **命中**：檔案、行號、類別、規則（或「不允許」）。金鑰類別只記位置。
- **規則**：類別、說明、該中的樣本、不該中的樣本；第一條符合的規則決定類別。
- **例外清單**：由掃描產生的 `docs/personal-scan.md`（每條規則的適用類別、規則、理由與檔案；處數每次當場算，不寫進檔案。2026-10-22 稽核補記）。

## 發佈（FR-016、FR-016a）

| 實體 | 欄位 | 說明 |
|---|---|---|
| 排除清單 | 路徑樣式 | 目前只有 `HANDOFF.md`；寫在 `scripts/publish.py` 的常數，契約列出 |
| 公開資料夾 | 路徑 | 預設〈專案資料夾〉旁的 `SweetSpot-public`；它自己的 git repo，本機設定寫入 noreply 作者 |
| 發佈紀錄 | master 上的 annotated tag `publish/NNN` | 訊息三行：`public <公開 commit 的 40 位雜湊>`、發佈時間（ISO 8601，含時區）、`範圍：<上一個 tag>..<master 短雜湊>`（第一次是 `範圍：初次公開`）。第一行會被下一次發佈讀回，用來確認公開資料夾沒有被手動改過。隨 `git push private --tags` 進私人 repo；不進公開版 |
| 公開 commit | 作者、提交者、訊息 | noreply 地址；第一次「SweetSpot 初次公開（YYYY-MM-DD）」，之後「SweetSpot 發佈 YYYY-MM-DD」＋範圍內的 commit 標題；不含對話連結（014 T058 起由程式檢查） |

> 2026-10-22 稽核補記：tag 訊息的格式、初次公開的日期以前沒寫。

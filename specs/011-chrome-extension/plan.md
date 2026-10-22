# Implementation Plan: Chrome 擴充功能

**Branch**: `011-chrome-extension` | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-chrome-extension/spec.md`

## Summary

1. **資料檔**（research R1、R2）：新模組 `report/extension.py` 從報告用的同一個決策字典產生 `steamsage.extension/1`（約 134 KB）。
   正式 `report` 寫到 `extension/data/steamsage-extension.json`，先寫暫存檔再改名。報告中的句子由 `report/html.py` 拆出的純文字函式產生，
   HTML 和擴充功能共用，所以兩邊的文字相同；HTML 報告逐位元組不變。
2. **擴充功能**（R3、R4）：`extension/`，MV3，不用框架、不需要建置、權限只有 `alarms`。Service Worker 每次都重新讀自己的資料檔，
   並在 Chrome 啟動、打開彈出視窗、載入 Steam 頁面時，以及每 30 分鐘更新圖示。三個位置：彈出視窗、遊戲頁面板（`#game_area_purchase` 正前方）、
   願望清單每列的一行（該列 grid 的 `mid` 區，就在名稱正下方）。
3. **不連外**（R0.4）：CSP `connect-src 'self'`、內容腳本不含網路 API（靜態測試）、端對端記錄擴充功能發出的請求 = 0。
4. **排程**（R6）：10/1 把每日背景更新改到 02:30。
5. **不變**：模型、規則、決策契約、正式紀錄、HTML 報告、資料庫。

**plan 階段的原型**（research R0，真實資料、Steam 未登入、唯讀）：

| 項目 | 結果 |
|---|---|
| 改寫資料檔後不重新載入（P1） | **13/13**：暫存檔再改名、直接覆寫、Service Worker 被停止後、寫到一半、檔案不存在都正確；彈出視窗 49–60 ms |
| 遊戲頁（P2、P3，16 款） | 追蹤的購買選項 **15/15** 在頁面上找得到；頁面現價＝紀錄現價 **14/14**；面板在 DOMContentLoaded 後 200–246 ms 出現；不在資料中的遊戲頁不變 |
| 願望清單（P4） | 產生的 **59/59** 列恰好一行，0 重複，0 列超過 1 秒；列高不變（174 px，1280／700 px）；改版的測試頁 0 行。未登入時 Steam 不列出 9 款（裝不裝都一樣），要在使用者的 Chrome 上確認 |
| 第一版插入點的錯誤 | 插在名稱後面會擠壓或遮住名稱（截圖才發現），改用 grid 的 `mid` 區 |
| 對外請求（P1、P3） | 擴充功能發出的請求 **0**；Service Worker 連外被 CSP 擋下 |
| 資料檔（P0） | 134 KB、產生並寫檔 9 ms |
| 替代做法 | **不需要**：原本的做法（擴充功能讀自己資料夾的檔案）可行 |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv；擴充功能用原生 JavaScript（ES2022）、HTML、CSS，Chrome MV3。

**Primary Dependencies**：不新增 Python 套件；擴充功能不用任何 npm 套件。測試工具：`node --test`（Node 24，內建）、
Playwright（`uv run --with playwright`，只用於端對端，不加進專案相依）。

**Storage**：新增 `extension/data/steamsage-extension.json`（不進版控）。資料庫與正式紀錄不變。

**Testing**：pytest（測試先行）；`node --test "tests/extension/*.test.js"`；端對端 `tests/extension/e2e.py`（測試頁；`--live` 連真實 Steam）。

**Target Platform**：Windows 11 本機；Chrome 154（開發人員模式載入未封裝項目）。

**Project Type**：單一 Python CLI 專案＋一個本機 Chrome 擴充功能資料夾（第二個呈現層）。

**Performance Goals**（R0.3、R0.2）：`report` 增加 ≤ 0.1 秒（實測 9 ms；spec 上限 0.5 秒）；資料檔 ≤ 200 KB（spec 上限 500 KB）；
彈出視窗 < 0.2 秒；面板與行在頁面內容出現後 < 0.5 秒（spec 上限 1 秒）。

**Constraints**：

- 擴充功能不連外、不讀 Cookie、不重算、不判斷「已到價」（spec FR-004、FR-005）。
- 非正式執行不寫資料檔；寫檔失敗不影響報告（FR-002、憲章 III）。
- HTML 報告逐位元組不變（SC-009）。
- 找不到頁面結構時不顯示，不猜位置（FR-016）。

**Scale/Scope**：68 款、6 個組合包；願望清單一次畫約 9–16 列。

## Constitution Check

依憲章 **1.2.0**。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 未知的現價、機率、時間在資料檔中為 `null`，顯示「未知」或「—」；資料時間全部未知時視為過舊；讀不到資料檔時不顯示任何遊戲 | ✅ |
| II 證據可追溯 | 資料檔帶正式紀錄檔名、模型與規則版本、分析時間、資料時間；三個位置都顯示資料時間 | ✅ |
| III 逐項隔離失敗 | 資料檔寫入失敗不影響 HTML 報告與正式紀錄（結束代碼為部分成功）；擴充功能每列、每頁各自 `try/catch`，錯誤只影響自己的節點 | ✅ |
| IV 預測必須可驗證 | 不改模型與規則；不引用新的準確率；正式紀錄照常保存 | ✅（不適用） |
| V 規則單一正本 | 擴充功能不含任何規則；句子由報告的同一段函式產生 | ✅ |
| VI 簡單優先 | 沒有框架、沒有建置、沒有新的 Python 套件；唯一的新常數「26 小時」是 spec 確認的呈現用預設值（和核心的 24 小時現價過舊不同用途） | ✅ |
| VII 核心與呈現分離 | 擴充功能只讀核心結果；格式化限於千分位、百分比、台北時間；「已到價」不判斷；文字與 HTML 報告相同（測試比對） | ✅ |
| VIII 遵守資料來源條款 | 擴充功能不抓任何資料；只讀使用者自己正在看的 Steam 頁面上已經顯示的內容，不發請求 | ✅ |
| IX 本機與安全 | 資料檔在本機、不含金鑰；不讀 Cookie 或登入資料；頁面價格只在顯示新台幣時並列；外部字串一律跳脫或用 `textContent` | ✅ |
| 技術約束 | Python 部分照舊；擴充功能是憲章 VII 預告的呈現層，技術約束中的「語言：Python」指的是分析核心 | ✅ |
| 開發流程 | Python 匯出測試先行；JS 的純函式先寫 `node --test`；功能測試與預測準確度分開（本 feature 不涉及準確度） | ✅ |

**Post-design re-check（Phase 1 後）**：data-model、contracts 符合上表。

### 使用者確認的設計決定（2026-09-27，全部依建議 A）

1. **D1 句子由 Python 產生**（R1）：
   - 建議 A：擴充功能顯示的句子（原因、版本說明、組合包指引與卡片）由報告的同一段函式產生，寫進資料檔；JS 只做格式化。
     這需要把 `report/html.py` 中組句子的部分拆成純文字函式（HTML 輸出逐位元組不變）。
   - B：JS 自己組句子（兩份實作，文字可能不一致）。
2. **D2 寫檔失敗的結束代碼**（R2）：
   - 建議 A：報告照常完成，結束代碼為部分成功，背景更新的日誌會記錄下來。
   - B：只印提醒，結束代碼不變。
3. **D3 合併時機**（R7）：
   - 建議 A：10/1 修正完就合併到 master。排程在工作目錄執行，目前的分支要有匯出程式，秋特期間才會每天更新資料檔。
   - B：秋特期間工作目錄留在 011 分支，秋特結束後再合併。

其他照 research 的建議：資料時間用 `confirmed_at`（R0.3；spec 的 clarify 句已改）；彈出視窗「現在買」「即將到價」預設展開；
滑鼠移上用原生 `title` 提示；圖示過舊為橘底、讀不到為紅底「!」。

## Project Structure

### Documentation (this feature)

```text
specs/011-chrome-extension/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R7 設計決定
├── data-model.md        # 資料檔、執行期狀態、頁面對應
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── extension-data.md    # steamsage.extension/1
│   └── extension-ui.md      # manifest、訊息、三個位置、圖示、report 的變更
├── prototype/           # p0–p4、ext/（原型擴充功能）；ext/data/、out/ 不進版控
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── report/
│   ├── html.py          # 拆出純文字的句子函式（輸出不變）
│   └── extension.py     # 新：build(data) -> steamsage.extension/1；write(path, payload)
├── commands.py          # report：正式執行寫擴充功能資料檔、摘要 extension、失敗時部分成功
└── config.py            # Config.extension_dir（設定檔所在資料夾 / "extension"）

extension/               # 新：使用者在 Chrome 載入的資料夾
├── manifest.json
├── lib.js               # 純函式（node --test 也能載入）
├── sw.js
├── popup.html / popup.js / popup.css
├── content.js
├── icons/               # 16／32／48／128 px
└── data/                # 報告寫入；.gitignore 排除

tests/
├── unit/report/test_extension_data.py
├── contract/test_extension_contract.py
├── contract/test_cli_report.py          # 延伸：寫檔條件與失敗
└── extension/
    ├── lib.test.js / manifest.test.js / static.test.js
    ├── fixtures/                         # 精簡的 Steam 頁面（遊戲頁、已擁有、願望清單、改版）
    └── e2e.py                            # Playwright；--live 連真實 Steam

README.md、HANDOFF.md、.gitignore（extension/data/）
```

**Structure Decision**：Python 部分沿用單一專案，新增 `report/extension.py` 一個模組；擴充功能放在專案根目錄的 `extension/`，
使用者直接載入這個資料夾，報告寫入它的 `data/`。

## Complexity Tracking

沒有違反憲章而需要辯護的設計。

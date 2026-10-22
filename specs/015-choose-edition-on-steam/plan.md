# Implementation Plan: 在 Steam 遊戲頁直接指定追蹤版本

**Branch**: `015-choose-edition-on-steam` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/015-choose-edition-on-steam/spec.md`

## Summary

1. **本機程式**（research R2–R6）：新套件 `steamsage.host`。Chrome 透過 `data/host/sweetspot-host.bat` 啟動它（專案 `.venv` 的 python，
   設定檔路徑在安裝時寫死），每次一問一答：`status`、`choose`、`reset`。`choose`／`reset` 依序取處理鎖與寫入鎖、以資料庫驗證、逐行修改
   `[purchase_options]` 的那一行、在同一個程序內執行正式 `report`（和命令列同一條路徑），失敗時把設定檔、HTML 報告、擴充功能資料檔還原
   （已保存的正式紀錄保留，憲章 IV）。
2. **安裝**：`uv run steamsage host install|uninstall|status`，只寫 `data/host/` 與 `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.sweetspot.edition`。
3. **擴充功能**：manifest 加 `nativeMessaging` 權限與固定編號用的 `key`；Service Worker 檢查後轉送；遊戲頁面板新增「版本」一節（預設收合，展開時才查詢本機程式）；
   Steam 購買框加捷徑；按兩下確認、只認真正的使用者操作、60 秒時限、成功後重畫。
4. **資料檔**：`steamsage.extension/1` 的每款遊戲新增 `versions`（只新增欄位，Python 產生，擴充功能不重算）。
5. **不變**：模型、規則、決策契約、資料庫結構（v7）、HTML 報告、正式紀錄格式、願望清單頁與彈出視窗、每日排程。

**plan 階段的原型**（research R0，這台電腦，HKCU 只登記測試名稱、跑完刪除）：

| 項目 | 結果 |
|---|---|
| 固定擴充功能編號（manifest `key`） | 載入前算出的編號＝Chromium 給的編號 |
| `.bat` 本機程式 | 可行；Chrome 傳入來源與 `--parent-window`；來回 89–99 ms；沒有登記時錯誤為 `Specified native messaging host not found.` |
| 內容腳本 → Worker → 本機程式 | 可行（96 ms），Worker 看得到分頁網址 |
| 頁面程式的模擬點擊 | 6 種方式全部不是 `isTrusted`；真正的滑鼠、Enter、空白鍵是 |
| 本機程式的存活 | Worker 停止、連線中斷時本機程式**不會被結束**，工作照樣完成；40 秒的工作兩種呼叫方式都收到回覆 |
| 時間 | 載入 steamsage 0.36–0.43 秒；`report` 5.9 秒 → 一次指定預計約 7 秒（SC-001 上限 30 秒） |
| 替代做法 | **不需要**：spec 的做法（擴充功能 → 本機程式 → 改設定檔＋正式 `report`）可行 |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14），uv；擴充功能用原生 JavaScript、Chrome MV3（沿用 011）。

**Primary Dependencies**：不新增 Python 套件（決定 D2、D3 建議 A）；Windows 登錄用標準函式庫 `winreg`；設定檔驗證用 `tomllib`。
測試工具同 011（`node --test`；Playwright 只用於端對端，`uv run --with playwright==1.63.0`）。

**Storage**：資料庫不變（v7）。新增 `data/host/`（啟動檔、登記檔；不進版控）、`data/.host.lock`；HKCU 一個登錄鍵；擴充功能資料檔多一個欄位。

**Testing**：pytest（測試先行）；`node --test "tests/extension/*.test.js"`；端對端 `tests/extension/e2e.py`（用假的本機程式，research R9）。

**Target Platform**：Windows 11 本機；Chrome（開發人員模式載入未封裝項目）。

**Project Type**：單一 Python CLI 專案＋本機 Chrome 擴充功能＋（新）擴充功能呼叫的本機程式。

**Performance Goals**：按下確認到面板更新 ≤ 30 秒（SC-001；預計約 7 秒）；背景更新進行中 ≤ 1 秒拒絕（SC-007）；`status` 約 0.5 秒；
資料檔增加約 10 KB；`report` 增加的時間可忽略。

**Constraints**：

- 擴充功能仍不連外（FR-021、SC-006）；只多 `nativeMessaging` 權限。
- 請求只決定遊戲、版本與指令；檔案與動作在安裝時固定（FR-015）。
- 設定檔只改一行，其他逐位元組不變（FR-008、SC-003）；失敗時還原（FR-009、SC-004）。
- 指定後的報告是正式執行，和手動 `report` 同一條路徑（FR-007、FR-012）。
- 金鑰不出現在回覆、日誌與錯誤訊息（FR-020、憲章 IX）。

**Scale/Scope**：願望清單 69 款，24 款有其他版本、共 31 個；一次一個請求。

## Constitution Check

依憲章 **1.2.1**。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 版本的現價未知時為 null、顯示「—」；本機程式狀態未知時顯示「檢查本機程式…」或「無法使用」，不假設可用 | ✅ |
| II 證據可追溯 | 指定後的報告照常保存正式紀錄（模型、規則、分析時間）；每個請求一行日誌（時間、指令、遊戲、版本、結果與原因） | ✅ |
| III 逐項隔離失敗 | 本機程式失敗或未安裝時擴充功能其他功能照常（US2）；失敗時設定檔、報告、資料檔都回到之前（R5）；個別遊戲的決策錯誤不算失敗 | ✅ |
| IV 預測必須可驗證 | 不改模型與規則；指定後的報告是正式執行並保存紀錄（clarify Q1）；指定失敗而還原時，已保存的正式紀錄**保留**，不刪除任何紀錄（2026-10-14 analyze C1）；不宣稱準確率 | ✅（不適用回測） |
| V 規則單一正本 | 指定規則沿用 009 的 `choices.resolve_choice`；擴充功能不含規則，只看資料檔的 `action` | ✅ |
| VI 簡單優先 | 不新增套件；不做中斷紀錄與自動復原（R5）；新常數（確認 5 秒、時限 60 秒、請求 512 位元組、註解 80 字）都是 spec 或呈現用的預設值 | ✅ |
| VII 核心與呈現分離 | `versions` 由 Python 從決策字典組成；擴充功能只顯示；本機程式不是呈現層，它改的是使用者偏好（009 的設定），報告照常由核心產生 | ✅ |
| VIII 遵守資料來源條款 | 不抓任何資料；本機程式與它執行的 `report` 都不連網 | ✅ |
| IX 本機與安全 | 只登記目前使用者（HKCU）、只允許這個擴充功能；外部文字（版本名稱）寫進設定檔註解前移除控制字元與換行，擴充功能用 `textContent`；金鑰照舊只從環境變數讀取 | ✅ |
| 技術約束 | Python／uv／Windows；啟動檔以 OEM 字碼頁寫入，路徑可以有中文與空白（R2） | ✅ |
| 開發流程 | spec 已確認（2026-10-14，commit 134b4e9）；本機程式、設定檔編輯、資料檔測試先行；JS 純函式先寫 `node --test` | ✅ |

**Post-design re-check（Phase 1 後）**：data-model、contracts 符合上表。

### 使用者確認的設計決定（2026-10-14，全部依建議 A）

1. **D1 擴充功能編號**（R1）：
   - 建議 A：manifest 加 `key`，編號固定；第一次要在 `chrome://extensions` 重新載入一次。
   - B：`host install --extension-id <編號>`，使用者從 `chrome://extensions` 複製。
2. **D2 本機程式怎麼啟動**（R2）：
   - 建議 A：安裝時產生 `.bat`，直接呼叫專案 `.venv` 的 python。
   - B：`.bat` 呼叫 `uv run`（較慢、uv 的輸出不受控制）。
3. **D3 設定檔怎麼改**（R3）：
   - 建議 A：自己寫逐行編輯，寫入前用 `tomllib` 驗證「只差這一行」；不新增套件。
   - B：新增 `tomlkit` 套件。
4. **D4 寫入鎖**（R4；**spec FR-019 的前提要修正**：`report` 本身不取寫入鎖）：
   - 建議 A：本機程式取自己的處理鎖＋現有的寫入鎖；和其他正式 `report` 同時執行的情況不排除（和現在手動 `report` 與背景更新相同）。
     spec FR-019 改成「和每日更新相同的寫入鎖」。
   - B：正式 `report` 也改成取寫入鎖（改變 003 R9 的行為與兩個 `.cmd` 的結束代碼）。
5. **D5 失敗時還原的範圍**（R5）：
   - 建議 A：設定檔、HTML 報告、擴充功能資料檔寫回原始內容（符合 spec FR-009 的字面）；已保存的正式紀錄保留。
     （2026-10-14 `/speckit-analyze` C1 修正：原本還會刪除這次新增的正式紀錄，違反憲章 IV「每次正式執行 MUST 保存當次預測紀錄」；使用者同意依建議改為保留。）
   - B：只還原設定檔；spec FR-009 要改寫。
6. **D6 呼叫方式**（R6）：依原型直接採用 `sendNativeMessage`（每次一個程序），不需要長連線。
7. **D7 寫入的那一行**（R3）：
   - 建議 A：`1091500 = "bundle/32470"   # 《名稱》（日期 從 Steam 頁面指定）`，和設定檔現有那一行的寫法一致。
   - B：只寫 `1091500 = "bundle/32470"`。

依 D1、D4 修改了 spec（2026-10-14）：FR-019 改成「和每日更新相同的寫入鎖」並註明 `report` 不取鎖；Assumptions 第一點與 Edge Cases 最後一點
改成「擴充功能編號固定、專案資料夾搬家後要重新安裝本機程式」。

## Project Structure

### Documentation (this feature)

```text
specs/015-choose-edition-on-steam/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R9 設計決定
├── data-model.md        # versions 欄位、請求與回覆、安裝、日誌、鎖、執行期狀態
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── native-host.md   # 通道訊息、錯誤代碼、處理順序、steamsage host 指令、安全不變式
│   └── extension-ui.md  # manifest、Worker 轉送、版本一節、按兩下確認、購買框捷徑
├── prototype/           # p1_native.py、host_probe.py、ext/（原型擴充功能）
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── host/                    # 新：本機程式
│   ├── __init__.py
│   ├── __main__.py          # Chrome 的進入點：python -m steamsage.host --config <設定檔> <來源> [--parent-window=N]
│   ├── protocol.py          # 訊息讀寫（4 位元組長度＋JSON）、請求格式檢查
│   ├── toml_edit.py         # [purchase_options] 的逐行編輯與 tomllib 驗證
│   ├── service.py           # status／choose／reset：鎖、驗證、改設定檔、執行 report、還原、日誌
│   └── install.py           # 啟動檔、登記檔、HKCU 登錄（登錄操作可替換，測試不碰真的登錄）
├── report/extension.py      # games[].versions
├── cli.py                   # 新增 host 子指令（install／uninstall／status）
└── commands.py              # host_command

extension/
├── manifest.json            # nativeMessaging、key、版本 1.1.0
├── lib.js                   # versionsModel、按鈕狀態、轉送檢查（純函式）
├── sw.js                    # {type: "host"} 的檢查與轉送
└── content.js               # 版本一節、購買框捷徑、重畫

tests/
├── unit/host/               # test_protocol.py、test_toml_edit.py、test_install.py
├── integration/test_host_service.py   # 安全（SC-002）、鎖（SC-007）、失敗注入（SC-004）、和手動 report 相同（SC-005）
├── unit/report/test_extension_data.py # 延伸：versions
├── contract/test_extension_contract.py # 延伸：versions 欄位
└── extension/
    ├── lib.test.js / manifest.test.js / static.test.js   # 延伸
    ├── fake_host.py         # 端對端用的假本機程式（固定回覆，帶 fake: true）
    └── e2e.py               # 延伸：版本一節、按兩下、模擬點擊、進度、重畫、逾時、未安裝、購買框捷徑

README.md（安裝、能做與不能做的事）、HANDOFF.md、.gitignore（data/host/）
```

**Structure Decision**：沿用單一 Python 專案；本機程式放在 `src/steamsage/host/`，用 steamsage 自己的設定、鎖、日誌與 `report`，
不另立專案。擴充功能維持專案根目錄的 `extension/`。

## Complexity Tracking

沒有違反憲章而需要辯護的設計。

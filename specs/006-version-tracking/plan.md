# Implementation Plan: 版本追蹤

**Branch**: `006-version-tracking` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-version-tracking/spec.md`

## Summary

1. **版本的判定**（research R1）：預設購買選項 = App 的購買選項中，價格和同一次更新的 `price_overview` 相同的那個套件。
   用 `GetItems` 批次查，每天多 2 個請求。
2. **對應與驗證**（R2）：`sub/<套件>` → ITAD 商品。和 App 本身相同就沿用 001 的驗證；不同時用擴充規則驗證：
   接受本體加自己的 DLC，拒絕組合包與其他遊戲；價格取自 App 自己的購買選項。
3. **儲存**（R3）：schema v3。價格觀測、抓取紀錄與現價核對記錄 ITAD 商品 id；新表 `app_versions` 每天每款一列，只新增。
   遷移時把既有歷史補上 id（每款剛好一個 id，沒有歧義），先備份。
4. **讀取**（R4）：每款遊戲在分析時點用「當時最新版本紀錄」的 ITAD 商品；沒有紀錄就用 App 本身的商品。
   「已知至」依商品計算，版本紀錄顯示 ITAD 已停止追蹤時截在最後確認時間。
5. **輸出**（R6）：預測與決策輸出新增 `version` 物件、標籤與變動；報告顯示追蹤的版本、版本更換與停止追蹤。契約不升版。
6. **回測資料集不變**（R0.4、R4）：版本紀錄從本 feature 開始才有，2026-09-25 截止的資料集識別碼仍是 `d547c29d…`。

**plan 階段的原型**（research R0）：

| 項目 | 結果 |
|---|---|
| 預設購買選項（價格比對） | 66/66 款唯一決定，0.9 秒 |
| 版本對應 | 64 款和現在相同；Dying Light 換成 Essentials Edition 並通過驗證；範例分季作品 因組合包被拒絕；3.3 秒 |
| Dying Light 換版本之後 | 現在買（低信心，甜蜜價 NT$268）→ **即將到價：2026 秋特 NT$101（-85%），機率 86%** |
| 現行的舊版本歷史 | 「最近 6 場都是 -70%」是 ITAD 停止追蹤後被沿用的最後狀態，虛構的 |
| 回測資料集 | 停止追蹤只有 Dying Light 1 款（驗證組）；原價來回切換 9 款 |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。

**Storage**：

- SQLite 升為 schema v3（data-model）：3 個既有表各加欄位、新表 `app_versions`、唯一索引重建、一次性補值遷移（自動備份）。
- 預測紀錄 `data/forecasts/*.json.gz` 新增選用欄位，契約版本不變。
- 進版控的文件：
  - `docs/model/model-definition.md`：資料定義（價格歷史跟著預設購買選項）、規則 2.1.0 與 3.1.0、版本歷史
  - `docs/model/comparisons.md`：只附加一筆「規則 2.1.0：不影響回測的資料品質規則」
  - README、HANDOFF

**Testing**：pytest，測試先行（research R9）。

- 版本判定與驗證：人工 `GetItems` 回應（放在 `tests/fixtures/steam/`），涵蓋 DLC 套件、組合包、其他遊戲、不販售的套件、同價多套件。
- 儲存：v2 → v3 遷移前後逐列比對；唯一索引允許兩個版本並存。
- 讀取：人工資料的版本更換、換回、只換套件、停止追蹤；時點過濾（洩漏測試證明抓得到偷看）。
- 資料集：加入版本紀錄前後，截止時間早於第一筆紀錄的資料集識別碼相同。
- 契約與報告：人工契約 dict 產生報告並比對。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `steamsage.store`、`steamsage.sources`、`steamsage.pipeline`、`steamsage.forecast`、
`steamsage.decision` 與 `steamsage.report`

**Performance Goals**（research R8）：

| 執行 | 目標 |
|---|---|
| `update` 的版本步驟 | 平常 < 3 秒；第一次 < 10 秒（SC-007 上限 30 秒） |
| 遷移 | 一次性，< 30 秒（估計 10 秒以內，實作時實測） |
| `report` | 增加 < 0.5 秒（現行約 3.6 秒） |
| `backtest`、`backtest-rule` | 不變 |

**Constraints**：

- 只新增：`app_versions` 只新增；既有表只在遷移中補 `external_id`，其他欄位不變。
- 版本步驟的來源錯誤只影響版本步驟，各款沿用上一筆版本。
- 只用台灣區判定版本；美國區只提供同一個 ITAD 商品的折扣百分比。
- 呈現層不判斷版本。

**Scale/Scope**：

- 願望清單 68 款（66 款有價格）。
- 價格觀測約 22 萬列需要補 `external_id`，2,687 款。
- 回測資料集 2,583 款，不變。

## Constitution Check

依憲章 **1.2.0**（2026-09-26 修訂原則 IV，見 spec Clarifications 的 analyze 後一節）。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 停止追蹤的歷史「已知至」截在最後確認時間，之後的特賣是未知（修正 Dying Light 的 6 場虛構特賣）。無法確認版本、驗證失敗都有明確狀態 | ✅ |
| II 證據可追溯 | 每筆 ITAD 觀測記錄所屬的 ITAD 商品；版本紀錄保存套件、商品、驗證結果、別名與取得時間；沿用的驗證保留原始驗證時間 `verified_at`；輸出寫出使用的版本與偵測時間 | ✅ |
| III 逐項隔離失敗 | 版本步驟出錯時沿用上一筆，不中斷更新；單款驗證失敗只影響該款 | ✅ |
| IV 預測必須可驗證 | 模型不變。資料集識別碼不變（測試＋真實資料確認）。版本紀錄依 `checked_at` 做時點過濾，洩漏測試涵蓋。規則升 2.1.0：依憲章 **1.2.0** 原則 IV 的「資料品質旗標」例外（2026-09-26 修訂），證明回測逐案相同、記錄在比較文件、使用者同意（R5 A） | ✅ |
| V 規則單一正本 | 「停止追蹤 → 低信心」是規則變更，規則升為 2.1.0、3.0.0 候選升為 3.1.0，模型定義同步更新（R5 A、spec FR-018） | ✅ |
| VI 簡單優先 | 不新增使用者偏好。新增的常數只有「價格比對決定預設選項」與「DLC 判定」，都有原型依據。不做使用者指定版本（YAGNI） | ✅ |
| VII 核心與呈現分離 | `version` 由預測核心決定，決策逐欄複製，報告只讀 | ✅ |
| VIII 遵守資料來源條款 | 只用 Steam 官方 API 與 ITAD API；批次查詢，每天多 3 個請求；沿用速率限制 | ✅ |
| IX 本機與安全 | 只用台灣區判定版本與金額；美國區只存折扣百分比；金鑰不寫入檔案 | ✅ |
| 開發流程 | 每個核心改動先寫會失敗的測試；遷移有逐列比對測試 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 符合上表。R5 已由使用者決定採用 A（2026-09-26）。

### 使用者確認的設計決定（2026-09-26，全部依建議）

1. **R5（必須決定）**：「停止追蹤 → 低信心」是決策規則的改變。
   - **建議 A**：規則升為 `sweet-price` 2.1.0（3.0.0 候選同步升 3.1.0，驗證組次數沿用）。回測逐案相同，比較文件附加一筆，不需要驗證組比較。
   - B：不降信心，只加原因與標籤（要改 spec）。
   - C：不升版（違反憲章 V，不建議）。
2. **R3**：資料庫升為 v3，遷移時補上既有歷史的 ITAD 商品 id，並自動備份成 `steamsage.db.bak-v2`（約 140 MB）。
3. **R2**：和 App 本身同一個 ITAD 商品時沿用 001 的驗證，不重新驗證；001 用套件的「最佳購買選項」當價格的問題（可能誤判 Eternights）
   只在新的版本驗證中修正，參考遊戲的 001 驗證不改。
4. **R4**：之後以更晚的截止時間建立資料集時，Dying Light 整段使用 Essentials Edition 的歷史（2025-06 起），之前的分析時點看不到歷史。
5. **R6**：報告在名稱下方一直顯示追蹤的版本（只在和 App 名稱不同時）；「版本更換」只在第一份報告的變動欄出現（clarify 的決定）。

## Project Structure

### Documentation (this feature)

```text
specs/006-version-tracking/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R9 設計決定
├── data-model.md        # schema v3、app_versions、讀取介面、狀態轉換
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── outputs-version.md   # 預測與決策輸出的 version 欄位與標籤
│   └── cli-and-report.md    # update 的版本步驟與摘要、報告顯示
├── prototype/           # P1–P4 原型；out/ 不進版控
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── store/
│   ├── schema.py        # v3：新欄位、app_versions、唯一索引、v2→v3 遷移與備份
│   ├── writer.py        # NewObservation.external_id、add_version()
│   └── query.py         # versions()、history_keys()、依商品過濾的 series_rows／known_until
├── sources/
│   ├── __init__.py      # PurchaseOption、VersionSource 介面
│   ├── steam_webapi.py  # GetItems 全部購買選項、套件內容、DLC 的 parent_appid
│   └── itad.py          # current_prices 回傳 Steam 現價筆數
├── pipeline/
│   ├── versions.py      # 新：預設選項判定、ITAD 對應、擴充驗證、版本紀錄（FR-001～FR-006）
│   ├── verify.py        # 擴充規則（DLC、價格來源）；001 規則不變
│   ├── history.py       # 依版本的 ITAD 商品抓歷史，寫 external_id
│   ├── daily.py         # 版本步驟、摘要 versions、alerts
│   ├── consistency.py   # 依商品過濾
│   ├── reference.py、legacy_import.py  # 寫入 external_id
├── coverage.py          # 依商品過濾
├── forecast/
│   ├── engine.py        # load_games 依 history_keys；unverified 原因；輸出 version
│   └── contract.py      # Forecast.version
├── decision/
│   ├── prices.py        # 依商品的 known_until；history_stopped
│   ├── rule.py          # 2.1.0／3.1.0：資料可疑的條件加入停止追蹤；RULE_BACKTESTS 加 2.1.0
│   ├── engine.py        # 複製 version、原因、標籤
│   ├── contract.py      # version 欄位
│   └── changes.py       # 版本變動
└── report/html.py       # 版本行、版本更換、停止追蹤

tests/
├── unit/                # 版本判定、驗證、遷移、讀取、known_until、規則旗標、變動
├── contract/            # 輸出保證、時點無洩漏、資料集識別碼不變
├── integration/         # update 的版本步驟（人工來源）、報告流程
└── fixtures/steam/      # GetItems 購買選項、套件、DLC 的回應
```

**Structure Decision**：沿用單一 Python 專案。新增一個模組 `pipeline/versions.py`，其他都是既有模組的延伸。

## Complexity Tracking

沒有違反憲章而需要辯護的設計。

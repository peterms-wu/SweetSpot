# Implementation Plan: 價格資料基礎

**Branch**: `001-price-data-foundation` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-price-data-foundation/spec.md`

## Summary

建立 SteamSage2 的資料層：同步公開的 Steam 願望清單，取得台灣區現價、ITAD 台灣區歷史，以及美國區的折扣百分比歷史，
並用 Steam 官方資料核對商品身分。所有資料以「只新增」的方式存進單一 SQLite 檔，並提供不會洩漏未來資訊的時點查詢介面，
給 feature 002 回測使用。另外建立參考遊戲資料集（相關樣本加上分層隨機的廣泛樣本）、匯入舊專案快取，
以及維護 Steam 特賣行事曆（含預估日期）。技術選擇與依據見 [research.md](research.md)。

## Technical Context

**Language/Version**: Python ≥3.12（開發機為 3.14.6）

**Primary Dependencies**: `httpx`（HTTP）。其餘都用標準庫：`sqlite3`、`tomllib`、`argparse`、`dataclasses`、`zoneinfo`，
以及 Windows 上需要的 `tzdata`

**Storage**: 單一 SQLite 檔 `data/steamsage.db`（WAL 模式）。特賣行事曆正本為 `data/steam_sales.toml`

**Testing**: pytest；HTTP 用 `httpx.MockTransport` 搭配錄製的 fixture；另有 contract tests 驗證 store-api 的保證事項

**Target Platform**: Windows 11 本機。路徑須支援中文與空白

**Project Type**: 單一 Python CLI 專案（套件名稱 `steamsage`）

**Performance Goals**: 68 款日常更新，首次 ≤15 分鐘、之後 ≤5 分鐘（SC-001）；參考資料集累計 ≥2,000 款（SC-006）

**Constraints**:
- ITAD 每 5 分鐘上限 1000 次，實作取 750 次；Steam Store 每次間隔 ≥1.5 秒；Steam Web API 每天上限 100,000 次
- 不使用 SteamDB（憲章 VIII）
- 金鑰只從環境變數讀取（憲章 IX）

**Scale/Scope**: 願望清單 ≤500 款；參考遊戲約 2,000–3,000 款；價格觀測約數十萬筆

**API 用量估計**：
- 68 款首次執行：ITAD 約 210 次（對應 1、反向核對 68、兩區歷史 136、現價 1），Steam 約 80 次，
  依節流約需 4–6 分鐘
- 之後的日常更新：歷史快取 24 小時內不重新抓取，Steam 現價 1–2 次批次請求，約 1 分鐘，再加上參考小批次的 2 分鐘

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 金額 NULL 與 0 分開；`history_state` 區分 none、not-fetched、available；缺資料時保留原因代碼 | ✅ |
| II 證據可追溯 | 每筆觀測與事實都有 source、retrieved_at、run_id；追蹤起點另外標記；舊資料標為 legacy | ✅ |
| III 逐項隔離失敗 | 每款遊戲在自己的 transaction 中寫入；有逐商品結果表；清單被拒絕時不覆蓋；只新增不修改 | ✅ |
| IV 預測必須可驗證 | 本 feature 不做預測，但提供不洩漏未來資訊的時點查詢，並以 contract tests 驗證；volatile 屬性不會被用來回測過去 | ✅ |
| V 規則單一正本 | 本 feature 沒有預測規則。抽樣參數集中在設定檔，並以 sample_version 標示版本 | ✅ |
| VI 簡單優先 | 只多一個第三方套件（httpx）；觀測與特賣的對應在查詢時計算，不另外保存 | ✅ |
| VII 核心與呈現分離 | 以 store-api 介面提供資料；本 feature 沒有呈現層 | ✅ |
| VIII 遵守資料來源條款 | 不用 SteamDB 或 SteamSpy；遵守 robots.txt；節流、Retry-After、401/403 時停用；標示資料來自 ITAD | ✅ |
| IX 本機與安全 | 固定 TW；輔助區域不保存金額，並有一致性驗證；金鑰只從環境變數讀取，並在輸出中遮蔽；不需要 Steam 登入 | ✅ |
| 開發流程 | 核心邏輯測試先行：核對規則、時點查詢、去重、狀態轉換、行事曆預估 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。
有一項規格調整：使用情境 3 AS2 把中繼資料分成固定與變動兩類，理由見 research R6，已同步更新 spec.md，需要使用者確認。

## Project Structure

### Documentation (this feature)

```text
specs/001-price-data-foundation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── config.md
│   ├── store-api.md
│   └── sales-calendar.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
pyproject.toml / uv.lock
steamsage.toml                 # 使用者設定（不含金鑰；第一次執行時自動建立）
更新資料.cmd                    # 一鍵入口 → uv run steamsage update
data/
├── steam_sales.toml           # 特賣行事曆正本（納入版本控制）
└── steamsage.db               # 資料庫（.gitignore 排除）
src/steamsage/
├── cli.py                     # argparse 指令、exit codes、摘要輸出
├── config.py                  # 載入與驗證 steamsage.toml，讀取環境變數中的金鑰
├── lock.py                    # 單一寫入者鎖
├── timeutil.py                # UTC 轉換、ITAD 的 since 格式
├── store/
│   ├── schema.py              # 建表與 migration
│   ├── writer.py              # 只新增的寫入、去重、異常資料隔離
│   └── query.py               # PriceStore 唯讀時點查詢介面（store-api contract）
├── sources/
│   ├── http.py                # 節流、重試、Retry-After、401/403 停用、金鑰遮蔽、User-Agent
│   ├── itad.py                # 對應、反向對應、歷史、現價、遊戲資訊
│   ├── steam_store.py         # appdetails、packagedetails、appreviews、商店搜尋
│   └── steam_webapi.py        # GetWishlist、GetItems、GetAppList
├── pipeline/
│   ├── wishlist.py            # 同步清單與狀態轉換
│   ├── verify.py              # 商品核對規則（research R2）
│   ├── daily.py               # update 指令的流程
│   ├── reference.py           # 相關樣本與分層廣泛樣本、續接
│   ├── legacy_import.py       # 匯入舊快取（research R8）
│   └── consistency.py         # 區域一致性計算
├── calendar.py                # 載入與驗證行事曆、預估、對應、漏收偵測
└── coverage.py                # 覆蓋摘要
tests/
├── fixtures/                  # 錄製的 API 回應（已去除金鑰）、舊快取樣本
├── unit/                      # 核對、去重、時間、行事曆、抽樣、狀態轉換
├── contract/                  # store-api 的保證事項、CLI 的 exit codes 與 JSON 摘要
└── integration/               # 以 MockTransport 端到端跑 update、reference、import-legacy
```

**Structure Decision**：單一套件、單一 CLI。依資料流程分為 sources → pipeline → store 三層：
- sources 可以抽換，不依賴 store。
- store 不依賴任何外部來源。
- feature 002 只透過 `store.query.PriceStore` 讀取資料。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**：專案骨架（uv、pyproject、pytest）、設定、鎖、時間工具、資料庫 schema、寫入器、時點查詢，以及查詢的 contract tests
2. **P1 使用情境 1**：願望清單同步與狀態轉換、Steam 現價、中繼資料、`update --no-history`
3. **P1 使用情境 2**：ITAD client、商品核對、台灣區與輔助區域歷史、現價交叉核對
4. **P1 使用情境 3**：補齊時點查詢的完整保證事項（固定與變動屬性）
5. **P2 使用情境 5**：匯入舊快取。建議提早做，可以用來驗證 2、3 的資料格式
6. **P2 使用情境 7**：行事曆資料檔、驗證、預估、對應、提醒
7. **P2 使用情境 4**：參考資料集，包含相關樣本、分層廣泛樣本、日常小批次與續接
8. **P3 使用情境 6**：覆蓋摘要，以及區域一致性報告
9. **收尾**：一鍵 `.cmd`、README、實際跑 68 款的端到端驗證、檢查金鑰是否外洩（SC-008）

## Complexity Tracking

沒有違反憲章的項目。

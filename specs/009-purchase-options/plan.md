# Implementation Plan: 使用者指定版本、列出其他購買選項

**Branch**: `009-purchase-options` | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-purchase-options/spec.md`

## Summary

1. **購買選項與版本**（research R1、R2）：每日更新在 006 的版本步驟之後新增「購買選項步驟」，重用同一次的購買選項請求，
   判定每個選項是不是這款遊戲的版本（本體＋自己的 DLC）。版本才查 ITAD 商品並驗證；006 的驗證擴充成接受「別名是這個組合包本身」。
2. **儲存**（R3）：schema v4，新表 `purchase_options`（只新增）。版本的價格歷史寫進 `price_observations`，
   但用**獨立的來源名稱** `itad-option-history`，既有的讀取（預設序列、季節特賣偵測、回測資料集）都自動忽略它。
3. **指定**（R4）：`steamsage.toml` 的 `[purchase_options]`。產生預測時依設定與 as_of 以前的購買選項紀錄解析；不能用時退回預設並附原因。
   全部遊戲照舊用預設版本讀取，整體比例不變；指定的遊戲另外讀版本的歷史，只用來產生它自己的證據。
4. **現價**（R5）：取購買選項紀錄中這個選項的價格。
5. **輸出與報告**（R6、R7）：`version` 新增 `source`、`option`、`fallback`；決策新增 `editions`（含設定行）；變動新增 `cause`。
   報告摘要行「另有 N 個版本」，展開後列出版本。契約不升版。
6. **不變**：模型、規則、回測資料集與識別碼。

**plan 階段的原型**（research R0，真實資料，寫入只在資料庫副本上）：

| 項目 | 結果 |
|---|---|
| 清點（P1） | 25 款、32 個版本；12 個組合包版本在新規則下 12/12 通過；Dying Light 十週年完整版仍被拒絕 |
| 不指定（P3 A／B） | 副本加入 32 個版本的歷史後，68/68 款決策和真實資料庫完全相同（SC-001） |
| 指定 10 款（P3 C） | 其他 58 款完全相同（SC-002）；4 款組別改變（AC Odyssey 現在買 → 即將、KCD II 與 33號遠征隊 現在買 → 等待、Granblue 等待 → 低信心） |
| 回測資料集（P3 D） | 真實與副本都是 `d493ac02…`（SC-007） |
| 每日成本（P1、P2） | 平常多約 19 秒、第一次約 29 秒（SC-008 上限 30 秒） |
| 原型發現 | 價格序列建構也依來源過濾；`latest_observations` 會把新來源誤當成商店現價，必須修正（R3） |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。

**Storage**：

- SQLite 升為 schema v4（data-model §1）：新表 `purchase_options` 與只新增觸發器；自動備份 `steamsage.db.bak-v3`。
- `price_observations`、`history_fetches` 新增來源值 `itad-option-history`、`itad-option`（不改表結構）。
- 預測紀錄 `data/forecasts/*.json.gz` 新增選用欄位，契約版本不變。
- 進版控的文件：`docs/model/model-definition.md`（資料定義：指定版本、已知限制 1 改寫）、README、HANDOFF。
  不附加比較文件（模型與規則都沒有改）。

**Testing**：pytest，測試先行（research R9）。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `steamsage.config`、`store`、`sources`、`pipeline`、`forecast`、`decision`、`report`

**Performance Goals**（research R8）：

| 執行 | 目標 |
|---|---|
| `update` 的購買選項步驟＋版本歷史 | 平常 < 20 秒；第一次 < 30 秒（SC-008） |
| 遷移 v3 → v4 | < 5 秒（只建表；備份約 1 秒） |
| `report` | 增加 < 0.5 秒（現行約 5.0 秒） |
| `backtest`、`backtest-rule` 等 | 不變 |

**Constraints**：

- 只新增：`purchase_options` 只新增；既有表不改結構、不補值。
- 購買選項步驟的來源錯誤只影響這個步驟，讀取時沿用上一次紀錄。
- 組合包內其他 App 的類型不得寫進 `products`／`product_facts`（會改變參考資料的範圍，research R1）。
- 呈現層不判斷版本、不產生設定行。

**Scale/Scope**：願望清單 68 款；每天約 231 列購買選項紀錄（一年約 8.4 萬列）；32 個版本的歷史約 2,000 列。

## Constitution Check

依憲章 **1.2.0**。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 版本沒有歷史時，歷史最低價與起點為 null（報告寫「還沒有價格歷史」），不是 0；指定版本歷史不足照現行規則判低信心，不借用預設版本的折扣 | ✅ |
| II 證據可追溯 | 購買選項紀錄保存選項、價格、內容、ITAD 商品、驗證與取得時間；沿用的類型與驗證保留原始時間；決策紀錄寫出追蹤的選項、來源與退回原因 | ✅ |
| III 逐項隔離失敗 | 購買選項步驟出錯時沿用上一次，不中斷更新；指定不能用只退回那一款 | ✅ |
| IV 預測必須可驗證 | 模型與規則不變；回測不讀指定與版本歷史，資料集識別碼不變（P3 D＋測試）；購買選項紀錄依 `checked_at` 做時點過濾，洩漏測試涵蓋 | ✅ |
| V 規則單一正本 | 沒有規則變更；模型定義的資料定義與已知限制同步更新 | ✅ |
| VI 簡單優先 | 新增的使用者偏好只有 `[purchase_options]`，明確標示為偏好；新增常數只有「組合包別名等於自己可接受」，有 P1 依據。不為含其他遊戲的組合包預建抽象 | ✅ |
| VII 核心與呈現分離 | 版本清單、設定行、來源與退回原因都由核心產生；報告只讀 | ✅ |
| VIII 遵守資料來源條款 | 只用 Steam 官方 API 與 ITAD API；重用版本步驟的請求；每天約多 3 個 Steam 請求與 35 個 ITAD 請求；沿用速率限制 | ✅ |
| IX 本機與安全 | 只用台灣區判定版本與價格；美國區只存折扣百分比；外部文字（選項名稱）只當資料顯示 | ✅ |
| 技術約束：套裝不支援 | 本 feature 就是組合包的功能規格，範圍只到「願望清單遊戲的購買選項中，只含本體與自己 DLC 的組合包」；願望清單上的套裝本身仍標示不支援 | ✅ |
| 開發流程 | 每個核心改動先寫會失敗的測試；遷移有逐表比對測試 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 符合上表。

### 使用者確認的設計決定（2026-09-27，全部依建議）

1. **D1（改 spec 的一條 Edge Case）**：以過去時點執行報告（`--as-of`）時，指定依**目前的設定**，搭配當時已記錄的購買選項。
   - 建議 A：設定是使用者偏好，和 `[preferences]` 一樣不按時間記錄；正式紀錄已保存當時追蹤的選項與來源，追溯以紀錄為準。
   - B：每天把設定寫進資料庫，過去時點用當時的設定（要多一張表，而且改設定後要等下一次更新才生效，和 US1 不符）。
2. **D2**：版本的美國區歷史只抓指定生效的版本（R8）。
   - 建議 A：平常每天多約 19 秒。代價：改設定後、還沒更新前產生的報告，指定版本沒有美國區輔助證據，原因會寫出。
   - B：所有版本都抓，每天再多約 13.5 秒，會超過 SC-008 的 30 秒。
3. **D3（改 spec FR-008 的一句）**：設定檔中「完全相同的鍵重複」是 TOML 語法錯誤，照現行規則整個設定檔讀取失敗並說明位置；
   數值相同、寫法不同的鍵（`"0123"` 與 `"123"`）才是「忽略並警告」。建議接受（TOML 解析器的限制）。

其他照 research 的建議：schema v4 並自動備份；組合包別名等於自己可接受；指定的版本剛好是 Steam 預設時仍固定它；
設定行由核心產生。

## Project Structure

### Documentation (this feature)

```text
specs/009-purchase-options/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R9 設計決定
├── data-model.md        # schema v4、purchase_options、版本歷史的來源、設定、讀取介面、狀態轉換
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── outputs-options.md   # version 的新欄位、editions、變動的 cause
│   └── cli-and-report.md    # 設定、update 的購買選項步驟與摘要、報告顯示
├── prototype/           # P1–P3；out/ 不進版控
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── config.py            # [purchase_options] 解析與警告、DEFAULT_TOML 範例
├── store/
│   ├── schema.py        # v4：purchase_options、觸發器、v3→v4 遷移與備份
│   ├── writer.py        # add_purchase_options()
│   └── query.py         # purchase_options()、option_keys()、option_lows()、series_rows(sources=)、讀取修正
├── sources/
│   ├── __init__.py      # BundleContents、VersionSource.bundle_contents
│   ├── steam_webapi.py  # GetItems bundleid
│   └── itad.py          # lookup_ids（sub 與 bundle）
├── pipeline/
│   ├── options.py       # 新：購買選項步驟（判定、驗證、紀錄、摘要）
│   ├── verify.py        # verify_version 的 option 參數（組合包別名等於自己）
│   ├── history.py       # 版本歷史（itad-option-history）、fetch_state／history_is_fresh 只計 itad
│   └── daily.py         # 步驟順序、摘要 purchase_options、alerts
├── coverage.py          # 只計來源 itad 的抓取紀錄
├── forecast/
│   ├── series.py        # build_series 接受版本歷史的來源
│   ├── engine.py        # load_games(sources=)、run_forecast(targets=)、version_info 的 source／option／fallback
│   ├── contract.py      # VersionInfo 新欄位
│   └── nonseasonal/engine.py  # ns_forecast(targets=)
├── decision/
│   ├── engine.py        # 解析指定、讀指定版本、editions
│   ├── prices.py        # 指定選項的現價
│   ├── contract.py      # editions
│   └── changes.py       # 比較追蹤的購買選項、cause
└── report/html.py       # 另有 N 個版本、版本清單、複製按鈕、版本行、變動文字

tests/
├── unit/                # 判定、驗證、設定解析、遷移、讀取修正、解析、現價、變動
├── contract/            # 輸出保證、時點無洩漏、資料集識別碼不變、整體比例不變
├── integration/         # update 的購買選項步驟（人工來源）、報告流程
└── fixtures/steam/      # GetItems 組合包內容、購買選項的回應
```

**Structure Decision**：沿用單一 Python 專案。新增一個模組 `pipeline/options.py`，其他都是既有模組的延伸。

## Complexity Tracking

沒有違反憲章而需要辯護的設計。

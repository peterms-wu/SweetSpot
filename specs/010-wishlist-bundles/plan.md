# Implementation Plan: 同時含多款願望清單遊戲的組合包

**Branch**: `010-wishlist-bundles` | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-wishlist-bundles/spec.md`

## Summary

1. **找出與分級**（research R1）：從 009 的購買選項紀錄，找出內容含 ≥ 2 款願望清單遊戲的組合包，分成純粹與混合。不需要新的抓取。
2. **儲存**（R2、R6）：schema v5，`purchase_options` 加 `bundle_discount_pct`、`before_bundle_cents`（009 的請求已經帶回）；
   這些組合包的內容現價多一次 GetItems，寫進 `contents_json` 的 `final_cents`。不存 ITAD 組合包歷史。
3. **公式檢查**（R3）：Steam 組合包現價 vs (1 − b) × Σ 內容現價，容許 max(NT$2, 1%)；不一致那天不給建議。
4. **組合包建議 `bundle-advice` 1.0.0**（R4）：
   - 分開買的計畫 = 各款甜蜜價（「現在買」用現價）的加總。
   - 下一場季節特賣的推算 = 同時到價 ≥ 50% 的折扣組合中最便宜的一組 × (1 − b)。
   - 建議：現在買組合包／下一場買組合包／分開買。
   - 寫進模型定義新的一節；各款決策不變。
5. **輸出與報告**（R5）：決策批次新增 `bundles`、`bundle_rule`，每個決策新增 `bundles`；報告新增「組合包」一節和每款遊戲的指引。契約不升版。
6. **不變**：模型、決策規則、回測資料集與識別碼、每款遊戲的決策。

**plan 階段的原型**（research R0；回測類只用調參組、截止 2026-09-25、資料集 `858b3147…`）：

| 項目 | 結果 |
|---|---|
| 單場機率（P1） | 用「模型對下一場的機率」（M1）：k ≥ 2 的 Brier 0.0708，比逐場推算（M2）的 0.0799 好；所以每一場的推算都相同，候選只剩「現在」與「下一場」 |
| 同時到價（P2） | 同時到價 ≥ 50% 中最便宜的一組：隨機配對預測 0.731、實際 **0.800**（68,699 個單位）；同發行商 0.733 → 0.822。0.5–0.6 一組實際 68.5% |
| 同發行商 | 一起打折（殘差共變異 0.033 vs 0.005），但方向是更容易同時到價，獨立假設對它們更保守，不另外修正 |
| 目前的願望清單（P3） | E33 x Dispatch：2026 秋特約 NT$1,063（73%），比分開買的計畫 NT$1,132 便宜 NT$69、早一場；DAVE x MiSide：2026 秋特約 NT$366（51%），便宜 NT$41 |
| 每日成本（s2） | 組合包折扣：0 個新請求；內容現價：1 次 GetItems，約 0.6 秒 |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。

**Storage**：

- SQLite 升為 schema v5（data-model §1）：`purchase_options` 加兩個可為 null 的欄位；`contents_json` 的內容多 `final_cents`。自動備份 `steamsage.db.bak-v4`。
- 預測紀錄 `data/forecasts/*.json.gz` 新增選用欄位，契約版本不變。
- 進版控的文件：`docs/model/model-definition.md`（新的一節、`sweet-price` 已知限制 1、現行組合表）、README、HANDOFF。不附加比較文件（沒有模型或規則換版）。

**Testing**：pytest，測試先行（research R9）。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `store`、`sources`、`pipeline`、`decision`、`report`

**Performance Goals**（research R8）：`update` 平常增加 ≤ 2 秒（spec 上限 5 秒）；遷移 < 5 秒；`report` 增加 ≤ 0.2 秒（上限 1 秒）；回測類指令不變。

**Constraints**：

- 只新增：`purchase_options` 只新增列；遷移只加欄位。
- 非願望清單的 App 不寫進 `products`／`product_facts`（009 R1）。
- 組合包的步驟出錯只影響組合包部分，決策照常（憲章 III）。
- 呈現層不重算組合包的任何數字（憲章 VII）。

**Scale/Scope**：目前 6 個組合包（純粹 2、混合 4）、31 個內容 App；每天多約 25 個內容現價寫進既有的 JSON 欄位。

## Constitution Check

依憲章 **1.2.0**。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 內容現價、組合包折扣未知時為 null；公式檢查為 `unknown`、不給建議；v5 以前的紀錄不補值 | ✅ |
| II 證據可追溯 | 組合包折扣、折扣前價格、內容現價都在同一列購買選項紀錄，附 `checked_at`；建議附規則版本、下一場、各款折扣與機率、命中率來源 | ✅ |
| III 逐項隔離失敗 | 內容現價請求失敗只讓比較為未知；組合包步驟例外讓 `bundles` 為 null，決策照常 | ✅ |
| IV 預測必須可驗證 | 沒有新模型；單場機率與同時到價在調參組回測（R0.1、R0.2，截止 2026-09-25），報告只引用模型定義中的命中率；洩漏測試（R7）；不用驗證組（沒有換版） | ✅ |
| V 規則單一正本 | `bundle-advice` 1.0.0 只寫在模型定義的一節與 `decision/bundles.py`，版本出現在每份輸出 | ✅ |
| VI 簡單優先 | 新增的規則常數只有 50%（和甜蜜時點相同）與 max(NT$2, 1%)（R3 有依據）；沒有新的使用者偏好；選 M1 而不是 M2 | ✅ |
| VII 核心與呈現分離 | 比較、推算、建議句、指引都由核心產生；報告只讀 | ✅ |
| VIII 遵守資料來源條款 | 只用 Steam 官方 GetItems；每天多 1 次請求；不抓 ITAD 組合包歷史（validation 的一次性檢查用 ITAD API） | ✅ |
| IX 本機與安全 | 只用台灣區價格；美國區只在 validation 交叉檢查公式，不換算台幣；不讀使用者的遊戲庫（不需要登入） | ✅ |
| 技術約束：套裝不支援 | 本 feature 就是「同時含多款願望清單遊戲的組合包」的功能規格；只含 1 款的組合包、願望清單上的套裝本身仍不支援 | ✅ |
| 開發流程 | 核心邏輯（分級、檢查、規則）測試先行；功能測試與「同時到價準不準」分開報告 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 符合上表。

### 使用者確認的設計決定（2026-09-27，全部依建議；spec FR-008、FR-009 與 Clarifications 已同步）

1. **D1（調整 spec FR-008 的寫法）**：單場機率用「模型對下一場的機率」（R0.1 M1），所以 12 個月內每一場的推算都相同。
   - 建議 A：報告只寫一行「任何一場季節特賣（最早〈下一場〉）：約 NT$X，同時到價 Y%」，建議的候選是「現在」與「下一場」；spec FR-008 改成這個說法。
   - B：照 spec 每一場列一行（數字都一樣，只是重複）。
2. **D2**：報告引用的命中率。
   - 建議 A：依同時到價機率所在的區間，引用隨機配對的實際比例（50–60%：68.5%、60–70%：76.9%、70–80%：83.0%、80–90%：85.6%、90–100%：90.5%）。
   - B：一律引用整體 80.0%（機率剛過 50% 的說法會被高估）。
3. **D3**：同發行商的組合包不另外處理（R0.2：它們更容易同時到價，獨立假設較保守）。建議接受。

其他照 research 的建議：schema v5 並自動備份；公式容許 max(NT$2, 1%)；低信心照常建議並標示；報告的組合包一節放在群組之前。

## Project Structure

### Documentation (this feature)

```text
specs/010-wishlist-bundles/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R9 設計決定
├── data-model.md        # schema v5、實體、狀態、讀取介面
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── outputs-bundles.md   # bundles、bundle_rule、決策的 bundles
│   └── cli-and-report.md    # update 摘要與提醒、報告、模型定義的新一節
├── prototype/           # s1–s6（清點）、p1–p3（plan 原型）；out/ 不進版控
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── store/
│   ├── schema.py        # v5：兩個欄位、v4→v5 遷移與備份
│   ├── writer.py        # NewPurchaseOption 的兩個欄位
│   └── query.py         # OptionRecord 的兩個欄位、contents 的 final_cents
├── sources/
│   ├── __init__.py      # PurchaseOption 的 bundle_discount_pct、before_bundle_cents
│   └── steam_webapi.py  # 解析兩個欄位；內容現價（GetItems best_purchase_option）
├── pipeline/
│   ├── options.py       # FR-001 組合包的內容現價、摘要 bundles、提醒
│   └── daily.py         # 摘要與提醒的串接
├── decision/
│   ├── bundles.py       # 新：分級、公式檢查、比較、bundle-advice 1.0.0、建議句、BUNDLE_BACKTESTS
│   ├── engine.py        # _with_bundles（隔離失敗）
│   └── contract.py      # Decision.bundles、DecisionBatch.bundles／bundle_rule
└── report/html.py       # 組合包一節、每款的指引行

docs/model/model-definition.md   # 組合包建議一節、已知限制 1、現行組合表

tests/
├── unit/decision/       # 分級、檢查、計畫、最便宜組合、建議分支、不給建議的原因、命中率查表
├── unit/                # 遷移、解析
├── contract/            # 輸出欄位與舊紀錄相容、時點無洩漏、常數與模型定義一致
├── integration/         # update 的組合包部分（人工來源）、報告流程
└── fixtures/steam/      # 含 bundle_discount_pct 的購買選項回應、內容現價的回應
```

**Structure Decision**：沿用單一 Python 專案。新增一個模組 `decision/bundles.py`，其他都是既有模組的延伸。

## Complexity Tracking

沒有違反憲章而需要辯護的設計。

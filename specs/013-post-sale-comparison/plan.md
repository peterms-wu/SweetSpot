# Implementation Plan: 事後對照（2026 秋特）

**Branch**: `013-post-sale-comparison` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/013-post-sale-comparison/spec.md`

## Summary

1. **指令**（research R8）：新的唯讀指令 `steamsage review`：選一場已結束的季節特賣與開賣前最後一份正式紀錄，逐款對照，輸出 `steamsage.review/1` 與文字摘要；
   `--doc` 印出 `comparisons.md`「事後對照」一節的草稿。
2. **實際價格**（R1、R2）：每款讀紀錄當時追蹤的商品（`version.itad_id`／使用者指定的版本），算特賣期間的最深折扣與最低價；
   和那個購買選項的每日紀錄交叉檢查。
3. **計分**（R4–R7）：季節機率（兩種到價定義並列，D1）、決策（最低價 ≤ 甜蜜價；提早到價查特賣期間的紀錄有沒有改成現在買）、組合包（逐個）、
   非季節（只計已到期）、同一時點重算現行與基準模型。區間依遊戲重抽樣，種子固定。
4. **不變**：資料庫、紀錄、行事曆檔、設定檔、模型、規則、報告、擴充功能、每日更新、回測。

**plan 階段的原型**（research R0，真實資料、唯讀）：

| 項目 | 結果 |
|---|---|
| 可對照 | 65/68 款（3 款紀錄中沒有預測）；價格歷史都涵蓋到特賣結束 |
| 即將到價 | **25/26** 在秋特到甜蜜價（規則回測 92.4%）；未到：CRYMACHINA（整場沒打折） |
| 繼續等 → 提早到價 | 6 款；**6/6 在特賣第一份紀錄就改成現在買**，錯過 0 |
| 現在買 | 9 款紀錄當時的價格＝特賣最低價（開賣前就以相同折扣在打） |
| 季節機率 Brier | 特賣最深折扣 **0.040**；回測的定義 **0.125**（差在 12 款開賣前已在打折的遊戲，見 D1） |
| 組合包 | E33 x Dispatch 推算 NT$1,063 → 實際 NT$1,062；DAVE THE DIVER x MiSide NT$366 → NT$350；兩個都同時到價 |
| 重算（US5） | 12 秒；重算 0.0399、正式紀錄 0.0400、基準模型 0.0957；1 款分組不同（柏德之門3） |
| 非季節 | 0 個單位到期（最早 10/30） |
| **發現的問題** | ① spec 對「到價」的假設前後矛盾（D1）；② 交叉檢查要比對追蹤的購買選項，不是 App 的預設價格（D2）；③ **每日更新的 bug**：劍星的秋特折扣被誤隔離，價格歷史以為整場 0%（D3） |

## 使用者的決定（D1–D3）

2026-10-13 使用者全部選 **A**（下表的「建議」欄即為採用的做法）。

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| D1 | 季節機率用哪一種「到價」計分？12/65 款在開賣前 22.5 小時就以特賣的折扣在打，回測的定義（之後**首次進入** ≥ d）把它們記為沒到價，Brier 0.125；用「特賣期間的最深折扣」是 0.040 | **A** 主要用特賣最深折扣，並列回測定義與差異的遊戲／**B** 只用回測定義（能直接比回測數字）／**C** 只用特賣最深折扣 | **A**：模型的證據本身就是每場的最深折扣，也是你實際買得到的價格；並列回測定義才看得到差異從哪裡來。spec FR-004 與 Assumptions「到價的判定」依此修正 |
| D2 | 價格歷史和那個購買選項的每日價格紀錄不一致時？（劍星：歷史 0%、每日紀錄 -33%） | **A** 每日紀錄較深時取較深者並標示「補正」，照常計分／**B** 標示不一致、不計分／**C** 只用價格歷史並標示 | **A**：每日紀錄是商店當下的直接讀數；B 讓已知的資料錯誤變成樣本流失；C 把已知錯誤的值當事實（憲章 I）。歷史比每日紀錄深是正常的（一天只讀一次），只註記 |
| D3 | 劍星的折扣為什麼不見了：每日更新把**批次開始時間**當作取得時間，ITAD 在批次開始後幾秒才記下的事件被當成「發生在取得之後」而隔離。全資料庫 12 筆，願望清單只有劍星（10/1 的 2 筆）；不修的話它之後的預測都少一場 -33% | **A** 013 只標示與補正；另開小修補（013 之後、014 之前），先提案再做／**B** 在 013 一起修／**C** 只記在 HANDOFF | **A**：013 是唯讀的報告；修補會動到每日更新與既有資料，應該單獨驗證 |

已依 D1、D2 更正 spec：US2、FR-004、FR-005（交叉檢查對象是追蹤的購買選項）、Edge Cases、Key Entities、SC-003 與 Assumptions「到價的判定」；
Clarifications 記一筆「Session 2026-10-13（plan 時更正）」。D3 的修補不在本 feature。

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14），uv。

**Primary Dependencies**：不新增套件。

**Storage**：不改 schema（v6）；只讀資料庫、`data/forecasts/`、`data/steam_sales.toml`；只寫結果檔 `data/reviews/*.json`。

**Testing**：pytest，核心的判定與計分測試先行（憲章「開發流程」）；小型測試資料庫＋手寫的測試紀錄（3–5 款，結果事先手算），不連網。
重算的洩漏測試沿用 `tests/contract/test_no_future_leak.py` 的做法。真實資料的驗證用主資料夾的檔案（唯讀）。

**Target Platform**：Windows 11 本機；每日背景更新 02:30（主資料夾 master，不受影響）。

**Project Type**：單一 Python CLI 專案。

**Performance Goals**：不含重算 ≤ 60 秒、含重算 ≤ 300 秒（SC-008；原型：實際價格 < 5 秒、重算 12 秒）。

**Constraints**：

- 唯讀：不取寫入鎖、不連網；失敗時不寫結果檔。
- 實際價格只讀紀錄當時追蹤的商品；未知不是零（`no-actual` 不進分母）。
- 同一份資料、同一組參數結果逐位元組相同（`run` 區塊除外）。
- 不改模型、規則、報告、擴充功能（FR-020）。

**Scale/Scope**：一場特賣、68 款、1,235 個季節計分單位、2 個組合包建議、約 3,900 個非季節單位（68 × 3 × 19，目前都未到期）。

## Constitution Check

依憲章 **1.2.1**。

| 原則 | 檢查 | 結果 |
|---|---|---|
| I 未知不是零 | 價格序列沒涵蓋、沒有序列、紀錄沒有預測的遊戲各有狀態與原因，不進分母；非季節未到期的單位列為 `pending`；劍星依每日紀錄補正而不是當作 0%（D2） | ✅ |
| II 證據可追溯 | 結果寫出紀錄檔名、`as_of`、版本、每款讀的商品與 `known_until`、補正的來源；回測數字附出處章節 | ✅ |
| III 逐項隔離失敗 | 單款的序列讀取或計分例外只讓那一款變成 `no-actual`；整體失敗時不寫結果檔 | ✅ |
| IV 可驗證（不可協商） | 這個 feature 就是原則 IV「保存預測紀錄，供日後與實際價格對照」的第一次執行；不改模型（不需要回測比較）；重算的防洩漏沿用回測規則並加測試；文件不把事後對照寫成新的準確率 | ✅ |
| V 規則單一正本 | 不新增或改變預測、決策規則；計分規則寫在契約與 research，並引用模型定義文件的回測數字 | ✅ |
| VI 簡單優先 | 沒有新參數（3 天、2,000 次重抽樣沿用既有經驗與框架設定）；不新增套件；不在報告顯示（YAGNI） | ✅ |
| VII 核心與呈現分離 | 結果是版本化的 JSON 契約；文字摘要與 `--doc` 只讀它 | ✅ |
| VIII 資料來源條款 | 不連網 | ✅ |
| IX 本機與安全 | 結果存在本機 `data/`；沒有金鑰；遊戲名稱只當資料 | ✅ |

**Post-design re-check**：data-model 與 contracts 沒有新增違反。D3 的修補不在本 feature（若選 B，要重做這張表的 III 與每日更新相關的檢查）。

## Project Structure

### Documentation (this feature)

```text
specs/013-post-sale-comparison/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0（原型）、R1–R9
├── data-model.md
├── quickstart.md
├── contracts/
│   └── review.md
├── checklists/requirements.md
├── prototype/           # common、p1_actual、p2_flip、p3_recompute、p4_bundles、p5_mismatch；out/ 不進版控
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
src/steamsage/
├── review/__init__.py           # 新
├── review/target.py             # 選特賣與紀錄（開賣前最後一份正式紀錄、特賣期間的紀錄、缺漏的日期）
├── review/actual.py             # 每款的實際價格：追蹤的商品、特賣最深折扣與最低價、兩種到價、每日紀錄的交叉檢查與補正
├── review/score.py              # 季節、決策、提早到價、組合包、非季節的計分與彙總；重抽樣區間
├── review/recompute.py          # US5：同一時點的現行模型決策與基準模型預測
├── review/contract.py           # steamsage.review/1、文字摘要、--doc 草稿
├── review/run.py                # 整個對照的流程（實作後依使用者同意從 commands.py 搬出；指令只剩參數、寫檔、輸出）
├── commands.py                  # review 指令
└── cli.py                       # review 的參數

src/steamsage/store/query.py     # 加一個唯讀查詢 option_steps（某個購買選項在一段期間的每日紀錄）；既有方法不改

tests/
├── review_builders.py           # 小型資料庫＋測試紀錄的建構函式（沿用 tests/*_builders.py 的慣例；tasks 時由 fixtures/review/ 改過來）
├── unit/test_review_actual.py   # 追蹤的商品、最深折扣、最低價、兩種到價、補正、5 種無法對照
├── unit/test_review_score.py    # 季節、決策、提早到價（改口／錯過／無法判斷）、組合包、非季節（到期與未到期）、區間的重現性
├── unit/test_review_target.py   # 選紀錄：非正式、讀不到、特賣未結束、不到 3 天、--record
├── contract/test_review_leak.py # 重算的洩漏測試＋反向測試
└── contract/test_cli_review.py  # 指令、結束代碼、--json、--doc、唯讀（雜湊不變）、逐位元組相同
```

**Structure Decision**：新的 `review/` 套件，因為它同時讀預測、決策、非季節與組合包的結果，放進其中任何一個都會讓那個套件依賴其他三個。
它只呼叫既有的函式（`build_series`、`sale_outcomes`、`first_crossings`、`nonseasonal.events`、`run_decisions`、`run_forecast`、`records.load_record`），不修改它們。
唯一新增在 review/ 以外的是 `PriceStore.option_steps`（tasks 時補上：SQL 留在 store/query.py，和其他查詢一致）。

## 實作順序與 checkpoint

（tasks 時調整：最小的指令提前，MVP 直接用指令跑；組合包移到 MVP 之後。細節見 tasks.md。）

1. 測試資料（小型資料庫＋測試紀錄）、`option_steps`、`target.py`、`actual.py`（測試先行）→ commit。
2. `score.py`（季節、決策、提早到價）＋最小的 `contract.py` 與 `review` 指令；無法對照與 D2 補正 → commit；**MVP：在真實資料上跑一次，給使用者看秋特的結果**。
3. `--doc` 與可重現 → commit。
4. 組合包、非季節（到期判斷、`--today`）、`recompute.py`（含洩漏測試）→ 各自 commit。
5. 驗證（SC-001–SC-009，和 master 在同一份資料上比對回測）、`comparisons.md`「事後對照」一節、HANDOFF §3、README → commit，詢問是否合併。

## Complexity Tracking

沒有違反憲章的地方需要說明。

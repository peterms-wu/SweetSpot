# Quickstart: 驗收情境（feature 008）

在 repo 根目錄執行。Bash 印中文前先 `export PYTHONIOENCODING=utf-8`。
**每個回測指令都明確加 `--cutoff 2026-09-25`**（HANDOFF §7 的教訓）。耗時是估計，實測寫進 validation.md。

## A. 測試（功能，不代表準確）

```bash
uv run pytest
```

- 預期：全部通過，數量比 939 多。
- 新測試涵蓋：
  - contracts/model-api.md 的 8 項保證
  - 登錄表的版本與 `名稱@版本`
  - 新指標
  - FR-004 排除
  - `--target-groups`
  - 洩漏測試（含偷看的變體）

## B. 1.1.0 退化成 1.0.0

```bash
uv run steamsage backtest --model seasonal-record@1.1.0 --param low_base=population --param shrink=0 \
  --split tuning --cutoff 2026-09-25 --json
```

- 預期：台灣區 0.0630、美國區 0.0658，和 1.0.0 的調參組逐位相同（research R0.4）。
- 新指標 `finished_calibration` 的 Brier 為 0.0594。

## C. 調參組網格（spec FR-008；約 8–10 分鐘）

```bash
uv run steamsage grid --model seasonal-record@1.1.0 --split tuning --cutoff 2026-09-25 \
  --grid low_base=new,new-split --grid shrink=0,0.25,0.5,1 --record
```

- 預期：和 research R0.3、R0.4 一致，差距在 ±0.001 內。
  - `shrink=1` 或以上可能被 FR-004 排除（2 場組）。
  - 選中的大概是 `new-split`、`shrink` 0.25 或 0.5。
- **checkpoint**：把網格結果交給使用者看，再進入 D。

## D. 驗證組比較第 1 次（spec FR-009、FR-010）

```bash
uv run steamsage backtest --split validation --cutoff 2026-09-25                       # 現行 1.0.0
uv run steamsage backtest --model seasonal-record@1.1.0 --param low_base=<選定> --param shrink=<選定> \
  --split validation --cutoff 2026-09-25
uv run steamsage compare <現行.json> <候選.json> --attempt 1 --target-groups 0,1 --record
```

- 比較紀錄要有：兩區差距與區間、0 場與 1 場兩組的 Brier、只計已結束的「預測平均 − 實際比例」，以及判定。
- 判定屬於會影響換版的決定：**停下來等使用者確認**。

## E. 規則回測並列與願望清單（spec FR-012、FR-013）

```bash
uv run steamsage backtest-rule --split validation --cutoff 2026-09-25
uv run steamsage backtest-rule --model seasonal-record@1.1.0 --param ... --split validation --cutoff 2026-09-25
uv run steamsage compare-rule <1.0.0.json> <1.1.0.json> --record
```

- 並列到價率、現在買的後續、照建議買的淨效益（評估成本 0–80 與 20）。
- 列出「低信心 → 現在買」的決策數（research R7）。
- 願望清單差異。原型的預期：
  - 分組不變。
  - 2 款低信心遊戲的甜蜜價從 -75% 變成 -30%。
  - Breath of Fire IV 從 100% 變成 91%。
- **checkpoint**：使用者看過後決定換不換。

## F. 換版（只有 D 判定優於而且使用者同意時）

```bash
uv run steamsage backtest-rule --cutoff 2026-09-25        # 完整資料集，新的 CURRENT_MODEL
uv run pytest                                             # 回測常數與模型定義一致
uv run steamsage report --open
```

- 報告頁首與紀錄的模型是 1.1.0。
- 低信心組的到價率來自新的規則回測。
- 變動註明模型版本改變。
- 用 `specs/006-version-tracking/prototype/check_390.py` 檢查報告，並用 `SendUserFile` 把報告交給使用者。

## G. 原因措辭的抽查（contracts/model-api.md）

- 願望清單：
  - 2 款低信心遊戲：新遊戲依據與樣本數
  - Breath of Fire IV：收縮的一行
- 回測時點：挑 1 款預購遊戲，確認用的是預購序列的措辭。

## H. 文件更正（spec FR-017）

```bash
uv run --with numpy python specs/008-new-game-forecast/prototype/p5_compare.py
```

- 預期：原始版本那一列是「96.6% → 89.8%（8,688）」，和更正後的 005 research R0.2、模型定義 3.0.0 已知限制 1 一致。
- 比較文件有一筆附加的更正紀錄。

## I. 效能（SC-008）

- 完整資料集兩區回測（1.1.0）< 10 分鐘，預估約 2 分鐘。
- `report` < 30 秒，預估約 5.5 秒。

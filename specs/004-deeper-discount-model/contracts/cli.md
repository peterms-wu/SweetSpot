# Contract: CLI 新增與變更（feature 004）

延伸 [002](../../002-backtest-baseline/contracts/cli.md) 與 [003](../../003-sweet-price-report/contracts/cli.md) 的 CLI 契約。共用規則不變：

- 進度寫到 stderr，摘要寫到 stdout；`--json` 改為輸出 JSON 摘要。
- 所有新指令與新參數都是唯讀：以唯讀方式開資料庫、不取寫入鎖。結果只寫到 `data/backtests/` 與（`--record` 時）`docs/model/comparisons.md`。

## `steamsage backtest`：新增 `--split`

| 參數 | 預設 | 說明 |
|---|---|---|
| `--split` | `all` | `all`、`tuning`、`validation`。計分的遊戲只取該組，整體比例仍用全部合格遊戲（research R4） |

- 摘要與結果檔多了 `split`。
- `--split` 和 `--apps-limit` 同時使用時，先切分再取前 N 款。

## `steamsage grid`（新）

```text
steamsage grid --model 名稱 --grid k=v1,v2 [--grid …] [--param k=v …] [--split tuning] [--region all] [--record]
```

（2026-10-22 稽核補記：程式從 004 起還接受 `--cutoff 日期`（資料截止日，預設為最新的資料已知時間；008 contracts/cli.md 的
`grid` 範例有用到）與 `--record-to 檔案`（附加到指定檔案，隱含 `--record`；同 002 contracts/cli.md 的 `compare`）。
`--model` 可以加 `@版本`，沒有版本時同 008 contracts/cli.md 的「模型版本」。）

- 在指定的切分（預設 `tuning`）上，跑現行模型與網格中的每個設定，選參數規則見 research R7。
- `--param` 是網格以外的固定參數。
- 設定之間只差 `tw_only_params` 時，美國區只跑一次。
- 進度：`網格 n/N：k=v, …` 以及 `回測 … 分析時點 n/N`。
- 摘要與 stdout：每個設定一行（兩區 Brier、差距、95% 區間、是否因美國區顯著變差而排除），最後一行是選中的設定。
  （2026-10-22 稽核補記：已被 008 T019–T020 擴充：排除條件另外有 008 FR-003（模型提供，`seasonal-record` 1.1.0 的
  `shrink = 0`，`fr-003`，仍列出作為對照）與 008 FR-004（`2`／`3-5`／`6+` 任一場數組顯著變差，`own-sales-worse:<組名>`）；
  全部被排除時結束代碼 2。見 008 contracts/cli.md 的 `grid`。）
- 加上 `--record` 時，附加一筆「調參組網格」紀錄到比較文件。
- **拒絕**：`--split validation` 時不選參數，結束代碼 1，並說明「網格只能在調參組或全部資料上執行（FR-011）」。
- **結束代碼**：0 完成並選出設定；2 全部設定都被排除，或有模型錯誤；1 失敗。

## `steamsage compare`：新增 `--attempt`、`--change`

| 參數 | 說明 |
|---|---|
| `--attempt N` | 驗證組比較的次數，1–3。兩份結果都是 `validation` 而且有 `--record` 時必填 |
| `--change "說明"` | 這次比較改了什麼、為什麼改。第 2、3 次必填 |

**規則**：

- 兩份結果的 `split` 必須相同。它們的資料集識別本來就不同，會照 002 的規則拒絕。
- 以下情況拒絕，結束代碼 1：
  - `N > 3`
  - 比較文件中同一候選模型名稱已有第 N 次驗證組紀錄
    （2026-10-22 稽核補記：已被 008 T021–T022 取代：次數依候選的「名稱＋版本」計算，例如 `seasonal-record` 1.1.0
    從第 1 次算起，不和 1.0.0 混算。見 008 contracts/cli.md 的 `compare`。）
  - 第 2、3 次缺少 `--change`
- 紀錄新增一列「比本身過去更深」分組的兩個 Brier（有這個欄位時）。

## `steamsage backtest-rule`：新增 `--model`、`--param`、`--rule`、`--split`

| 參數 | 預設 | 說明 |
|---|---|---|
| `--model`、`--param` | 現行模型 | 同 `backtest` |
| `--rule` | 現行規則 | `1.0.0` 或 `2.0.0`（2026-10-22 稽核補記：已被 005 T014 與 006 T042 擴充：現在可選 `1.0.0`、`2.0.0`、`2.1.0`、`3.0.0`、`3.1.0`，預設是現行的 2.1.0；3.x 另有 `--wait-cost`，見 005 contracts/cli.md） |
| `--split` | `all` | 同 `backtest` |

摘要新增 `rule`、`split`、`sweet_timing`、`follow_advice`（全體）、`hindsight`。

## `steamsage compare-rule`（新）

```text
steamsage compare-rule 現行.json 候選.json [--record] [--decision "文字"] [--no-wishlist]
```

- 讀兩份規則回測結果。
- **拒絕**（結束代碼 1，說明哪裡不同）：資料集識別、截止時間或使用者偏好不同。
  （2026-10-22 稽核補記：已被 005 T025–T026 取代：偏好只比較兩份結果都有的鍵，例如 2.x 的容許差距對 3.x 的
  `wait_cost_twd` 不會擋；見 005 contracts/cli.md 的 `compare-rule`「一致性」。005 也加了多個候選、`--attempt`、`--change`。）
- **列出**：
  - research R6 的所有指標，兩邊並列並附差距。
  - 願望清單差異：依兩份結果記錄的模型、參數與規則，對現在的願望清單各做一次決策，列出：
    - 各組款數
    - 改變分組的遊戲（名稱、分組、甜蜜價與甜蜜時點的前後值）
    - 甜蜜價的平均變化
  - `--no-wishlist` 跳過願望清單差異，例如沒有資料庫的測試環境。
- **`--record`**：附加一筆「規則回測並列」紀錄到比較文件。
- **`--decision`**：在同一筆紀錄後附上使用者的決定，隱含 `--record`。
- **結束代碼**：0 完成；1 失敗或拒絕。

## `steamsage forecast`、`report`：不變

- `forecast` 已有 `--model`、`--param`，可以用舊模型檢查（spec FR-026）。
- `report` 一律使用現行模型與現行規則。（2026-10-22 稽核補記：已被 005 T013–T014 擴充：`report --rule 版本` 用非現行規則產生預覽，
  不寫紀錄、不和前一天比較，輸出 `data/reports/preview-<版本>.html`；見 005 contracts/cli.md 的 `report`。）換版後頁首的模型與規則版本自動改變；變動標示的「版本改變」沿用 003 FR-021。

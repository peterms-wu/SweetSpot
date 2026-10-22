# Quickstart：驗收步驟

在 Bash 中先設 `PYTHONIOENCODING=utf-8`。耗時以 [research R7](research.md) 為估計，實測寫入 `validation.md`。

## 0. 測試

```bash
uv run pytest
```

- 全部通過，而且比 feature 前（860）多。
- 新增的測試涵蓋 research R8：定義、模型、洩漏、計分、決策不變、輸出與報告、文件一致。

## 1. 定義與原型一致（spec SC-001）

```bash
uv run python specs/007-non-seasonal-discounts/prototype/t018_parity.py
```

正式程式與 `prototype/nslib.py` 的非季節到價與非季節促銷逐款相同。和 P0 的差異只來自 P0 沒有 1 天容許（tasks T018）。

## 2. 調參組網格（spec FR-009）

```bash
uv run steamsage ns-grid --split tuning --grid smoothing=1,2,5 --grid history=TW,TW+US --grid clock=true,false --record
```

- 12 組，10 分鐘內完成。
- 比較文件多一筆網格紀錄。
- 選定的參數預期接近 research R0.2 的 M3：`smoothing=2, history=TW+US, clock=true`，Brier 約 0.127。
- 和原型差距超過 0.005 時，先逐項查明原因再往下走（006 的教訓）。
- **停下來**：把網格結果給使用者看。

## 3. 驗證組比較（spec FR-010）：只做一次

```bash
uv run steamsage ns-backtest --split validation --param smoothing=… --param history=… --param clock=…
uv run steamsage ns-compare data/backtests/<結果檔> --record --attempt 1
```

- 判定「優於」的條件：全體 Brier 比整體比例低，95% 區間不含 0。
- **停下來**：把判定、依 h 的分數、校準表、更早到價的命中率給使用者看，由使用者決定是否採用。
  決定附加到比較文件。

## 4. 採用後（使用者同意時）

```bash
uv run steamsage ns-backtest --split all --no-earlier
uv run steamsage ns-backtest --split all
```

- 第一個（不含「更早到價」）2 分鐘內完成（spec SC-008）。第二個取得「更早到價」的命中率，耗時另外記錄。
- 數字寫進模型定義的非季節一節與 `NS_BACKTESTS`，測試比對兩者一致（spec SC-007）。

## 5. 決策不變（spec SC-005）

- 在同一份資料上，以 feature 前後的程式各產生一次願望清單的決策（不寫正式紀錄）。
  逐款比對 group、甜蜜價、甜蜜時點與等待對照表，必須完全相同。
- 規則 2.1.0 的規則回測，feature 前後在同一份資料上重跑，用 `t043_rule_equivalence.py` 比對，逐案相同。

## 6. 真實報告（MVP，spec SC-006）

```bash
uv run steamsage report --open
uv run --with playwright python specs/006-version-tracking/prototype/check_390.py data/reports/latest.html
```

- 每款可決策的遊戲都有「季節特賣以外」一段。
- 抽查以下特殊情況的措辭：沒有促銷、只有 1 次、用美國區補、歷史太短、正在促銷、停止更新（Dying Light 的舊商品若仍出現）、`model-error`。
- 採用後，每一句「可能提早」都有機率、期間與命中率。
  秋特（10/1）前夕的「即將到價」應該都沒有這句話（沒有判斷期間）。
- 390px 沒有水平捲動。
- **停下來**：把報告用 `SendUserFile` 傳給使用者看。

## 7. 文件（spec FR-017～FR-019）

- 模型定義：
  - 新的非季節一節
  - 評分框架設定的新項目
  - `seasonal-record` 已知限制 1 的兩種校準（完整資料集重算）
  - 決策規則已知限制 4
- 比較文件只有附加，沒有修改舊紀錄：`git diff docs/model/comparisons.md` 只出現新增的行。

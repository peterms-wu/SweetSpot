# Quickstart: 驗收同時含多款願望清單遊戲的組合包（feature 010）

前提：分支 `010-wishlist-bundles`；`ITAD_API_KEY`、`STEAM_WEB_API_KEY` 已設定；在 Bash 印中文前設 `PYTHONIOENCODING=utf-8`。
每個回測類指令都明確給 `--cutoff 2026-09-25`。

## 1. 測試

```bash
uv run pytest
```

期望：全部通過（009 結束時 1113 passed，加上本 feature 的新測試）。

## 2. 遷移與每日更新

```bash
uv run steamsage update
```

期望：
- 第一次執行時資料庫從 v4 升到 v5，`data/steamsage.db.bak-v4` 存在；遷移 < 5 秒。
- 摘要 `purchase_options.bundles`：`wishlist_bundles` 6、`pure` 2、`mixed` 4（依當天的願望清單與購買選項，數字可能不同）；`check_mismatch` 為空，或每個都有提醒。
- 購買選項步驟比 009 平常多 ≤ 2 秒（SC-007 上限 5 秒）；實測寫進 validation.md。

## 3. 報告

```bash
uv run steamsage report --open
```

期望：
- 「組合包」一節在群組之前：E33 x Dispatch、DAVE x MiSide 有比較、推算與建議；4 個混合組合包有「多付 NT$X，多得 N 款」。
- 光與影：33號遠征隊、Dispatch、DAVE THE DIVER、MiSide、OPUS 兩款、活俠傳、範例遊戲乙、範例遊戲丙 的展開內容有指引行，點了跳到組合包卡片。
- 數字和決策輸出（`data/forecasts/` 最新一份的 `bundles`）完全相同。
- 390 px 截圖：`uv run --with playwright python specs/006-version-tracking/prototype/check_390.py data/reports/latest.html`，組合包卡片的每一欄都看得到（SC-008）。

## 4. 決策不變（SC-002）

在同一份資料上比對本分支與 master（009 `prototype/t029_same_data.py` 的做法：master 讀刪掉 v5 新資料的副本）：
每款遊戲的分組、甜蜜價、甜蜜時點、等待對照表與原因 100% 相同，只有新增的 `bundles`、`bundle_rule` 欄位不同。

## 5. 公式交叉檢查（FR-016，validation）

```bash
uv run python specs/010-wishlist-bundles/prototype/s4_itad.py
uv run python specs/010-wishlist-bundles/prototype/s6_ratio.py
```

期望：台灣區每個組合包公式成立的天數 ≥ 99%；美國區 46393、5170 的不成立期間寫出原因（ITAD 停止更新、內容改變）。

## 6. 同時到價的檢查（FR-017，只用調參組）

```bash
uv run python specs/010-wishlist-bundles/prototype/p1_pairs.py
uv run python specs/010-wishlist-bundles/prototype/p2_cheapest.py
```

期望：資料集 `858b3147…`（調參組，截止 2026-09-25）；數字和模型定義「組合包建議」一節相同；程式常數 `BUNDLE_BACKTESTS` 由測試檢查一致。

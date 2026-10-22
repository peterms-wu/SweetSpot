# Contract: 決策輸出的組合包欄位（feature 010）

延伸 [005 的決策輸出 `steamsage.decision/2`](../../005-waiting-cost/contracts/decision-output-v2.md) 與
[009 的購買選項欄位](../../009-purchase-options/contracts/outputs-options.md)。

**不升版**：只新增選用欄位。舊紀錄沒有這些欄位，讀取與變動比較照常；變動比較不看組合包（spec 不包含）。

## 批次的新欄位

| 欄位 | 說明 |
|---|---|
| `bundle_rule` | `{"name": "bundle-advice", "version": "1.0.0"}` |
| `bundles` | 同時含 2 款以上願望清單遊戲的組合包清單，純粹在前、再依組合包編號；沒有時為空陣列；沒有購買選項紀錄或整個步驟出錯時為 null |

### `bundles[]`

| 欄位 | 說明 |
|---|---|
| `id`、`name`、`checked_at` | 組合包與那次購買選項紀錄的時間 |
| `grade` | `pure`、`mixed` |
| `discount_pct` | 組合包折扣（例如 10）；v5 以前的紀錄為 null |
| `price_cents`、`price_twd` | 組合包現價 |
| `contents` | `[{app_id, name, role, price_cents, price_twd, specified}]`，`role` 為 `wishlist`、`wishlist-dlc`、`other-game`、`other` |
| `check` | `{status: ok｜mismatch｜unknown, expected_cents, expected_twd, text}`；`text` 在 mismatch／unknown 時說明兩個數字與可能原因 |
| `separate_cents`、`wishlist_cents` | 全部分開買、只買願望清單遊戲的現價（未知為 null） |
| `extra_cents`、`extra_games`、`extra_dlc` | 混合：多付的金額、多得的遊戲數、多得的 DLC 等其他內容數；純粹為 null |
| `plan` | 純粹：`{cents, twd, latest_point}`，`latest_point` 是最晚的甜蜜時點（`{index, label, start, end, status}`），全部「現在買」時為 null；混合為 null |
| `advice` | 純粹：見下表；混合為 null |
| `owned_note` | 固定說明「價格以全部內容都未擁有計算；已擁有其中的內容時，Steam 的價格會更低」 |

### `advice`

| 欄位 | 說明 |
|---|---|
| `status` | `ok`、`none` |
| `reason_code`、`reason_text` | `status = none` 時：`no-forecast`、`specified`、`check-mismatch`、`check-unknown`、`stale-price`、`no-sale`、`error`（這個組合包計算出錯）與核心寫好的原因 |
| `kind` | `now`、`next-sale`、`separately`（`status = ok` 時） |
| `sale` | 下一場季節特賣 `{index, label, start, end, status}` |
| `levels` | `[{app_id, pct, cents, twd, probability}]`：下一場推算用的折扣 |
| `estimate_cents`、`estimate_twd`、`joint_probability` | 下一場的組合包推算價與同時到價機率（`status = ok` 時都有） |
| `saving_cents`、`saving_twd` | 比分開買的計畫便宜的金額；`separately` 時為 null |
| `timing` | `now`、`earlier`、`same`；`separately` 時為 null |
| `hit_rate` | `{bin: [0.5, 0.6], observed: 0.685, units: 16338, source: "model-definition"}`：`joint_probability` 所在區間的回測實際比例；`kind = now` 時為 null |
| `confidence` | `normal`、`low` |
| `text` | 建議句，例如「兩款都要買的話，2026 秋特買組合包：約 NT$1,063（兩款同時到價 73%；過去這類說法 83% 成真），比各自在甜蜜時點買便宜 NT$69，而且早一場」（2026-10-22 稽核補記：實際結尾是「，而且早 1 場」：`timing = earlier` 時寫「而且早 N 場」，N＝各款甜蜜時點中最晚那場與這場相差的場數，用數字；golden 測試鎖住這個寫法。`decision/bundles.py`） |

## 決策的新欄位

| 欄位 | 說明 |
|---|---|
| `bundles` | 這款遊戲所在的 `bundles[].id` 清單（spec FR-014 的指引）；不在任何組合包中為空陣列；批次的 `bundles` 為 null 時也為 null |

## 例子（純粹組合包，2026-09-27 的資料；數字來自 research R0.3）

```json
{
  "id": 74895, "name": "Clair Obscur: Expedition 33 x Dispatch", "grade": "pure", "discount_pct": 10,
  "price_cents": 115000, "price_twd": 1150,
  "contents": [{"app_id": 1903340, "name": "光與影：33號遠征隊", "role": "wishlist", "price_cents": 79000, "specified": false},
               {"app_id": 2592160, "name": "Dispatch 超英派遣中心", "role": "wishlist", "price_cents": 48800, "specified": false}],
  "check": {"status": "ok", "expected_cents": 115020, "expected_twd": 1150, "text": null},
  "separate_cents": 127800, "wishlist_cents": 127800, "extra_cents": null,
  "plan": {"cents": 113160, "twd": 1132, "latest_point": {"index": 2, "label": "2026 冬特", "…": "…"}},
  "advice": {"status": "ok", "kind": "next-sale", "sale": {"index": 1, "label": "2026 秋特", "…": "…"},
             "levels": [{"app_id": 1903340, "pct": 20, "cents": 79040, "probability": 0.826},
                        {"app_id": 2592160, "pct": 20, "cents": 39040, "probability": 0.881}],
             "estimate_cents": 106272, "estimate_twd": 1063, "joint_probability": 0.728,
             "saving_cents": 6888, "saving_twd": 69, "timing": "earlier",
             "hit_rate": {"bin": [0.7, 0.8], "observed": 0.830, "units": 13902, "source": "model-definition"},
             "confidence": "normal", "text": "…"}
}
```

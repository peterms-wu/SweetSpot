# Contract: 預測與決策輸出的購買選項欄位（feature 009）

延伸 [006 的版本欄位](../../006-version-tracking/contracts/outputs-version.md)、
[002 的預測輸出 `steamsage.forecast/1`](../../002-backtest-baseline/contracts/forecast-output.md)
與 [005 的決策輸出 `steamsage.decision/2`](../../005-waiting-cost/contracts/decision-output-v2.md)。

**不升版**：只新增選用欄位（沿用 003、006 的契約規則）。舊紀錄沒有這些欄位，讀取與變動比較照常。

## `version` 的新欄位（預測與決策相同）

| 欄位 | 說明 |
|---|---|
| `source` | `steam-default`（沒有指定，006 的行為）、`user`（使用者指定生效）、`user-fallback`（有指定但不能用，退回預設） |
| `option` | 追蹤的購買選項 `{kind: "sub"｜"bundle", id, name}`；006 的 `package_id`、`package_name` 保留（組合包時 `package_id` 為 null） |
| `fallback` | `source = user-fallback` 時：`{code, detail, text, requested: {kind, id, name}}`；code 見下表，`text` 是核心寫好的原因（實作時新增，報告只顯示）。其他為 null |
| `aux_pending` | 指定生效的版本還沒抓過美國區歷史（plan D2）：原因與版本行寫出「美國區歷史下一次更新才會取得」。其他為 false |

`basis` 新增 `user`：價格歷史來自指定版本的 ITAD 商品（`itad_id`）。其他欄位（`history_start`、`known_until`、`tracking`、`change`…）
的意義不變，都是**實際使用的那份歷史**的值。

| `fallback.code` | 原因（決策原因與報告顯示的文字，`{requested}` 是指定的名稱或 `sub/N`） |
|---|---|
| `not-offered` | 指定的版本（{requested}）目前不在購買選項中，改用 Steam 預設版本 |
| `not-edition` | 指定的購買選項（{requested}）不是這款遊戲的版本（{detail}），改用 Steam 預設版本 |
| `not-in-itad` | 指定的版本（{requested}）在 ITAD 沒有對應的商品，沒有價格歷史，改用 Steam 預設版本 |
| `rejected` | 指定的版本（{requested}）在 ITAD 的商品核對未通過（{detail}），改用 Steam 預設版本 |
| `no-record` | 這個時點還沒有購買選項紀錄，使用 Steam 預設版本 |

例子（指定 Cyberpunk 2077 終極版）：

```json
"version": {
  "basis": "user", "source": "user",
  "option": {"kind": "bundle", "id": 32470, "name": "《電馭叛客 2077：終極版》"},
  "package_id": null, "package_name": "《電馭叛客 2077：終極版》",
  "itad_id": "018d937f-79a6-7172-bf81-41ce50854095", "own_itad_id": "018d937e-…",
  "history_start": "2024-12-11T…Z", "known_until": "2026-09-27T…Z", "tracking": "ok",
  "fallback": null, "change": null, "…": "…"
}
```

## 決策的新欄位 `editions`

這款遊戲**除了追蹤的那一個以外**的版本（`role = edition` 的購買選項，含驗證未通過的；使用者指定時包含 Steam 預設版本），
依 Steam 商店的順序。沒有其他版本時為空陣列；資料庫沒有購買選項紀錄時為 null。

| 欄位 | 說明 |
|---|---|
| `kind`、`id`、`name` | 購買選項 |
| `is_default` | 是否為 Steam 預設購買選項 |
| `price_cents`、`regular_cents`、`cut_pct` | 台灣區現價與原價（最新一次購買選項紀錄） |
| `checked_at` | 那次紀錄的時間 |
| `verification`、`reason_code`、`reason_detail`、`reason_text` | 驗證結果；未通過時附原因，`reason_text` 是核心寫好的說明（實作時新增） |
| `itad_id` | ITAD 商品（沒有時為 null） |
| `history_start` | 台灣區歷史的第一筆時間；沒有歷史為 null。Steam 預設版本（已指定時的那一列）取自預設版本的歷史（`itad-history`），其他版本取自 `itad-option-history` |
| `low_cents`、`low_at` | 台灣區歷史最低價與日期；沒有歷史為 null（不是 0，憲章 I） |
| `config_line` | 指定用的設定行，例如 `1091500 = "bundle/32470"`；驗證未通過或是 Steam 預設（未指定時）為 null |
| `unset_hint` | 只在「已指定、這一列是 Steam 預設」時為 true：報告顯示「刪掉設定檔中的這一行即可取消指定」 |

報告的「另有 N 個版本」中，N = `len(editions)`：追蹤版本以外的所有版本，已指定時包含 Steam 預設版本（spec FR-015）。

## 變動物件

`change.version`（006）新增 `cause`：

| `cause` | 條件（和前一次正式紀錄比較追蹤的購買選項 kind＋id） | 報告文字 |
|---|---|---|
| `user` | 這一份 `source = user`，前一份不是同一個選項 | 版本更換（使用者指定）：舊 → 新 |
| `unset` | 前一份 `source = user`，這一份 `steam-default` | 版本更換（取消指定）：舊 → 新 |
| `fallback` | 這一份 `source = user-fallback`，前一份是 `user` | 版本更換（指定的版本不能用）：舊 → 新，附原因 |
| `steam` | 兩份都是 `steam-default`，006 的版本更換 | 版本更換：舊 → 新（006 原樣） |

前一次紀錄沒有 `option`（本 feature 之前）時，以它的 `package_id` 視為 `sub/<id>`；只換套件、商品相同仍不算更換（006 FR-003）。

> 2026-10-22 稽核補記：`fallback` 的變動標示實際只寫「版本更換（指定的版本不能用）：舊 → 新」，不附原因；原因在同一款遊戲名稱下方的版本行（`fallback.text`）
> （`decision/changes.py`、`report/html.py` 的 `CHANGE_CAUSES`）。`user`、`unset`、`fallback` 三種的 `detected_at` 為 null，標示不帶偵測日期。

## 保證事項（contract tests，`tests/contract/test_options_contract.py`）

1. 沒有任何指定時，所有決策的 `group`、`sweet_*`、`p_min_*`、機率、原因與 006 相同（只多了 `source`、`option`、`editions`）。
2. `source = user` 時，`version.itad_id` 是指定版本的 ITAD 商品，`current.regular_cents` 等於指定選項的原價。
3. 決策的 `version` 與預測的 `version` 完全相同；`editions` 由核心產生，報告只讀（憲章 VII）。
4. 過去時點的輸出不包含 as_of 之後的購買選項紀錄。
5. `editions` 中不會出現 `role` 不是 `edition` 的購買選項（含其他遊戲、不含本體）。

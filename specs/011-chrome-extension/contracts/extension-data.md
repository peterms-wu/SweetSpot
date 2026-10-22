# Contract: `steamsage.extension/1`（擴充功能資料檔）

產生者：`steamsage.report.extension.build(data: dict, record: dict | None = None, config_path: Path | None = None) -> dict`（`data` = `decision_to_dict(batch)`；`record` = `report` 的紀錄保存結果；`config_path` = 設定檔，2026-10-14 起；正式執行才寫檔）。
讀取者：`extension/lib.js` 的 `checkData(obj)`；`format` 不是 `steamsage.extension/1` 時視為「格式不認得」，不顯示任何遊戲資料。

時間一律是 UTC `YYYY-MM-DDTHH:MM:SSZ`；金額是新台幣整數元（`*_twd`）；機率是 0–1 的小數；未知是 `null`。

```jsonc
{
  "format": "steamsage.extension/1",
  "generated_at": "2026-09-27T05:06:39Z",      // 決策字典的 generated_at
  "as_of": "2026-09-27T05:06:39Z",             // 分析時間（報告產生時間）
  "data_time": "2026-09-27T05:06:12Z",         // 現價最後確認時間的中位數；null = 全部未知（視為過舊）
  "stale_hours": 26,                           // 超過就顯示「資料超過 26 小時，請先執行更新」
  "lowest_label": "12 個月內最低",              // 報告的最低價名稱（html.lowest_label：規則有 p_min_months 為「12 個月內最低」，否則「長期最低」）
  "refresh_note": null,                        // data_refresh.note：這次報告前的更新失敗說明（和 HTML 報告的橫幅相同）
  "calendar_notices": [],                      // feature 012 起：需要使用者處理的特賣日期提醒（和 HTML 報告的橫幅相同）；舊資料檔沒有這個欄位
  "reference_notice": "參考資料集目前 340 款…",   // feature 014 起（選用）：參考資料集不到 2,000 款時的提示，文字和 HTML 報告頁首相同；到門檻時沒有這個欄位
  "config_path": "〈專案資料夾〉\\steamsage.toml",   // 2026-10-14 起：這次報告用的設定檔絕對路徑（015「版本」一節的手動步驟）；舊資料檔沒有，build() 沒給時為 null
  "record": "20260927T050639Z.json.gz",        // 正式紀錄檔名；紀錄沒保存時為 null（build(data, record=record_status)）
  "versions": {"model": "seasonal-record 1.1.0", "rule": "sweet-price 2.1.0"},
  "summary": {"now": 11, "soon": 24, "wait": 28, "low": 2, "na": 3},
  "games": [
    {
      "app_id": 1903340,
      "name": "光與影：33號遠征隊",
      "group": "now",                          // now | soon | wait | low | na
      "status_reason": null,                   // na 時的原因（和報告相同）
      "price_twd": 790, "cut_pct": 20, "stale": false,   // 核心的現價（current）；na 時可能為 null
      "sweet_twd": 790, "sweet_pct": 20,       // na 時為 null（以下同）
      "point": {"label": "2026 秋特", "status": "announced", "start": "2026-10-01T17:00:00Z", "end": "2026-10-08T17:00:00Z"},
      "probability": 0.825835,
      "p_min_twd": 692, "p_min_pct": 30,
      "tags": ["低於過去最低"],                // 報告的標籤文字（TAGS 對照後）
      "option": {"kind": "sub", "id": 685434, "name": "Clair Obscur: Expedition 33", "user": false},
      "version_text": null,                    // 報告的版本說明（_version 的純文字）；沒有時為 null
      "editions": 1,                           // 其他版本的數量
      "bundle_hints": [{"id": 74895, "text": "可和 Dispatch 超英派遣中心 一起買：組合包 −10%"}],
      "ns_reasons": ["…"],                     // 非季節預測的句子（報告「季節特賣以外」）
      "versions": [{"kind": "sub", "id": 685434, "tracked": true, "action": null, "…": "…"}],   // （2026-10-22 稽核補記；2026-10-14，015 起）追蹤中的版本在前，接著其他版本，各帶 name、price_twd、cut_pct、is_default、action（choose／reset／null）、reason、manual；沒有購買選項紀錄時為 []；欄位見 015 data-model §1
      "reasons": ["…"]                         // 全部原因，順序和報告相同
    }
  ],
  "bundles": [
    {
      "id": 74895,
      "name": "Clair Obscur: Expedition 33 x Dispatch",
      "grade_text": "只含願望清單遊戲",
      "discount_text": "組合包 −10%",
      "price_twd": 1150,
      "lines": ["現在：組合包 NT$1,150｜分開買 NT$1,278｜各自在甜蜜時點買 NT$1,132（最晚 2026 冬特）", "任何一場季節特賣（最早 2026 秋特）：約 NT$1,063，同時到價 73%"],
      "advice_text": "兩款都要買的話，2026 秋特買組合包：約 NT$1,063（…）",   // 報告卡片的粗體句；沒有時為 null
      "advice_low": false,                     // 建議為低信心（報告的「低信心」標籤）
      "check_text": null,                      // 公式檢查不符的說明；lines 的原因句已經包含它時為 null（014 T075）
      "contents": ["光與影：33號遠征隊", "Dispatch 超英派遣中心"],
      "owned_note": "價格以全部內容都未擁有計算；…"
    }
  ]
}
```

## 規則

1. `games` 的順序 = 報告的順序（分組 now → soon → wait → low → na，組內用 `_sorted`）。`summary` 的款數 = 各組的 `games` 數。
2. 所有句子（`lowest_label`、`status_reason`、`tags`、`version_text`、`bundle_hints[].text`、`ns_reasons`、`reasons`、組合包的 `*_text`、`lines`、`owned_note`）
   和同一份資料產生的 HTML 報告**字元相同**（由同一段函式產生，測試比對）。
3. 擴充功能對數字只做格式化：千分位（`NT$1,063`）、百分比（四捨五入到整數，`83%`）、台北時間（UTC+8，`2026-09-27 13:06`）。
   唯一的比較是「現在 − `data_time` > `stale_hours` 小時」。
4. 版本規則：新增選用欄位不升版；移除或改變欄位意義升為 `/2`，擴充功能同時更新。
5. 不含金鑰、Cookie、Steam 登入資訊（測試：檔案內容不含設定中的金鑰字串）。

> 2026-10-22 稽核補記（2026-10-14，015）：擴充功能有一份每款遊戲必備欄位的清單（`extension/lib.js` 的 `GAME_FIELDS`，目前只有 `versions`）。資料檔有任何一款缺其中的欄位時（更新擴充功能之後、還沒重新跑 `report` 時寫的舊檔），遊戲頁面板頂端顯示「資料檔是舊版，部分功能不會顯示：請執行 更新資料.cmd 重新產生」，「版本」一節與捷徑不出現；其他內容照常顯示（015 contracts/extension-ui.md）。

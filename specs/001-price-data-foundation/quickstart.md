# Quickstart & Validation: 價格資料基礎

驗證 feature 001 端到端可用的步驟。指令細節見 [contracts/cli.md](contracts/cli.md)，設定見 [contracts/config.md](contracts/config.md)。

## 前置條件

- Windows 11，已安裝 uv。
- 環境變數 `ITAD_API_KEY` 已設定。
- 選用：`STEAM_WEB_API_KEY`（廣泛樣本需要）。
- 願望清單為公開狀態。

```powershell
uv sync
uv run pytest -q
```

預期結果：全部通過。其中 contract tests 驗證：時點查詢不洩漏未來資料、輔助區域不含金額、volatile 屬性的時點限制，
以及 CLI 的 exit codes。

## 情境 A：首次日常更新（使用情境 1、2；SC-001、SC-002）

```powershell
uv run steamsage update --skip-reference --json > run1.json
```

預期結果：
- exit 0 或 2，15 分鐘內完成。
- `wishlist.count` 與 Steam 願望清單頁面上的遊戲數一致。
- 每款遊戲都出現在 `current_prices` 的某個分類，或出現在 `failures` 中（沒有任何遊戲處於無狀態）。
- 核對被拒絕的遊戲，在 `failures` 中有 `reason_code`。

## 情境 B：第二次更新（FR-004、FR-025、SC-001）

```powershell
uv run steamsage update --skip-reference --json > run2.json
uv run steamsage coverage --app 620
```

預期結果：
- 5 分鐘內完成。
- `history.reused` 約等於清單數。
- Portal 2 多一筆 `steam-current` 觀測。
- 覆蓋摘要中，台灣區最早時間為 2024-12-11（追蹤起點），美國區早於 2013 年。

## 情境 C：匯入舊快取（使用情境 5；SC-005）

```powershell
uv run steamsage import-legacy --json > imp1.json
uv run steamsage import-legacy --json > imp2.json
```

預期結果：
- 第一次約匯入 1,750 款的歷史，跳過的項目會列出原因。
- 第二次新增的觀測數為 0。

> 2026-10-22 稽核補記（已被 014 T013 取代）：PATH 沒有預設值了。不帶路徑、設定檔的 `[legacy] cache_path` 也是空的時，`sweetspot import-legacy --json` 以 1 結束、
> 輸出 `{"status": "not_configured"}`；要照上面驗證，得在指令後面加上前身專案的快取資料夾，或填入 `cache_path`。見 [contracts/cli.md](contracts/cli.md)「`import-legacy`」。

## 情境 D：時點查詢（使用情境 3；SC-003）

由 contract tests 涵蓋：`tests/contract/test_store_as_of.py`。另外手動抽查一款遊戲：

```powershell
uv run python -c "from steamsage.store.query import PriceStore; from datetime import datetime, UTC; s=PriceStore.open('data/steamsage.db'); print(max(o.observed_at for o in s.observations(620, datetime(2025,12,31,tzinfo=UTC))))"
```

預期結果：輸出的時間不晚於 2025-12-31。

## 情境 E：參考資料集與中斷續接（使用情境 4；SC-006）

```powershell
uv run steamsage reference --budget 300
# 執行途中按 Ctrl+C，然後：
uv run steamsage reference --budget 300 --json
```

預期結果：
- 第二次執行時，已經 `fetched` 的遊戲不會再出現在請求中。
- 摘要中的 `dataset_size` 持續增加。
- 沒有 `STEAM_WEB_API_KEY` 時，摘要標示「廣泛樣本停用」，相關樣本照常執行。

## 情境 F：特賣行事曆（使用情境 7；SC-009）

```powershell
uv run steamsage calendar --check
```

預期結果：
- 2024 年起每一季都有特賣資料。
- 尚未公告的季節特賣標示為「預估」並附上推估依據。
- 疑似漏收的特賣會被列出，若沒有就顯示「無」。
  （2026-10-22 稽核補記）沒有漏收時實際輸出是 `possible_missed_sales: []`，不是「無」。有提醒或疑似漏收時以 2 結束，都沒有時 0（`commands.py` 的 `calendar_command`）。

## 情境 G：安全與中斷（SC-007、SC-008）

- 在 `update` 執行途中強制結束程序，然後重新執行：資料庫可以正常開啟，前一次的 run 被標為 `interrupted`。
- 檢查是否有金鑰外洩：

  ```powershell
  Select-String -Path data\*, *.json -Pattern $env:ITAD_API_KEY -SimpleMatch
  ```

  預期結果：找不到任何符合的內容。

# 014 盤點腳本

2026-10-18 盤點個人資訊時用的唯讀腳本（014 research「盤點」、tasks T001、T028）。真實值（SteamID、帳號名、願望清單）都在**執行時**從本機讀或由參數傳入，腳本本身不含個人值。輸出可能列出遊戲名稱，只看不存檔。

在〈專案資料夾〉執行。第一個參數指向要掃描的資料夾；願望清單取自擴充功能資料檔（`extension/data/sweetspot-extension.json`，只有〈專案資料夾〉有），掃描 worktree 時用〔〕裡的參數指給它：

| 腳本 | 參數 | 做什麼 |
|---|---|---|
| `inventory_personal.py` | 資料夾、本人的 SteamID、帳號名 | 依類別數 SteamID、Windows 絕對路徑、email、對話連結、帳號名、私鑰標頭 |
| `where_wishlist.py` | 資料夾〔、擴充功能資料檔〕 | 目前願望清單的遊戲出現在哪些區域、哪些檔案 |
| `remaining_wishlist.py` | 資料夾〔、擴充功能資料檔〕 | 處理完完整清單檔與逐款表後，還有哪些願望清單遊戲留在公開檔案 |
| `collect_apps.py` | 資料夾、輸出 JSON〔、擴充功能資料檔〕 | 公開檔案裡出現的 app id 與所在檔案 |
| `nsfw_check.py` | `collect_apps.py` 的輸出、擴充功能資料檔 | 以公開的 GetItems 查 Steam 內容描述（會連網，約 3 個請求） |

SteamID 與帳號名可以這樣傳入，不必打字：

```
sid=$(grep -oE "profiles/[0-9]{17}" sweetspot.toml | head -1 | cut -d/ -f2)
acct=$(git remote get-url private | sed -E 's#.*github.com[:/]([^/]+)/.*#\1#')
PYTHONUTF8=1 uv run python specs/014-publish-github/inventory/inventory_personal.py <資料夾> "$sid" "$acct"
```

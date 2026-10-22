# Contract: 發佈步驟（014 FR-016～FR-018a）

```
uv run python scripts/publish.py [--to 資料夾] [--dry-run] [--message-file 檔案]
```

本機 master 是唯一正本；公開 repo 是它的發佈快照。第一次發佈與之後每次都用這個步驟。

## 1. 前提檢查（任一不成立就停止，結束代碼 1，什麼都不改）

- 在〈專案資料夾〉執行，目前分支是 master，工作目錄乾淨（發佈的是已提交的內容）。
- `gh` 已登入（取得 noreply 地址）；`uv`、`node` 可用。
  （2026-10-22，014 T058）這兩項以前到匯出之後才檢查：第一次發佈時 gh 失敗會印 traceback。現在在建立任何東西之前檢查（gh 不在、沒登入、輸出看不懂都算），不成立就說明並以 1 結束。
- （2026-10-22，014 T058）commit 訊息（草稿或 `--message-file`）不得有對話連結（FR-016；用個資掃描的「對話連結」同一個正規表示式），有就拒絕。
- `--to`：**公開資料夾**，也就是公開 repo 在本機的工作資料夾（預設〈專案資料夾〉旁的 `SweetSpot-public`）。不存在 → 第一次發佈；存在 → 必須是 git repo、工作目錄乾淨、它最新的 commit 等於最新的 `publish/*` tag 記錄的公開 commit（沒有人在公開資料夾手動改過）。
  - 2026-10-22 稽核補記（程式從 2026-10-18 起就這樣檢查）：已經有 `publish/*` tag、公開資料夾卻不存在 → 拒絕（不會悄悄變成第二次「初次公開」）；
    公開資料夾存在、卻還沒有任何 `publish/*` tag → 拒絕（第一次發佈要用新的資料夾）。要重做第一次發佈，就刪掉 `publish/001` 與公開資料夾（014 T053）。

## 2. 步驟

1. 範圍：上一個 `publish/*` tag（沒有就是「初次公開」）到 master HEAD。
2. 匯出：`git archive master` 的內容扣掉排除清單（`HANDOFF.md`），整份換掉公開資料夾（`.git/` 除外）；master 沒有的檔案刪掉。
   被 `.gitignore` 排除的檔案（上次測試步驟留下的 `.venv/`、快取）留著：不進 commit，下次測試不用重建環境。
3. 掃描：`scripts/scan_personal.py --publish <公開資料夾>`（離線＋發佈時的類別；只掃 clone 會有的檔案，scan-personal §1，014 T055）。
4. 測試：在公開資料夾 `uv sync`、`uv run pytest`、`node --test "tests/extension/*.test.js"`。e2e 需要 Chrome，不在這裡跑（在 master 跑過才發佈）。
5. 訊息：「SweetSpot 發佈 YYYY-MM-DD」（初次為「SweetSpot 初次公開（YYYY-MM-DD）」，不附標題清單）＋範圍內 master commit 的標題清單；`--message-file` 可改；顯示給使用者看。
6. Commit：第一次在公開資料夾 `git init -b main` 並加上 remote `origin`＝`https://github.com/<帳號>/SweetSpot.git`（和公開 repo 的複本相同，掃描才找得到 LICENSE 那一行的帳號名；2026-10-18 T042 試跑時發現），在**那個 repo 的本機設定**寫入 `user.name` = 帳號名、`user.email` = `<編號>+<帳號>@users.noreply.github.com`、`commit.gpgsign` = `false`（全域設定要求簽署時也不帶簽章：公開 commit 只有 noreply 地址）；作者與提交者都是它。之後每次一個新 commit。
7. 紀錄：在 master HEAD 打 annotated tag `publish/NNN`（NNN 從 001 起），訊息三行：`public <公開 commit 的 40 位雜湊>`、時間（ISO 8601，含時區）、`範圍：<上一個 tag>..<master 短雜湊>`（第一次是 `範圍：初次公開`）。第一行由 §1 的「沒有人手動改過」讀回。
8. 不推送：印出下一步
   - 第一次：`gh repo create <帳號>/SweetSpot --public`（建立空的公開 repo），再 `git -C <公開資料夾> push -u origin main`，以及 `git push private --tags`
   - 之後：`git -C <公開資料夾> push`，以及 `git push private --tags`（把發佈紀錄備份到私人 repo）
   - 公開資料夾的 `origin` 是 https 網址；`gh` 設定成用 ssh 推送的使用者，推送前先 `git -C <公開資料夾> remote set-url origin git@github.com:<帳號>/SweetSpot.git`（2026-10-22 發現：https 在沒有認證輔助程式時會停在等帳密）。

> 2026-10-22 稽核補記：初次公開訊息的日期、`commit.gpgsign`、tag 訊息的三行格式、第一次也印 `git push private --tags`，程式從 2026-10-18 起就是這樣，以前沒寫。
> 第 2 步之後就 `git add -A`（先 stage 再掃描與測試：測試讀 `git ls-files`，要和 clone 看到的一樣；記在 quickstart 情境 F）。

任何一步不通過：公開資料夾回到這次開始前的狀態（`git reset --hard`／`git clean` 只作用在公開資料夾；第一次發佈則刪掉新建的資料夾），不打 tag，結束代碼 1，列出問題。
（2026-10-22，014 T058）第 7 步打 tag 失敗（例如全域設定要求簽署 tag 卻沒有金鑰）時，第 6 步的公開 commit 也撤回；以前會留下沒有 tag 的公開 commit，之後每次發佈都被當成「有人手動改過」而拒絕。

沒有東西可發佈時不發佈、結束代碼 0（2026-10-22 稽核補記；後者是 014 T058）：
- 最新的 `publish/*` tag 就是 master HEAD：「master 沒有新的內容」。
- 有新的 commit，但匯出後公開資料夾沒有任何變動（例如只改了 `HANDOFF.md`）：不跑掃描與測試。以前會跑完再因為空的 commit 失敗、以 1 結束。

## 3. `--dry-run`

做 1–5，不 commit、不打 tag；印出會新增、修改、刪除的檔案清單與訊息草稿。公開資料夾在結束時回到原狀。

檔案清單（`--dry-run` 與正式發佈都印）是 stage 之後的 `git status --porcelain`，只列前 40 行，其餘印「…另外 N 個」（2026-10-22 稽核補記）。

## 4. 不做的事

- 不改〈專案資料夾〉的檔案、git 設定或 HEAD（只多一個 tag）；不碰私人 repo、排程工作、本機程式登錄（FR-017）。
- 不建立公開 repo、不推送（FR-017：使用者確認後自己執行印出的指令）。
- 不從公開 repo 拉回任何東西（外人的 PR 由作者搬回 master，FR-018a）。

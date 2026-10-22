@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem rem lines stay ASCII: after some Chinese rem lines cmd misreads the next line (tests/integration/test_cmd_run.py)
where uv >nul 2>nul
if errorlevel 1 (
  echo 找不到 uv，請先安裝：https://docs.astral.sh/uv/
  if not "%~1"=="--no-pause" pause
  exit /b 1
)
rem First use: with no settings file, ask for the wishlist URL first (feature 014)
if exist "sweetspot.toml" goto :ready
uv run sweetspot setup
set "scode=%errorlevel%"
if not "%scode%"=="0" (
  if "%scode%"=="4" echo 找到舊名稱的檔案，請先執行搬家：uv run sweetspot migrate
  if not "%~1"=="--no-pause" pause
  exit /b %scode%
)
echo.
:ready
uv run sweetspot update
set "code=%errorlevel%"
rem An update code no command gives (a killed update's status) counts as 1 (014 T069)
set "known=0"
for %%c in (0 1 2 3 4 5) do if "%code%"=="%%c" set "known=1"
echo.
echo 產生甜蜜價報告...
uv run sweetspot report --open --update-exit %code%
set "rcode=%errorlevel%"
echo.
if "%rcode%"=="1" (
  echo 報告產生失敗，請看上方訊息或 data\logs 內的日誌。
) else (
  if "%code%"=="0" echo 更新完成，報告已開啟。
  if "%code%"=="2" echo 更新完成，但有部分項目需要注意，請看上方摘要的 failures 與 alerts；報告已開啟。
  if "%code%"=="1" echo 資料更新失敗，報告使用既有資料並已開啟。
  if "%code%"=="3" echo 另一個更新正在執行；報告使用既有資料並已開啟。
  if "%code%"=="4" echo 找到舊名稱的檔案，請先執行搬家：uv run sweetspot migrate
  if "%code%"=="5" echo 還沒設定願望清單：請先執行 uv run sweetspot setup
  if "%known%"=="0" echo 資料更新沒有正常結束（代碼 %code%），報告使用既有資料並已開啟。
)
rem The overall exit code is the more serious one: 1 > 5 > 4 > 3 > 2 > 0
rem (4: only the files of before the rename, migrate first, feature 016; 5: not set up yet, feature 014)
set "final=0"
if "%code%"=="2" set "final=2"
if "%rcode%"=="2" set "final=2"
if "%code%"=="3" set "final=3"
if "%code%"=="4" set "final=4"
if "%rcode%"=="4" set "final=4"
if "%code%"=="5" set "final=5"
if "%rcode%"=="5" set "final=5"
if "%code%"=="1" set "final=1"
if "%rcode%"=="1" set "final=1"
if "%known%"=="0" set "final=1"
if not "%~1"=="--no-pause" pause
exit /b %final%

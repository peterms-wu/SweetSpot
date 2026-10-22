@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem rem lines stay ASCII: after some Chinese rem lines cmd misreads the next line (tests/integration/test_cmd_run.py)
rem Tell sweetspot it runs in the background: with no settings file it does not ask, it ends with exit code 5 (feature 014)
set "SWEETSPOT_BACKGROUND=1"
rem The scheduled background update: update the data and make the report, no browser, no pause.
rem Output: data\logs\background-update.log (overwritten each time); the detailed logs stay in data\logs.
if not exist "data\logs" mkdir "data\logs"
set "log=data\logs\background-update.log"
echo ===== 開始 %date% %time% =====> "%log%"
where uv >nul 2>nul
if errorlevel 1 (
  echo 找不到 uv，請先安裝：https://docs.astral.sh/uv/>> "%log%"
  exit /b 1
)
uv run sweetspot update >> "%log%" 2>&1
set "code=%errorlevel%"
rem An update code no command gives (a killed update's status) counts as 1 (014 T069)
set "known=0"
for %%c in (0 1 2 3 4 5) do if "%code%"=="%%c" set "known=1"
uv run sweetspot report --update-exit %code% >> "%log%" 2>&1
set "rcode=%errorlevel%"
rem Not set up yet (update 5): nothing to back up, and the Python side leaves no daily log (014 T059)
set "bcode=略過（還沒設定）"
if "%code%"=="5" goto :overall
uv run python scripts\backup_db.py >> "%log%" 2>&1
set "bcode=%errorlevel%"
:overall
rem The overall exit code is the more serious one: 1 > 5 > 4 > 3 > 2 > 0, as in the double-click script
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
echo ===== 結束 %date% %time%：update %code%，report %rcode%，backup %bcode%，整體 %final% =====>> "%log%"
exit /b %final%

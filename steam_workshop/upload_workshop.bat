@echo off
rem Publish / update the Steam Workshop item via SteamCMD.
rem All logic lives in tools\upload_workshop.ps1 (Unicode-safe). The password is never stored:
rem SteamCMD asks for it and for the Steam Guard code itself.
rem Usage: upload_workshop.bat [-Login name] [-DryRun] [-ChangeNote "text"] [-Yes]
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\upload_workshop.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo Upload script finished with error code %RC%.
pause
exit /b %RC%

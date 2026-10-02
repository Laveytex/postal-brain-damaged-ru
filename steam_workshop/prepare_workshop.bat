@echo off
rem Copies the release build of the patcher into steam_workshop\content.
rem Build it first with ..\build_exe.bat (creates ..\dist\ru_patch.exe),
rem or run: prepare_workshop.bat --build
setlocal
cd /d "%~dp0"
set "EXE=%~dp0..\dist\ru_patch.exe"

if /i "%~1"=="--build" (
    call "%~dp0..\build_exe.bat"
    if errorlevel 1 goto :fail_build
)
if not exist "%EXE%" goto :no_exe

if not exist "%~dp0content" mkdir "%~dp0content"
copy /y "%EXE%" "%~dp0content\ru_patch.exe" >nul
if errorlevel 1 goto :fail_copy

echo.
echo Workshop content is ready:
dir /b "%~dp0content"
echo.
echo Next: upload_workshop.bat
pause
exit /b 0

:no_exe
echo.
echo ru_patch.exe not found: "%EXE%"
echo Build it first: ..\build_exe.bat   (or run: prepare_workshop.bat --build)
pause
exit /b 1

:fail_build
echo.
echo Build failed, see messages above.
pause
exit /b 1

:fail_copy
echo.
echo Could not copy ru_patch.exe into content\ (is it open or locked?).
pause
exit /b 1

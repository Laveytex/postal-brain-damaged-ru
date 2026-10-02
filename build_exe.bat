@echo off
rem Сборка ru_patch.exe (нужен Python 3.12: pip install UnityPy pyinstaller)
cd /d "%~dp0"
py -3.12 -m PyInstaller --noconfirm --onefile --console --name ru_patch --add-data "ru.json;." --collect-all UnityPy ru_patch.py

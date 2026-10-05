@echo off
rem Build dist/ru_patch.exe (needs Python 3.12: pip install UnityPy pyinstaller)
cd /d "%~dp0"
py -3.12 -m PyInstaller --noconfirm --onefile --console --name ru_patch --add-data "ru.json;." --add-data "fontgen/out;fontgen/out" --collect-all UnityPy ru_patch.py

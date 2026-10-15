@echo off
rem Build dist/ru_patch.exe (needs Python 3.12: pip install UnityPy pyinstaller)
cd /d "%~dp0"
if not exist texgen\out mkdir texgen\out
py -3.12 -m PyInstaller --noconfirm --onefile --console --name ru_patch --add-data "ru.json;." --add-data "fontgen/out;fontgen/out" --add-data "texgen/out;texgen/out" --hidden-import etcpak --hidden-import texture2ddecoder --collect-data archspec --collect-all UnityPy --exclude-module fmod_toolkit --exclude-module pyfmodex --exclude-module numpy --exclude-module scipy ru_patch.py

@echo off
rem Build dist/ru_patch/ (ru_patch.exe + _internal) (needs Python 3.12: pip install UnityPy pyinstaller)
rem --onedir instead of --onefile: the single self-extracting exe was flagged by Defender ML (Wacatac.C!ml)
cd /d "%~dp0"
if not exist texgen\out mkdir texgen\out
py -3.12 -m PyInstaller --noconfirm --onedir --console --name ru_patch --version-file version_info.txt --add-data "ru.json;." --add-data "fontgen/out;fontgen/out" --add-data "texgen/out;texgen/out" --hidden-import etcpak --hidden-import texture2ddecoder --collect-data archspec --collect-all UnityPy --exclude-module fmod_toolkit --exclude-module pyfmodex --exclude-module numpy --exclude-module scipy ru_patch.py

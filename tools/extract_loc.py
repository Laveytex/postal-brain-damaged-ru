# -*- coding: utf-8 -*-
"""Выгружает все тексты (LocalizedString) и сведения о шрифтах из POSTAL Brain Damaged.
Только ЧИТАЕТ файлы игры, ничего в них не меняет. Результат пишет рядом со скриптом."""
import os, sys, json, struct, re, time, traceback
try:
    import UnityPy
except ImportError:
    print("Нет UnityPy. Выполните: pip install UnityPy fonttools"); sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, ".."))          # скрипт лежит в <папка игры>\_ru_tools
DATA = os.path.join(GAME, "POSTAL Brain Damaged_Data")
if not os.path.isdir(DATA):
    DATA = sys.argv[1] if len(sys.argv) > 1 else DATA
OUT = os.path.join(HERE, "loc_dump.json")
REPORT = os.path.join(HERE, "report.txt")

def rs(d, p):
    n = struct.unpack_from('<i', d, p)[0]
    if n < 0 or n > 100000 or p + 4 + n > len(d): raise ValueError("bad str")
    s = d[p+4:p+4+n].decode('utf8'); p += 4 + n; p = (p + 3) & ~3
    return s, p

def parse_loc(d):
    """Раскладка найдена на resources.assets: заголовок 28 байт, name, key, [языки], [значения]."""
    if len(d) < 60 or b'[EN]' not in d: return None
    p = 28
    name, p = rs(d, p)
    key, p = rs(d, p)
    n = struct.unpack_from('<i', d, p)[0]; p += 4
    if not (0 < n < 40): return None
    langs = []
    for _ in range(n):
        s, p = rs(d, p); langs.append(s)
    m = struct.unpack_from('<i', d, p)[0]; p += 4
    if m < n or m > n + 2: return None
    vals = []
    for _ in range(m):
        s, p = rs(d, p); vals.append(s)
    tr = dict(zip(langs, vals))
    if m > n: tr['_extra'] = vals[n:]
    return name, key, tr, (p == len(d))

def scan_files():
    res = []
    for root, _, files in os.walk(DATA):
        if os.sep + "il2cpp_data" in root or os.sep + "Plugins" in root: continue
        for f in files:
            lf = f.lower()
            if lf.endswith((".resS", ".resource", ".json", ".dat", ".dll", ".bank", ".info", ".config")) or lf.endswith(".ress"): continue
            p = os.path.join(root, f)
            if lf.endswith((".assets", ".bundle")) or re.fullmatch(r"(level\d+|globalgamemanagers|resources)", lf):
                res.append(p)
    return sorted(res)

loc, dup, fonts, sdf, texts = {}, 0, [], [], []
lines = []
def log(s):
    print(s); lines.append(s)

t0 = time.time()
files = scan_files()
log("Найдено файлов для чтения: %d" % len(files))
for path in files:
    rel = os.path.relpath(path, DATA)
    try:
        env = UnityPy.load(path)
        found = 0
        for o in env.objects:
            tn = o.type.name
            try:
                if tn == "MonoBehaviour":
                    d = o.get_raw_data()
                    r = parse_loc(d)
                    if r:
                        name, key, tr, exact = r
                        if name in loc:
                            dup += 1
                            if loc[name]["tr"] != tr: loc[name].setdefault("variants", []).append(tr)
                        else:
                            loc[name] = {"key": key, "tr": tr, "src": rel, "pid": o.path_id, "exact": exact}
                        found += 1
                    elif 28 < len(d) < 400:
                        m = re.search(rb'^.{28}.{4}([A-Za-z0-9_ -]{3,60})', d, re.S)
                        if m and re.search(rb'(SDF|Font|Atlas)', m.group(1), re.I): sdf.append((rel, m.group(1).decode()))
                elif tn == "Font":
                    x = o.read(); data = bytes(x.m_FontData or b'')
                    cyr = None
                    if data:
                        try:
                            from fontTools.ttLib import TTFont
                            import io
                            cm = TTFont(io.BytesIO(data)).getBestCmap()
                            cyr = all(c in cm for c in range(0x410, 0x450))
                        except Exception: cyr = "?"
                    fonts.append((rel, x.m_Name, len(data), cyr))
                elif tn == "TextAsset":
                    x = o.read()
                    if re.search(r'i18n|locali', x.m_Name, re.I): texts.append((rel, x.m_Name))
            except Exception:
                pass
        log("  %-80s строк: %d" % (rel, found))
    except Exception as e:
        log("  %-80s ОШИБКА: %s" % (rel, e))

json.dump(loc, open(OUT, "w", encoding="utf8"), ensure_ascii=False, indent=1)
log("")
log("ИТОГО уникальных текстовых записей: %d (повторов: %d), время %.0f с" % (len(loc), dup, time.time() - t0))
bad = [k for k, v in loc.items() if not v["exact"]]
log("С нестандартной раскладкой: %d" % len(bad))
log("")
log("ШРИФТЫ (файл, имя, размер, есть ли кириллица):")
for f in fonts: log("  %s" % (f,))
log("")
log("Объекты, похожие на TMP-шрифты/атласы:")
for f in sorted(set(sdf)): log("  %s" % (f,))
log("")
log("TextAsset с i18n:")
for f in texts: log("  %s" % (f,))
open(REPORT, "w", encoding="utf8").write("\n".join(lines))
print("\nГотово. Файлы loc_dump.json и report.txt лежат в папке _ru_tools. Напишите мне в чат: готово.")

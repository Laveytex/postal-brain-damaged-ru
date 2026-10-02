# -*- coding: utf-8 -*-
"""Русификатор POSTAL: Brain Damaged (фанатский, неофициальный).

Перевод ставится в слот венгерского языка: в игре выбрать язык «Русский» (бывший «Magyar»).
  ru_patch.exe              - меню (установить / удалить)
  ru_patch.exe --install    - установить без вопросов
  ru_patch.exe --restore    - вернуть оригинальные файлы
  ru_patch.exe --game "D:\\...\\POSTAL Brain Damaged"   - указать папку игры вручную
Перед изменением оригиналы копируются в <папка игры>\\_ru_backup.
Steam «Проверить целостность файлов» тоже возвращает оригиналы."""
import os, sys, json, struct, shutil, time, re, base64, subprocess

VERSION = "1.0.1"
GAME_DIR_NAME = "POSTAL Brain Damaged"
DATA_NAME = "POSTAL Brain Damaged_Data"
GAME_EXE = "POSTAL Brain Damaged.exe"
SLOT = "[HU]"
AA = os.path.join("StreamingAssets", "aa", "StandaloneWindows64")
FALLBACK_FONTS = {"LiberationSans SDF - Fallback"}   # динамические TMP-шрифты, которым включаем мульти-атлас
ALL_SLOTS = {"LOC_LANGUAGE_Hungarian": "Русский"}  # заменить во всех языках (названия языков одинаковы везде)

def res_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

# ---------- поиск игры ----------
def is_game_dir(p):
    return bool(p) and os.path.isdir(os.path.join(p, DATA_NAME))

def steam_libraries():
    libs = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for val in ("SteamPath", "InstallPath"):
                        try: libs.append(winreg.QueryValueEx(k, val)[0])
                        except OSError: pass
            except OSError: pass
    except ImportError: pass
    for root in list(libs):
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf8", errors="ignore").read())]
        except OSError: pass
    return list(dict.fromkeys(os.path.normpath(l) for l in libs))

def find_game():
    if "--game" in sys.argv:
        p = sys.argv[sys.argv.index("--game") + 1]
        return p if is_game_dir(p) else None
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    p = here
    for _ in range(4):                      # патчер лежит в папке игры или во вложенной папке
        if is_game_dir(p): return p
        p = os.path.dirname(p)
    p = here                                # запуск из Steam Workshop: <библиотека>\steamapps\workshop\content\<appid>\<id>
    while os.path.dirname(p) != p:
        if os.path.basename(p).lower() == "steamapps":
            cand = os.path.join(p, "common", GAME_DIR_NAME)
            if is_game_dir(cand): return cand
        p = os.path.dirname(p)
    for lib in steam_libraries():
        p = os.path.join(lib, "steamapps", "common", GAME_DIR_NAME)
        if is_game_dir(p): return p
    return None

def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + GAME_EXE], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return GAME_EXE.lower() in out.lower()
    except Exception:
        return False

# ---------- записи LocalizedString ----------
def rs(d, p):
    n = struct.unpack_from('<i', d, p)[0]
    s = d[p + 4:p + 4 + n].decode('utf8'); p += 4 + n; p = (p + 3) & ~3
    return s, p

def ws(s):
    b = s.encode('utf8')
    return struct.pack('<i', len(b)) + b + b'\0' * ((4 - len(b) % 4) % 4)

def parse_record(d):
    """(name, langs, vals, vals_off) или None, если это не запись текста."""
    if len(d) < 60 or b'[EN]' not in d: return None
    try:
        p = 28
        name, p = rs(d, p)
        _key, p = rs(d, p)
        n = struct.unpack_from('<i', d, p)[0]; p += 4
        if not 0 < n < 64: return None
        langs = []
        for _ in range(n):
            s, p = rs(d, p); langs.append(s)
        m = struct.unpack_from('<i', d, p)[0]; vals_off = p; p += 4
        if not 0 < m < 64: return None
        vals = []
        for _ in range(m):
            s, p = rs(d, p); vals.append(s)
        if p != len(d) or SLOT not in langs: return None
        return name, langs, vals, vals_off
    except Exception:
        return None

def patch_record(d, ru):
    """-> (новые байты или None, была ли запись уже переведена)"""
    r = parse_record(d)
    if r is None: return None, False
    name, langs, vals, vals_off = r
    if name not in ru and name not in ALL_SLOTS: return None, False
    if name in ALL_SLOTS: new = [ALL_SLOTS[name] if v else v for v in vals]
    else:
        new = list(vals); new[langs.index(SLOT)] = ru[name]
    if new == vals: return None, True
    return d[:vals_off] + struct.pack('<i', len(new)) + b''.join(ws(v) for v in new), False

# ---------- шрифт ----------
def font_tail(d):
    """Смещение флага m_IsMultiAtlasTexturesEnabled в сыром TMP_FontAsset.
    Запись глифа 48 байт (основная сборка) или 52 (более новый бандл)."""
    for gs in (48, 52):
        for p in range(100, min(len(d) - 8, 1200), 4):
            try:
                N = struct.unpack_from('<i', d, p)[0]
                if not 0 < N < 20000 or p + 4 + gs * N > len(d): continue
                gl = set(struct.unpack_from('<I', d, p + 4 + gs * i)[0] for i in range(N))
                q = p + 4 + gs * N
                M = struct.unpack_from('<i', d, q)[0]
                if not 0 < M <= N * 4 or q + 4 + 16 * M > len(d): continue
                if not all(struct.unpack_from('<I', d, q + 12 + 16 * i)[0] in gl for i in range(M)): continue
                r = q + 4 + 16 * M
                A = struct.unpack_from('<i', d, r)[0]
                if not 1 <= A <= 16: continue
                s = r + 4 + 12 * A
                idx, multi, clear, used = struct.unpack_from('<iiii', d, s)
                if 0 <= idx < A and multi in (0, 1) and clear in (0, 1) and 0 <= used <= N + 1:
                    return s + 4
            except struct.error: pass
    return None

def patch_font(d):
    try:
        n = struct.unpack_from('<i', d, 28)[0]
        if not 0 < n < 100 or d[32:32 + n].decode('utf8', 'replace') not in FALLBACK_FONTS: return None
    except struct.error: return None
    off = font_tail(d)
    if off is None:
        print("  ВНИМАНИЕ: не удалось разобрать шрифт", d[32:32 + n].decode('utf8', 'replace')); return None
    if d[off] == 1: return None
    return d[:off] + bytes([1]) + d[off + 1:]

# ---------- файлы ----------
class Patcher:
    def __init__(self, game):
        self.game = game
        self.data = os.path.join(game, DATA_NAME)
        self.backup_dir = os.path.join(game, "_ru_backup")

    def backup(self, path, fresh):
        """fresh=True: файл сейчас оригинальный (например, после обновления игры) - копию обновляем."""
        dst = os.path.join(self.backup_dir, os.path.relpath(path, self.data))
        if fresh or not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)

    def patch_file(self, rel, ru, is_bundle):
        import UnityPy
        path = os.path.join(self.data, rel)
        if not os.path.exists(path): return 0
        with open(path, 'rb') as fh: raw = fh.read()
        env = UnityPy.load(raw)      # из памяти, чтобы Windows дала заменить файл
        del raw
        changed = already = 0
        for o in env.objects:
            if o.type.name != "MonoBehaviour": continue
            d = o.get_raw_data()
            nd, was = patch_record(d, ru)
            already += was
            if nd is None and rel != "resources.assets":
                nd = patch_font(d)
            if nd is not None:
                o.set_raw_data(nd); changed += 1
        name = os.path.basename(rel)
        if not changed:
            print("  %s: уже переведён" % name if already else "  %s: нечего менять" % name); return 0
        self.backup(path, fresh=(already == 0))
        tmp = path + ".ru_tmp"
        with open(tmp, "wb") as f:
            f.write(env.file.save(packer="original") if is_bundle else env.file.save())
        with open(tmp, 'rb') as fh: UnityPy.load(fh.read())   # проверка, что файл читается
        os.replace(tmp, path)
        print("  %s: заменено записей: %d" % (name, changed))
        return changed

    def fix_catalog(self):
        """Обнуляем проверку CRC бандлов в catalog.json, иначе изменённые бандлы не загрузятся."""
        p = os.path.join(self.data, "StreamingAssets", "aa", "catalog.json")
        if not os.path.exists(p): return
        j = json.load(open(p, encoding="utf8"))
        xd = base64.b64decode(j["m_ExtraDataString"])
        head = '"m_Crc":'.encode("utf-16-le")
        pat = re.compile(re.escape(head) + b'(?:[0-9]\x00)+')
        nonzero = 0
        def rep(m):
            nonlocal nonzero
            digits = m.group(0)[len(head)::2]
            if digits.strip(b'0'): nonzero += 1
            return head + b'0\x00' + b' \x00' * (len(digits) - 1)   # длина не меняется
        out = pat.sub(rep, xd)
        if not nonzero:
            print("  catalog.json: уже подготовлен"); return
        self.backup(p, fresh=True)
        j["m_ExtraDataString"] = base64.b64encode(out).decode()
        json.dump(j, open(p, "w", encoding="utf8"), separators=(",", ":"))
        print("  catalog.json: отключено проверок CRC:", nonzero)

    def install(self):
        ru = json.load(open(res_path("ru.json"), encoding="utf8"))
        print("Строк перевода: %d. Это займёт 3-5 минут, не закрывай окно..." % len(ru))
        t0 = time.time()
        total = 0
        for rel in ("resources.assets", "sharedassets0.assets"):
            total += self.patch_file(rel, ru, False)
        aa = os.path.join(self.data, AA)
        bundles = sorted(f for f in os.listdir(aa) if f.startswith("defaultlocalgroup") and f.endswith(".bundle")) if os.path.isdir(aa) else []
        if bundles: self.fix_catalog()
        for f in bundles:
            total += self.patch_file(os.path.join(AA, f), ru, True)
        print("Готово за %.0f с. В игре: Настройки -> Язык -> «Русский»." % (time.time() - t0))

    def restore(self):
        if not os.path.isdir(self.backup_dir):
            print("Резервных копий нет. Верни оригинал через Steam: «Свойства -> Установленные файлы -> Проверить целостность»."); return
        for root, _, files in os.walk(self.backup_dir):
            for f in files:
                src = os.path.join(root, f); rel = os.path.relpath(src, self.backup_dir)
                shutil.copy2(src, os.path.join(self.data, rel)); print("  восстановлено:", rel)
        shutil.rmtree(self.backup_dir, ignore_errors=True)
        print("Оригинальные файлы возвращены.")

def main():
    print("Русификатор POSTAL: Brain Damaged v%s (фанатский перевод)\n" % VERSION)
    game = find_game()
    if not game:
        print("Не нашёл папку игры. Положи ru_patch.exe в папку игры (где лежит %s)" % GAME_EXE)
        print('или запусти: ru_patch.exe --game "путь\\к\\%s"' % GAME_DIR_NAME)
        return 1
    print("Игра:", game)
    if game_running():
        print("\nИгра запущена — закрой её и запусти русификатор снова."); return 1
    p = Patcher(game)
    if "--restore" in sys.argv: mode = "2"
    elif "--install" in sys.argv: mode = "1"
    else:
        print("\n  1 — установить русификатор\n  2 — удалить (вернуть оригинальные файлы)\n")
        mode = input("Выбери 1 или 2 и нажми Enter: ").strip()
    print()
    try:
        if mode == "1": p.install()
        elif mode == "2": p.restore()
        else: print("Ничего не выбрано.")
    except PermissionError as e:
        print("\nНет доступа к файлу (игра или Steam его держат?): %s\nЗакрой игру и попробуй ещё раз." % e); return 1
    return 0

if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        import traceback; traceback.print_exc(); code = 1
        print("\nОшибка. Пришли этот текст автору на GitHub (Issues).")
    if not any(a in sys.argv for a in ("--install", "--restore")):
        input("\nНажми Enter, чтобы закрыть...")
    sys.exit(code)

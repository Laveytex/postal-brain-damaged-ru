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

VERSION = "1.1.0"
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

# ---------- кириллица в фирменных шрифтах ----------
FONT_FAMILY = {"FONT_Clickable": "smash", "FONT_NotClickable": "smash", "FONT_Text": "typewriter", "FONT_InputText": "typewriter"}
CYR_MARK = 0x0416   # «Ж»: если она есть в шрифте — кириллица уже встроена

def load_font_kits():
    kits = {}
    for fam in ("smash", "typewriter"):
        try:
            from PIL import Image
            info = json.load(open(res_path(os.path.join("fontgen", "out", fam + ".json")), encoding="utf8"))
            info["top"] = Image.open(res_path(os.path.join("fontgen", "out", fam + "_atlas_top.png"))).convert("L")
            kits[fam] = info
        except Exception as e:
            print("  ВНИМАНИЕ: нет данных шрифта %s (%s) — кириллица в нём останется запасной" % (fam, e))
    return kits

def font_layout(d):
    """Разбор TMP_FontAsset (TMP 3.0, формат 1.1.0, Unity 2021.3.14): нужные смещения и таблицы. None — другой формат."""
    try:
        r = [28]
        def i32():
            v = struct.unpack_from('<i', d, r[0])[0]; r[0] += 4; return v
        def s_():
            n = i32(); v = d[r[0]:r[0] + n]; r[0] += n; r[0] = (r[0] + 3) & ~3; return v
        def pptr():
            v = struct.unpack_from('<iq', d, r[0]); r[0] += 12; return v
        L = {"name": s_().decode('utf8')}
        i32(); L["material"] = pptr(); i32()
        s_(); s_(); pptr(); i32()                       # version, GUID, source font, population mode
        i32(); s_(); s_(); i32(); r[0] += 4 + 15 * 4      # FaceInfo
        L["glyph_off"] = r[0]
        n = i32(); L["glyphs"] = [struct.unpack_from('<I5f4if i', d, r[0] + 48 * k) for k in range(n)]; r[0] += 48 * n
        m = i32(); L["chars"] = [struct.unpack_from('<iIIf', d, r[0] + 16 * k) for k in range(m)]; r[0] += 16 * m
        L["tables_end"] = r[0]
        a = i32(); L["atlases"] = [pptr() for _ in range(a)]
        i32(); i32(); i32()                             # atlas index, multi-atlas, clear dynamic
        for _ in range(2):                              # used / free rects
            n_r = i32(); r[0] += 16 * n_r
        s_(); r[0] += 4 * 20                            # legacy fontInfo: Name + 20 полей
        pptr()                                          # legacy atlas
        L["wh_off"] = r[0]
        L["W"], L["H"], L["pad"] = struct.unpack_from('<iii', d, r[0])
        glyph_idx = {g[0] for g in L["glyphs"]}
        if not (1 <= a <= 16 and L["W"] in (256, 512, 1024, 2048, 4096) and 0 < L["pad"] < 64
                and all(c[2] in glyph_idx for c in L["chars"])):
            return None
        return L
    except (struct.error, UnicodeDecodeError):
        return None

def embed_cyrillic(o, d, kit):
    """Встраивает кириллицу в FontAsset: атлас 1024x1024 -> 1024x2048 (оригинал внизу, наши глифы сверху),
    дописывает таблицы глифов/символов, обновляет _TextureHeight материала. Возвращает новые байты или None."""
    from PIL import Image
    L = font_layout(d)
    if L is None:
        print("  ВНИМАНИЕ: не разобрал шрифт", d[32:32 + struct.unpack_from('<i', d, 28)[0]].decode('utf8', 'replace')); return None
    if any(c[1] == CYR_MARK for c in L["chars"]): return None
    W, H = kit["atlas_width"], kit["atlas_height"]
    if (L["W"], L["H"]) != (W, H // 2) or L["pad"] != kit["padding"]:
        print("  ВНИМАНИЕ: %s: неожиданный атлас %dx%d pad %d — пропускаю" % (L["name"], L["W"], L["H"], L["pad"])); return None
    af = o.assets_file
    fid, tex_pid = L["atlases"][0]
    mfid, mat_pid = L["material"]
    if fid != 0 or mfid != 0:
        print("  ВНИМАНИЕ: %s: атлас/материал в другом файле — пропускаю" % L["name"]); return None
    # атлас
    tex = af.objects[tex_pid].read()
    img = tex.image
    chans = [img.getchannel(c) for c in img.getbands()]
    sdf = max(chans, key=lambda c: c.getextrema()[1] - c.getextrema()[0])
    if sdf.size != (W, H // 2): print("  ВНИМАНИЕ: %s: размер текстуры %s" % (L["name"], sdf.size)); return None
    big = Image.new("L", (W, H), 0)
    big.paste(sdf, (0, H // 2)); big.paste(kit["top"], (0, 0))
    white = Image.new("L", (W, H), 255)
    tex.set_image(Image.merge("RGBA", (white, white, white, big)), target_format=1)   # 1 = Alpha8
    tex.save()
    # материал: _TextureHeight
    mat = af.objects[mat_pid].read()
    fl = mat.m_SavedProperties.m_Floats
    for i, it in enumerate(fl):
        k = it[0] if isinstance(it, (list, tuple)) else it.first
        if k != "_TextureHeight": continue
        if isinstance(it, tuple): fl[i] = (k, float(H))
        elif isinstance(it, list): it[1] = float(H)
        else: it.second = float(H)
    mat.save()
    # таблицы
    used = {g[0] for g in L["glyphs"]}
    base = kit["glyph_index_base"]
    while any(base + i in used for i in range(len(kit["glyphs"]))): base += 1000
    glyph_bytes = b"".join(struct.pack('<I5f4if i', *g) for g in L["glyphs"])
    char_bytes = b"".join(struct.pack('<iIIf', *c) for c in L["chars"])
    have = {c[1] for c in L["chars"]}
    n_g = len(L["glyphs"]); n_c = len(L["chars"])
    for i, g in enumerate(kit["glyphs"]):
        if g["unicode"] in have: continue
        x, y, w, h = g["rect"]
        glyph_bytes += struct.pack('<I5f4if i', base + i, g["width"], g["height"], g["bearingX"], g["bearingY"], g["advance"], x, y, w, h, 1.0, 0)
        char_bytes += struct.pack('<iIIf', 1, g["unicode"], base + i, 1.0)
        n_g += 1; n_c += 1
    lat = {c[1]: c[2] for c in L["chars"]}
    for cyr, latin in kit["aliases"].items():
        if ord(cyr) in have or ord(latin) not in lat: continue
        char_bytes += struct.pack('<iIIf', 1, ord(cyr), lat[ord(latin)], 1.0); n_c += 1
    nd = (d[:L["glyph_off"]] + struct.pack('<i', n_g) + glyph_bytes + struct.pack('<i', n_c) + char_bytes
          + d[L["tables_end"]:L["wh_off"]] + struct.pack('<ii', W, H) + d[L["wh_off"] + 8:])
    return nd

def fix_preset_materials(env, font_atlas):
    """Материалы-пресеты (напр. «FONT_ClickableClicked Material» для наведённой кнопки) ссылаются на копию
    старого атласа 1024x1024. Перенаправляем их на новый атлас шрифта и ставим _TextureHeight.
    font_atlas: имя шрифта -> (pathID атласа, высота атласа). Возвращает число изменённых материалов."""
    names = {}
    for o in env.objects:
        if o.type.name == "Texture2D":
            try:
                n = o.read().m_Name
                if n.startswith("FONT_"): names[o.path_id] = n
            except Exception: pass
    by_pid = {pid: (f, h) for f, (pid, h) in font_atlas.items()}
    fixed = 0
    for o in env.objects:
        if o.type.name != "Material": continue
        m = o.read()
        tex = None
        for it in m.m_SavedProperties.m_TexEnvs:
            k, te = (it[0], it[1]) if isinstance(it, (list, tuple)) else (it.first, it.second)
            if k == "_MainTex": tex = te
        if tex is None or tex.m_Texture.m_FileID != 0: continue
        pid = tex.m_Texture.m_PathID
        if pid in by_pid:
            target, h = pid, by_pid[pid][1]
        else:
            tname = names.get(pid, "")
            if not tname.endswith(" Atlas"): continue
            cands = [f for f in font_atlas if tname[:-6].startswith(f)]
            if not cands: continue
            target, h = font_atlas[max(cands, key=len)]
        dirty = False
        if pid != target:
            tex.m_Texture.m_PathID = target; dirty = True
        fl = m.m_SavedProperties.m_Floats
        for i, it in enumerate(fl):
            k = it[0] if isinstance(it, (list, tuple)) else it.first
            v = it[1] if isinstance(it, (list, tuple)) else it.second
            if k != "_TextureHeight" or v == float(h): continue
            if isinstance(it, tuple): fl[i] = (k, float(h))
            elif isinstance(it, list): it[1] = float(h)
            else: it.second = float(h)
            dirty = True
        if dirty:
            m.save(); fixed += 1
            print("  материал %s: атлас и высота обновлены" % m.m_Name)
    return fixed

def live_bundles(data_dir):
    """Бандлы, которые реально грузит игра (по catalog.json)."""
    try:
        j = json.load(open(os.path.join(data_dir, "StreamingAssets", "aa", "catalog.json"), encoding="utf8"))
        return {os.path.basename(i.replace("\\", "/")) for i in j["m_InternalIds"] if i.endswith(".bundle")}
    except Exception:
        return None

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

    def patch_file(self, rel, ru, is_bundle, kits=None):
        import UnityPy
        from UnityPy.streams import EndianBinaryReader
        path = os.path.join(self.data, rel)
        if not os.path.exists(path): return 0
        with open(path, 'rb') as fh: raw = fh.read()
        env = UnityPy.load(raw)      # из памяти, чтобы Windows дала заменить файл
        del raw
        res_fh = None
        if kits and not is_bundle and os.path.exists(path + ".resS"):
            # пиксели атласов лежат в .resS (его не меняем, поэтому читаем прямо из файла)
            res_fh = open(path + ".resS", "rb")
            env.register_cab(os.path.basename(path) + ".resS", EndianBinaryReader(res_fh, endian="<"))
        changed = already = fonts = 0
        font_atlas = {}
        try:
            for o in env.objects:
                if o.type.name != "MonoBehaviour": continue
                d = o.get_raw_data()
                nd, was = patch_record(d, ru)
                already += was
                if nd is None and rel != "resources.assets":
                    nd = patch_font(d)
                    if kits:
                        n = struct.unpack_from('<i', d, 28)[0] if len(d) > 40 else 0
                        fname = d[32:32 + n].decode('utf8', 'replace') if 0 < n < 64 else ""
                        if fname in FONT_FAMILY and FONT_FAMILY[fname] in kits:
                            emb = embed_cyrillic(o, nd if nd is not None else d, kits[FONT_FAMILY[fname]])
                            if emb is not None:
                                nd = emb; fonts += 1
                                print("  шрифт %s: добавлена кириллица" % fname)
                            L2 = font_layout(nd if nd is not None else d)
                            if L2 and L2["H"] == kits[FONT_FAMILY[fname]]["atlas_height"] and L2["atlases"][0][0] == 0:
                                font_atlas[fname] = (L2["atlases"][0][1], L2["H"])
                if nd is not None:
                    o.set_raw_data(nd); changed += 1
            if font_atlas:
                changed += fix_preset_materials(env, font_atlas)
            name = os.path.basename(rel)
            if changed:
                self.backup(path, fresh=(already == 0))
                tmp = path + ".ru_tmp"
                with open(tmp, "wb") as f:
                    f.write(env.file.save(packer="original") if is_bundle else env.file.save())
        finally:
            if res_fh: res_fh.close()
        if not changed:
            print("  %s: уже переведён" % name if already else "  %s: нечего менять" % name); return 0
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
        kits = load_font_kits()
        live = live_bundles(self.data)
        total += self.patch_file("resources.assets", ru, False)
        total += self.patch_file("sharedassets0.assets", ru, False, kits)
        aa = os.path.join(self.data, AA)
        bundles = sorted(f for f in os.listdir(aa) if f.startswith("defaultlocalgroup") and f.endswith(".bundle")) if os.path.isdir(aa) else []
        if bundles: self.fix_catalog()
        for f in bundles:
            # шрифты меняем только в бандлах, которые игра реально грузит (остальные — остатки старых сборок)
            total += self.patch_file(os.path.join(AA, f), ru, True, kits if (live is None or f in live) else None)
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

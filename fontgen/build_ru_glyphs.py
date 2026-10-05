# -*- coding: utf-8 -*-
"""Сборка кириллических SDF-глифов для шрифтов POSTAL: Brain Damaged из листов-концептов.

Вход:  fontgen/source/<family>_cyrillic_sheet.webp (белые буквы на чёрном, фиксированная сетка строк)
Выход: fontgen/out/<family>_atlas_top.png  — верхняя половина атласа 1024x1024 (только наши SDF-тайлы)
       fontgen/out/<family>.json           — метрики и прямоугольники глифов (координаты атласа 1024x2048)
Патчер (ru_patch.py) склеивает это с оригинальным атласом игры у пользователя — атласы игры мы не распространяем.

Нужны numpy, scipy, Pillow (только для сборки; игрокам не нужны).
  py -3.12 fontgen/build_ru_glyphs.py [--atlas-dir <папка с оригинальными атласами для калибровки и превью>]
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "source")
OUT = os.path.join(HERE, "out")

UP1 = "АБВГДЕЁЖЗИЙКЛМН"; UP2 = "ОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
LO1 = "абвгдеёжзийклмн"; LO2 = "опрстуфхцчшщъыьэюя"
PUN = "«»–…№"

# Метрики оригинальных шрифтов (m_FaceInfo / m_CreationSettings из игры, см. PBD_Font_Research)
FAMILIES = {
    "smash": {"sheet": "smash_cyrillic_sheet.webp", "fonts": ["FONT_Clickable", "FONT_NotClickable"],
              "point": 94, "pad": 15, "cap": 73.0, "mean": 54.0, "ascent": 95.1934, "descent": -23.5,
              # строки листа: (y0, y1) в пикселях листа
              "rows": {"U1": (220, 342), "U2": (350, 452), "L1": (515, 618), "L2": (628, 732), "P": (800, 882)}},
    "typewriter": {"sheet": "typewriter_cyrillic_sheet.webp", "fonts": ["FONT_Text", "FONT_InputText"],
                   "point": 98, "pad": 15, "cap": 69.0, "mean": 50.0, "ascent": 88.2383, "descent": -20.4805,
                   "rows": {"U1": (226, 342), "U2": (358, 458), "L1": (520, 624), "L2": (630, 734), "P": (804, 884)}},
}
# Кириллица, совпадающая по форме с латиницей: берём оригинальные латинские глифы шрифта
ALIASES = {"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
           "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x"}
# исключения: латинский глиф в этой гарнитуре не годится для кириллицы (у Smash строчная x похожа на «н»)
ALIAS_EXCLUDE = {"smash": set("х"), "typewriter": set()}
DESC_UP = set("ДЦЩ"); DESC_LO = set("дрруфцщ")
TALL_UP = set("ЁЙ"); TALL_LO = set("бёйф")
SS = 4                     # суперсэмплинг для построения SDF
SDF_SLOPE = 1.0 / 32.0     # изменение значения (0..1) на 1 пиксель; уточняется калибровкой по оригиналу
ATLAS_W, ATLAS_H = 1024, 2048
TOP_H = 1024               # наши глифы — в верхней половине (в координатах картинки сверху)

def split_row(mask, n):
    """Делит строку на n букв по n-1 самым широким промежуткам пустых столбцов."""
    cols = mask.any(axis=0)
    xs = np.where(cols)[0]
    x0, x1 = xs[0], xs[-1] + 1
    gaps = []; run = None
    for x in range(x0, x1):
        if not cols[x]:
            if run is None: run = x
        elif run is not None:
            gaps.append((x - run, run, x)); run = None
    gaps.sort(reverse=True)
    cuts = sorted(g[1] + g[0] // 2 for g in gaps[:n - 1])
    bounds = [x0] + cuts + [x1]
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        c = np.where(cols[a:b])[0]
        out.append((a + c[0], a + c[-1] + 1))
    return out

def glyph_boxes(gray, y0, y1, chars):
    band = gray[y0:y1]
    mask = band > 128
    boxes = []
    for (a, b) in split_row(mask, len(chars)):
        rows = np.where(mask[:, a:b].any(axis=1))[0]
        boxes.append({"x0": int(a), "x1": int(b), "y0": int(y0 + rows[0]), "y1": int(y0 + rows[-1] + 1)})
    return dict(zip(chars, boxes))

def calibrate(atlas_png, rects):
    """Наклон SDF оригинала: регрессия значения атласа по расстоянию до контура (уровень 128)."""
    a = np.asarray(Image.open(atlas_png).convert("RGBA"))
    ch = max(range(4), key=lambda i: int(a[..., i].max()) - int(a[..., i].min()))
    a = a[..., ch].astype(np.float32) / 255.0
    H = a.shape[0]; slopes = []
    for (x, y, w, h), pad in rects:
        top = H - (y + h)
        t = a[top - pad: top + h + pad, x - pad: x + w + pad]
        inside = t >= 0.5
        d = ndimage.distance_transform_edt(inside) - ndimage.distance_transform_edt(~inside)
        sel = (np.abs(d) > 1.5) & (np.abs(d) < 10)
        if sel.sum() > 50:
            k = np.polyfit(d[sel], t[sel], 1)[0]; slopes.append(k)
    return float(np.median(slopes)) if slopes else None

def make_sdf(gray_crop, scale, pad, slope):
    """gray_crop: L-картинка буквы с листа. Возвращает (sdf_tile L, w, h) в пикселях атласа."""
    w = max(1, int(round(gray_crop.size[0] * scale))); h = max(1, int(round(gray_crop.size[1] * scale)))
    big = gray_crop.resize((w * SS, h * SS), Image.LANCZOS)
    m = np.asarray(big) >= 128
    m = np.pad(m, pad * SS, constant_values=False)
    d = ndimage.distance_transform_edt(m) - ndimage.distance_transform_edt(~m)   # в пикселях SS
    d = d / SS
    H2, W2 = (h + 2 * pad), (w + 2 * pad)
    d = d.reshape(H2, SS, W2, SS).mean(axis=(1, 3))
    v = np.clip(0.5 + d * slope, 0, 1)
    return Image.fromarray((v * 255 + 0.5).astype(np.uint8), "L"), w, h

def build(fam, cfg, atlas_dir):
    aliases = {k: v for k, v in ALIASES.items() if k not in ALIAS_EXCLUDE[fam]}
    gray = np.asarray(Image.open(os.path.join(SRC, cfg["sheet"])).convert("L"))
    G = Image.fromarray(gray)
    boxes = {}
    for key, chars in (("U1", UP1), ("U2", UP2), ("L1", LO1), ("L2", LO2), ("P", PUN)):
        boxes.update(glyph_boxes(gray, *cfg["rows"][key], chars))
    def med(vals): return float(np.median(vals))
    up = [c for c in UP1 + UP2]; lo = [c for c in LO1 + LO2]
    base_u = {r: med([boxes[c]["y1"] for c in s if c not in DESC_UP]) for r, s in (("U1", UP1), ("U2", UP2))}
    base_l = {r: med([boxes[c]["y1"] for c in s if c not in DESC_LO]) for r, s in (("L1", LO1), ("L2", LO2))}
    capt = med([base_u["U1" if c in UP1 else "U2"] - boxes[c]["y0"] for c in up if c not in TALL_UP])
    xht = med([base_l["L1" if c in LO1 else "L2"] - boxes[c]["y0"] for c in lo if c not in TALL_LO])
    base_p = med([boxes[c]["y1"] for c in "…№"])
    s_up = cfg["cap"] / capt; s_lo = cfg["mean"] / xht
    print("%s: высота заглавных на листе %.1f px, строчных %.1f px -> масштаб %.3f / %.3f" % (fam, capt, xht, s_up, s_lo))
    # калибровка наклона SDF по оригинальным глифам
    slope = SDF_SLOPE
    meta = None
    if atlas_dir:
        import glob
        fa = glob.glob(os.path.join(atlas_dir, "tmp_font_assets", cfg["fonts"][0] + "__sharedassets0*.json"))
        at = glob.glob(os.path.join(atlas_dir, "atlases", cfg["fonts"][0] + "__sharedassets0*_atlas_0.png"))
        chj = glob.glob(os.path.join(atlas_dir, "glyph_tables", cfg["fonts"][0] + "__sharedassets0*_characters.json"))
        if fa and at and chj:
            meta = {"atlas": at[0], "chars": json.load(open(chj[0], encoding="utf8"))}
            rects = [(c["rect"], cfg["pad"]) for c in meta["chars"] if c["char"] in "HIEOMNTLU" and c["width"]]
            k = calibrate(at[0], rects)
            if k: slope = k; print("   наклон SDF по оригиналу: %.4f /px (1/%.1f)" % (k, 1 / k))
    # латинские боковые отступы оригинала — для ширины (advance) новых букв
    lsb_u = rsb_u = lsb_l = rsb_l = None
    if meta:
        U = [c for c in meta["chars"] if c["char"].isupper() and c["char"].isascii() and c["width"]]
        L = [c for c in meta["chars"] if c["char"].islower() and c["char"].isascii() and c["width"]]
        lsb_u = med([c["bearingX"] for c in U]); rsb_u = med([c["advance"] - c["bearingX"] - c["width"] for c in U])
        lsb_l = med([c["bearingX"] for c in L]); rsb_l = med([c["advance"] - c["bearingX"] - c["width"] for c in L])
        print("   отступы латиницы: заглавные %.1f/%.1f, строчные %.1f/%.1f" % (lsb_u, rsb_u, lsb_l, rsb_l))
    lsb_u = 3.0 if lsb_u is None else lsb_u; rsb_u = 3.0 if rsb_u is None else rsb_u
    lsb_l = 3.0 if lsb_l is None else lsb_l; rsb_l = 3.0 if rsb_l is None else rsb_l
    pad = cfg["pad"]
    top = Image.new("L", (ATLAS_W, TOP_H), 0)
    glyphs = []; x = y = 0; rowh = 0; gap = 2
    extra = ["—"] if fam == "typewriter" else []     # у Typewriter нет длинного тире: тянем короткое
    for ch in list(UP1 + UP2 + LO1 + LO2 + PUN) + extra:
        if ch in aliases: continue
        b = dict(boxes["–"]) if ch == "—" else boxes[ch]
        stretch = 1.7 if ch == "—" else 1.0
        if ch in UP1 + UP2:
            s = s_up; base = base_u["U1" if ch in UP1 else "U2"]; lsb, rsb = lsb_u, rsb_u
        elif ch in LO1 + LO2:
            s = s_lo; base = base_l["L1" if ch in LO1 else "L2"]; lsb, rsb = lsb_l, rsb_l
        else:
            s = s_up; base = base_p; lsb, rsb = lsb_l, rsb_l
        crop = G.crop((b["x0"] - 2, b["y0"] - 2, b["x1"] + 2, b["y1"] + 2))
        if stretch != 1.0:
            crop = crop.resize((int(crop.size[0] * stretch), crop.size[1]), Image.LANCZOS)
            b["x1"] = b["x0"] + int((b["x1"] - b["x0"]) * stretch)
        tile, w, h = make_sdf(crop, s, pad, slope)
        tw, th = tile.size
        if x + tw > ATLAS_W: x = 0; y += rowh + gap; rowh = 0
        if y + th > TOP_H: raise SystemExit("не помещается в верхнюю половину атласа")
        top.paste(tile, (x, y))
        bearing_y = (base - (b["y0"] - 2)) * s          # от базовой линии до верха картинки (с запасом 2 px листа)
        adv = lsb + (b["x1"] - b["x0"]) * s + rsb
        glyphs.append({"char": ch, "unicode": ord(ch),
                       "rect": [x + pad, ATLAS_H - (y + pad + h), w, h],      # GlyphRect: от нижнего края атласа
                       "width": float(w), "height": float(h),
                       "bearingX": round(lsb - 2 * s, 3), "bearingY": round(bearing_y, 3), "advance": round(adv, 3)})
        x += tw + gap; rowh = max(rowh, th)
    os.makedirs(OUT, exist_ok=True)
    top.save(os.path.join(OUT, fam + "_atlas_top.png"), optimize=True)
    info = {"family": fam, "fonts": cfg["fonts"], "atlas_width": ATLAS_W, "atlas_height": ATLAS_H, "padding": pad,
            "sdf_slope": slope, "glyph_index_base": {"smash": 20000, "typewriter": 21000}[fam],
            "aliases": aliases, "glyphs": glyphs}
    json.dump(info, open(os.path.join(OUT, fam + ".json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print("   глифов: %d (+%d латинских совпадений), занято по высоте %d из %d px" % (len(glyphs), len(aliases), y + rowh, TOP_H))
    return info, meta

def preview(fam, info, meta, text):
    """Превью: оригинальная латиница из атласа игры + наши глифы, по метрикам."""
    orig = Image.open(meta["atlas"]).convert("RGBA")
    ch_ = max(range(4), key=lambda i: orig.getchannel(i).getextrema()[1] - orig.getchannel(i).getextrema()[0])
    big = Image.new("L", (ATLAS_W, ATLAS_H), 0)
    big.paste(orig.getchannel(ch_), (0, TOP_H)); big.paste(Image.open(os.path.join(OUT, fam + "_atlas_top.png")), (0, 0))
    gm = {g["char"]: g for g in info["glyphs"]}
    lat = {c["char"]: c for c in meta["chars"]}
    for k, v in info["aliases"].items():
        if v in lat: gm[k] = lat[v]
    pad = info["padding"]; lh = FAMILIES[fam]["ascent"] - FAMILIES[fam]["descent"] + 20
    lines = text.split("\n")
    W = 40 + max(sum((gm.get(c) or lat.get(c) or {"advance": 30})["advance"] for c in ln) for ln in lines)
    out = Image.new("L", (int(W), int(lh * len(lines) + 30)), 0)
    for li, ln in enumerate(lines):
        pen = 20; base = 15 + FAMILIES[fam]["ascent"] + li * lh
        for c in ln:
            g = gm.get(c) or lat.get(c)
            if not g: pen += 30; continue
            if g["width"]:
                x, y, w, h = g["rect"]; t = ATLAS_H - (y + h)
                tile = big.crop((x - pad, t - pad, x + w + pad, t + h + pad)).point(lambda v: 255 if v >= 128 else 0)
                out.paste(255, (int(pen + g["bearingX"] - pad), int(base - g["bearingY"] - pad)), tile)
            pen += g["advance"]
    out = out.resize((out.size[0] // 2, out.size[1] // 2), Image.LANCZOS)
    pdir = os.path.join(HERE, "preview"); os.makedirs(pdir, exist_ok=True)   # содержит глифы игры — не коммитить
    out.save(os.path.join(pdir, fam + "_preview.png"))

if __name__ == "__main__":
    atlas_dir = sys.argv[sys.argv.index("--atlas-dir") + 1] if "--atlas-dir" in sys.argv else None
    for fam, cfg in FAMILIES.items():
        info, meta = build(fam, cfg, atlas_dir)
        if meta:
            preview(fam, info, meta, "ПОСТАЛ: Повреждённый мозг\nСЧЁТ ПАТРОНЫ НАСТРОЙКИ Score\nсъешь же ещё этих мягких булок\nЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ «№1…»")

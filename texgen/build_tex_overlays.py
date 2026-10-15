# -*- coding: utf-8 -*-
"""Сборка «накладок» для русских текстур.

Берёт перерисованные текстуры (PNG того же размера, что оригинал) и оригиналы, находит изменённые
участки и сохраняет только их: texgen/out/<NNNN>.json + <NNNN>_<k>.png. Патчер вклеивает эти участки
в текстуры игры у пользователя — целые текстуры игры мы не распространяем.

  py -3.12 texgen/build_tex_overlays.py [--ready <папка ГОТОВО>] [--orig <папка с оригиналами>]
        [--index <tex_inventory/index.json>] [--out <папка>]
По умолчанию: ../Текстуры_для_перевода/ГОТОВО, оригиналы — в подпапках ../Текстуры_для_перевода, ../tex_inventory/index.json.
Нужны numpy, scipy, Pillow (только для сборки)."""
import os, sys, json, glob, re
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.abspath(os.path.join(HERE, "..", ".."))

def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

READY = arg("--ready", os.path.join(TOOLS, "Текстуры_для_перевода", "ГОТОВО"))
ORIG = arg("--orig", os.path.join(TOOLS, "Текстуры_для_перевода"))
INDEX = arg("--index", os.path.join(TOOLS, "tex_inventory", "index.json"))
OUT = arg("--out", os.path.join(HERE, "out"))
THRESH = 10        # порог отличия пикселя (0..255), ниже — шум сохранения
GROW = 3           # расширение маски изменений, px
MERGE_GAP = 8      # участки ближе этого сливаются в один

def find_orig(fname):
    for p in glob.glob(os.path.join(ORIG, "*", fname)):
        if os.path.normpath(os.path.dirname(p)) != os.path.normpath(READY):
            return p
    return None

def boxes_from_mask(mask):
    m = ndimage.binary_dilation(mask, iterations=GROW + MERGE_GAP // 2)
    lab, n = ndimage.label(m)
    out = []
    for sl in ndimage.find_objects(lab):
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        # обратно «сжимаем» на запас слияния, но не меньше исходных изменений
        sub = mask[y0:y1, x0:x1]
        ys, xs = np.where(sub)
        if len(ys) == 0: continue
        out.append([int(max(0, x0 + xs.min() - GROW)), int(max(0, y0 + ys.min() - GROW)),
                    int(min(mask.shape[1], x0 + xs.max() + 1 + GROW)), int(min(mask.shape[0], y0 + ys.max() + 1 + GROW))])
    return out

def main():
    index = {i["idx"]: i for i in json.load(open(INDEX, encoding="utf8"))}
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "*")): os.remove(old)
    ready = sorted(f for f in os.listdir(READY) if f.lower().endswith(".png")) if os.path.isdir(READY) else []
    if not ready: print("В", READY, "нет PNG"); return
    total = 0; bad = 0
    for f in ready:
        m = re.match(r"(\d{4})_", f)
        if not m: print("  пропуск (нет номера):", f); bad += 1; continue
        idx = int(m.group(1)); info = index.get(idx)
        op = find_orig(f)
        if not info or not op: print("  пропуск (нет оригинала/номера в индексе):", f); bad += 1; continue
        a = Image.open(op).convert("RGBA"); b = Image.open(os.path.join(READY, f)).convert("RGBA")
        if a.size != b.size:
            print("  ОШИБКА размер %s: %s, а у оригинала %s" % (f, b.size, a.size)); bad += 1; continue
        A = np.asarray(a).astype(np.int16); B = np.asarray(b).astype(np.int16)
        diff = np.abs(A - B).max(axis=2) > THRESH
        share = diff.mean()
        if not diff.any(): print("  без изменений:", f); continue
        boxes = boxes_from_mask(diff)
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes) / (a.size[0] * a.size[1])
        if area > 0.6:
            print("  ВНИМАНИЕ %s: изменено %.0f%% площади — проверьте, не сдвинуто/пересохранено ли всё изображение" % (f, area * 100))
        rects = []
        for k, (x0, y0, x1, y1) in enumerate(boxes):
            name = "%04d_%d.png" % (idx, k)
            b.crop((x0, y0, x1, y1)).save(os.path.join(OUT, name), optimize=True)
            rects.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "png": name})   # y — сверху вниз
        files = sorted({re.split(r"[\\/]", p)[-1] for p in [info["file"]] + [c[0] for c in info.get("copies", [])]})
        json.dump({"idx": idx, "name": info["name"], "width": a.size[0], "height": a.size[1], "files": files, "rects": rects},
                  open(os.path.join(OUT, "%04d.json" % idx), "w", encoding="utf8"), ensure_ascii=False, indent=1)
        total += 1
        print("  %s: участков %d, площадь %.1f%%" % (f, len(rects), area * 100))
    print("Готово: текстур %d, ошибок %d -> %s" % (total, bad, OUT))

if __name__ == "__main__":
    main()

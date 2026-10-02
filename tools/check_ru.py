# -*- coding: utf-8 -*-
"""Проверка ru.json: ключи есть в игре, теги и плейсхолдеры совпадают с английским оригиналом.
Сначала выгрузи тексты игры: python tools/extract_loc.py "<папка игры>\POSTAL Brain Damaged_Data"
(создаст tools/loc_dump.json — его не коммитить, это тексты игры)."""
import json, re, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, 'loc_dump.json'), encoding='utf8'))
ru = json.load(open(os.path.join(HERE, '..', 'ru.json'), encoding='utf8'))
TAG = re.compile(r'\{\d+\}|<[^>]+>')
bad = 0
for k, v in ru.items():
    if k not in d: print('нет в игре:', k); bad += 1; continue
    en = d[k]['tr']['[EN]']
    if sorted(TAG.findall(en)) != sorted(TAG.findall(v)) or \
       re.findall(r'<input>(.*?)</input>', en) != re.findall(r'<input>(.*?)</input>', v):
        print('теги:', k, '\n  EN:', en, '\n  RU:', v); bad += 1
missing = [k for k in d if k not in ru]
print('строк: %d, ошибок: %d, без перевода: %d' % (len(ru), bad, len(missing)))
sys.exit(1 if bad else 0)

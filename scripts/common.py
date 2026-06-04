"""Общие функции отчёта (единая точка правды для всех скриптов)."""
import json, os, re

def load_map(state_dir, prefix):
    """Словарь ручных соответствий артикулов: merge_map_<PREFIX>.json.
    Заполняется Claude'ом, когда автоматика не видит, что два артикула —
    один товар (пример: 'Orzax-MILK THISTLE' == 'ORZAX MILK THISTLE PLUS').
    Формат: {"нормализованный артикул": "базовый артикул"}."""
    f = os.path.join(state_dir, f"merge_map_{prefix}.json")
    return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}

def base_art(art, mapping=None):
    """Базовый артикул: автонормализация + ручной словарь поверх."""
    b = norm(art)
    if mapping:
        return mapping.get(b, mapping.get((art or "").strip(), b))
    return b

def norm(art):
    """База артикула: срезаем маркеры дублей.
    Префиксы: (FBS)/!FBS/FBS/блок/блок2/бан. Суффиксы: фбо/фбс/fbo/fbs.
    Пример: 'Orzax, MAGNESIUM /60 табл./ фбо' == 'Orzax, MAGNESIUM /60 табл./'"""
    s = (art or "").strip()
    s = re.sub(r"^(!FBS\s*|\(FBS\)|FBS!|FBS\s+|бан|блок2|блок)\s*", "", s, flags=re.I)
    s = re.sub(r"[\s\-_]*(фбо|фбс|fbo|fbs)\s*$", "", s, flags=re.I)
    return s.strip()

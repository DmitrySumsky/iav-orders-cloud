#!/usr/bin/env python3
"""Бэкфилл истории заказов из TrueStats (замена медленных WB-батчей history.py
для брендов на TrueStats). Заполняет недостающие дни в history_<PREFIX>.json:
1 быстрый запрос TrueStats на день на маркетплейс вместо десятков батчей WB
(3 req/min). Дыры после простоев закрываются за секунды.

Формат истории — тот же, что у history.py:
  {"data": {<базовый артикул>: {<дата>: {"wb": N, "oz": N}}},
   "wb_dates": [...], "oz_dates": [...], "wb_done": [...]}

Использование:
  python3 history_ts.py --brand NATURI --keys api_keys.txt[,extra] --state-dir state [--days 30]
Печатает DONE, когда все дни на месте.
"""
import argparse, json, os, re, sys, time
from datetime import date, timedelta, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_map, base_art
from collect_ts import load_keys, ts_products
from direct_orders import ozon_units, wb_units, pick_source, total as dtotal

MSK = timezone(timedelta(hours=3))

p = argparse.ArgumentParser()
p.add_argument("--brand", required=True)
p.add_argument("--keys", required=True)
p.add_argument("--state-dir", required=True)
p.add_argument("--days", type=int, default=30)
a = p.parse_args()

prefix = re.sub(r"[^A-Z0-9]", "", a.brand.upper())
K = load_keys(a.keys)
contour = K.get(f"{prefix}_TS_TOKEN", "")
token = K.get(f"TRUESTATS_TOKEN_{contour.upper()}", "")
ts_wb = [int(x) for x in K.get(f"{prefix}_TS_WB_ACCOUNTS", "").split(",") if x.strip()]
ts_oz = [int(x) for x in K.get(f"{prefix}_TS_OZON_ACCOUNTS", "").split(",") if x.strip()]
if not token:
    print(f"ERROR: нет TrueStats-токена для {a.brand}"); sys.exit(1)

today = datetime.now(MSK).date()
yest = today - timedelta(days=1)
want = [(yest - timedelta(days=i)).isoformat() for i in range(a.days)]

hist_f = os.path.join(a.state_dir, f"history_{prefix}.json")
H = json.load(open(hist_f, encoding="utf-8")) if os.path.exists(hist_f) else \
    {"data": {}, "wb_done": [], "wb_dates": [], "oz_dates": []}
MAP = load_map(a.state_dir, prefix)

def add(base, day, platform, n):
    d = H["data"].setdefault(base, {}).setdefault(day, {"wb": 0, "oz": 0})
    d[platform] = d.get(platform, 0) + n

def clear(day, platform):
    """Стереть день перед перезаписью — иначе повторный сбор удвоит числа."""
    for per in H["data"].values():
        if day in per: per[day][platform] = 0

def fill(day, accounts, platform):
    """Кладёт заказы за день в историю. TrueStats — основной источник, но при
    его «заморозке» (нули вместо данных, см. direct_orders) день берётся из
    API маркетплейса."""
    rows = ts_products(token, accounts, day, day)
    ts_map, ids = {}, {}
    for r in rows:
        rid, art = str(r.get("article") or ""), r.get("vendorCode") or ""
        key = art or rid
        if rid: ids[rid] = art
        n = r.get("ordersCount") or 0
        if key and n:
            slot = ts_map.setdefault(key, {"orders": 0, "sum": 0})
            slot["orders"] += n
    use = ts_map
    if platform == "wb" and K.get(f"{prefix}_WB_TOKEN") and not dtotal(ts_map) and day in RECHECK:
        try:
            use, took, msg = pick_source(ts_map, wb_units(K[f"{prefix}_WB_TOKEN"], day, ids),
                                         f"WB история {day}")
            print(msg)
        except Exception as e:
            print(f"WB история {day}: сверка не вышла ({str(e)[:80]})")
    if platform == "oz" and K.get(f"{prefix}_OZON_API_KEY") and not dtotal(ts_map):
        try:
            fresh = ozon_units(K.get(f"{prefix}_OZON_CLIENT_ID", ""),
                               K[f"{prefix}_OZON_API_KEY"], day, ids)
            use, took, msg = pick_source(ts_map, fresh, f"Ozon история {day}")
            print(msg)
        except Exception as e:
            print(f"Ozon история {day}: сверка не вышла ({str(e)[:80]})")
    old = sum((per.get(day) or {}).get(platform, 0) for per in H["data"].values())
    if dtotal(use) < old:      # источник просел — сохранённое лучше нового
        print(f"{platform} {day}: источник дал {dtotal(use)} < {old} — оставляю прошлое")
        return len(rows), old
    clear(day, platform)
    for key, v in use.items():
        if v["orders"]: add(base_art(key, MAP), day, platform, v["orders"])
    return len(rows), dtotal(use)

# последние дни перекачиваем всегда: у маркетплейсов данные дозревают, а
# «замороженный» TrueStats мог записать в историю нули как факт
RECHECK = set(want[:3])

changed = False
for day in sorted(want):
    if ts_wb and (day not in H["wb_dates"] or day in RECHECK):
        n, tot = fill(day, ts_wb, "wb")
        H["wb_dates"] = sorted(set(H["wb_dates"]) | {day}); changed = True
        print(f"WB {day}: {n} строк, заказов {tot}")
        time.sleep(0.3)
    if ts_oz and (day not in H["oz_dates"] or day in RECHECK):
        n, tot = fill(day, ts_oz, "oz")
        H["oz_dates"] = sorted(set(H["oz_dates"]) | {day}); changed = True
        print(f"Ozon {day}: {n} строк, заказов {tot}")
        time.sleep(0.3)

if changed:
    json.dump(H, open(hist_f, "w", encoding="utf-8"), ensure_ascii=False)
wb_ok = (not ts_wb) or all(d in H["wb_dates"] for d in want)
oz_ok = (not ts_oz) or all(d in H["oz_dates"] for d in want)
print("DONE" if wb_ok and oz_ok else "PROGRESS — перезапусти")

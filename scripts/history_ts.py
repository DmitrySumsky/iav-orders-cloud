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
H = json.load(open(hist_f)) if os.path.exists(hist_f) else \
    {"data": {}, "wb_done": [], "wb_dates": [], "oz_dates": []}
MAP = load_map(a.state_dir, prefix)

def add(base, day, platform, n):
    d = H["data"].setdefault(base, {}).setdefault(day, {"wb": 0, "oz": 0})
    d[platform] = d.get(platform, 0) + n

def fill(day, accounts, platform):
    rows = ts_products(token, accounts, day, day)
    for r in rows:
        art = r.get("vendorCode") or str(r.get("article") or "")
        n = r.get("ordersCount") or 0
        if art and n:
            add(base_art(art, MAP), day, platform, n)
    return len(rows)

changed = False
for day in sorted(want):
    if ts_wb and day not in H["wb_dates"]:
        n = fill(day, ts_wb, "wb")
        H["wb_dates"] = sorted(set(H["wb_dates"]) | {day}); changed = True
        print(f"WB {day}: {n} строк из TrueStats")
        time.sleep(0.3)
    if ts_oz and day not in H["oz_dates"]:
        n = fill(day, ts_oz, "oz")
        H["oz_dates"] = sorted(set(H["oz_dates"]) | {day}); changed = True
        print(f"Ozon {day}: {n} строк из TrueStats")
        time.sleep(0.3)

if changed:
    json.dump(H, open(hist_f, "w"), ensure_ascii=False)
wb_ok = (not ts_wb) or all(d in H["wb_dates"] for d in want)
oz_ok = (not ts_oz) or all(d in H["oz_dates"] for d in want)
print("DONE" if wb_ok and oz_ok else "PROGRESS — перезапусти")

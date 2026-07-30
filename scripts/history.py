#!/usr/bin/env python3
"""Накопительная история заказов по дням (WB+Ozon) для листа «Общее».

Хранит .iav-orders/history_<PREFIX>.json:
  {"data": {<базовый артикул>: {<дата>: {"wb": N, "oz": N}}},
   "wb_done": [...пары окно|батч...], "wb_dates": [...], "oz_dates": [...]}

При первом запуске бэкфиллит последние --days дней (WB: окна по 7 дней,
батчи по 20 nmIds, 3 req/min — НЕБЫСТРО, скрипт резюмируемый, запускать
повторно до DONE). В ежедневном режиме дотягивает только недостающие дни.

Требует уже собранный state-файл collect.py (карточки + маппинг sku→offer).

Использование:
  python3 history.py --brand NATURI --keys api_keys.txt --state-dir .iav-orders [--days 30]
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import date, timedelta, datetime, timezone

TIME_BUDGET = int(__import__("os").environ.get("TIME_BUDGET", 33))
T0 = time.time()
MSK = timezone(timedelta(hours=3))
def budget_left(): return TIME_BUDGET - (time.time() - T0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import norm, load_map, base_art

p = argparse.ArgumentParser()
p.add_argument("--brand", required=True)
p.add_argument("--keys", required=True)
p.add_argument("--state-dir", required=True)
p.add_argument("--days", type=int, default=30)
a = p.parse_args()

prefix = re.sub(r"[^A-Z0-9]", "", a.brand.upper())
K = {}
for line in open(a.keys, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); K[k] = v.strip()
wb_token = K.get(f"{prefix}_WB_TOKEN", "")
oz_id, oz_key = K.get(f"{prefix}_OZON_CLIENT_ID", ""), K.get(f"{prefix}_OZON_API_KEY", "")

today = datetime.now(MSK).date()
yest = today - timedelta(days=1)
want_dates = [(yest - timedelta(days=i)).isoformat() for i in range(a.days)]

# state-файл за сегодня (карточки, маппинги)
state_f = os.path.join(a.state_dir, f"{prefix}_{yest.isoformat()}.json")
if not os.path.exists(state_f):
    print(f"ERROR: нет {state_f} — сначала запусти collect.py"); sys.exit(1)
S = json.load(open(state_f))

hist_f = os.path.join(a.state_dir, f"history_{prefix}.json")
H = json.load(open(hist_f)) if os.path.exists(hist_f) else \
    {"data": {}, "wb_done": [], "wb_dates": [], "oz_dates": []}
def save(): json.dump(H, open(hist_f, "w"), ensure_ascii=False)

def http(url, headers=None, body=None, timeout=60, _tries=12, _net_tries=3):
    # Автоповтор при 429/5xx и сетевых сбоях: один IP GitHub упирается в
    # rate-limit WB/Ozon, когда бренды идут подряд. Ждём и повторяем.
    # Таймаут ЧТЕНИЯ прилетает голым TimeoutError (urllib заворачивает в
    # URLError только фазу соединения) — ловим OSError целиком.
    req = urllib.request.Request(url, data=body, headers=headers or {})
    net_fails = 0
    for attempt in range(_tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < _tries - 1:
                wait = 0
                try: wait = int(e.headers.get("Retry-After", 0))
                except Exception: wait = 0
                time.sleep(wait or min(60, 5 * (2 ** attempt)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # висящий эндпоинт не должен съесть все 12 попыток по таймауту:
            # накопленное уже в файле, выходим кодом 0 — оркестратор повторит
            net_fails += 1
            if net_fails >= _net_tries or attempt == _tries - 1:
                print(f"{urllib.parse.urlsplit(url).netloc} не ответил "
                      f"({type(e).__name__}: {e}) — перезапусти")
                sys.exit(0)
            time.sleep(min(30, 5 * (2 ** net_fails)))

def add(art_base, day, platform, n):
    d = H["data"].setdefault(art_base, {}).setdefault(day, {"wb": 0, "oz": 0})
    d[platform] = d.get(platform, 0) + n

# ---------- WB ----------
# Три источника (от дешёвого к дорогому):
#   1. state-файл сегодняшнего сбора — вчера и позавчера, 0 запросов;
#   2. воронка history — окно не глубже 7 дней назад (ограничение WB);
#   3. funnel-products по одному дню — для дат старше 7 дней (бэкфилл).
if wb_token and S.get("has_wb"):
    MAP = load_map(a.state_dir, prefix)
    nm2base = {str(c["nmID"]): base_art(c["vendorCode"], MAP) for c in S["wb_cards"]}
    nm_all = [c["nmID"] for c in S["wb_cards"]]
    WB_H = {"Authorization": wb_token, "Content-Type": "application/json"}
    URL_HIST = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products/history"
    URL_PROD = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products"

    # 1) из state — бесплатно
    for day in (S["yest"], S["prev"]):
        if day in want_dates and day not in H["wb_dates"]:
            for nmid, per_day in S["wb_funnel"].items():
                base = nm2base.get(nmid)
                if base and day in per_day:
                    add(base, day, "wb", per_day[day].get("orders", 0))
            H["wb_dates"].append(day); save()

    def wb_throttle():
        if budget_left() < 26:
            print("PROGRESS — перезапусти (rate-limit пауза)"); sys.exit(0)
        time.sleep(21)

    # 2) последние 7 дней — окном через history
    recent_floor = (today - timedelta(days=7)).isoformat()
    recent_missing = sorted(d for d in want_dates
                            if d not in H["wb_dates"] and d >= recent_floor)
    if recent_missing:
        batches = [nm_all[i:i+20] for i in range(0, len(nm_all), 20)]
        w_start, w_end = recent_missing[0], recent_missing[-1]
        for bi, nm in enumerate(batches):
            key = f"win|{w_start}|{w_end}|{bi}"
            if key in H["wb_done"]: continue
            if budget_left() < 5:
                print("PROGRESS wb recent — перезапусти"); sys.exit(0)
            body = json.dumps({"nmIds": nm, "selectedPeriod": {"start": w_start, "end": w_end},
                               "aggregationLevel": "day"}).encode()
            try:
                d = http(URL_HIST, WB_H, body)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    print(f"WB {e.code} — перезапусти через минуту"); sys.exit(0)
                print("WB ERR", e.code, e.read()[:200]); sys.exit(1)
            payload = d.get("data", d) if isinstance(d, dict) else d
            for prod in (payload if isinstance(payload, list) else payload.get("products", [])):
                nmid = str((prod.get("product") or {}).get("nmId") or "")
                base = nm2base.get(nmid)
                if not base: continue
                for h in prod.get("history", []):
                    day = (h.get("date") or h.get("dt"))[:10]
                    if day in recent_missing:
                        add(base, day, "wb", h.get("orderCount", 0) or 0)
            H["wb_done"].append(key); save()
            print(f"WB recent батч {bi+1}/{len(batches)}")
            if bi + 1 < len(batches): wb_throttle()
        H["wb_dates"] = sorted(set(H["wb_dates"]) | set(recent_missing)); save()

    # 3) бэкфилл старых дат — funnel-products по одному дню, батчи по 50
    # один запрос дня X возвращает ещё и past = день X-1 — берём по 2 дня за запрос
    batches50 = [nm_all[i:i+50] for i in range(0, len(nm_all), 50)]
    while True:
        old_missing = sorted((d for d in want_dates
                              if d not in H["wb_dates"] and d < recent_floor), reverse=True)
        if not old_missing: break
        day = old_missing[0]
        prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        take_past = prev_day in old_missing
        for bi, nm in enumerate(batches50):
            key = f"pd|{day}|{bi}"
            if key in H["wb_done"]: continue
            if budget_left() < 5:
                print(f"PROGRESS wb backfill (осталось {len(old_missing)} дней) — перезапусти"); sys.exit(0)
            body = json.dumps({"nmIds": nm, "selectedPeriod": {"start": day, "end": day}}).encode()
            try:
                d = http(URL_PROD, WB_H, body)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    print(f"WB {e.code} — перезапусти через минуту"); sys.exit(0)
                print("WB ERR", e.code, e.read()[:200]); sys.exit(1)
            for p_ in d.get("data", {}).get("products", []):
                nmid = str((p_.get("product") or {}).get("nmId") or "")
                base = nm2base.get(nmid)
                if not base: continue
                st_ = p_.get("statistic") or {}
                add(base, day, "wb", (st_.get("selected") or {}).get("orderCount", 0) or 0)
                if take_past:
                    add(base, prev_day, "wb", (st_.get("past") or {}).get("orderCount", 0) or 0)
            H["wb_done"].append(key); save()
            wb_throttle()
        new_dates = {day} | ({prev_day} if take_past else set())
        H["wb_dates"] = sorted(set(H["wb_dates"]) | new_dates); save()
        print(f"WB backfill {day}{' + ' + prev_day if take_past else ''} готов")

# ---------- Ozon ----------
if oz_id and oz_key and S.get("has_oz"):
    MAP2 = load_map(a.state_dir, prefix)
    missing = [d for d in want_dates if d not in H["oz_dates"]]
    if missing:
        sku2base = {}
        for sku, v in (S.get("ozon") or {}).items():
            sku2base[str(sku)] = base_art(v.get("offer_id") or v.get("name", ""), MAP2)
        OZ_H = {"Client-Id": oz_id, "Api-Key": oz_key, "Content-Type": "application/json"}
        offset = 0
        while True:
            body = json.dumps({"date_from": min(missing), "date_to": max(missing),
                               "metrics": ["ordered_units"], "dimension": ["sku", "day"],
                               "limit": 1000, "offset": offset}).encode()
            d = http("https://api-seller.ozon.ru/v1/analytics/data", OZ_H, body)
            rows = d.get("result", {}).get("data", [])
            for r in rows:
                dims = r["dimensions"]
                sku = dims[0]["id"]; day = dims[1]["id"][:10]
                if day not in missing: continue
                base = sku2base.get(str(sku))
                if not base:  # sku вне сегодняшнего маппинга — берём имя из ответа
                    base = base_art(dims[0].get("name", ""), MAP2) or str(sku)
                add(base, day, "oz", r["metrics"][0])
            if len(rows) < 1000: break
            offset += 1000; time.sleep(1)
        H["oz_dates"] = sorted(set(H["oz_dates"]) | set(missing)); save()
        print(f"Ozon history: +{len(missing)} дней")

wb_ok = (not (wb_token and S.get("has_wb"))) or all(d in H["wb_dates"] for d in want_dates)
oz_ok = (not (oz_id and oz_key and S.get("has_oz"))) or all(d in H["oz_dates"] for d in want_dates)
print("DONE" if wb_ok and oz_ok else "PROGRESS — перезапусти")

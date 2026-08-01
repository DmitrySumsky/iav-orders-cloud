#!/usr/bin/env python3
"""Быстрый сбор ядра отчёта из TrueStats (заказы/выручка/остатки/цены)
+ воронка Ozon напрямую (быстро). Воронка WB (переходы/корзины) сюда НЕ
собирается — она приходит из ночного прогона collect.py и подмешивается:
скрипт СЛИВАЕТ данные TrueStats в существующий state-файл, если он есть.

Ядро отчёта не зависит от лимитов WB: даже если ночной сбор воронки упал,
заказы/выручка за вчера/позавчера будут свежими из TrueStats.

Ключи в api_keys (можно несколько файлов через запятую, последний побеждает):
  TRUESTATS_TOKEN_IGOR / TRUESTATS_TOKEN_VEXOR — токены контуров
  <BRAND>_TS_TOKEN=igor|vexor        — какой контур у бренда
  <BRAND>_TS_WB_ACCOUNTS=13668       — id WB-кабинетов TrueStats (через запятую)
  <BRAND>_TS_OZON_ACCOUNTS=13604     — id Ozon-кабинетов TrueStats

Использование:
  python3 collect_ts.py --brand NATURI --keys api_keys.txt[,api_keys_extra.txt] --state-dir state [--compare]
Печатает DONE в конце (как collect.py); --compare — сверка с данными,
уже лежащими в state (старый сборщик), без изменения поведения.
"""
import argparse, io, json, os, re, sys, time, urllib.request, urllib.error, uuid, zipfile
from datetime import date, timedelta, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from direct_orders import ozon_units, wb_units, pick_source, total as dtotal

MSK = timezone(timedelta(hours=3))
TS_BASE = "https://api.truestats.ru"
WB_AN = "https://seller-analytics-api.wildberries.ru"

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", required=True)
    p.add_argument("--keys", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--compare", action="store_true")
    return p.parse_args()

def load_keys(paths):
    d = {}
    for path in paths.split(","):
        path = path.strip()
        if not path or not os.path.exists(path): continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); d[k.strip()] = v.strip()
    return d

def http(url, headers=None, body=None, timeout=90, tries=5):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(60, 5 * (2 ** attempt))); continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            if attempt < tries - 1:
                time.sleep(min(30, 5 * (2 ** attempt))); continue
            raise
    raise RuntimeError(last)

def ts_call(token, path, body):
    # Капканы TrueStats: без User-Agent отдаёт 500; изредка 500 на тяжёлых — ретраим
    H = {"X-Api-Token": token, "Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    return http(TS_BASE + path, H, json.dumps(body).encode())

def ts_products(token, accounts, d_from, d_to):
    """Все строки /reporting/main/products за период (с пагинацией)."""
    rows, page = [], 1
    while True:
        d = ts_call(token, "/reporting/main/products",
                    {"dateFrom": d_from, "dateTo": d_to,
                     "filters": {"accounts": accounts},
                     "groupBy": "nm_id", "limit": 500, "page": page})
        got = d.get("byProduct") or []
        rows += got
        pag = d.get("pagination") or {}
        total_pages = pag.get("totalPages") or pag.get("pages") or 1
        if page >= total_pages or not got: break
        page += 1
    return rows

def http_raw(url, headers=None, timeout=90):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def wb_funnel_async(wb_token, d_from, d_to, wait_sec=480):
    """Воронка WB одним асинхронным CSV-отчётом (без лимита 3 req/min).
    Возвращает {nm: {date: {open, cart, orders, orderSum}}} или None при сбое —
    вызывающий код тогда оставляет данные TrueStats (отчёт уходит без воронки)."""
    H = {"Authorization": wb_token, "Content-Type": "application/json"}
    rid = str(uuid.uuid4())
    body = json.dumps({"id": rid, "reportType": "DETAIL_HISTORY_REPORT",
                       "params": {"startDate": d_from, "endDate": d_to,
                                  "aggregationLevel": "day"}}).encode()
    try:
        # у создания отчёта свой лимит (~1/мин) — ждём терпеливо
        http(WB_AN + "/api/v2/nm-report/downloads", H, body, tries=8)
    except Exception as e:
        print(f"WB async: не удалось создать отчёт ({e})"); return None
    t0 = time.time()
    status = ""
    while time.time() - t0 < wait_sec:
        time.sleep(10)
        try:
            d = http(WB_AN + "/api/v2/nm-report/downloads", H, tries=2)
        except Exception:
            continue
        mine = [x for x in (d.get("data") or []) if x.get("id") == rid]
        status = (mine[0].get("status") or "") if mine else ""
        if status.upper() in ("SUCCESS", "DONE", "READY"): break
        if status.upper() in ("FAILED", "ERROR"):
            print(f"WB async: отчёт упал ({status})"); return None
    else:
        print(f"WB async: не дождались отчёта за {wait_sec}с (статус {status})"); return None
    try:
        raw = http_raw(WB_AN + f"/api/v2/nm-report/downloads/file/{rid}", H, timeout=120)
        z = zipfile.ZipFile(io.BytesIO(raw))
        text = z.read(z.namelist()[0]).decode("utf-8")
    except Exception as e:
        print(f"WB async: не удалось скачать файл ({e})"); return None
    lines = text.splitlines()
    hdr = lines[0].split(",")
    idx = {name: hdr.index(name) for name in
           ("nmID", "dt", "openCardCount", "addToCartCount", "ordersCount", "ordersSumRub")}
    out = {}
    for line in lines[1:]:
        c = line.split(",")
        if len(c) < len(hdr): continue
        nm, day = c[idx["nmID"]], c[idx["dt"]]
        out.setdefault(nm, {})[day] = {
            "open": int(c[idx["openCardCount"]] or 0), "cart": int(c[idx["addToCartCount"]] or 0),
            "orders": int(c[idx["ordersCount"]] or 0), "orderSum": int(float(c[idx["ordersSumRub"]] or 0))}
    return out

def wb_funnel_batched(wb_token, nm_all, d_from, d_to):
    """Запасной путь: воронка батчами по 20 nmId (лимит 3 req/min, терпеливые
    ретраи). Возвращает {nm: {date: {...}}}; частичный результат лучше нуля."""
    H = {"Authorization": wb_token, "Content-Type": "application/json"}
    out, batches = {"_complete": False}, [nm_all[i:i+20] for i in range(0, len(nm_all), 20)]
    for i, nm in enumerate(batches):
        body = json.dumps({"nmIds": [int(x) for x in nm],
                           "selectedPeriod": {"start": d_from, "end": d_to},
                           "aggregationLevel": "day"}).encode()
        try:
            d = http(WB_AN + "/api/analytics/v3/sales-funnel/products/history",
                     H, body, timeout=60, tries=8)
        except Exception as e:
            print(f"WB батчи: батч {i+1}/{len(batches)} не взят ({e}) — воронка частичная")
            return out
        payload = d.get("data", d) if isinstance(d, dict) else d
        for prod in (payload if isinstance(payload, list) else payload.get("products", [])):
            nmid = str((prod.get("product") or {}).get("nmId") or prod.get("nmID") or "")
            if not nmid: continue
            for h in prod.get("history", []):
                day = (h.get("date") or h.get("dt"))[:10]
                out.setdefault(nmid, {})[day] = {
                    "open": h.get("openCount", 0) or 0, "cart": h.get("cartCount", 0) or 0,
                    "orders": h.get("orderCount", 0) or 0, "orderSum": h.get("orderSum", 0) or 0}
        print(f"WB батчи: {i+1}/{len(batches)}")
        if i + 1 < len(batches): time.sleep(21)
    out["_complete"] = True
    return out

def main():
    a = parse_args()
    prefix = re.sub(r"[^A-Z0-9]", "", a.brand.upper())
    K = load_keys(a.keys)

    contour = K.get(f"{prefix}_TS_TOKEN", "")
    token = K.get(f"TRUESTATS_TOKEN_{contour.upper()}", "")
    ts_wb = [int(x) for x in K.get(f"{prefix}_TS_WB_ACCOUNTS", "").split(",") if x.strip()]
    ts_oz = [int(x) for x in K.get(f"{prefix}_TS_OZON_ACCOUNTS", "").split(",") if x.strip()]
    if not token or not (ts_wb or ts_oz):
        print(f"ERROR: нет TrueStats-настроек для {a.brand} "
              f"(нужны {prefix}_TS_TOKEN и {prefix}_TS_WB_ACCOUNTS/{prefix}_TS_OZON_ACCOUNTS)")
        sys.exit(1)
    oz_id, oz_key = K.get(f"{prefix}_OZON_CLIENT_ID", ""), K.get(f"{prefix}_OZON_API_KEY", "")

    today = datetime.now(MSK).date()
    d_yest = (today - timedelta(days=1)).isoformat()
    d_prev = (today - timedelta(days=2)).isoformat()
    d14_from = (today - timedelta(days=14)).isoformat()

    os.makedirs(a.state_dir, exist_ok=True)
    state_f = os.path.join(a.state_dir, f"{prefix}_{d_yest}.json")
    S = None
    if os.path.exists(state_f):
        try:
            S = json.load(open(state_f))
            if not isinstance(S, dict) or "brand" not in S:
                print(f"ВНИМАНИЕ: {state_f} повреждён/чужой — пересоздаю"); S = None
        except Exception:
            print(f"ВНИМАНИЕ: {state_f} не читается — пересоздаю"); S = None
    # Снимок уже собранных заказов: прогонов за день несколько (06:45 сбор,
    # 07:30 отправка), и если во втором источник «просел» (замёрзший TrueStats,
    # 429 у WB), нельзя затирать то, что первый прогон уже добыл.
    def snapshot(state):
        if not isinstance(state, dict): return {}
        snap = {}
        for day in (d_prev, d_yest):
            snap[("wb", day)] = {nm: (v.get(day) or {}).get("orders", 0) or 0
                                 for nm, v in (state.get("wb_funnel") or {}).items()}
            snap[("oz", day)] = {sku: (v.get(day) or {}).get("orders", 0) or 0
                                 for sku, v in (state.get("ozon") or {}).items()}
        return snap

    SNAP = snapshot(S)
    if S is None:
        S = {
        "brand": a.brand, "yest": d_yest, "prev": d_prev,
        "has_wb": bool(ts_wb), "has_oz": bool(ts_oz),
        "wb_cards": None, "wb_funnel_done": 0, "wb_funnel": {},
        "wb_orders14": None, "wb_stocks": {},
        "ozon": None, "oz_stocks": None, "oz_orders14": None}
    cmp_report = []

    def diff(tag, nm, old, new):
        if old is not None and old != new:
            cmp_report.append(f"{tag} {nm}: старое {old} -> TrueStats {new}")

    # ---------- WB из TrueStats ----------
    if ts_wb:
        day_rows = {d: ts_products(token, ts_wb, d, d) for d in (d_prev, d_yest)}
        rows14 = ts_products(token, ts_wb, d14_from, d_yest)
        print(f"TS WB: {d_yest} {len(day_rows[d_yest])} строк, "
              f"{d_prev} {len(day_rows[d_prev])}, 14д {len(rows14)}")

        S["has_wb"] = True
        cards = {str(c["nmID"]): c for c in (S.get("wb_cards") or [])}
        funnel = S.setdefault("wb_funnel", {})
        prices = dict(S.get("wb_client_price") or {})
        for day, rows in day_rows.items():
            for r in rows:
                nm = str(r.get("article") or "")
                if not nm: continue
                cards.setdefault(nm, {"nmID": int(nm), "vendorCode": r.get("vendorCode") or "",
                                      "title": r.get("vendorCode") or ""})
                per = funnel.setdefault(nm, {}).setdefault(day, {"open": 0, "cart": 0,
                                                                 "orders": 0, "orderSum": 0})
                if a.compare:
                    diff(f"WB заказы {day}", nm, per.get("orders"), r.get("ordersCount") or 0)
                per["orders"] = r.get("ordersCount") or 0
                per["orderSum"] = r.get("orders") or 0
                if day == d_yest and r.get("averagePriceAfterSPP"):
                    prices[nm] = round(r["averagePriceAfterSPP"])
        o14, stocks = {}, dict(S.get("wb_stocks") or {})
        for r in rows14:
            nm = str(r.get("article") or "")
            if not nm: continue
            o14[nm] = r.get("ordersCount") or 0
            stocks[nm] = r.get("stockBalanceInWh") or 0
            cards.setdefault(nm, {"nmID": int(nm), "vendorCode": r.get("vendorCode") or "",
                                  "title": r.get("vendorCode") or ""})
        S["wb_cards"] = list(cards.values())
        S["wb_orders14"] = o14
        S["wb_stocks"] = stocks
        S["wb_client_price"] = prices

        # Воронка WB (переходы/корзины) — асинхронный CSV-отчёт, один запрос
        # на весь кабинет. При сбое отчёт уходит с данными TrueStats без воронки.
        wb_token = K.get(f"{prefix}_WB_TOKEN", "")
        if wb_token and not S.get("wb_funnel_async_done"):
            fun, complete = wb_funnel_async(wb_token, d_prev, d_yest), True
            if not fun:
                print("WB async недоступен — пробую батчами (запасной путь)")
                fun = wb_funnel_batched(wb_token, [str(c["nmID"]) for c in S["wb_cards"]],
                                        d_prev, d_yest)
                complete = bool(fun.pop("_complete", False))
            if fun:
                for nm, days in fun.items():
                    slot = funnel.setdefault(nm, {})
                    for day, v in days.items():
                        if a.compare:
                            diff(f"WB воронка-заказы {day}", nm,
                                 (slot.get(day) or {}).get("orders"), v["orders"])
                        slot[day] = v
                if complete: S["wb_funnel_async_done"] = 1  # полная воронка получена
                print(f"WB воронка: {len(fun)} артикулов" + ("" if complete else " (частично, дособерём при повторе)"))
            else:
                print("WB воронка недоступна — в отчёте будут нули в переходах/корзинах")

    # Сверка дня с первоисточниками. Неполный день приходит молча с обеих
    # сторон: TrueStats при остановке своего сбора отдаёт нули, а аналитика WB
    # ночью ещё не дозрела (31.07.2026 в 04 МСК отчёт WB давал у SUNSHINE 218
    # заказов, к полудню — 574 за тот же день). Проверяем, когда день выглядит
    # обрубленным, и берём источник с бОльшим числом заказов.
    def verify_wb(force=False):
        wb_tok = K.get(f"{prefix}_WB_TOKEN", "")
        if not (ts_wb and wb_tok): return
        funnel = S.setdefault("wb_funnel", {})
        for day, base in ((d_yest, d_prev), (d_prev, None)):
            def day_map():
                return {nm: {"orders": (v.get(day) or {}).get("orders", 0) or 0,
                             "sum": (v.get(day) or {}).get("orderSum", 0) or 0}
                        for nm, v in funnel.items()}
            cur = was = day_map()             # was — то, что попало в 14-дневный итог
            ref = (sum((v.get(base) or {}).get("orders", 0) or 0 for v in funnel.values())
                   if base else 0)
            if not force and dtotal(cur) and (not base or dtotal(cur) >= 0.6 * ref):
                continue                      # день выглядит целым — не тратим запросы
            # 1) пересобрать отчёт WB: те же переходы/корзины, но дозревшие
            fun = wb_funnel_async(wb_tok, day, day, wait_sec=240)
            if fun:
                for nm, days in fun.items():
                    if day in days: funnel.setdefault(nm, {})[day] = days[day]
                print(f"WB {day}: отчёт пересобран, заказов {dtotal(day_map())}")
                cur = day_map()
            # 2) statistics-api — первоисточник, но лимит 1 запрос в минуту на
            # кабинет и его выедают сторонние сервисы, поэтому вторым
            try:
                use, took, msg = pick_source(cur, wb_units(wb_tok, day), f"WB заказы {day}")
                print(msg)
            except Exception as e:
                print(f"WB сверка {day}: statistics-api не ответил ({str(e)[:80]})")
                use, took = cur, False
            if took:
                for nm in set(cur) | set(use):
                    slot = funnel.setdefault(nm, {}).setdefault(
                        day, {"open": 0, "cart": 0, "orders": 0, "orderSum": 0})
                    slot["orders"] = use.get(nm, {}).get("orders", 0)
                    slot["orderSum"] = use.get(nm, {}).get("sum", 0) or slot.get("orderSum", 0)
            if day == d_yest and S.get("wb_orders14") is not None:
                for nm, v in day_map().items():   # 14 дней собраны из TrueStats
                    S["wb_orders14"][nm] = max(   # — доливаем разницу за вчера
                        0, (S["wb_orders14"].get(nm, 0) or 0)
                        - was.get(nm, {}).get("orders", 0) + v["orders"])

    ts_frozen = False       # TrueStats замёрз на этом дне (видно по Ozon)

    # ---------- Ozon из TrueStats ----------
    if ts_oz:
        day_rows = {d: ts_products(token, ts_oz, d, d) for d in (d_prev, d_yest)}
        rows14 = ts_products(token, ts_oz, d14_from, d_yest)
        print(f"TS Ozon: {d_yest} {len(day_rows[d_yest])} строк, "
              f"{d_prev} {len(day_rows[d_prev])}, 14д {len(rows14)}")

        S["has_oz"] = True
        oz = S.get("ozon") or {}
        cp = dict(S.get("oz_client_price") or {})
        for day, rows in day_rows.items():
            for r in rows:
                sku = str(r.get("article") or "")
                if not sku: continue
                rec = oz.setdefault(sku, {"name": r.get("vendorCode") or "",
                                          "offer_id": r.get("vendorCode") or ""})
                old = rec.get(day, {})
                if a.compare:
                    diff(f"Ozon заказы {day}", sku, old.get("orders"), r.get("ordersCount") or 0)
                rec[day] = {"orders": r.get("ordersCount") or 0, "revenue": r.get("orders") or 0,
                            "view": old.get("view", 0), "view_pdp": old.get("view_pdp", 0),
                            "tocart": old.get("tocart", 0)}
                if day == d_yest and r.get("averagePriceAfterSPP"):
                    cp[sku] = round(r["averagePriceAfterSPP"])
        o14, stocks = {}, dict(S.get("oz_stocks") or {})
        for r in rows14:
            sku = str(r.get("article") or "")
            if not sku: continue
            o14[sku] = r.get("ordersCount") or 0
            offer = r.get("vendorCode") or ""
            if offer: stocks[offer] = r.get("stockBalanceInWh") or 0
        S["ozon"] = oz
        S["oz_orders14"] = o14
        S["oz_stocks"] = stocks
        S["oz_client_price"] = cp

        # Воронка Ozon (показы/просмотры/корзины) — напрямую, Ozon API быстрый
        if oz_id and oz_key:
            OZ_H = {"Client-Id": oz_id, "Api-Key": oz_key, "Content-Type": "application/json"}
            for day in (d_prev, d_yest):
                body = json.dumps({"date_from": day, "date_to": day,
                                   "metrics": ["ordered_units", "revenue", "hits_view",
                                               "hits_view_pdp", "hits_tocart"],
                                   "dimension": ["sku"], "limit": 1000, "offset": 0}).encode()
                d = http("https://api-seller.ozon.ru/v1/analytics/data", OZ_H, body)
                for row in d.get("result", {}).get("data", []):
                    sku = row["dimensions"][0]["id"]
                    m = (row["metrics"] + [0] * 5)[:5]
                    rec = oz.get(str(sku))
                    if rec is None:
                        rec = oz.setdefault(str(sku), {"name": row["dimensions"][0]["name"],
                                                       "offer_id": ""})
                    per = rec.setdefault(day, {"orders": m[0], "revenue": m[1]})
                    per["view"], per["view_pdp"], per["tocart"] = m[2], m[3], m[4]
                time.sleep(1)
            print("Ozon воронка: ок")

            # Сверка заказов с кабинетом Ozon — тот же ответ analytics/data,
            # что и у старого сборщика. Стоит один запрос на день, поэтому
            # проверяем оба дня всегда (TrueStats замерзал именно на Ozon).
            for day in (d_prev, d_yest):
                cur = {sku: {"orders": (v.get(day) or {}).get("orders", 0) or 0,
                             "sum": (v.get(day) or {}).get("revenue", 0) or 0}
                       for sku, v in oz.items()}
                try:
                    fresh = ozon_units(oz_id, oz_key, day)
                except Exception as e:
                    print(f"Ozon сверка {day}: не вышло ({str(e)[:80]})"); continue
                use, took, msg = pick_source(cur, fresh, f"Ozon заказы {day}")
                print(msg)
                if took and not sum(v["orders"] for v in cur.values()):
                    ts_frozen = True      # ноль вместо данных = сбор TS стоит
                if took:
                    for sku in set(cur) | set(use):
                        rec = oz.setdefault(sku, {"name": "", "offer_id": ""})
                        slot = rec.setdefault(day, {"orders": 0, "revenue": 0, "view": 0,
                                                    "view_pdp": 0, "tocart": 0})
                        was = slot.get("orders", 0) or 0
                        slot["orders"] = use.get(sku, {}).get("orders", 0)
                        slot["revenue"] = use.get(sku, {}).get("sum", 0) or slot.get("revenue", 0)
                        if day == d_yest and S.get("oz_orders14") is not None:
                            S["oz_orders14"][sku] = max(
                                0, (S["oz_orders14"].get(sku, 0) or 0) + slot["orders"] - was)
                time.sleep(1)
        else:
            print("Ozon воронка: нет ключей кабинета — пропуск")

    # WB проверяем последним: если Ozon показал, что TrueStats стоит, WB-день
    # сверяем принудительно — просадка там могла не дотянуть до порога
    verify_wb(force=ts_frozen)

    # заказы за день не уменьшаем: собранное прошлым прогоном лучше просевшего
    for (kind, day), per in SNAP.items():
        store = (S.get("wb_funnel") if kind == "wb" else S.get("ozon")) or {}
        back = 0
        for key, was in per.items():
            slot = (store.get(key) or {}).get(day)
            if slot and (slot.get("orders", 0) or 0) < was:
                back += was - slot["orders"]; slot["orders"] = was
        if back:
            print(f"{'WB' if kind == 'wb' else 'Ozon'} {day}: источник просел, "
                  f"вернул {back} шт из прошлого прогона")

    json.dump(S, open(state_f, "w"), ensure_ascii=False)
    if a.compare and cmp_report:
        print(f"--- СВЕРКА: {len(cmp_report)} расхождений ---")
        for line in cmp_report[:40]: print("  " + line)
    elif a.compare:
        print("--- СВЕРКА: расхождений нет ---")
    wb_y = sum((f.get(d_yest) or {}).get("orders", 0) for f in S.get("wb_funnel", {}).values())
    oz_y = sum((v.get(d_yest) or {}).get("orders", 0) for v in (S.get("ozon") or {}).values())
    print(f"Заказы вчера: WB {wb_y}, Ozon {oz_y}")
    print("DONE")

if __name__ == "__main__":
    main()

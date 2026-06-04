#!/usr/bin/env python3
"""Сбор данных WB (воронка) + Ozon (аналитика) по бренду за вчера/позавчера
+ фильтр активности (остатки сегодня, заказы за 14 дней).

Резюмируемый: состояние пишется в <state_dir>/<BRAND>_<дата>.json.
Запускать ПОВТОРНО, пока не напечатает DONE (WB rate-limit 3 req/min не
влезает в один 45-секундный вызов на кабинетах > 40 SKU).

Использование:
  python3 collect.py --brand NATURI --keys /path/api_keys.txt --state-dir /path/.iav-orders
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import date, timedelta, datetime, timezone

TIME_BUDGET = int(__import__("os").environ.get("TIME_BUDGET", 33))
T0 = time.time()
MSK = timezone(timedelta(hours=3))

def budget_left(): return TIME_BUDGET - (time.time() - T0)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", required=True)
    p.add_argument("--keys", required=True)
    p.add_argument("--state-dir", required=True)
    return p.parse_args()

def load_keys(path):
    d = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); d[k] = v.strip()
    return d

def http(url, headers=None, body=None, timeout=35):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def main():
    a = parse_args()
    prefix = re.sub(r"[^A-Z0-9]", "", a.brand.upper())
    K = load_keys(a.keys)
    wb_token = K.get(f"{prefix}_WB_TOKEN", "")
    oz_id, oz_key = K.get(f"{prefix}_OZON_CLIENT_ID", ""), K.get(f"{prefix}_OZON_API_KEY", "")
    has_wb, has_oz = bool(wb_token), bool(oz_id and oz_key)
    if not has_wb and not has_oz:
        print(f"ERROR: в {a.keys} нет ключей для бренда {a.brand} (префикс {prefix})"); sys.exit(1)

    today = datetime.now(MSK).date()
    d_yest = (today - timedelta(days=1)).isoformat()
    d_prev = (today - timedelta(days=2)).isoformat()
    d14_from = (today - timedelta(days=14)).isoformat()

    os.makedirs(a.state_dir, exist_ok=True)
    state_f = os.path.join(a.state_dir, f"{prefix}_{d_yest}.json")
    S = json.load(open(state_f)) if os.path.exists(state_f) else {
        "brand": a.brand, "yest": d_yest, "prev": d_prev,
        "has_wb": has_wb, "has_oz": has_oz,
        "wb_cards": None, "wb_funnel_done": 0, "wb_funnel": {},
        "wb_orders14": None, "wb_stocks": {},
        "ozon": None, "oz_stocks": None, "oz_orders14": None}
    def save(): json.dump(S, open(state_f, "w"), ensure_ascii=False)

    WB_H = {"Authorization": wb_token, "Content-Type": "application/json"}
    OZ_H = {"Client-Id": oz_id, "Api-Key": oz_key, "Content-Type": "application/json"}

    # ---------- WB ----------
    if has_wb and S["wb_cards"] is None:
        cards, cursor = [], {"limit": 100}
        while True:
            body = json.dumps({"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}}).encode()
            d = http("https://content-api.wildberries.ru/content/v2/get/cards/list", WB_H, body)
            got = d.get("cards", [])
            for c in got:
                cards.append({"nmID": c["nmID"], "vendorCode": c.get("vendorCode", ""),
                              "title": c.get("title", "")})
            cur = d.get("cursor", {})
            if len(got) < 100: break
            cursor = {"limit": 100, "updatedAt": cur.get("updatedAt"), "nmID": cur.get("nmID")}
            time.sleep(0.7)
        S["wb_cards"] = cards; save()
        print(f"WB cards: {len(cards)}")

    if has_wb:
        nm_all = [c["nmID"] for c in S["wb_cards"]]
        batches = [nm_all[i:i+20] for i in range(0, len(nm_all), 20)]
        # воронка за 2 дня (история): батчи по 20, 3 req/min
        while S["wb_funnel_done"] < len(batches):
            if budget_left() < 5:
                print(f"PROGRESS wb_funnel {S['wb_funnel_done']}/{len(batches)} — перезапусти"); return
            nm = batches[S["wb_funnel_done"]]
            body = json.dumps({"nmIds": nm, "selectedPeriod": {"start": d_prev, "end": d_yest},
                               "aggregationLevel": "day"}).encode()
            try:
                d = http("https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products/history",
                         WB_H, body, timeout=60)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print("WB 429 — перезапусти через минуту"); return
                print("WB funnel ERR", e.code, e.read()[:200]); sys.exit(1)
            payload = d.get("data", d) if isinstance(d, dict) else d
            for prod in (payload if isinstance(payload, list) else payload.get("products", [])):
                nmid = str((prod.get("product") or {}).get("nmId") or prod.get("nmID") or "")
                if not nmid: continue
                per_day = {}
                for h in prod.get("history", []):
                    per_day[(h.get("date") or h.get("dt"))[:10]] = {
                        "open": h.get("openCount", 0) or 0, "cart": h.get("cartCount", 0) or 0,
                        "orders": h.get("orderCount", 0) or 0, "orderSum": h.get("orderSum", 0) or 0}
                S["wb_funnel"][nmid] = per_day
            S["wb_funnel_done"] += 1; save()
            print(f"WB funnel batch {S['wb_funnel_done']}/{len(batches)}")
            if S["wb_funnel_done"] < len(batches):
                if budget_left() < 26:
                    print("PROGRESS — перезапусти (rate-limit пауза)"); return
                time.sleep(21)

        # заказы за 14 дней + остатки: funnel-products.
        # ВАЖНО: параметр page игнорируется API (возвращает всегда первые 50) — nmIds явно!
        if S["wb_orders14"] is None:
            if budget_left() < 26:
                print("PROGRESS wb_orders14 pending — перезапусти"); return
            time.sleep(21)  # после истории — общий rate-limit seller-analytics
            orders = dict(S.get("wb_o14_partial", {}))
            todo = [nm for nm in nm_all if str(nm) not in orders]
            while todo:
                if budget_left() < 5:
                    S["wb_o14_partial"] = orders; save()
                    print("PROGRESS wb_orders14 — перезапусти"); return
                batch = todo[:50]
                body = json.dumps({"selectedPeriod": {"start": d14_from, "end": d_yest},
                                   "nmIds": batch}).encode()
                try:
                    d = http("https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products",
                             WB_H, body, timeout=60)
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        S["wb_o14_partial"] = orders; save()
                        print("WB 429 — перезапусти через минуту"); return
                    raise
                got = set()
                for p in d.get("data", {}).get("products", []):
                    prod = p.get("product") or {}
                    nm = str(prod.get("nmId") or "")
                    if not nm: continue
                    got.add(nm)
                    sel = (p.get("statistic") or {}).get("selected", {})
                    orders[nm] = sel.get("orderCount", 0) or 0
                    st = prod.get("stocks") or {}
                    S["wb_stocks"][nm] = (st.get("wb", 0) or 0) + (st.get("mp", 0) or 0)
                for nm in batch:
                    if str(nm) not in got: orders[str(nm)] = 0
                todo = todo[len(batch):]
                S["wb_o14_partial"] = orders; save()
                if todo:
                    if budget_left() < 12: print("PROGRESS wb_orders14 — перезапусти"); return
                    time.sleep(8)
            S["wb_orders14"] = orders; S.pop("wb_o14_partial", None); save()
            print(f"WB orders14: {len(orders)}")

    # ---------- Ozon (быстро, без жёстких лимитов) ----------
    if has_oz and S["ozon"] is None:
        items, last_id = [], ""
        while True:
            body = json.dumps({"filter": {"visibility": "ALL"}, "limit": 1000, "last_id": last_id}).encode()
            d = http("https://api-seller.ozon.ru/v3/product/list", OZ_H, body)
            res = d.get("result", {})
            items += res.get("items", []); last_id = res.get("last_id", "")
            if len(res.get("items", [])) < 1000 or not last_id: break
        pid2offer = {it["product_id"]: it["offer_id"] for it in items}
        sku2offer = {}
        pids = list(pid2offer)
        for i in range(0, len(pids), 100):
            body = json.dumps({"product_id": pids[i:i+100]}).encode()
            d = http("https://api-seller.ozon.ru/v3/product/info/list", OZ_H, body)
            for it in d.get("items", []):
                offer = it.get("offer_id") or pid2offer.get(it.get("id"), "")
                for sk in ([it.get("sku")] + [s.get("sku") for s in it.get("sources", [])]):
                    if sk: sku2offer[str(sk)] = offer
            time.sleep(0.4)
        oz = {}
        for day in (d_prev, d_yest):
            body = json.dumps({"date_from": day, "date_to": day,
                               "metrics": ["ordered_units", "revenue", "hits_view", "hits_view_pdp", "hits_tocart"],
                               "dimension": ["sku"], "limit": 1000, "offset": 0}).encode()
            d = http("https://api-seller.ozon.ru/v1/analytics/data", OZ_H, body, timeout=60)
            for row in d.get("result", {}).get("data", []):
                sku = row["dimensions"][0]["id"]
                # без Ozon Premium API молча отдаёт только первые метрики — добиваем нулями
                m = (row["metrics"] + [0] * 5)[:5]
                rec = oz.setdefault(sku, {"name": row["dimensions"][0]["name"],
                                          "offer_id": sku2offer.get(sku, "")})
                rec[day] = {"orders": m[0], "revenue": m[1], "view": m[2],
                            "view_pdp": m[3], "tocart": m[4]}
            time.sleep(1)
        S["ozon"] = oz; save()
        print(f"Ozon skus: {len(oz)}")

    if has_oz and S["oz_stocks"] is None:
        st, cursor = {}, ""
        while True:
            body = json.dumps({"filter": {"visibility": "ALL"}, "limit": 1000, "cursor": cursor}).encode()
            d = http("https://api-seller.ozon.ru/v4/product/info/stocks", OZ_H, body)
            items = d.get("items", d.get("result", {}).get("items", []))
            for it in items:
                offer = it.get("offer_id", "")
                st[offer] = st.get(offer, 0) + sum((s.get("present", 0) or 0) for s in it.get("stocks", []))
            cursor = d.get("cursor", "")
            if len(items) < 1000 or not cursor: break
        S["oz_stocks"] = st; save()
        print(f"Ozon stocks: {len(st)}")

    if has_oz and S["oz_orders14"] is None:
        body = json.dumps({"date_from": d14_from, "date_to": d_yest,
                           "metrics": ["ordered_units"], "dimension": ["sku"],
                           "limit": 1000, "offset": 0}).encode()
        d = http("https://api-seller.ozon.ru/v1/analytics/data", OZ_H, body, timeout=60)
        S["oz_orders14"] = {r["dimensions"][0]["id"]: r["metrics"][0]
                            for r in d.get("result", {}).get("data", [])}
        save()
        print(f"Ozon orders14: {len(S['oz_orders14'])}")

    wb_ok = (not has_wb) or (S["wb_cards"] is not None and
             S["wb_funnel_done"] >= (len(S["wb_cards"]) + 19)//20 and S["wb_orders14"] is not None)
    oz_ok = (not has_oz) or (S["ozon"] is not None and S["oz_stocks"] is not None
                             and S["oz_orders14"] is not None)
    print("DONE" if wb_ok and oz_ok else "PROGRESS — перезапусти")

if __name__ == "__main__":
    main()

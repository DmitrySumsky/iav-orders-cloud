#!/usr/bin/env python3
"""Прямые источники заказов за день — страховка от «замерзания» TrueStats.

Зачем: TrueStats — зеркало, и когда его сбор останавливается, API отвечает
200 с НУЛЯМИ, а не ошибкой (31.07.2026: Ozon — 0 заказов у всех кабинетов
обоих контуров, WB — неполный день). Отчёт при этом уходит «успешно», но с
нулями. Поэтому день сверяется с первоисточником: Ozon Seller API и WB
Statistics API.

Правило выбора: оба источника умеют только НЕДОдать заказы (заморозка сбора,
лаг выгрузки), но не выдумать лишние — значит за день берём тот, где заказов
больше (см. pick_source).

Формат всех функций: {ключ артикула: {"orders": шт, "sum": руб}}. Ключ — тот
же, что кладёт TrueStats (vendorCode у WB, offer_id у Ozon), чтобы данные
ложились в существующие структуры state без переделки.
"""
import json, time, urllib.error, urllib.parse, urllib.request

OZ_BASE = "https://api-seller.ozon.ru"
WB_STAT = "https://statistics-api.wildberries.ru"

# насколько прямой источник должен обгонять TrueStats, чтобы его предпочесть
GAP = 1.02


def _http(url, headers=None, body=None, timeout=120, tries=5):
    req = urllib.request.Request(url, data=body, headers=headers or {})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(65 if e.code == 429 else min(60, 5 * (2 ** attempt)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < tries - 1:
                time.sleep(min(30, 5 * (2 ** attempt))); continue
            raise


def total(m):
    return sum(v["orders"] for v in m.values())


def pick_source(ts_map, direct_map, tag=""):
    """Из двух карт выбирает ту, где заказов ощутимо больше.
    Возвращает (карта, взят_ли_прямой_источник, строка для лога)."""
    ts_n, dr_n = total(ts_map), total(direct_map)
    if dr_n > ts_n * GAP:
        return direct_map, True, f"{tag}: TrueStats {ts_n} < API {dr_n} — беру API"
    return ts_map, False, f"{tag}: TrueStats {ts_n}, API {dr_n} — оставляю TrueStats"


# ---------------------------------------------------------------- Ozon
def ozon_units(client_id, api_key, day, sku2offer=None):
    """Заказы за день из /v1/analytics/data (первоисточник кабинета).
    sku2offer=None — ключи остаются sku (как в state брендового отчёта);
    словарь (пусть и пустой) — ключи переводятся в offer_id, недостающие
    соответствия добираются из каталога (как нужно своду)."""
    H = {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
    raw, offset = {}, 0
    while True:
        body = json.dumps({"date_from": day, "date_to": day,
                           "metrics": ["ordered_units", "revenue"], "dimension": ["sku"],
                           "limit": 1000, "offset": offset}).encode()
        d = _http(OZ_BASE + "/v1/analytics/data", H, body)
        rows = (d.get("result") or {}).get("data") or []
        for row in rows:
            sku = str(row["dimensions"][0]["id"])
            m = (row.get("metrics") or []) + [0, 0]
            n = int(m[0] or 0)
            if n:
                r = raw.setdefault(sku, {"orders": 0, "sum": 0})
                r["orders"] += n; r["sum"] += m[1] or 0
        if len(rows) < 1000: break
        offset += 1000
        time.sleep(1)
    if sku2offer is None:
        return raw
    m = dict(sku2offer)
    unknown = [s for s in raw if s not in m]
    if unknown:
        m.update(ozon_sku_offers(client_id, api_key, unknown))
    out = {}
    for sku, v in raw.items():
        key = m.get(sku) or sku
        o = out.setdefault(key, {"orders": 0, "sum": 0})
        o["orders"] += v["orders"]; o["sum"] += v["sum"]
    return out


def ozon_sku_offers(client_id, api_key, skus):
    """{sku: offer_id} — для тех sku, которых нет в карте TrueStats."""
    H = {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
    out, skus = {}, [str(s) for s in skus]
    for i in range(0, len(skus), 100):
        body = json.dumps({"sku": [int(s) for s in skus[i:i + 100] if s.isdigit()]}).encode()
        try:
            d = _http(OZ_BASE + "/v3/product/info/list", H, body)
        except Exception as e:
            print(f"Ozon sku→offer_id: не сопоставлено ({str(e)[:80]})"); break
        for it in d.get("items", []):
            offer = it.get("offer_id") or ""
            if not offer: continue
            for sk in [it.get("sku")] + [s.get("sku") for s in (it.get("sources") or [])]:
                if sk: out[str(sk)] = offer
        time.sleep(0.4)
    return out


# ---------------------------------------------------------------- WB
def wb_units(token, day, nm2vendor=None):
    """Заказы за день из statistics-api: flag=1 — все заказы этой даты,
    одна запись = одна штука, отменённые не в счёт. Лимит эндпоинта —
    1 запрос в минуту на кабинет, поэтому дёргаем только при подозрении."""
    url = WB_STAT + "/api/v1/supplier/orders?" + urllib.parse.urlencode(
        {"dateFrom": day, "flag": 1})
    rows = _http(url, {"Authorization": token}, timeout=300)
    m, out = dict(nm2vendor or {}), {}
    for r in rows or []:
        if r.get("isCancel"): continue
        nm = str(r.get("nmId") or "")
        if not nm: continue
        key = m.get(nm) or nm
        o = out.setdefault(key, {"orders": 0, "sum": 0})
        o["orders"] += 1
        o["sum"] += r.get("finishedPrice") or 0
    return out

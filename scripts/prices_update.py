#!/usr/bin/env python3
"""Отчёт по ценам WB + Ozon: ежедневное обновление таблицы «Аналитика цен»
из MPStats (облачная версия скилла wb-ceny-konkurentov + Ozon-контур).

Листы одной таблицы:
  - первый лист книги               — WB, цена wallet_price (с WB-Кошельком)
  - лист с «ozon» в имени (если есть) — Ozon, цена ozon_card_price (с Ozon Картой)
Раскладка листа: A=название, B=артикул(nmID/SKU), C=бренд, D..=даты DD.MM (свежая слева).

Логика по каждому листу: узнать последнюю дату MPStats -> вставить недостающие
столбцы слева (история не трогается) -> заполнить; пустой ответ MPStats никогда
не затирает старые значения. Конкурентов в строки добавляют руками — скрипт
подхватывает любые новые строки.

Использование:
  python3 prices_update.py --keys api_keys.txt[,extra] --sa google_sa.json --sheet-id <ID>
Печатает DONE при успехе.
"""
import argparse, json, re, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import jwt

BASE = "https://sheets.googleapis.com/v4/spreadsheets/"
FIRST_DATE_COL = 4  # D (1-based)

def load_keys(paths):
    d = {}
    for p in paths.split(","):
        p = p.strip()
        if not p: continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); d[k.strip()] = v.strip()
    return d

def token_of(sa_path):
    SA = json.load(open(sa_path)); now = int(time.time())
    a_ = jwt.encode({"iss": SA["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
        SA["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": a_}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]

def api(path, tok, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def col_letter(i0):
    s, i = "", i0 + 1
    while i:
        i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s

def hdr_to_iso(s, today):
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%d.%m"):
        try:
            dt = datetime.strptime(s, fmt).date()
            if fmt == "%d.%m":
                y = today.year
                if date(y, dt.month, dt.day) > today: y -= 1
                return date(y, dt.month, dt.day).isoformat()
            return dt.isoformat()
        except ValueError:
            continue
    return None

def mp_history(art, mp_token, mp_kind, field, tries=4):
    """История цен MPStats: {iso_date: цена}. Пусто при недоступности."""
    url = f"https://mpstats.io/api/{mp_kind}/get/item/{art}/sales"
    req = urllib.request.Request(url, headers={"X-Mpstats-TOKEN": mp_token,
                                               "Content-Type": "application/json"})
    rows = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                rows = json.loads(r.read()); break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503): time.sleep(1.0 * (i + 1)); continue
            return {}
        except Exception:
            time.sleep(0.7 * (i + 1))
    out = {}
    if isinstance(rows, list):
        for r in rows:
            d = r.get("data"); v = r.get(field) or r.get("final_price")
            if d and v: out[d] = round(v)
    return out

def as_int(x):
    x = re.sub(r"[^\d]", "", str(x))
    return int(x) if x else ""

def process_tab(sheet_id, tok, props, mp_token, mp_kind, field, workers):
    """Один лист: догнать даты + заполнить пустые. Возвращает None или ошибку."""
    title, gid = props["title"], props["sheetId"]
    q = "'" + title.replace("'", "''") + "'"; qurl = urllib.parse.quote(q)
    today = date.today()

    rows = api(f"{sheet_id}/values/{qurl}!A2:C5000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])
    arts = [(r + 2, row[1].strip()) for r, row in enumerate(rows)
            if len(row) > 1 and row[1].strip().isdigit()]
    if not arts:
        print(f"[{title}] нет строк с артикулами — пропуск"); return None

    # последняя дата у MPStats (проба по первым артикулам)
    lat = None
    for _, probe in arts[:5]:
        h = mp_history(probe, mp_token, mp_kind, field)
        if h: lat = max(h.keys()); break
    if not lat:
        return f"[{title}] MPStats не ответил на пробы"
    lat = datetime.strptime(lat, "%Y-%m-%d").date()

    hdr = api(f"{sheet_id}/values/{qurl}!A1:BZ1?valueRenderOption=FORMATTED_VALUE",
              tok).get("values", [[]])[0]
    existing = []
    for i, v in enumerate(hdr):
        if i >= FIRST_DATE_COL - 1 and str(v).strip():
            iso = hdr_to_iso(str(v), today)
            if iso: existing.append(datetime.strptime(iso, "%Y-%m-%d").date())
    newest = max(existing) if existing else (lat - timedelta(days=1))
    print(f"[{title}] в таблице по {newest}, у MPStats по {lat}, строк {len(arts)}")

    missing = []
    d = lat
    while d > newest:
        missing.append(d); d -= timedelta(days=1)
    if missing:
        n = len(missing)
        api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
            {"insertDimension": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": FIRST_DATE_COL - 1, "endIndex": FIRST_DATE_COL - 1 + n},
                "inheritFromBefore": False}}]})
        last_new = col_letter(FIRST_DATE_COL - 1 + n - 1)
        api(sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
            "data": [{"range": f"{q}!{col_letter(FIRST_DATE_COL-1)}1:{last_new}1",
                      "values": [[x.strftime('%d.%m') for x in missing]]}]})
        print(f"[{title}] добавлены даты: {[x.strftime('%d.%m') for x in missing]}")

    # полная заливка окна дат (существующее не затирается пустотой)
    hdr = api(f"{sheet_id}/values/{qurl}!A1:BZ1?valueRenderOption=FORMATTED_VALUE",
              tok).get("values", [[]])[0]
    col_iso = {}
    for i, v in enumerate(hdr):
        if i >= FIRST_DATE_COL - 1 and str(v).strip():
            iso = hdr_to_iso(str(v), today)
            if iso: col_iso[i] = iso
    lo, hi = min(col_iso), max(col_iso)
    newest_col = max(col_iso, key=lambda c: col_iso[c])
    last = col_letter(hi)
    data = api(f"{sheet_id}/values/{qurl}!A2:{last}5000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])
    todo = []
    for r, row in enumerate(data):
        art = row[1].strip() if len(row) > 1 else ""
        if not art.isdigit(): continue
        ex_vals = [as_int(row[ci]) if len(row) > ci else "" for ci in range(lo, hi + 1)]
        need = missing or not str(row[newest_col] if len(row) > newest_col else "").strip()
        if need: todo.append((r + 2, art, ex_vals))
    print(f"[{title}] к заливке: {len(todo)} строк")

    def fetch(item):
        rownum, art, ex_vals = item
        h = mp_history(art, mp_token, mp_kind, field)
        vals = []
        for k, ci in enumerate(range(lo, hi + 1)):
            iso = col_iso.get(ci)
            v = h.get(iso) if (iso and iso in h) else ex_vals[k]
            vals.append(v if v is not None else "")
        return rownum, vals

    updates, filled = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rownum, vals in ex.map(fetch, todo):
            filled += sum(1 for v in vals if v != "")
            updates.append({"range": f"{q}!{col_letter(lo)}{rownum}:{last}{rownum}",
                            "values": [vals]})
    for i in range(0, len(updates), 60):
        api(sheet_id + "/values:batchUpdate", tok, "POST",
            {"valueInputOption": "USER_ENTERED", "data": updates[i:i + 60]})
    print(f"[{title}] залито ячеек: {filled}")
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", required=True)
    ap.add_argument("--sa", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    K = load_keys(a.keys)
    mp_token = K.get("MPSTATS_TOKEN", "")
    if not mp_token:
        print("ERROR: нет MPSTATS_TOKEN"); sys.exit(1)
    tok = token_of(a.sa)
    meta = api(a.sheet_id + "?fields=sheets.properties(sheetId,title,index)", tok)
    sheets = sorted((s["properties"] for s in meta["sheets"]), key=lambda p_: p_.get("index", 0))

    errors = []
    err = process_tab(a.sheet_id, tok, sheets[0], mp_token, "wb", "wallet_price", a.workers)
    if err: errors.append(err)
    oz_tab = next((p_ for p_ in sheets if "ozon" in p_["title"].lower()
                   or "озон" in p_["title"].lower()), None)
    if oz_tab:
        err = process_tab(a.sheet_id, tok, oz_tab, mp_token, "oz", "ozon_card_price", a.workers)
        if err: errors.append(err)
    else:
        print("Листа Ozon нет — только WB")

    if errors:
        print("ОШИБКИ:", "; ".join(errors)); sys.exit(1)
    print("DONE")

if __name__ == "__main__":
    main()

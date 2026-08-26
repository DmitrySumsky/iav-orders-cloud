#!/usr/bin/env python3
"""ЦЕНЫ WB ПО ПОЗИЦИЯМ v1.0.0 — 26.08.2026

История версий (новое сверху, старое не переписывать):

v1.0.0 — 26.08.2026
  В СВОДЕ «ОБЩАЯ» НЕ БЫЛО ЦЕН — их смотрели руками в книге «Цены», где
  «Позиция» проставлялась вручную и матрица «Общее» так и осталась пустой
  (задача Дмитрия, 26.08.2026).
  • Два новых листа в книге свода: «Цены» (позиция × бренд: цена без скидки,
    скидка %, цена со скидкой) и «История цен» (позиция × бренд × дни,
    свежая дата слева, до 60 колонок).
  • Позиции берутся из ЛИСТА «Маппинг позиций» — того же, по которому
    считаются заказы. Отдельного ручного сопоставления нет: строка цены и
    строка заказов по одному товару всегда совпадают.
  • Источник — `discounts-prices-api…/api/v2/list/goods/filter` своего
    кабинета: `price` = цена ДО скидки (её мы и ставим), `discountedPrice` =
    цена ПОСЛЕ нашей скидки и ДО СПП. Публичная витрина не годится: там
    цена уже с СПП, и своей скидки в ней не видно.
  • Лимитер «Цены и скидки» общий НА КАБИНЕТ (10 запросов/6 с со всеми
    подключёнными сервисами) — ждём по заголовку `X-Ratelimit-Retry`, а не
    вслепую, и между кабинетами держим паузу.
  • Один товар = несколько артикулов (FBS-двойник, бан-карточка): цена
    берётся с ОСНОВНОГО артикула (`common.norm` срезает маркеры дублей),
    расхождение цен внутри позиции печатается в лог.
  • Артикул кабинета, которого нет в маппинге (нет заказов за 60 дней),
    не теряется — уходит в конец листа строкой со своим артикулом.

Использование:
  python3 svod_prices.py --keys api_keys.txt[,extra] --sa google_sa.json \\
      [--sheet-id <ID>] [--dry-run]
Печатает DONE при успехе.
"""
import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_ts import load_keys
from common import norm as art_norm

MSK = timezone(timedelta(hours=3))
MAPR = "Маппинг позиций"
CUR = "Цены"
HIST = "История цен"
HIST_MAX = 60
GOODS_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"

p = argparse.ArgumentParser()
p.add_argument("--keys", required=True)
p.add_argument("--sa", required=True)
p.add_argument("--sheet-id", default="")
p.add_argument("--goods-json", default="", help="отладка: взять товары из файла, не ходить в WB")
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()

K = load_keys(a.keys)
SHEET_ID = a.sheet_id or K.get("SVOD_GSHEET_ID", "")
brands_cfg = [x.strip() for x in K.get("SVOD_BRANDS", "").split(",") if x.strip()]
BRANDS = [(b.split("=")[0].strip(), b.split("=")[1].strip()) for b in brands_cfg if "=" in b]
if not SHEET_ID or not BRANDS:
    print("ERROR: нужны SVOD_GSHEET_ID и SVOD_BRANDS в ключах"); sys.exit(1)
DISP = [d for d, _ in BRANDS]
TODAY = datetime.now(MSK).date()
DD = TODAY.strftime("%d.%m")

# ---------------------------------------------------------------- WB: цены
def wb_goods(token):
    """Все товары кабинета с ценой и скидкой. Лимитер общий на кабинет —
    ждём столько, сколько просит сам WB (`X-Ratelimit-Retry`)."""
    out, off = [], 0
    while True:
        url = f"{GOODS_URL}?limit=1000&offset={off}"
        r = None
        for att in range(6):
            try:
                req = urllib.request.Request(url, headers={"Authorization": token})
                r = json.loads(urllib.request.urlopen(req, timeout=90).read())
                break
            except urllib.error.HTTPError as e:
                wait = int(e.headers.get("X-Ratelimit-Retry") or 0) or 20 * (att + 1)
                print(f"    HTTP {e.code} — жду {wait} с", flush=True); time.sleep(wait)
            except Exception as e:
                print(f"    сеть {type(e).__name__} — жду 15 с", flush=True); time.sleep(15)
        if r is None:
            raise RuntimeError("WB не ответил после 6 попыток")
        g = r.get("data", {}).get("listGoods", []) or []
        out += g
        if len(g) < 1000: return out
        off += 1000; time.sleep(3)

def price_of(good):
    """(цена без скидки, скидка %, цена со скидкой) по товару.
    Размеров у БАДа один; если их несколько с разной ценой — берём меньшую
    цену клиента, чтобы не завысить картину."""
    sizes = [s for s in (good.get("sizes") or []) if s.get("price")]
    if not sizes: return None
    s = min(sizes, key=lambda x: x.get("discountedPrice") or x.get("price") or 0)
    return (s.get("price"), good.get("discount"), s.get("discountedPrice"))

errors = []
goods = {}
if a.goods_json:
    goods = json.load(open(a.goods_json, encoding="utf-8"))
    print("товары из файла:", {k: len(v) for k, v in goods.items()})
for disp, pref in ([] if a.goods_json else BRANDS):
    tok = K.get(f"{pref}_WB_TOKEN", "")
    if not tok:
        errors.append(f"{disp}: нет WB-токена"); goods[disp] = []; continue
    try:
        goods[disp] = wb_goods(tok)
        print(f"{disp}: товаров в кабинете {len(goods[disp])}", flush=True)
    except Exception as e:
        errors.append(f"{disp}: {e}"); goods[disp] = []
        print(f"{disp}: ОШИБКА {e}", flush=True)
    time.sleep(4)

# ------------------------------------------------------------ Google Sheets
import jwt
SA = json.load(open(a.sa, encoding="utf-8"))
now = int(time.time())
assertion = jwt.encode({"iss": SA["client_email"],
                        "scope": "https://www.googleapis.com/auth/spreadsheets",
                        "aud": "https://oauth2.googleapis.com/token",
                        "iat": now, "exp": now + 3600},
                       SA["private_key"], algorithm="RS256")
body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": assertion}).encode()
TOK = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]
H = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
BASE = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"

def api(url, payload=None, method=None, tries=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=H, method=method)
    for att in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and att < tries - 1:
                time.sleep(min(30, 3 * (2 ** att))); continue
            print(f"Sheets API {e.code}: {e.read().decode()[:400]}")
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if att < tries - 1:
                time.sleep(min(30, 3 * (2 ** att))); continue
            raise

def col_a1(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s

def hexrgb(h):
    return {"red": int(h[1:3], 16) / 255, "green": int(h[3:5], 16) / 255, "blue": int(h[5:7], 16) / 255}

meta = api(f"{BASE}?fields=sheets(properties(sheetId,title,index))")
props = {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}

def ensure(title):
    if title not in props:
        r = api(f"{BASE}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": title}}}]})
        props[title] = r["replies"][0]["addSheet"]["properties"]
    return props[title]["sheetId"]

def values(rng):
    return api(f"{BASE}/values/{urllib.parse.quote(rng)}").get("values", [])

# --------------------------------------------- позиции из «Маппинг позиций»
rows = values(f"{MAPR}!A2:{col_a1(1 + len(BRANDS))}10000")
positions, by_offer = [], {}
for rw in rows:
    pos = (rw[0] if rw else "").strip()
    if not pos: continue
    if pos not in positions: positions.append(pos)
    for bi, disp in enumerate(DISP):
        for o in (rw[1 + bi] if len(rw) > 1 + bi else "").split(","):
            o = o.strip()
            if o: by_offer[disp + "||" + o] = pos

# ------------------------------------- цена позиции = цена основного артикула
cell = {}          # (позиция, бренд) -> (цена, скидка, цена со скидкой)
extra = []         # артикулы кабинета вне маппинга
spread = []
for disp in DISP:
    seen = {}
    for g in goods.get(disp, []):
        pr = price_of(g)
        if not pr: continue
        vc = (g.get("vendorCode") or "").strip()
        pos = by_offer.get(disp + "||" + vc)
        if not pos:
            extra.append((disp, vc, pr)); continue
        main = art_norm(vc) == vc          # артикул без маркеров дубля
        prev = seen.get(pos)
        if prev is None or (main and not prev[1]):
            seen[pos] = (pr, main, vc)
        elif prev[0][2] != pr[2] and prev[1] == main:
            spread.append((disp, pos, prev[2], prev[0][2], vc, pr[2]))
    for pos, (pr, _, _) in seen.items():
        cell[(pos, disp)] = pr

print(f"позиций с ценой: {len({p for p, _ in cell})} | артикулов вне маппинга: {len(extra)}")
for d, pos, v1, p1, v2, p2 in spread[:20]:
    print(f"  ⚠ {d} «{pos}»: {v1} = {p1} ₽, {v2} = {p2} ₽ — взята первая")
if errors: print("Ошибки кабинетов:", "; ".join(errors))

if a.dry_run:
    for pos in positions[:15]:
        print(" ", pos, {d: cell.get((pos, d)) for d in DISP if (pos, d) in cell})
    print("DRY RUN — в таблицу не пишу"); print("DONE"); sys.exit(0)

# --------------------------------------------------------------- лист «Цены»
GREEN, GREY = "#38761D", "#F3F3F3"
head2 = ["Позиция"]
for d in DISP: head2 += [f"{d}\nцена без скидки", f"{d}\nскидка, %", f"{d}\nцена со скидкой"]
ncol = len(head2)

body = []
for pos in positions:
    if not any((pos, d) in cell for d in DISP): continue
    rw = [pos]
    for d in DISP:
        v = cell.get((pos, d))
        rw += ["", "", ""] if not v else [v[0], v[1], v[2]]
    body.append(rw)
if extra:
    body.append(["— артикулы кабинета без заказов за 60 дней (в маппинге их нет) —"] + [""] * (ncol - 1))
for disp, vc, pr in sorted(extra):
    rw = [vc]
    for d in DISP:
        rw += [pr[0], pr[1], pr[2]] if d == disp else ["", "", ""]
    body.append(rw)

warn = " ⚠ НЕПОЛНЫЕ ДАННЫЕ" if errors else ""
table = [[f"ЦЕНЫ WB на {DD}{warn}"] + [""] * (ncol - 1), head2] + body

sid = ensure(CUR)
api(f"{BASE}/values/{urllib.parse.quote(CUR)}!A1?valueInputOption=RAW",
    {"values": table}, method="PUT")
api(f"{BASE}/values/{urllib.parse.quote(CUR)}!A{len(table) + 1}:{col_a1(ncol)}10000:clear",
    {}, method="POST")
api(f"{BASE}:batchUpdate", {"requests": [
    {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"backgroundColor": hexrgb(GREEN),
                                                   "horizontalAlignment": "LEFT",
                                                   "textFormat": {"bold": True, "fontSize": 12,
                                                                  "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                    "fields": "userEnteredFormat"}},
    {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2},
                    "cell": {"userEnteredFormat": {"backgroundColor": hexrgb(GREY),
                                                   "horizontalAlignment": "CENTER",
                                                   "wrapStrategy": "WRAP",
                                                   "textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat"}},
    {"updateSheetProperties": {"properties": {"sheetId": sid,
                                              "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 1}},
                               "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
    {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                             "startIndex": 0, "endIndex": 1},
                                   "properties": {"pixelSize": 330}, "fields": "pixelSize"}},
]})
print(f"«{CUR}»: строк {len(body)}")

# ---------------------------------------------------------- «История цен»
# лист заводим ДО чтения: у несуществующего листа Sheets отвечает 400
# «Unable to parse range», а не пустым значением
hsid = ensure(HIST)
old = values(f"{HIST}!A1:{col_a1(2 + HIST_MAX)}10000")
old_head = old[1] if len(old) > 1 else []
dates = [d for d in old_head[2:] if d.strip()]
old_rows = {}
for rw in old[2:] if len(old) > 2 else []:
    if len(rw) > 1 and rw[0].strip():
        old_rows[(rw[0], rw[1])] = (rw + [""] * (2 + len(dates)))[2:2 + len(dates)]

dates_new = dates if DD in dates else ([DD] + dates)[:HIST_MAX]

# порядок строк — как в маппинге (позиция, дальше бренды слева направо),
# чтобы «История цен» читалась в одном порядке с «Ценами» и листами заказов
today_row = {}
for pos in positions:
    for d in DISP:
        if (pos, d) in cell: today_row[(pos, d)] = cell[(pos, d)]
for disp, vc, pr in sorted(extra): today_row[(vc, disp)] = pr
keys = list(old_rows) + [k for k in today_row if k not in old_rows]
hbody = []
for k in keys:
    prev = old_rows.get(k, [])
    line = ([""] * len(dates_new))
    for i, dt in enumerate(dates_new):
        if dt == DD and k in today_row: line[i] = today_row[k][2]
        elif dt in dates: line[i] = (prev[dates.index(dt)] if dates.index(dt) < len(prev) else "")
    if any(str(x).strip() for x in line): hbody.append([k[0], k[1]] + line)

hhead = [[f"ИСТОРИЯ ЦЕН WB — цена со скидкой (до СПП), ₽"] + [""] * (1 + len(dates_new)),
         ["Позиция", "Бренд"] + dates_new]
api(f"{BASE}/values/{urllib.parse.quote(HIST)}!A1?valueInputOption=RAW",
    {"values": hhead + hbody}, method="PUT")
api(f"{BASE}/values/{urllib.parse.quote(HIST)}!A{len(hhead) + len(hbody) + 1}:"
    f"{col_a1(2 + HIST_MAX)}10000:clear", {}, method="POST")
api(f"{BASE}:batchUpdate", {"requests": [
    {"repeatCell": {"range": {"sheetId": hsid, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"backgroundColor": hexrgb(GREEN),
                                                   "textFormat": {"bold": True, "fontSize": 12,
                                                                  "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                    "fields": "userEnteredFormat"}},
    {"repeatCell": {"range": {"sheetId": hsid, "startRowIndex": 1, "endRowIndex": 2},
                    "cell": {"userEnteredFormat": {"backgroundColor": hexrgb(GREY),
                                                   "horizontalAlignment": "CENTER",
                                                   "textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat"}},
    {"updateSheetProperties": {"properties": {"sheetId": hsid,
                                              "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 2}},
                               "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
    {"updateDimensionProperties": {"range": {"sheetId": hsid, "dimension": "COLUMNS",
                                             "startIndex": 0, "endIndex": 1},
                                   "properties": {"pixelSize": 330}, "fields": "pixelSize"}},
]})
print(f"«{HIST}»: строк {len(hbody)}, колонок дат {len(dates_new)}")
print("DONE")

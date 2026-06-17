#!/usr/bin/env python3
"""Перезапись отчёта в Google Таблице (одна и та же таблица каждый день).

Пишет листы WB / Ozon / Общее: значения + формулы дельт + форматирование
(шапка, ИТОГО в строке 2, закрепление, форматы чисел, подсветка Δ
зелёным/красным). Старые условные форматы листа удаляются, чтобы правила
не копились при ежедневной перезаписи.

Требует: pip install PyJWT cryptography --break-system-packages

Использование:
  python3 push_gsheet.py --state <state.json> --sa <service_account.json> --sheet-id <ID>

ВНИМАНИЕ: построение строк дублирует build_excel.py — менять синхронно.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
import jwt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import norm, load_map, base_art

p = argparse.ArgumentParser()
p.add_argument("--state", required=True)
p.add_argument("--sa", required=True)
p.add_argument("--sheet-id", required=True)
p.add_argument("--history", default="", help="history_<PREFIX>.json для колонок прошлых дней в «Общее»")
a = p.parse_args()

S = json.load(open(a.state))
MAP = load_map(os.path.dirname(os.path.abspath(a.state)), __import__("re").sub(r"[^A-Z0-9]", "", S["brand"].upper()))
Y, P = S["yest"], S["prev"]
ddmm = lambda iso: f"{iso[8:10]}.{iso[5:7]}"
Y_L, P_L = ddmm(Y), ddmm(P)

# ---------- строки (синхронно с build_excel.py; norm — из common.py) ----------
def wb_active(nm):
    nm = str(nm)
    return S.get("wb_stocks", {}).get(nm, 0) > 0 or S.get("wb_orders14", {}).get(nm, 0) > 0

def oz_active(offer, sku):
    return (S.get("oz_stocks", {}) or {}).get(offer, 0) > 0 or \
           (S.get("oz_orders14", {}) or {}).get(str(sku), 0) > 0

wb_rows, oz_rows = [], []
if S.get("has_wb"):
    for c in S["wb_cards"]:
        if not wb_active(c["nmID"]): continue
        f = S["wb_funnel"].get(str(c["nmID"]), {})
        y, pp = f.get(Y, {}), f.get(P, {})
        if not y and not pp: continue
        wb_rows.append({"art": c["vendorCode"], "nm": c["nmID"],
            "o_y": y.get("orders", 0), "o_p": pp.get("orders", 0),
            "v_y": y.get("open", 0),   "v_p": pp.get("open", 0),
            "c_y": y.get("cart", 0),   "c_p": pp.get("cart", 0),
            "rev_y": y.get("orderSum", 0),
            "cp": (S.get("wb_client_price") or {}).get(str(c["nmID"]))})
    wb_rows.sort(key=lambda r: -r["o_y"])
if S.get("has_oz"):
    for sku, v in (S.get("ozon") or {}).items():
        if not oz_active(v.get("offer_id", ""), sku): continue
        y, pp = v.get(Y, {}), v.get(P, {})
        if not y and not pp: continue
        oz_rows.append({"art": v.get("offer_id") or v["name"], "sku": sku,
            "o_y": y.get("orders", 0),    "o_p": pp.get("orders", 0),
            "sh_y": y.get("view", 0),     "sh_p": pp.get("view", 0),
            "cl_y": y.get("view_pdp", 0), "cl_p": pp.get("view_pdp", 0),
            "c_y": y.get("tocart", 0),    "c_p": pp.get("tocart", 0),
            "rev_y": y.get("revenue", 0),
            "cp": (S.get("oz_client_price") or {}).get(str(sku))})
    oz_rows.sort(key=lambda r: -r["o_y"])
agg = {}
for row in wb_rows:
    g = agg.setdefault(base_art(row["art"], MAP), {"y": 0, "p": 0}); g["y"] += row["o_y"]; g["p"] += row["o_p"]
for row in oz_rows:
    g = agg.setdefault(base_art(row["art"], MAP), {"y": 0, "p": 0}); g["y"] += row["o_y"]; g["p"] += row["o_p"]
items = sorted(agg.items(), key=lambda kv: -kv[1]["y"])

# ---------- Google API ----------
SA = json.load(open(a.sa))
now = int(time.time())
assertion = jwt.encode({"iss": SA["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
    "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
    SA["private_key"], algorithm="RS256")
body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": assertion}).encode()
TOK = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]
H = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
BASE = f"https://sheets.googleapis.com/v4/spreadsheets/{a.sheet_id}"

def api(url, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=H, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

meta = api(f"{BASE}?fields=sheets(properties(sheetId,title),conditionalFormats)")
sheets = {s["properties"]["title"]: s for s in meta["sheets"]}

def ensure_sheet(title):
    if title not in sheets:
        r = api(f"{BASE}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": title}}}]})
        props = r["replies"][0]["addSheet"]["properties"]
        sheets[title] = {"properties": props}
    return sheets[title]["properties"]["sheetId"]

GREEN_BG = {"red": 0.776, "green": 0.937, "blue": 0.808}
GREEN_FG = {"red": 0.0, "green": 0.38, "blue": 0.0}
RED_BG = {"red": 1.0, "green": 0.78, "blue": 0.808}
RED_FG = {"red": 0.61, "green": 0.0, "blue": 0.024}
HDR_BG = {"red": 0.122, "green": 0.306, "blue": 0.47}
TOTAL_BG = {"red": 0.867, "green": 0.922, "blue": 0.969}
FMT_DELTA = '+#,##0;-#,##0;"—"'
FMT_PCT = '+0.0%;-0.0%;"—"'

def push_sheet(title, header, total_row, data_rows, delta_cols, pct_cols, n_cols, col_widths=None):
    sid = ensure_sheet(title)
    last = 2 + len(data_rows)
    # очистка значений
    api(f"{BASE}/values/{urllib.parse.quote(title)}!A1:AZ5000:clear", {}, "POST")
    # значения + формулы
    api(f"{BASE}/values/{urllib.parse.quote(title)}!A1?valueInputOption=USER_ENTERED",
        {"values": [header, total_row] + data_rows}, "PUT")
    # форматирование
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sid,
            "gridProperties": {"frozenRowCount": 2}}, "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
            "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 80}, "fields": "pixelSize"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": HDR_BG, "wrapStrategy": "WRAP",
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,wrapStrategy,horizontalAlignment,verticalAlignment,textFormat)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2,
            "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
    ]
    for i, w in enumerate(col_widths or []):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": i, "endIndex": i + 1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    for col in delta_cols + pct_cols:
        reqs.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": last,
            "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                "pattern": FMT_PCT if col in pct_cols else FMT_DELTA}}},
            "fields": "userEnteredFormat.numberFormat"}})
    # старые CF-правила удаляем (иначе копятся при ежедневной перезаписи)
    n_cf = len(sheets[title].get("conditionalFormats", []))
    for _ in range(n_cf):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    for col in delta_cols + pct_cols:
        rng = [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": last,
                "startColumnIndex": col, "endColumnIndex": col + 1}]
        reqs.append({"addConditionalFormatRule": {"rule": {"ranges": rng,
            "booleanRule": {"condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                "format": {"backgroundColor": GREEN_BG, "textFormat": {"foregroundColor": GREEN_FG}}}}, "index": 0}})
        reqs.append({"addConditionalFormatRule": {"rule": {"ranges": rng,
            "booleanRule": {"condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                "format": {"backgroundColor": RED_BG, "textFormat": {"foregroundColor": RED_FG}}}}, "index": 0}})
    api(f"{BASE}:batchUpdate", {"requests": reqs})

# история заказов по дням (для листов WB / Ozon / Общее)
hist_dates, hist = [], {}
if a.history and os.path.exists(a.history):
    HF = json.load(open(a.history))
    hist = HF.get("data", {})
    all_dates = sorted(set(HF.get("wb_dates", [])) | set(HF.get("oz_dates", [])), reverse=True)
    hist_dates = [d for d in all_dates if d < P]
def col_letter(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s
def hday(base, day, plat):
    rec = hist.get(base, {}).get(day)
    return rec.get(plat, 0) if rec else 0
def hval(base, day):
    rec = hist.get(base, {}).get(day)
    return (rec.get("wb", 0) + rec.get("oz", 0)) if rec else 0
HDATES = [ddmm(d) for d in hist_dates]

def heatmap(title, start_col, ncols, last_row):
    # Тепловая подсветка истории — ПО КАЖДОЙ СТРОКЕ отдельно (свой min/max),
    # чтобы видеть динамику товара по дням, а не сравнивать крупные с мелкими.
    if ncols <= 0 or last_row < 3: return
    try:  # подсветка — косметика, её сбой не должен прерывать выгрузку данных
        sid = ensure_sheet(title)
        reqs = []
        for row in range(2, last_row):  # 0-индекс: строки данных с 3-й (индекс 2)
            reqs.append({"addConditionalFormatRule": {"rule": {
                "ranges": [{"sheetId": sid, "startRowIndex": row, "endRowIndex": row + 1,
                            "startColumnIndex": start_col, "endColumnIndex": start_col + ncols}],
                "gradientRule": {"minpoint": {"color": {"red": 1, "green": 1, "blue": 1}, "type": "MIN"},
                                 "maxpoint": {"color": {"red": 0.388, "green": 0.745, "blue": 0.482}, "type": "MAX"}}},
                "index": 0}})
        for i in range(0, len(reqs), 200):
            api(f"{BASE}:batchUpdate", {"requests": reqs[i:i+200]})
    except Exception as e:
        print(f"  (подсветка {title} пропущена: {str(e)[:80]})")

if wb_rows:
    header = ["Артикул", "SKU", f"Заказы вчера ({Y_L})", f"Заказы позавчера ({P_L})", "Δ заказы", "Δ %",
              "Переходы в карточку вчера", "Переходы позавчера", "Δ переходы",
              "Корзины вчера", "Корзины позавчера", "Δ корзины"] + HDATES
    last = 2 + len(wb_rows)
    total = ["ИТОГО WB", "", f"=SUM(C3:C{last})", f"=SUM(D3:D{last})", "=C2-D2",
             "=IF(D2=0;\"\";(C2-D2)/D2)", f"=SUM(G3:G{last})", f"=SUM(H3:H{last})", "=G2-H2",
             f"=SUM(J3:J{last})", f"=SUM(K3:K{last})", "=J2-K2"]
    for j in range(len(hist_dates)):
        L = col_letter(13 + j)
        total.append(f"=SUM({L}3:{L}{last})")
    rows = []
    for i, r in enumerate(wb_rows, 3):
        base = base_art(r["art"], MAP)
        rows.append([r["art"], r["nm"], r["o_y"], r["o_p"], f"=C{i}-D{i}",
                     f"=IF(D{i}=0;\"\";(C{i}-D{i})/D{i})", r["v_y"], r["v_p"], f"=G{i}-H{i}",
                     r["c_y"], r["c_p"], f"=J{i}-K{i}"]
                    + [hday(base, d, "wb") for d in hist_dates])
    push_sheet("WB", header, total, rows, [4, 8, 11], [5], 12 + len(hist_dates),
               [300, 95, 105, 115, 85, 75, 115, 105, 95, 100, 110, 90] + [60] * len(hist_dates))
    heatmap("WB", 12, len(hist_dates), 2 + len(wb_rows))
    print(f"WB: {len(rows)} строк, история {len(hist_dates)} дн")

if oz_rows:
    header = ["Артикул", "SKU Ozon", f"Заказы вчера ({Y_L})", f"Заказы позавчера ({P_L})", "Δ заказы", "Δ %",
              "Показы вчера", "Показы позавчера", "Δ показы",
              "Просмотры карточки вчера", "Просмотры позавчера", "Δ просмотры",
              "Корзины вчера", "Корзины позавчера", "Δ корзины"]
    header = header + HDATES
    last = 2 + len(oz_rows)
    total = ["ИТОГО Ozon", "", f"=SUM(C3:C{last})", f"=SUM(D3:D{last})", "=C2-D2",
             "=IF(D2=0;\"\";(C2-D2)/D2)", f"=SUM(G3:G{last})", f"=SUM(H3:H{last})", "=G2-H2",
             f"=SUM(J3:J{last})", f"=SUM(K3:K{last})", "=J2-K2",
             f"=SUM(M3:M{last})", f"=SUM(N3:N{last})", "=M2-N2"]
    for j in range(len(hist_dates)):
        L = col_letter(16 + j)
        total.append(f"=SUM({L}3:{L}{last})")
    rows = []
    for i, r in enumerate(oz_rows, 3):
        base = base_art(r["art"], MAP)
        rows.append([r["art"], int(r["sku"]), r["o_y"], r["o_p"], f"=C{i}-D{i}",
                     f"=IF(D{i}=0;\"\";(C{i}-D{i})/D{i})", r["sh_y"], r["sh_p"], f"=G{i}-H{i}",
                     r["cl_y"], r["cl_p"], f"=J{i}-K{i}", r["c_y"], r["c_p"], f"=M{i}-N{i}"]
                    + [hday(base, d, "oz") for d in hist_dates])
    push_sheet("Ozon", header, total, rows, [4, 8, 11, 14], [5], 15 + len(hist_dates),
               [300, 105, 105, 115, 85, 75, 105, 115, 95, 115, 110, 100, 100, 110, 90] + [60] * len(hist_dates))
    heatmap("Ozon", 15, len(hist_dates), 2 + len(oz_rows))
    print(f"Ozon: {len(rows)} строк, история {len(hist_dates)} дн")

n_cols = 5 + len(hist_dates)
header = ["Артикул (база)", f"Заказы ВСЕГО вчера ({Y_L})", f"Заказы ВСЕГО позавчера ({P_L})",
          "Δ всего", "Δ %"] + [ddmm(d) for d in hist_dates]
last = 2 + len(items)
total = ["ИТОГО", f"=SUM(B3:B{last})", f"=SUM(C3:C{last})", "=B2-C2", "=IF(C2=0;\"\";(B2-C2)/C2)"]
for j in range(len(hist_dates)):
    L = col_letter(6 + j)
    total.append(f"=SUM({L}3:{L}{last})")
rows = []
for i, (k, g) in enumerate(items, 3):
    rows.append([k, g["y"], g["p"], f"=B{i}-C{i}", f"=IF(C{i}=0;\"\";(B{i}-C{i})/C{i})"]
                + [hval(k, d) for d in hist_dates])
push_sheet("Общее", header, total, rows, [3], [4], n_cols,
           [320, 130, 145, 90, 80] + [72] * len(hist_dates))
heatmap("Общее", 5, len(hist_dates), 2 + len(items))
print(f"Общее: {len(rows)} строк, история: {len(hist_dates)} дней")

# ---------- лист «Доли» (доля площадок + конверсия + средняя цена) ----------
DEF = lambda: {"wo":0,"wopen":0,"oo":0,"ov":0,"wtop":-1,"otop":-1,"wprice":None,"oprice":None}
sh = {}  # base -> агрегаты
for r in wb_rows:
    g = sh.setdefault(base_art(r["art"], MAP), DEF())
    g["wo"] += r["o_y"]; g["wopen"] += r["v_y"]
    if r["o_y"] >= g["wtop"]: g["wtop"] = r["o_y"]; g["wprice"] = r.get("cp")
for r in oz_rows:
    g = sh.setdefault(base_art(r["art"], MAP), DEF())
    g["oo"] += r["o_y"]; g["ov"] += r["cl_y"]
    if r["o_y"] >= g["otop"]: g["otop"] = r["o_y"]; g["oprice"] = r.get("cp")
sh_items = sorted(sh.items(), key=lambda kv: -(kv[1]["wo"] + kv[1]["oo"]))

def rate(a, b): return round(a / b, 4) if b else ""

sh_header = ["Артикул (база)", "Заказы WB", "Заказы Ozon", "Заказы всего",
             "Доля WB", "Доля Ozon", "Конверсия WB", "Конверсия Ozon",
             "Цена WB (клиент)", "Цена Ozon (клиент)"]
sh_last = 2 + len(sh_items)
tot = {k: sum(g[k] for _, g in sh_items) for k in ("wo","wopen","oo","ov")}
sh_total = ["ИТОГО", tot["wo"], tot["oo"], "=B2+C2",
            "=IF(D2=0;\"\";B2/D2)", "=IF(D2=0;\"\";C2/D2)",
            rate(tot["wo"], tot["wopen"]), rate(tot["oo"], tot["ov"]), "", ""]
sh_rows = []
for i, (k, g) in enumerate(sh_items, 3):
    sh_rows.append([k, g["wo"], g["oo"], f"=B{i}+C{i}",
                    f"=IF(D{i}=0;\"\";B{i}/D{i})", f"=IF(D{i}=0;\"\";C{i}/D{i})",
                    rate(g["wo"], g["wopen"]), rate(g["oo"], g["ov"]),
                    g["wprice"] if g["wprice"] else "", g["oprice"] if g["oprice"] else ""])

sid = ensure_sheet("Доли")
api(f"{BASE}/values/{urllib.parse.quote('Доли')}!A1:Z5000:clear", {}, "POST")
api(f"{BASE}/values/{urllib.parse.quote('Доли')}!A1?valueInputOption=USER_ENTERED",
    {"values": [sh_header, sh_total] + sh_rows}, "PUT")
PCT = '0.0%'
RUB = '#,##0 ₽'
reqs = [
    {"updateSheetProperties": {"properties": {"sheetId": sid,
        "gridProperties": {"frozenRowCount": 2}}, "fields": "gridProperties.frozenRowCount"}},
    {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
        "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 46}, "fields": "pixelSize"}},
    {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
        "startColumnIndex": 0, "endColumnIndex": 10},
        "cell": {"userEnteredFormat": {"backgroundColor": HDR_BG, "wrapStrategy": "WRAP",
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "foregroundColor": {"red":1,"green":1,"blue":1}}}},
        "fields": "userEnteredFormat(backgroundColor,wrapStrategy,horizontalAlignment,verticalAlignment,textFormat)"}},
    {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2,
        "startColumnIndex": 0, "endColumnIndex": 10},
        "cell": {"userEnteredFormat": {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
]
for col, w in enumerate([300,80,80,90,70,70,90,95,90,95]):
    reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
        "startIndex": col, "endIndex": col+1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}})
for col in (4,5,6,7):  # доли и конверсии — проценты
    reqs.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": sh_last,
        "startColumnIndex": col, "endColumnIndex": col+1},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": PCT}}},
        "fields": "userEnteredFormat.numberFormat"}})
for col in (8,9):  # цены — рубли
    reqs.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": sh_last,
        "startColumnIndex": col, "endColumnIndex": col+1},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": RUB}}},
        "fields": "userEnteredFormat.numberFormat"}})
api(f"{BASE}:batchUpdate", {"requests": reqs})

# Попарная подсветка WB vs Ozon: в каждой метрике большее значение зелёным,
# меньшее красным. Сравнение двух ячеек (без числовых литералов) — локаль не мешает.
cf_reqs = []
for _ in range(len(sheets.get("Доли", {}).get("conditionalFormats", []))):
    cf_reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
def col_l(ci): return col_letter(ci + 1)
def cf_rule(ci, formula, fill, fg):
    return {"addConditionalFormatRule": {"rule": {
        "ranges": [{"sheetId": sid, "startRowIndex": 2, "endRowIndex": sh_last,
                    "startColumnIndex": ci, "endColumnIndex": ci + 1}],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                        "format": {"backgroundColor": fill, "textFormat": {"foregroundColor": fg}}}}, "index": 0}}
def pair(left, right, guard):
    L, R = col_l(left), col_l(right)
    if guard:
        g = lambda x, y: f"=AND(ISNUMBER(${x}3);ISNUMBER(${y}3);${x}3>${y}3)"
        l = lambda x, y: f"=AND(ISNUMBER(${x}3);ISNUMBER(${y}3);${x}3<${y}3)"
    else:
        g = lambda x, y: f"=${x}3>${y}3"
        l = lambda x, y: f"=${x}3<${y}3"
    cf_reqs.append(cf_rule(left, g(L, R), GREEN_BG, GREEN_FG))
    cf_reqs.append(cf_rule(left, l(L, R), RED_BG, RED_FG))
    cf_reqs.append(cf_rule(right, g(R, L), GREEN_BG, GREEN_FG))
    cf_reqs.append(cf_rule(right, l(R, L), RED_BG, RED_FG))
pair(1, 2, False)   # заказы WB / Ozon
pair(4, 5, False)   # доли
pair(6, 7, True)    # конверсии (могут быть пустыми)
pair(8, 9, True)    # цены
try:  # подсветка — косметика, не должна прерывать выгрузку
    api(f"{BASE}:batchUpdate", {"requests": cf_reqs})
    print(f"Доли: {len(sh_rows)} строк, подсветка WB/Ozon")
except Exception as e:
    print(f"Доли: {len(sh_rows)} строк (подсветка пропущена: {str(e)[:80]})")

# Порядок листов: «Общее» первый, «Доли» второй
api(f"{BASE}:batchUpdate", {"requests": [
    {"updateSheetProperties": {"properties": {"sheetId": ensure_sheet("Общее"), "index": 0}, "fields": "index"}},
    {"updateSheetProperties": {"properties": {"sheetId": ensure_sheet("Доли"), "index": 1}, "fields": "index"}},
]})

# самопроверка 1: ИТОГО
chk = api(f"{BASE}/values/{urllib.parse.quote('Общее')}!B2:C2?valueRenderOption=UNFORMATTED_VALUE")
got = chk.get("values", [[None, None]])[0]
exp = [sum(g["y"] for _, g in items), sum(g["p"] for _, g in items)]
totals_ok = [int(x) for x in got] == exp
# самопроверка 2: скан ВСЕХ ячеек на #ERROR!/#DIV/0! и пр.
# (формулы с аргументами обязаны использовать ';' — ',' ломается в русской локали)
err_n = 0
for title in (["WB"] if wb_rows else []) + (["Ozon"] if oz_rows else []) + ["Общее"]:
    d = api(f"{BASE}/values/{urllib.parse.quote(title)}!A1:AZ5000?valueRenderOption=FORMATTED_VALUE")
    for row in d.get("values", []):
        for cell in row:
            if isinstance(cell, str) and cell.startswith("#"):
                err_n += 1
print("ИТОГО в таблице:", got, "ожидалось:", exp, "| ячеек с ошибками:", err_n)
print("VERIFY", "OK" if totals_ok and err_n == 0 else "MISMATCH")

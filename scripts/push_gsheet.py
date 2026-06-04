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
            "c_y": y.get("cart", 0),   "c_p": pp.get("cart", 0)})
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
            "c_y": y.get("tocart", 0),    "c_p": pp.get("tocart", 0)})
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

if wb_rows:
    header = ["Артикул", "nmID", f"Заказы вчера ({Y_L})", f"Заказы позавчера ({P_L})", "Δ заказы", "Δ %",
              "Переходы в карточку вчера", "Переходы позавчера", "Δ переходы",
              "Корзины вчера", "Корзины позавчера", "Δ корзины"]
    last = 2 + len(wb_rows)
    total = ["ИТОГО WB", "", f"=SUM(C3:C{last})", f"=SUM(D3:D{last})", "=C2-D2",
             "=IF(D2=0;\"\";(C2-D2)/D2)", f"=SUM(G3:G{last})", f"=SUM(H3:H{last})", "=G2-H2",
             f"=SUM(J3:J{last})", f"=SUM(K3:K{last})", "=J2-K2"]
    rows = []
    for i, r in enumerate(wb_rows, 3):
        rows.append([r["art"], r["nm"], r["o_y"], r["o_p"], f"=C{i}-D{i}",
                     f"=IF(D{i}=0;\"\";(C{i}-D{i})/D{i})", r["v_y"], r["v_p"], f"=G{i}-H{i}",
                     r["c_y"], r["c_p"], f"=J{i}-K{i}"])
    push_sheet("WB", header, total, rows, [4, 8, 11], [5], 12,
               [300, 95, 105, 115, 85, 75, 115, 105, 95, 100, 110, 90])
    print(f"WB: {len(rows)} строк")

if oz_rows:
    header = ["Артикул", "SKU Ozon", f"Заказы вчера ({Y_L})", f"Заказы позавчера ({P_L})", "Δ заказы", "Δ %",
              "Показы вчера", "Показы позавчера", "Δ показы",
              "Просмотры карточки вчера", "Просмотры позавчера", "Δ просмотры",
              "Корзины вчера", "Корзины позавчера", "Δ корзины"]
    last = 2 + len(oz_rows)
    total = ["ИТОГО Ozon", "", f"=SUM(C3:C{last})", f"=SUM(D3:D{last})", "=C2-D2",
             "=IF(D2=0;\"\";(C2-D2)/D2)", f"=SUM(G3:G{last})", f"=SUM(H3:H{last})", "=G2-H2",
             f"=SUM(J3:J{last})", f"=SUM(K3:K{last})", "=J2-K2",
             f"=SUM(M3:M{last})", f"=SUM(N3:N{last})", "=M2-N2"]
    rows = []
    for i, r in enumerate(oz_rows, 3):
        rows.append([r["art"], int(r["sku"]), r["o_y"], r["o_p"], f"=C{i}-D{i}",
                     f"=IF(D{i}=0;\"\";(C{i}-D{i})/D{i})", r["sh_y"], r["sh_p"], f"=G{i}-H{i}",
                     r["cl_y"], r["cl_p"], f"=J{i}-K{i}", r["c_y"], r["c_p"], f"=M{i}-N{i}"])
    push_sheet("Ozon", header, total, rows, [4, 8, 11, 14], [5], 15,
               [300, 105, 105, 115, 85, 75, 105, 115, 95, 115, 110, 100, 100, 110, 90])
    print(f"Ozon: {len(rows)} строк")

# история прошлых дней (даты старше позавчера, от свежих к старым)
hist_dates, hist = [], {}
if a.history and os.path.exists(a.history):
    HF = json.load(open(a.history))
    hist = HF.get("data", {})
    all_dates = sorted(set(HF.get("wb_dates", [])) | set(HF.get("oz_dates", [])), reverse=True)
    hist_dates = [d for d in all_dates if d < P]

def hval(base, day):
    rec = hist.get(base, {}).get(day)
    return (rec.get("wb", 0) + rec.get("oz", 0)) if rec else 0

def col_letter(n):  # 1 -> A
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s

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
print(f"Общее: {len(rows)} строк, история: {len(hist_dates)} дней")

# «Общее» — всегда первый лист
api(f"{BASE}:batchUpdate", {"requests": [{"updateSheetProperties": {
    "properties": {"sheetId": ensure_sheet("Общее"), "index": 0}, "fields": "index"}}]})

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

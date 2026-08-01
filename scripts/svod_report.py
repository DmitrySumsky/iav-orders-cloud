#!/usr/bin/env python3
"""Сводный отчёт заказов «Общая» (позиции × бренды, только штуки) — облачная
версия GAS-скрипта из 26.svod_zakazov, данные из TrueStats.

Пишет в боевую таблицу 3 листа: «Общее» / «ВБ» / «Озон» (перезапись, дата в
цветной шапке, ИТОГО сверху, колонка «Все бренды», справа — колонки прошлых
дней с тепловой подсветкой по строкам). Лист «Маппинг позиций» читается и
дополняется новыми артикулами — ручные правки сохраняются.
GAS-скрипт в самой таблице остаётся как ручной запасной вариант.

История копится в <state-dir>/svod_history.json (сырые заказы по брендам и
артикулам за день; недостающие дни добираются из TrueStats автоматически).
Рядом пишется svod_summary.json — итоги по брендам вчера/позавчера для
Telegram-картинки (svod_telegram.py).

Полная история в таблице — листы «История Общее» / «История ВБ» / «История
Озон»: строка = позиция × бренд, колонки = все сохранённые дни (до 60),
сверху блок «Итого» по каждому бренду за каждый день. Тепловая подсветка
считается в скрипте и пишется цветом ячеек (без условных форматов — их
лимиты бережём для основных листов).

Ключи (api_keys, можно несколько файлов через запятую):
  SVOD_GSHEET_ID     — id боевой таблицы
  SVOD_BRANDS        — колонки отчёта по порядку: "Naturi=NATURI,Health Form=HEALTHFORM,..."
                       (слева отображаемое имя, справа префикс *_TS_* ключей)
  SVOD_HISTORY_DAYS  — колонки прошлых дней в ОСНОВНЫХ листах (дефолт 14)
  SVOD_BACKFILL_DAYS — глубина добора истории из TrueStats (дефолт 30)
  TRUESTATS_TOKEN_*, <PREFIX>_TS_WB_ACCOUNTS/_TS_OZON_ACCOUNTS — как у collect_ts

Использование:
  python3 svod_report.py --keys api_keys.txt[,extra] --sa google_sa.json \
      [--state-dir state] [--date YYYY-MM-DD] [--dry-run]
Печатает DONE при успехе (ошибки кабинетов не валят отчёт — помечаются в шапке).
"""
import argparse, json, re, sys, os, time, urllib.request, urllib.parse, urllib.error
from datetime import timedelta, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_ts import load_keys, ts_products, wb_funnel_async
from direct_orders import ozon_units, wb_units, pick_source

MSK = timezone(timedelta(hours=3))
MAPR = "Маппинг позиций"
SHEETS = [("Общее", "ОБЩЕЕ", "#38761D"), ("ВБ", "WB", "#C90076"), ("Озон", "OZON", "#0B5394")]

p = argparse.ArgumentParser()
p.add_argument("--keys", required=True)
p.add_argument("--sa", required=True)
p.add_argument("--date", default="")
p.add_argument("--state-dir",
               default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"))
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()

K = load_keys(a.keys)
SHEET_ID = K.get("SVOD_GSHEET_ID", "")
brands_cfg = [x.strip() for x in K.get("SVOD_BRANDS", "").split(",") if x.strip()]
BRANDS = [(b.split("=")[0].strip(), b.split("=")[1].strip()) for b in brands_cfg if "=" in b]
if not SHEET_ID or not BRANDS:
    print("ERROR: нужны SVOD_GSHEET_ID и SVOD_BRANDS в ключах"); sys.exit(1)
DAY = a.date or (datetime.now(MSK).date() - timedelta(days=1)).isoformat()
DD = f"{DAY[8:10]}.{DAY[5:7]}"

# ---------- нормализация (порт repNorm_/repTitle_ из GAS 1-в-1) ----------
KEEP = {"mg", "g", "caps", "ml"}
UP = {"bcaa": "BCAA", "zma": "ZMA", "msm": "MSM", "gaba": "GABA", "set": "SET",
      "aakg": "AAKG", "b6": "B6", "d3": "D3", "к2": "К2", "мк-7": "МК-7",
      "b-complex": "B-Complex", "5-htp": "5-HTP", "l-carnitine": "L-Carnitine",
      "l-tryptophan": "L-Tryptophan", "l-glutamine": "L-Glutamine", "hf": "HF", "sn": "SN"}

def rep_title(s):
    return " ".join(w if w in KEEP else UP.get(w, w[:1].upper() + w[1:]) for w in s.split(" "))

def rep_norm(offer, tokens):
    s = " " + re.sub(r"[^a-zа-я0-9%+*.\-]+", " ", str(offer).lower().replace("ё", "е"), flags=re.I) + " "
    for t in tokens:
        t = " " + t.lower() + " "
        while t in s: s = s.replace(t, " ")
    return re.sub(r"\s+", " ", s).strip()

# ---------- данные из TrueStats + история по дням ----------
PREV = (datetime.fromisoformat(DAY).date() - timedelta(days=1)).isoformat()
HIST_DAYS = max(2, int(K.get("SVOD_HISTORY_DAYS", "14") or 14))
BACKFILL = max(HIST_DAYS, int(K.get("SVOD_BACKFILL_DAYS", "30") or 30))
hist_f = os.path.join(a.state_dir, "svod_history.json")
try:
    HIST = json.load(open(hist_f, encoding="utf-8"))
except Exception:
    HIST = {}
HIST.setdefault("wb", {}); HIST.setdefault("oz", {})
want_days = [(datetime.fromisoformat(DAY).date() - timedelta(days=i)).isoformat()
             for i in range(BACKFILL)]

errors = []
probe, checked, frozen = {}, set(), set()   # что сверяли и где источник замёрз

def direct_day(prefix, disp, mp, day, ids, ts_day):
    """Заказы за день из API маркетплейса, когда TrueStats «заморожен».

    TrueStats при остановке своего сбора отвечает 200 с нулями, а не ошибкой
    (31.07.2026 — Ozon по всем кабинетам), поэтому подозрительный день
    сверяется с первоисточником; побеждает источник с бОльшим числом заказов
    (см. direct_orders).  Возвращает {артикул: шт}.
    """
    cur = {k: {"orders": v, "sum": 0} for k, v in ts_day.items()}
    fresh = {}
    try:
        if mp == "OZON":
            fresh = ozon_units(K.get(f"{prefix}_OZON_CLIENT_ID", ""),
                               K.get(f"{prefix}_OZON_API_KEY", ""), day, ids)
        else:
            wb_tok = K.get(f"{prefix}_WB_TOKEN", "")
            if not wb_tok: return ts_day
            # аналитика WB ночью не дозревает — пересобранный отчёт за день
            # обычно полнее того, что успел забрать ночной прогон
            fun = wb_funnel_async(wb_tok, day, day, wait_sec=240) or {}
            for nm, days in fun.items():
                n = (days.get(day) or {}).get("orders", 0) or 0
                if n:
                    k = ids.get(str(nm)) or str(nm)
                    fresh.setdefault(k, {"orders": 0, "sum": 0})["orders"] += n
            try:
                st = wb_units(wb_tok, day, ids)
                if sum(v["orders"] for v in st.values()) > sum(v["orders"] for v in fresh.values()):
                    fresh = st
            except Exception as e:
                print(f"WB {disp} {day}: statistics-api не ответил ({str(e)[:80]})")
    except Exception as e:
        print(f"{mp} {disp} {day}: сверка с API не вышла ({str(e)[:100]})")
        return ts_day
    use, took, msg = pick_source(cur, fresh, f"{mp} {disp} {day}")
    print(msg)
    return {k: v["orders"] for k, v in use.items() if v["orders"]} if took else ts_day

for disp, prefix in BRANDS:
    contour = K.get(f"{prefix}_TS_TOKEN", "")
    token = K.get(f"TRUESTATS_TOKEN_{contour.upper()}", "")
    for mp, acc_key, hkey in (("WB", f"{prefix}_TS_WB_ACCOUNTS", "wb"),
                              ("OZON", f"{prefix}_TS_OZON_ACCOUNTS", "oz")):
        accs = [int(x) for x in K.get(acc_key, "").split(",") if x.strip()]
        if not token or not accs:
            errors.append(f"{mp} {disp}: нет TrueStats-настроек"); continue
        for day in want_days:
            # закрытые дни из истории не перекачиваем; вчера/позавчера — всегда свежие
            if day not in (DAY, PREV) and disp in HIST[hkey].get(day, {}): continue
            try:
                rows = ts_products(token, accs, day, day)
            except Exception as e:
                if disp in HIST[hkey].get(day, {}):
                    print(f"{mp} {disp} {day}: обновить не удалось, беру сохранённое")
                elif day == DAY:
                    errors.append(f"{mp} {disp}: {str(e)[:200]}")
                else:
                    print(f"{mp} {disp} {day}: история не добрана ({str(e)[:80]})")
                continue
            d, ids = {}, {}
            for r in rows:
                rid = str(r.get("article") or "")
                art = (r.get("vendorCode") or rid).strip()
                if rid: ids[rid] = r.get("vendorCode") or ""
                n = r.get("ordersCount") or 0
                if art and n: d[art] = d.get(art, 0) + n
            # свежие дни сверяем с кабинетом: ноль или обвал больше 40 % к
            # предыдущему дню чаще означают замерший TrueStats, чем реальность
            if day in (DAY, PREV):
                yday = (datetime.fromisoformat(day).date() - timedelta(days=1)).isoformat()
                ref = sum(HIST[hkey].get(yday, {}).get(disp, {}).values())
                probe[(hkey, day, disp)] = (prefix, mp, ids, sum(d.values()) or 0)
                if sum(d.values()) < max(1, 0.6 * ref):
                    d = direct_day(prefix, disp, mp, day, ids, d)
                    if sum(d.values()) > probe[(hkey, day, disp)][3]:
                        checked.add((hkey, day, disp)); frozen.add((hkey, day))
                # прогонов за день несколько: если источник просел (429, замёрз),
                # оставляем то, что уже добыл прошлый прогон
                keep = HIST[hkey].get(day, {}).get(disp, {})
                if sum(keep.values()) > sum(d.values()):
                    print(f"{mp} {disp} {day}: источник дал {sum(d.values())} < "
                          f"{sum(keep.values())} из прошлого прогона — оставляю прошлое")
                    d = keep
            HIST[hkey].setdefault(day, {})[disp] = d
            time.sleep(0.3)
        print(f"{mp} {disp}: за {DAY} — {sum(HIST[hkey].get(DAY, {}).get(disp, {}).values())} шт")

# Заморозка источника — общая для всех кабинетов: если хоть у одного бренда
# день пришлось брать из API, у остальных просадка того же дня тоже подозрительна
# (31.07.2026: у 4me WB было 542 против 900 — до порога не дотянуло, а правда
# оказалась больше). Досверяем их вторым проходом.
for hkey, day in sorted(frozen):
    for (hk, d_, disp), (prefix, mp, ids, was) in list(probe.items()):
        if (hk, d_) != (hkey, day) or (hk, d_, disp) in checked: continue
        keep = HIST[hk].get(d_, {}).get(disp, {})
        fixed = direct_day(prefix, disp, mp, d_, ids, keep)
        if sum(fixed.values()) >= sum(keep.values()):
            HIST[hk].setdefault(d_, {})[disp] = fixed
        checked.add((hk, d_, disp))

# площадка целиком по нулям при живом предыдущем дне — это сбой источника, а
# не день без продаж: помечаем отчёт неполным (шапка листов + подпись картинки)
for hkey, mp in (("wb", "WB"), ("oz", "Ozon")):
    day_tot = sum(sum(v.values()) for v in HIST[hkey].get(DAY, {}).values())
    prev_tot = sum(sum(v.values()) for v in HIST[hkey].get(PREV, {}).values())
    if not day_tot and prev_tot:
        errors.append(f"{mp}: источник отдал 0 заказов за {DAY} (накануне {prev_tot})")

cutoff = (datetime.fromisoformat(DAY).date() - timedelta(days=60)).isoformat()
for hkey in ("wb", "oz"):
    HIST[hkey] = {d: v for d, v in HIST[hkey].items() if d >= cutoff}
os.makedirs(a.state_dir, exist_ok=True)
json.dump(HIST, open(hist_f, "w", encoding="utf-8"), ensure_ascii=False)

wb_by_brand = HIST["wb"].get(DAY, {})
oz_by_brand = HIST["oz"].get(DAY, {})
# союз артикулов по ВСЕМ дням истории — чтобы маппинг покрывал и снятые с продажи
union = {}
for hkey in ("wb", "oz"):
    for day_arts in HIST[hkey].values():
        for disp, arts in day_arts.items():
            u = union.setdefault(disp, {})
            for art in arts: u[art] = 1

# ---------- Google Sheets API ----------
import jwt
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
BASE = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"

def api(url, payload=None, method=None, tries=5):
    # 429/5xx и сетевые сбои у Google Sheets транзиентны — ретраим с backoff;
    # тело ответа печатаем, иначе 400 от batchUpdate неотлаживаем
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=H, method=method)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            print(f"Sheets API {e.code}: {e.read().decode()[:400]}")
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            raise

def col_a1(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s

def hexrgb(h):
    return {"red": int(h[1:3], 16)/255, "green": int(h[3:5], 16)/255, "blue": int(h[5:7], 16)/255}

disp_names = [d for d, _ in BRANDS]

# ---------- маппинг позиций (читаем лист, дополняем новыми) ----------
tokens = disp_names + [p_ for _, p_ in BRANDS]  # бренд-токены для нормализации
sheet_props, map_rows, cf_counts = {}, [], {}
try:
    meta = api(f"{BASE}?fields=sheets(properties(sheetId,title,index),conditionalFormats)")
    sheet_props = {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}
    cf_counts = {s["properties"]["title"]: len(s.get("conditionalFormats", [])) for s in meta["sheets"]}
    got = api(f"{BASE}/values/{urllib.parse.quote(MAPR)}!A2:{col_a1(1+len(BRANDS))}10000")
    map_rows = got.get("values", [])
except Exception as e:
    if not a.dry_run:
        print(f"ERROR: нет доступа к таблице {SHEET_ID} ({e}) — расшарьте её на "
              f"{SA.get('client_email', 'сервисный аккаунт')}")
        sys.exit(1)
    print(f"dry-run: таблица недоступна ({e}) — маппинг строю с нуля из TrueStats")

pos_by_norm, by_offer, positions = {}, {}, []
for rw in map_rows:
    pos = (rw[0] if rw else "").strip()
    if not pos: continue
    normp = rep_norm(pos, tokens) or pos.lower()
    canon = pos_by_norm.get(normp)
    if not canon:
        canon = pos; pos_by_norm[normp] = canon; positions.append(canon)
    for bi in range(len(BRANDS)):
        for o in (rw[1+bi] if len(rw) > 1+bi else "").split(","):
            o = o.strip()
            if o: by_offer[disp_names[bi] + "||" + o] = canon
new_arts = 0
for disp in disp_names:
    for off in (union.get(disp) or {}):
        if disp + "||" + off in by_offer: continue
        normo = rep_norm(off, tokens)
        pos2 = pos_by_norm.get(normo)
        if not pos2:
            pos2 = rep_title(normo); pos_by_norm[normo] = pos2; positions.append(pos2)
        by_offer[disp + "||" + off] = pos2; new_arts += 1

def aggregate(stats_by_brand):
    agg = {}
    for disp in disp_names:
        for off, n in (stats_by_brand.get(disp) or {}).items():
            pos = by_offer.get(disp + "||" + off)
            if not pos: continue
            agg.setdefault(pos, {})[disp] = agg.get(pos, {}).get(disp, 0) + n
    return agg

agg_wb, agg_oz = aggregate(wb_by_brand), aggregate(oz_by_brand)
agg_all = {}
for src in (agg_wb, agg_oz):
    for pos, bb in src.items():
        for b, n in bb.items():
            agg_all.setdefault(pos, {})[b] = agg_all.get(pos, {}).get(b, 0) + n

# ---------- колонки прошлых дней (по позициям, через тот же маппинг) ----------
hist_dates = sorted({d for hkey in ("wb", "oz") for d in HIST[hkey] if d < DAY},
                    reverse=True)[:HIST_DAYS]

def agg_hist(day, hkeys):
    out = {}
    for hkey in hkeys:
        for disp in disp_names:
            for art, n in HIST[hkey].get(day, {}).get(disp, {}).items():
                pos = by_offer.get(disp + "||" + art)
                if pos: out[pos] = out.get(pos, 0) + n
    return out

HCOLS = {"ОБЩЕЕ": [agg_hist(d, ("wb", "oz")) for d in hist_dates],
         "WB": [agg_hist(d, ("wb",)) for d in hist_dates],
         "OZON": [agg_hist(d, ("oz",)) for d in hist_dates]}

tot_wb = sum(n for bb in agg_wb.values() for n in bb.values())
tot_oz = sum(n for bb in agg_oz.values() for n in bb.values())
print(f"Итого за {DD}: WB {tot_wb} шт, Ozon {tot_oz} шт, всего {tot_wb + tot_oz}"
      + (f" | новых артикулов в маппинге: {new_arts}" if new_arts else ""))
print(f"История: {len(hist_dates)} дн в листах")
if errors: print("Ошибки кабинетов:", "; ".join(errors))

# ---------- сводка по брендам для Telegram-картинки ----------
def day_tot(hkey, day, disp):
    return sum(HIST[hkey].get(day, {}).get(disp, {}).values())
summary = {"date": DAY, "prev": PREV, "sheet_id": SHEET_ID, "errors": errors,
           "brands": [{"name": disp,
                       "wb_y": day_tot("wb", DAY, disp), "wb_p": day_tot("wb", PREV, disp),
                       "oz_y": day_tot("oz", DAY, disp), "oz_p": day_tot("oz", PREV, disp)}
                      for disp in disp_names]}
json.dump(summary, open(os.path.join(a.state_dir, "svod_summary.json"), "w", encoding="utf-8"),
          ensure_ascii=False)

if a.dry_run:
    for pos in positions[:12]:
        print(" ", pos, "->", agg_all.get(pos, {}))
    print("DRY RUN — в таблицу не пишу"); print("DONE"); sys.exit(0)

# ---------- запись маппинга ----------
head = ["Позиция"] + [d + " — артикулы" for d in disp_names]
table = []
for pos in positions:
    rw = [pos] + [""] * len(BRANDS)
    table.append(rw)
pos_index = {p_: i for i, p_ in enumerate(positions)}
for keyk, pos in by_offer.items():
    disp, off = keyk.split("||", 1)
    bi, pi = disp_names.index(disp), pos_index.get(pos)
    if pi is not None:
        cell = table[pi][1 + bi]
        table[pi][1 + bi] = (cell + ", " + off) if cell else off
if MAPR not in sheet_props:
    r = api(f"{BASE}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": MAPR}}}]})
    sheet_props[MAPR] = r["replies"][0]["addSheet"]["properties"]
api(f"{BASE}/values/{urllib.parse.quote(MAPR)}!A1?valueInputOption=RAW",
    {"values": [head] + table}, method="PUT")

# ---------- рендер трёх листов ----------
warn = " ⚠ НЕПОЛНЫЕ ДАННЫЕ" if errors else ""
reqs = []
for idx, ((name, ttl, color), agg) in enumerate(zip(SHEETS, (agg_all, agg_wb, agg_oz))):
    if name not in sheet_props:
        r = api(f"{BASE}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": name, "index": idx}}}]})
        sheet_props[name] = r["replies"][0]["addSheet"]["properties"]
    sid = sheet_props[name]["sheetId"]
    hh = HCOLS[ttl]                      # история этого листа: список {позиция: шт} по датам
    AB = 1 + len(BRANDS)                 # индекс колонки «Все бренды»
    n_cols = AB + 1 + len(hist_dates)
    totals, grand = [0] * len(BRANDS), 0
    body_rows = []
    for pos in positions:
        rw = [pos]
        for bi, disp in enumerate(disp_names):
            v = agg.get(pos, {}).get(disp)
            rw.append(v if v else "")
            if v: totals[bi] += v; grand += v
        rw.append("")
        rw += [h.get(pos) or "" for h in hh]
        body_rows.append(rw)
    rows = [[f"{ttl} {DD}{warn}"] + [""] * (n_cols - 1),
            ["Итого"] + totals + [grand] + [sum(h.values()) for h in hh],
            ["Наименование"] + disp_names + ["Все бренды"]
            + [f"{d[8:10]}.{d[5:7]}" for d in hist_dates]] + body_rows

    reqs += [
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "userEnteredValue,userEnteredFormat,note"}},
        # у листа по умолчанию 26 колонок — расширяем сетку под колонки истории
        {"updateSheetProperties": {"properties": {"sheetId": sid,
            "gridProperties": {"columnCount": max(n_cols + 2, 26)}},
            "fields": "gridProperties.columnCount"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "index": idx,
            "gridProperties": {"frozenRowCount": 3}}, "fields": "index,gridProperties.frozenRowCount"}},
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": n_cols}, "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": hexrgb("#CC0000" if errors else color),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 12, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2,
            "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": hexrgb("#FFF200"),
                "horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2,
            "startColumnIndex": AB, "endColumnIndex": AB + 1},
            "cell": {"userEnteredFormat": {"backgroundColor": hexrgb("#93C47D"),
                "horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 3,
            "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"backgroundColor": hexrgb("#D9D9D9"),
                "horizontalAlignment": "CENTER", "textFormat": {"bold": True}, "wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat,wrapStrategy)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 340}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": 1, "endIndex": AB + 1}, "properties": {"pixelSize": 110}, "fields": "pixelSize"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 3, "endRowIndex": 3 + len(positions),
            "startColumnIndex": 1, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
    ]
    if hist_dates:
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": AB + 1, "endIndex": n_cols}, "properties": {"pixelSize": 62}, "fields": "pixelSize"}})
    # старые условные форматы удаляем (иначе копятся) и вешаем тепловую подсветку
    # истории ПО КАЖДОЙ СТРОКЕ (свой min/max — видна динамика позиции, как в брендовых)
    for _ in range(cf_counts.get(name, 0)):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    cf_counts[name] = 0
    if hist_dates:
        for ri in range(3, 3 + len(positions)):
            reqs.append({"addConditionalFormatRule": {"rule": {
                "ranges": [{"sheetId": sid, "startRowIndex": ri, "endRowIndex": ri + 1,
                            "startColumnIndex": AB + 1, "endColumnIndex": n_cols}],
                "gradientRule": {"minpoint": {"color": {"red": 1, "green": 1, "blue": 1}, "type": "MIN"},
                                 "maxpoint": {"color": {"red": 0.388, "green": 0.745, "blue": 0.482}, "type": "MAX"}}},
                "index": 0}})
    if errors:
        reqs.append({"updateCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": 1},
            "rows": [{"values": [{"note": "Кабинеты с ошибками (данные по ним НЕ вошли):\n" + "\n".join(errors)}]}],
            "fields": "note"}})
    # значения пишем values.update (после очистки формата)
    reqs.append({"updateCells": {
        "range": {"sheetId": sid, "startRowIndex": 0, "startColumnIndex": 0,
                  "endRowIndex": len(rows), "endColumnIndex": n_cols},
        "rows": [{"values": [
            ({"userEnteredValue": {"numberValue": v}} if isinstance(v, (int, float)) and v != ""
             else {"userEnteredValue": {"stringValue": str(v)}})
            for v in rw]} for rw in rows],
        "fields": "userEnteredValue"}})

# ---------- листы «История …»: позиция × бренд, все сохранённые дни ----------
# Тепловая подсветка считается здесь и пишется цветом ячеек (по строке, свой
# min/max) — без условных форматов, чтобы их число в таблице не разрасталось.
all_days = sorted({d for hk in ("wb", "oz") for d in HIST[hk]}, reverse=True)
CENTER = {"horizontalAlignment": "CENTER"}

def heat(v, mn, mx):
    if not isinstance(v, (int, float)) or mx <= mn:
        return CENTER
    t = (v - mn) / (mx - mn)
    return {"horizontalAlignment": "CENTER",
            "backgroundColor": {"red": 1 - 0.612 * t, "green": 1 - 0.255 * t, "blue": 1 - 0.518 * t}}

def cell(v, fmt=None):
    c = {"userEnteredValue": ({"numberValue": v} if isinstance(v, (int, float)) and v != ""
                              else {"stringValue": str(v)})}
    if fmt: c["userEnteredFormat"] = fmt
    return c

hist_verify = None
HSHEETS = [("История Общее", "ОБЩЕЕ", ("wb", "oz"), "#38761D"),
           ("История ВБ", "WB", ("wb",), "#C90076"),
           ("История Озон", "OZON", ("oz",), "#0B5394")]
for hidx, (name, ttl, hkeys, color) in enumerate(HSHEETS):
    ser = {}                                     # (позиция, бренд) -> {день: шт}
    for hk in hkeys:
        for day, per in HIST[hk].items():
            for disp in disp_names:
                for art, n in per.get(disp, {}).items():
                    pos = by_offer.get(disp + "||" + art)
                    if not pos: continue
                    s = ser.setdefault((pos, disp), {})
                    s[day] = s.get(day, 0) + n
    btot = {}                                    # бренд -> {день: шт}
    for (pos, disp), s in ser.items():
        bt = btot.setdefault(disp, {})
        for day, n in s.items(): bt[day] = bt.get(day, 0) + n
    alld = {}
    for bt in btot.values():
        for day, n in bt.items(): alld[day] = alld.get(day, 0) + n
    if ttl == "ОБЩЕЕ": hist_verify = alld.get(DAY, 0)

    n_cols = 2 + len(all_days)
    WHITE = {"red": 1, "green": 1, "blue": 1}
    title_fmt = {"backgroundColor": hexrgb(color), "horizontalAlignment": "CENTER",
                 "textFormat": {"bold": True, "fontSize": 12, "foregroundColor": WHITE}}
    head_fmt = {"backgroundColor": hexrgb("#D9D9D9"), "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True}, "wrapStrategy": "WRAP"}
    bold = {"textFormat": {"bold": True}}

    grid = [[cell(f"ИСТОРИЯ {ttl} — заказы по дням (шт)", title_fmt)] + [cell("", title_fmt)] * (n_cols - 1),
            [cell("Позиция", head_fmt), cell("Бренд", head_fmt)]
            + [cell(f"{d[8:10]}.{d[5:7]}", head_fmt) for d in all_days]]
    def series_row(c1, c2, s, label_fmt):
        vals = [s.get(d, "") or "" for d in all_days]
        nums = [v for v in vals if isinstance(v, (int, float))]
        mn, mx = (min(nums), max(nums)) if nums else (0, 0)
        return [cell(c1, label_fmt), cell(c2, label_fmt)] + [cell(v, heat(v, mn, mx)) for v in vals]
    for disp in disp_names:
        grid.append(series_row("Итого", disp, btot.get(disp, {}), bold))
    grid.append(series_row("Итого", "Все бренды", alld,
                           {"textFormat": {"bold": True}, "backgroundColor": hexrgb("#FFF200")}))
    frozen = len(grid)
    for pos in positions:
        for disp in disp_names:
            s = ser.get((pos, disp))
            if s: grid.append(series_row(pos, disp, s, {}))

    if name not in sheet_props:
        r = api(f"{BASE}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": name, "index": 3 + hidx}}}]})
        sheet_props[name] = r["replies"][0]["addSheet"]["properties"]
    sid = sheet_props[name]["sheetId"]
    reqs += [
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "userEnteredValue,userEnteredFormat,note"}},
        # сетка по умолчанию — 26 колонок; под все дни истории нужно больше
        {"updateSheetProperties": {"properties": {"sheetId": sid,
            "gridProperties": {"columnCount": max(n_cols + 2, 26)}},
            "fields": "gridProperties.columnCount"}},
    ]
    for _ in range(cf_counts.get(name, 0)):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    cf_counts[name] = 0
    reqs += [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "index": 3 + hidx,
            "gridProperties": {"frozenRowCount": frozen, "frozenColumnCount": 2}},
            "fields": "index,gridProperties(frozenRowCount,frozenColumnCount)"}},
        # мерджить через границу закреплённых колонок нельзя — два отдельных мерджа
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 0, "endColumnIndex": 2}, "mergeType": "MERGE_ALL"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 340}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 120}, "fields": "pixelSize"}},
    ]
    if all_days:
        reqs.append({"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
            "startColumnIndex": 2, "endColumnIndex": n_cols}, "mergeType": "MERGE_ALL"}})
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": 2, "endIndex": n_cols}, "properties": {"pixelSize": 62}, "fields": "pixelSize"}})
    reqs += [
        {"updateCells": {"range": {"sheetId": sid, "startRowIndex": 0, "startColumnIndex": 0,
                                   "endRowIndex": len(grid), "endColumnIndex": n_cols},
                         "rows": [{"values": rw} for rw in grid],
                         "fields": "userEnteredValue,userEnteredFormat"}},
    ]
    print(f"{name}: {len(grid) - frozen} строк позиция×бренд, {len(all_days)} дн")

# порядок запросов важен — шлём последовательными чанками
for i in range(0, len(reqs), 300):
    api(f"{BASE}:batchUpdate", {"requests": reqs[i:i+300]})
verify = api(f"{BASE}/values/{urllib.parse.quote('Общее')}!B2:{col_a1(1+len(BRANDS)+1)}2").get("values", [[]])[0]
print("VERIFY строка Итого «Общее»:", verify)
print(f"VERIFY «История Общее» за {DD}: {hist_verify}",
      "OK" if hist_verify == tot_wb + tot_oz else f"≠ {tot_wb + tot_oz} (MISMATCH)")
print("DONE")

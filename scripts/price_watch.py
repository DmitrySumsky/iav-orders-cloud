#!/usr/bin/env python3
"""Часовой монитор «мы стали дороже конкурентов» по таблице «Аналитика цен».

Живая цена берётся НЕ из MPStats (там только дневной срез), а из публичного
card.wb.ru: `sizes[0].price.product / 100` = цена карточки, цена с WB-Кошельком
= floor(цена * 0.98) — сверено с MPStats, расхождений нет. До 100 артикулов
за запрос, без авторизации: весь лист (321 артикул) закрывается 4 запросами.

Товарная группа = значение колонки A (тянется вниз, пустая строка = разделитель).
Внутри группы наши бренды сравниваются с конкурентами тремя способами:
минимум / медиана / «дороже всех». Порог и получатели живут в листе
«Мониторинг цен» этой же книги — он же хранит состояние (что уже отправлено),
поэтому почасовые прогоны не коммитят ничего в репозиторий.

Использование:
  python3 price_watch.py --keys api_keys.txt[,extra] --sa google_sa.json \
      --sheet-id <ID> [--dry-run] [--force]
Печатает DONE при успехе.
"""
import argparse, html, json, math, os, re, statistics, sys, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
import jwt

BASE = "https://sheets.googleapis.com/v4/spreadsheets/"
MON_TITLE = "Мониторинг цен"
MSK = timezone(timedelta(hours=3))
COLS = ["Артикул", "Товар (группа)", "Бренд", "Наша цена", "Мин. конкурент",
        "Цена мин.", "% к мин.", "Медиана", "% к медиане", "Дешевле нас",
        "Статус", "Обновлено", "% при уведомлении"]
DEFAULTS = {"Порог, %": "5", "Получатели TG": "", "Часы работы (МСК)": "8-17",
            "Дни недели": "пн-пт", "Срочный порог, %": "",
            "Включён": "да", "Наши бренды": "NATURI, SUNSHINE, Health Form, 4ME, VEXOR, ORZAX",
            "Разбивать по брендам": "нет", "Чаты по брендам": "",
            "Тест: всё в чат": ""}
DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
# Раскладка листа СЧИТАЕТСЯ от числа настроек, а не забита числами: иначе новая
# строка настроек молча наезжает на строку «Сейчас» и затирает её значение.
# 1 — заголовок, 2..N+1 — настройки, N+2 — пусто, N+3 — «Сейчас», N+4 — шапка.
SUMMARY_ROW = len(DEFAULTS) + 3
HEAD_ROW = len(DEFAULTS) + 4
FIRST_DATA_ROW = HEAD_ROW + 1
NOTE = ("порог работает в обе стороны: на столько % дороже минимума конкурентов "
        "(теряем продажи) или дешевле его же (отдаём маржу). «Дни недели»: пн-пт, "
        "пн-вс или список через запятую. «Срочный порог, %»: пусто = вне рабочего "
        "окна молчим; заполнено = и ночью, и в выходной придёт то, где разрыв "
        "дорос до этого значения. «Чаты по брендам»: "
        "NATURI=-100…:5, SUNSHINE=-100…:7 — пусто = берётся из ключей отчёта. "
        "«Тест: всё в чат» — репетиция рассылки: разбивка по брендам включается "
        "принудительно, но все сообщения уходят в указанный чат с пометкой, куда "
        "они пойдут в бою; состояние при этом не помечается")
# повторное уведомление по той же позиции — только если разрыв вырос на столько п.п.
REALERT_STEP = 3.0
# Гистерезис: вход в сигнал по порогу, выход — когда разрыв ужался до половины
# порога. Симметричная петля шириной в половину порога; на нуле выходить нельзя —
# при пороге 5% это давало бы «липкую» зону в 5 п.п., позиция висела бы в сигнале
# годами. Ширина петли считается от порога, поэтому его правка не ломает логику.
HYST_FRAC = 0.5
# сколько товарных групп разбирать подробно, остальные — одной строкой
DETAIL_GROUPS = 12

# порядок строк в листе: самое горячее наверх. «Дороже» — риск потерять продажи,
# «дешевле» — недобранная маржа; первое срочнее, поэтому идёт выше
RANK = {"дороже": 0, "дешевле": 1, "ок": 2, "нет конкурентов": 3, "нет цены": 4}
# ширины колонок листа (px), под COLS; последняя (тех. поле) прячется
WIDTHS = [95, 300, 105, 90, 165, 90, 85, 90, 105, 100, 105, 105, 120]
# Заливка строки по разрыву с минимумом конкурента. Красная шкала — мы дороже
# (чем краснее, тем срочнее), зелёная — мы дешевле всех с большим отрывом
# (можно поднять цену и остаться самыми дешёвыми). Границы в %.
BANDS_UP = [(15.0, "#E06666", True), (8.0, "#EA9999", False),
            (3.0, "#F4CCCC", False), (0.0, "#FCE8E6", False)]
BANDS_DOWN = [(20.0, "#93C47D", True), (12.0, "#B6D7A8", False),
              (0.0, "#D9EAD3", False)]
WHITE, GRAY = "#FFFFFF", "#EFEFEF"

esc = lambda s: html.escape(str(s), quote=True)


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


def row_style(row):
    """Цвет и жирность строки листа по её статусу и разрыву с минимумом."""
    status, d_min = row[10], row[6]
    if isinstance(d_min, (int, float)):
        if status == "дороже":
            for edge, color, bold in BANDS_UP:
                if d_min >= edge:
                    return color, bold
            return BANDS_UP[-1][1], False
        if status == "дешевле":
            for edge, color, bold in BANDS_DOWN:
                if -d_min >= edge:
                    return color, bold
            return BANDS_DOWN[-1][1], False
    if status in ("нет цены", "нет конкурентов"):
        return GRAY, False
    return WHITE, False


def decorate(sheet_id, tok, gid, out, need_rows, has_alerts):
    """Оформление листа: заливка строк по остроте, форматы чисел, ширины.

    Цвета считаются здесь и кладутся статикой, а НЕ условным форматированием:
    правил расплодились бы сотни (та же причина, что в svod_report).
    Строки уже отсортированы по остроте, поэтому одинаковые цвета идут подряд
    и вся заливка укладывается в несколько repeatCell вместо строки на каждую.
    """
    reqs = [{"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}}
            for i, w in enumerate(WIDTHS)]
    reqs.append({"updateDimensionProperties": {           # тех. поле анти-спама
        "range": {"sheetId": gid, "dimension": "COLUMNS",
                  "startIndex": len(COLS) - 1, "endIndex": len(COLS)},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})

    body = {"startRowIndex": FIRST_DATA_ROW - 1, "endRowIndex": need_rows,
            "startColumnIndex": 0, "endColumnIndex": len(COLS)}
    reqs.append({"repeatCell": {"range": {"sheetId": gid, **body},
        "cell": {"userEnteredFormat": {"backgroundColor": rgb(WHITE),
                                       "textFormat": {"bold": False}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}})

    band_start, band_style, i = 0, None, 0
    for i, row in enumerate(out):
        st = row_style(row)
        if band_style is None:
            band_style = st
        elif st != band_style:
            reqs.append(paint(gid, FIRST_DATA_ROW - 1 + band_start,
                              FIRST_DATA_ROW - 1 + i, band_style))
            band_start, band_style = i, st
    if out and band_style is not None:
        reqs.append(paint(gid, FIRST_DATA_ROW - 1 + band_start,
                          FIRST_DATA_ROW - 1 + len(out), band_style))

    for cols, fmt in (((3, 4), None), ((5, 6), None), ((7, 8), None),
                      ((6, 7), '0.0"%"'), ((8, 9), '0.0"%"')):
        pattern = fmt or '#,##0" ₽"'
        reqs.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": FIRST_DATA_ROW - 1,
                      "endRowIndex": need_rows,
                      "startColumnIndex": cols[0], "endColumnIndex": cols[1]},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                            "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat"}})

    reqs.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": SUMMARY_ROW - 1,
                  "endRowIndex": SUMMARY_ROW, "startColumnIndex": 0,
                  "endColumnIndex": len(COLS)},
        "cell": {"userEnteredFormat": {
            "backgroundColor": rgb("#F4CCCC" if has_alerts else "#D9EAD3"),
            "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}})

    api(sheet_id + ":batchUpdate", tok, "POST", {"requests": reqs})


def paint(gid, r0, r1, style):
    color, bold = style
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": 0, "endColumnIndex": len(COLS)},
        "cell": {"userEnteredFormat": {"backgroundColor": rgb(color),
                                       "textFormat": {"bold": bold}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}}


def say(msg):
    """Прогресс с отметкой времени: почасовой прогон разбирают по логу, а не вживую."""
    print(f"[{datetime.now(MSK):%H:%M:%S}] {msg}", flush=True)


def load_keys(paths):
    d = {}
    for p in paths.split(","):
        p = p.strip()
        if not p:
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def token_of(sa_path, tries=4):
    """Токен сервисного аккаунта. С ретраем: разовый таймаут на выдаче токена
    иначе убивает весь часовой прогон ещё до первого запроса к таблице."""
    SA = json.load(open(sa_path)); now = int(time.time())
    a_ = jwt.encode({"iss": SA["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
                     "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
                    SA["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": a_}).encode()
    for attempt in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(min(20, 3 * (2 ** attempt)))


def api(path, tok, method="GET", body=None, tries=5):
    """Sheets API с backoff: 429/5xx у Google — транзиентные (ловили 503)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"}, method=method)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            print("Sheets API:", e.code, e.read()[:400].decode("utf-8", "replace"))
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            raise


def col_letter(i0):
    s, i = "", i0 + 1
    while i:
        i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s


def wb_live(arts, tries=4):
    """{артикул: цена с WB-Кошельком}. Нет в ответе = нет в наличии/удалён."""
    out = {}
    for k in range(0, len(arts), 100):
        chunk = arts[k:k + 100]
        url = "https://card.wb.ru/cards/v4/detail?" + urllib.parse.urlencode(
            {"appType": 1, "curr": "rub", "dest": -1257786, "spp": 30, "nm": ";".join(chunk)})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        for i in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    raw = r.read()
                # на удалённый/скрытый артикул полка отвечает 200 с пустым телом
                if not raw.strip():
                    break
                for p in json.loads(raw).get("products", []):
                    pr = ((p.get("sizes") or [{}])[0].get("price") or {})
                    prod = pr.get("product")
                    if prod:
                        out[str(p["id"])] = math.floor(prod / 100 * 0.98)
                break
            except Exception:
                if i == tries - 1:
                    print(f"  card.wb.ru: пачка {k // 100 + 1} не ответила — артикулы пропущены")
                else:
                    time.sleep(1.5 * (i + 1))
    return out


def as_num(x):
    x = re.sub(r"[^\d.-]", "", str(x).replace(",", "."))
    try:
        return float(x)
    except ValueError:
        return None


def find_sheet(sheet_id, tok, title):
    meta = api(sheet_id + "?fields=sheets.properties(sheetId,title,index)", tok)
    return next((s["properties"] for s in meta["sheets"]
                 if s["properties"]["title"] == title), None)


def ensure_monitor(sheet_id, tok, sheets, tg_default, dry=False):
    """Лист «Мониторинг цен»: создать/переложить шапку, вернуть (gid, настройки, состояние).

    Идемпотентно: addSheet мог пройти на сервере, а ответ — потеряться в сети,
    тогда ретрай вернёт 400 «already exists» — это не ошибка, лист просто есть.

    При dry=True лист НЕ трогается вообще. Иначе «сухой» прогон перекладывал
    раскладку (очистка + запись блока), а данные не писал, потому что выходил
    раньше — и состояние обнулялось, а следующий боевой прогон слал всю базу
    заново как новые сигналы. Поймано в бою 28.07.2026.
    """
    props = next((p for p in sheets if p["title"] == MON_TITLE), None)
    if not props and dry:
        print(f"  dry-run: листа «{MON_TITLE}» нет, работаю на дефолтных настройках")
        d = dict(DEFAULTS); d["Получатели TG"] = tg_default
        return None, d, {}
    if not props:
        print(f"Лист «{MON_TITLE}» не найден — создаю")
        try:
            res = api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
                {"addSheet": {"properties": {"title": MON_TITLE,
                                             "gridProperties": {"rowCount": 500,
                                                                "columnCount": len(COLS)}}}}]})
            props = res["replies"][0]["addSheet"]["properties"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            props = find_sheet(sheet_id, tok, MON_TITLE)
            if not props:
                raise
            print("  лист уже был создан (ответ на создание потерялся) — продолжаю")

    q = urllib.parse.quote("'" + MON_TITLE + "'")
    vals = api(f"{sheet_id}/values/{q}!A1:M2000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])

    # где шапка таблицы стоит СЕЙЧАС: раскладка могла быть сделана прошлой
    # версией скрипта с другим числом настроек
    old_head = None
    for idx, row in enumerate(vals[:30], 1):
        if row and row[0].strip() == COLS[0]:
            old_head = idx
            break

    cfg = dict(DEFAULTS)
    for row in vals[:(old_head - 1) if old_head else 30]:
        if len(row) > 1 and row[0].strip() in DEFAULTS:
            cfg[row[0].strip()] = row[1].strip()
    if not cfg["Получатели TG"].strip():
        cfg["Получатели TG"] = tg_default

    state = {}
    if old_head:
        for row in vals[old_head:]:
            art = (row[0].strip() if row else "")
            # ключ — пара «артикул + группа»: один и тот же nmID конкурента (и наш)
            # может стоять сразу в нескольких товарных группах (боевой случай VEXOR)
            grp = (row[1].strip() if len(row) > 1 else "")
            if art.isdigit():
                state[(art, grp)] = {"статус": (row[10].strip() if len(row) > 10 else ""),
                                     "пункты": as_num(row[12]) if len(row) > 12 else None}

    if old_head != HEAD_ROW and dry:
        print(f"  dry-run: раскладку не трогаю (шапка в строке {old_head or '—'})")
    elif old_head != HEAD_ROW:
        # Перекладываем верх листа: настройки записываем ТЕКУЩИМИ значениями
        # (иначе правки пользователя сбросятся на дефолты), состояние уже прочитано
        # выше, а данные всё равно переписываются каждый прогон.
        print(f"  раскладка: шапка {old_head or 'отсутствует'} → строка {HEAD_ROW}")
        api(f"{sheet_id}/values/{q}!A1:M2000:clear", tok, "POST", {})
        blank = [""] * len(COLS)
        # строки пишем на всю ширину: values.update трогает только переданные
        # ячейки, и остатки прежней раскладки иначе переживут перезапись
        rows = [["Настройки мониторинга цен", "", NOTE] + [""] * (len(COLS) - 3)]
        rows += [[k, cfg[k]] + [""] * (len(COLS) - 2) for k in DEFAULTS]
        rows.append(list(blank))
        rows.append(["Сейчас", ""] + [""] * (len(COLS) - 2))
        rows.append(list(COLS))
        assert len(rows) == HEAD_ROW, (len(rows), HEAD_ROW)
        api(sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
            "data": [{"range": f"'{MON_TITLE}'!A1", "values": rows}]})
        api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
            # сбросить заливку прежней раскладки: старая строка «Сейчас» иначе
            # останется розовой уже на месте обычной настройки
            {"repeatCell": {"range": {"sheetId": props["sheetId"], "startRowIndex": 0,
                                      "endRowIndex": HEAD_ROW, "startColumnIndex": 0,
                                      "endColumnIndex": len(COLS)},
                            "cell": {"userEnteredFormat": {"backgroundColor": rgb(WHITE),
                                                           "textFormat": {"bold": False}}},
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}},
            {"repeatCell": {"range": {"sheetId": props["sheetId"], "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}},
            {"repeatCell": {"range": {"sheetId": props["sheetId"], "startRowIndex": HEAD_ROW - 1,
                                      "endRowIndex": HEAD_ROW},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}},
            {"updateSheetProperties": {"properties": {"sheetId": props["sheetId"],
                                                      "gridProperties": {"frozenRowCount": HEAD_ROW}},
                                       "fields": "gridProperties.frozenRowCount"}}]})
    return props["sheetId"], cfg, state


def in_hours(cfg):
    m = re.match(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*$", cfg.get("Часы работы (МСК)", ""))
    if not m:
        return True
    lo, hi = int(m.group(1)), int(m.group(2))
    h = datetime.now(MSK).hour
    return lo <= h <= hi if lo <= hi else (h >= lo or h <= hi)


def in_days(cfg):
    """«пн-пт», «пн-вс»/«все», либо перечисление «пн,вт,сб». Пусто = все дни.

    Крон в GitHub ходит все семь дней — выходные включаются правкой ОДНОЙ ячейки
    в листе, без деплоя. Лишние прогоны выходят на этой проверке за секунды.
    """
    raw = cfg.get("Дни недели", "").strip().lower()
    if not raw or raw in ("все", "всегда", "пн-вс", "любые"):
        return True
    wd = datetime.now(MSK).weekday()          # 0 = понедельник
    m = re.match(r"([а-я]{2})\s*[-–]\s*([а-я]{2})\s*$", raw)
    if m and m.group(1) in DAYS and m.group(2) in DAYS:
        lo, hi = DAYS.index(m.group(1)), DAYS.index(m.group(2))
        return lo <= wd <= hi if lo <= hi else (wd >= lo or wd <= hi)
    named = {p.strip() for p in raw.replace(";", ",").split(",")} & set(DAYS)
    return DAYS[wd] in named if named else True


def tg_send(tok, targets, text):
    ok = True
    for cid, thr in targets:
        payload = {"chat_id": cid, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if thr:
            payload["message_thread_id"] = thr
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=40).read())
            print(f"  TG → {cid}{':' + thr if thr else ''}:", "OK" if r.get("ok") else r)
            ok = ok and bool(r.get("ok"))
        except Exception as e:
            print(f"  TG → {cid}: ОШИБКА {e}"); ok = False
    return ok


def parse_targets(raw):
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part.lstrip("-"):
            cid, thr = part.rsplit(":", 1)
            # топик 1 форума = General: слать без message_thread_id, иначе 400
            out.append((cid.strip(), None if thr.strip() == "1" else thr.strip()))
        else:
            out.append((part, None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", required=True)
    ap.add_argument("--sa", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--dry-run", action="store_true", help="посчитать и показать, ничего не слать и не писать")
    ap.add_argument("--force", action="store_true", help="слать все текущие превышения, игнорируя прошлое состояние")
    a = ap.parse_args()

    K = load_keys(a.keys)
    # Адреса брендов живут в «Настройках» пункта управления и перекрывают ключи.
    # Утренний отчёт их читает, а монитор раньше — нет: правка чата в таблице
    # переводила отчёт и НЕ переводила сигналы по ценам, и это было не видно.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from control_panel import load_settings
        ov = load_settings(a.sa, K)
        if ov:
            K.update(ov)
            print(f"пункт управления: перекрыто настроек {len(ov)}")
    except Exception as e:
        print(f"пункт управления недоступен ({type(e).__name__}: {str(e)[:60]}) — "
              "работаю на значениях из ключей")
    tg_token = K.get("TELEGRAM_BOT_TOKEN", "")
    say("авторизация Google…")
    tok = token_of(a.sa)
    say("читаю список листов…")
    meta = api(a.sheet_id + "?fields=properties.title,sheets.properties(sheetId,title,index)", tok)
    sheets = sorted((s["properties"] for s in meta["sheets"]), key=lambda p: p.get("index", 0))
    book = meta["properties"]["title"]

    gid, cfg, prev = ensure_monitor(a.sheet_id, tok, sheets,
                                    K.get("PRICE_WATCH_TG_CHATS", ""), dry=a.dry_run)
    thr_pct = as_num(cfg["Порог, %"]) or 5.0
    ours = {b.strip().lower() for b in cfg["Наши бренды"].split(",") if b.strip()}
    default_targets = parse_targets(cfg["Получатели TG"])
    split_brands = cfg["Разбивать по брендам"].strip().lower() in ("да", "yes", "1", "true")
    # Репетиция перед боевой рассылкой: разбивка считается включённой, но всё
    # уходит в один тестовый чат с пометкой, куда сообщение пойдёт в бою.
    # Состояние не помечается — после теста боевой прогон шлёт всё как в первый раз.
    test_targets = parse_targets(cfg["Тест: всё в чат"])
    if test_targets:
        split_brands = True
    # «Чаты по брендам»: NATURI=-100123:5, SUNSHINE=-100123:7 — перекрывает api_keys
    route_map = {}
    for part in cfg["Чаты по брендам"].split(","):
        if "=" in part:
            b, dst = part.split("=", 1)
            if b.strip() and dst.strip():
                route_map[b.strip().lower()] = parse_targets(dst)
    print(f"рассылка: {'по брендам' if split_brands else 'общая'}"
          + (f", переопределений в листе {len(route_map)}" if route_map else "")
          + (f", ТЕСТ: всё в {cfg['Тест: всё в чат'].strip()}" if test_targets else ""))
    print(f"{book}: порог {thr_pct}%, наши бренды {sorted(ours)}, окно {cfg['Часы работы (МСК)']}")
    if cfg["Включён"].strip().lower() not in ("да", "yes", "1", "true"):
        print("Мониторинг выключен в настройках листа"); print("DONE"); return
    # Вне рабочего окна по умолчанию молчим. Заполненный «Срочный порог, %»
    # оставляет форточку: придёт только то, где разрыв дорос до этого значения.
    urgent_pct = as_num(cfg["Срочный порог, %"]) or 0
    urgent_only = False
    if not a.dry_run and not a.force and not (in_hours(cfg) and in_days(cfg)):
        when = (f"{datetime.now(MSK):%a %H:%M} МСК, окно "
                f"{cfg['Дни недели']} {cfg['Часы работы (МСК)']}")
        if urgent_pct <= 0:
            print(f"Сейчас {when} — вне рабочего окна, прогон пропущен")
            print("DONE"); return
        urgent_only = True
        print(f"Сейчас {when} — вне окна, но задан срочный порог {urgent_pct}%: "
              "шлём только резкие отрывы")

    # ----- товарные группы с первого листа книги (WB) -----
    wb_title = sheets[0]["title"]
    q = urllib.parse.quote("'" + wb_title.replace("'", "''") + "'")
    rows = api(f"{a.sheet_id}/values/{q}!A2:C2000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])
    items, group = [], None
    for r in rows:
        name = (r[0].strip() if len(r) > 0 else "")
        art = (r[1].strip() if len(r) > 1 else "")
        brand = (r[2].strip() if len(r) > 2 else "")
        if name:
            group = name
        if art.isdigit():
            items.append({"group": group or "(без группы)", "art": art, "brand": brand})
    print(f"[{wb_title}] групп {len(set(i['group'] for i in items))}, артикулов {len(items)}")

    t0 = time.time()
    live = wb_live([i["art"] for i in items])
    print(f"card.wb.ru: {len(live)} живых цен из {len(items)} за {time.time() - t0:.1f} c")
    if not live:
        print("ОШИБКА: ни одной живой цены — прогон не засчитан"); sys.exit(1)

    # ----- сравнение внутри группы -----
    groups = {}
    for i in items:
        groups.setdefault(i["group"], []).append(i)

    cur, alerts, recovered = {}, [], []
    for g, lst in groups.items():
        mine = [i for i in lst if i["brand"].strip().lower() in ours]
        comp = [(i["brand"], live[i["art"]]) for i in lst
                if i["brand"].strip().lower() not in ours and i["art"] in live]
        for i in mine:
            st = {"group": g, "brand": i["brand"], "price": live.get(i["art"]),
                  "min_who": "", "min": None, "d_min": None, "med": None, "d_med": None,
                  "cheaper": None, "status": "нет цены", "top": False}
            if st["price"] and comp:
                mn = min(comp, key=lambda x: x[1])
                med = statistics.median([c[1] for c in comp])
                st["min_who"], st["min"] = mn[0], mn[1]
                st["med"] = round(med)
                st["d_min"] = round((st["price"] / mn[1] - 1) * 100, 1)
                st["d_med"] = round((st["price"] / med - 1) * 100, 1)
                st["cheaper"] = sum(1 for c in comp if c[1] < st["price"])
                st["comp_n"] = len(comp)
                st["top"] = st["cheaper"] == len(comp) and len(comp) > 0

            key = (i["art"], g)
            was = prev.get(key, {})
            was_st, was_pts = was.get("статус", ""), was.get("пункты")
            # «уже уведомляли» = не просто статус в листе, а записанные п.п. разрыва:
            # если отправка в TG упала, пункты не проставились и сигнал повторится
            notified = was_st in ("дороже", "дешевле") and was_pts is not None

            if st["price"] and comp:
                # Сигнал в обе стороны: дороже минимума конкурентов = теряем продажи,
                # дешевле минимума = отдаём маржу (можно поднять цену и всё равно
                # остаться самыми дешёвыми). Гистерезис: цены WB дёргаются на доли
                # процента, и позиция ровно на пороге иначе мигала бы каждый час
                # (поймано на двух прогонах с разницей в 5 минут) — поэтому вход в
                # сигнал по порогу, а выход только при возврате к минимуму.
                if notified:
                    exit_at = thr_pct * HYST_FRAC
                    still = (st["d_min"] > exit_at) if was_st == "дороже" \
                        else (st["d_min"] < -exit_at)
                    st["status"] = was_st if still else "ок"
                elif st["d_min"] > thr_pct:
                    st["status"] = "дороже"
                elif st["d_min"] < -thr_pct:
                    st["status"] = "дешевле"
                else:
                    st["status"] = "ок"
            elif st["price"]:
                st["status"] = "нет конкурентов"
            cur[key] = st

            if st["status"] in ("дороже", "дешевле"):
                # «хуже» — это дальше от рынка в свою сторону
                grew = was_pts is not None and (
                    st["d_min"] >= was_pts + REALERT_STEP if st["status"] == "дороже"
                    else st["d_min"] <= was_pts - REALERT_STEP)
                if (a.force or not notified or grew) and \
                        (not urgent_only or abs(st["d_min"]) >= urgent_pct):
                    alerts.append((key, st, "рост" if (grew and notified) else "новое"))
            elif st["status"] == "ок" and notified:
                if urgent_only:
                    # Срочный прогон только ДОБАВЛЯЕТ сигналы, закрывать их он не
                    # вправе: иначе «вернулись к рынку» тихо съедалось бы ночью.
                    # Оставляем позицию в прежнем статусе — утренний прогон в окне
                    # увидит её как незакрытую и отправит возврат.
                    st["status"] = was_st
                else:
                    recovered.append((key, st, was_st))

    now_s = f"{datetime.now(MSK):%d.%m %H:%M}"
    total_over = sum(1 for s in cur.values() if s["status"] == "дороже")
    total_under = sum(1 for s in cur.values() if s["status"] == "дешевле")
    print(f"позиций наших: {len(cur)}, дороже минимума на >{thr_pct}%: {total_over}, "
          f"дешевле на >{thr_pct}%: {total_under}, новых сигналов: {len(alerts)}, "
          f"вернулись к рынку: {len(recovered)}")

    # ----- сообщения (по адресатам) -----
    def targets_for(brand):
        """Куда слать сигнал по этому бренду. Пока разбивка выключена — всем в
        общий адрес. Включённая ищет бренд в настройке листа, затем в api_keys
        (`<PREFIX>_TG_CHATS` — те же чаты, что у утреннего отчёта), и только
        потом падает на общий адрес."""
        if not split_brands:
            return default_targets
        b = brand.strip().lower()
        if b in route_map:
            return route_map[b]
        raw = K.get(re.sub(r"[^A-Z0-9]", "", brand.upper()) + "_TG_CHATS", "")
        return parse_targets(raw) if raw else default_targets

    def build_message(part_alerts, part_recovered, scope):
        """Текст для одного адресата + ключи, которые в него вошли."""
        lines, keys = [], set()

        def section(head, entries_list, sign):
            # sign=+1 — мы дороже, -1 — мы дешевле; знак задаёт и порядок:
            # сначала самый большой разрыв в свою сторону
            if not entries_list:
                return
            by_group = {}
            for key, s, kind in entries_list:
                by_group.setdefault(s["group"], []).append((key, s, kind))
            ordered = sorted(by_group.items(),
                             key=lambda kv: -max(sign * x[1]["d_min"] for x in kv[1]))
            lines.append(head.format(n=len(entries_list), g=len(ordered)))
            lines.append("")
            for gname, entries in ordered[:DETAIL_GROUPS]:
                s0 = entries[0][1]
                lines.append(f"<b>{esc(gname)}</b>")
                lines.append(f"мин. {esc(s0['min_who'])} {s0['min']} ₽ · медиана {s0['med']} ₽ · "
                             f"конкурентов {s0.get('comp_n', 0)}")
                for key, s, kind in sorted(entries, key=lambda x: -sign * x[1]["d_min"]):
                    mark = "📈 " if kind == "рост" else ""
                    flag = " ‼️ дороже всех" if (sign > 0 and s["top"]) else ""
                    url = f"https://www.wildberries.ru/catalog/{key[0]}/detail.aspx"
                    lines.append(f"{mark}• <a href=\"{url}\">{esc(s['brand'])}</a> {s['price']} ₽ — "
                                 f"{s['d_min']:+}% к мин., {s['d_med']:+}% к медиане{flag}")
                    keys.add(key)
                lines.append("")
            tail = ordered[DETAIL_GROUPS:]
            if tail:
                lines.append(f"<b>Ещё {sum(len(e) for _, e in tail)} позиций (кратко):</b>")
                for gname, entries in tail:
                    for key, s, kind in sorted(entries, key=lambda x: -sign * x[1]["d_min"]):
                        lines.append(f"• {esc(gname)} — {esc(s['brand'])} {s['price']} ₽ "
                                     f"({s['d_min']:+}% к мин. {s['min']} ₽)")
                        keys.add(key)
                lines.append("")

        brands = sorted({s["brand"] for s in scope})
        head_brand = (brands[0] if len(brands) == 1 else ", ".join(brands)[:60])
        over = sum(1 for s in scope if s["status"] == "дороже")
        under = sum(1 for s in scope if s["status"] == "дешевле")
        lines.append(f"📊 <b>{esc(head_brand)} — цены на {now_s} МСК</b>")
        lines.append(f"дороже конкурентов: {over} из {len(scope)} · "
                     f"дешевле рынка: {under} · порог {thr_pct}%")
        lines.append("")
        section("⚠️ <b>СТАЛИ ДОРОЖЕ</b> — {n} позиций по {g} товарам",
                [x for x in part_alerts if x[1]["status"] == "дороже"], 1)
        section("💰 <b>СИЛЬНО ДЕШЕВЛЕ ВСЕХ</b> — {n} позиций по {g} товарам, "
                "можно поднять цену",
                [x for x in part_alerts if x[1]["status"] == "дешевле"], -1)
        if part_recovered:
            lines.append(f"✅ <b>Вернулись к рынку: {len(part_recovered)}</b>")
            for key, s, was_st in part_recovered:
                lines.append(f"• {esc(s['group'])} — {esc(s['brand'])} {s['price']} ₽ "
                             f"(было «{was_st}», сейчас {s['d_min']:+}% к мин. {s['min']} ₽)")
                keys.add(key)
            lines.append("")
        lines.append(f"<a href=\"https://docs.google.com/spreadsheets/d/{a.sheet_id}/edit\">"
                     f"Таблица цен</a>")
        return "\n".join(lines), keys

    def send_chunked(targets, text):
        chunks, buf = [], ""      # лимит Telegram — 4096 символов на сообщение
        for block in text.split("\n\n"):
            if buf and len(buf) + len(block) + 2 > 3500:
                chunks.append(buf); buf = block
            else:
                buf = (buf + "\n\n" + block) if buf else block
        if buf:
            chunks.append(buf)
        for c in [c for c in chunks if c.strip()]:
            if not tg_send(tg_token, targets, c):
                return False
        return True

    sent_keys = set()
    if alerts or recovered:
        # раскладываем сигналы по адресатам: у каждого чата своё сообщение и
        # свои счётчики, чтобы бренду не прилетала чужая статистика
        # ключ маршрута — адресат; в тестовом режиме адресат у всех один, поэтому
        # группируем по бренду, иначе репетиция слепила бы всё в одно сообщение
        def route_key(brand):
            return brand.strip() if test_targets else tuple(targets_for(brand))

        routes = {}
        for item in alerts:
            routes.setdefault(route_key(item[1]["brand"]), {"a": [], "r": []})["a"].append(item)
        for item in recovered:
            routes.setdefault(route_key(item[1]["brand"]), {"a": [], "r": []})["r"].append(item)

        def addr(t):
            return ", ".join(c + (":" + th if th else "") for c, th in t) or "—"

        for key, data in routes.items():
            brands_here = {s["brand"] for _, s, *_ in data["a"] + data["r"]}
            scope = [s for s in cur.values() if s["brand"] in brands_here]
            text, keys = build_message(data["a"], data["r"], scope)
            if test_targets:
                targets, real = list(test_targets), targets_for(key)
                text = (f"🧪 <b>ТЕСТ рассылки.</b> Бренд <b>{html.escape(key)}</b>, "
                        f"в бою уйдёт в <code>{addr(real)}</code>\n\n" + text)
            else:
                targets = list(key)
            who = addr(targets)
            if a.dry_run:
                print(f"\n----- сообщение для {who} (dry-run, не отправлено) -----")
                print(text)
                continue
            if not tg_token or not targets:
                print(f"ВНИМАНИЕ: некуда слать ({who}) — сообщение пропущено")
                continue
            if send_chunked(list(targets), text) and not test_targets:
                # в тесте состояние не помечаем: боевая рассылка должна уйти
                # как первая, а не «вы это уже видели»
                sent_keys |= keys      # иначе не помечаем: повторим в следующий прогон
    else:
        print("новых сигналов нет — сообщения не отправлялись")

    # ----- состояние в лист -----
    if a.dry_run:
        print("dry-run: лист не изменён"); print("DONE"); return

    # Порядок = приоритет: сначала где мы дороже всего (риск потерять продажи),
    # следом где мы сильнее всего дешевле рынка (недобранная маржа), потом «ок»
    # (ближайшие к порогу выше), в конце — строки без сравнения. Лист читают
    # сверху вниз и обычно только верх, поэтому сортировка тут важнее алфавита.
    def sort_key(kv):
        s = kv[1]
        d = s["d_min"] if s["d_min"] is not None else -999
        # внутри «дешевле» первым идёт самый большой отрыв вниз, то есть самый
        # маленький d_min — поэтому знак второго ключа зависит от статуса
        return (RANK.get(s["status"], 9), d if s["status"] == "дешевле" else -d,
                s["group"], s["brand"])

    order = sorted(cur.items(), key=sort_key)
    out = []
    for key, s in order:
        art = key[0]
        was = prev.get(key, {})
        pts = s["d_min"] if key in sent_keys else was.get("пункты")
        if s["status"] not in ("дороже", "дешевле"):
            pts = ""
        out.append([art, s["group"], s["brand"], s["price"] or "", s["min_who"],
                    s["min"] if s["min"] is not None else "",
                    s["d_min"] if s["d_min"] is not None else "",
                    s["med"] if s["med"] is not None else "",
                    s["d_med"] if s["d_med"] is not None else "",
                    s["cheaper"] if s["cheaper"] is not None else "",
                    s["status"], now_s, pts if pts is not None else ""])

    top_n = sum(1 for s in cur.values() if s["status"] == "дороже" and s["top"])
    no_price = sum(1 for s in cur.values() if s["status"] == "нет цены")
    summary = (f"дороже конкурентов: {total_over} из {len(cur)}"
               + (f" · дороже ВСЕХ в группе: {top_n}" if top_n else "")
               + f" · сильно дешевле рынка: {total_under}"
               + (f" · без цены (нет в наличии): {no_price}" if no_price else "")
               + f" · порог {thr_pct}% · обновлено {now_s} МСК")

    need_rows = FIRST_DATA_ROW + len(out) + 20
    last = col_letter(len(COLS) - 1)
    api(a.sheet_id + ":batchUpdate", tok, "POST", {"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": gid,
                                                  "gridProperties": {"rowCount": need_rows,
                                                                     "columnCount": len(COLS)}},
                                   "fields": "gridProperties(rowCount,columnCount)"}}]})
    api(f"{a.sheet_id}/values/'{urllib.parse.quote(MON_TITLE)}'!A{FIRST_DATA_ROW}:{last}2000:clear",
        tok, "POST", {})
    api(a.sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
        "data": [{"range": f"'{MON_TITLE}'!A{SUMMARY_ROW}", "values": [["Сейчас", summary]]},
                 {"range": f"'{MON_TITLE}'!A{FIRST_DATA_ROW}", "values": out}]})
    decorate(a.sheet_id, tok, gid, out, need_rows, bool(total_over))
    print(f"лист «{MON_TITLE}»: записано {len(out)} строк, наверху — {out[0][1] if out else '—'}")
    print("DONE")


if __name__ == "__main__":
    main()

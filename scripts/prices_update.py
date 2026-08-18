#!/usr/bin/env python3
"""ОТЧЁТ ПО ЦЕНАМ WB + Ozon v2.1.0 — 18.08.2026
  ПРОПУЩЕННЫЕ ДНИ ПОЗАДИ СВЕЖЕЙ КОЛОНКИ НЕ ДОГОНЯЛИСЬ НИКОГДА
  • Долив дыр ВНУТРИ блока дат: всё, что MPStats отдаёт в своём 30-дневном
    окне и чего нет в шапке, вставляется колонкой на своё место по порядку
    и заполняется. Обычная вставка идёт только слева (`while d > newest`) и
    дни, оставшиеся позади самой свежей колонки, не видит — а остаться без
    данных на несколько суток штатный случай (выбранная квота, упавший
    прогон), поэтому долив обязан жить в логике, а не в разовом скрипте.
  • Старее самой старой колонки книга не растёт: дыры берутся строго выше
    её нижней границы. Выключается `--no-gap-fill`.
  • Проверено на временном листе с искусственным пропуском 13–16.08
    (контур Ozon, 12 боевых SKU): четыре колонки встали по порядку между
    17.08 и 12.08, заполнены все 72 ячейки.

v2.0.0 — 18.08.2026.

Ежедневное обновление таблиц «Аналитика цен» (облачная версия скилла
wb-ceny-konkurentov + Ozon-контур).

История версий (новое сверху, старое не переписывать):

v2.0.0 — 18.08.2026
  ЦЕНЫ WB СТОЯЛИ ПЯТЬ СУТОК: У MPStats ВЫБРАНА СУТОЧНАЯ КВОТА ПО WB
  (жалоба «таблица не обновляется» по книге автохимии VEXOR, 18.08.2026)
  • WB получил резервный источник — публичный `card.wb.ru/cards/v4/detail`
    (без ключа и без квоты). MPStats остаётся основным: он отдаёт закрытый
    день и 30 дней истории. Резерв включается сам, когда MPStats не ответил
    на пробы, и пишет цену «сейчас» в колонку за СЕГОДНЯ.
  • Резерв НЕ заводит колонки за пропущенные дни: истории у card.wb.ru нет,
    пустая колонка посреди блока дат уже никогда не заполнится.
  • Товар без предложения резерв помечает словами «нет в наличии» / «нет
    карточки», а не молчит: у MPStats на такой товар всё равно есть число
    (последняя известная цена), и без пометки колонка выглядела бы дырявой
    без объяснения. На автохимии это 80 строк из 374 — проверено по четырём
    регионам, дело не в `dest`. Упавший батч не пишется вообще: дырка замера
    не должна выглядеть как факт о товаре.
  • Код 429 «Превышен лимит запросов за <дата>» больше не ретраится вместе
    с 5xx и не маскируется под «MPStats не ответил»: до полуночи ответ не
    изменится, а в логе теперь прямо написано про исчерпанный лимит.
  • Ozon резерва не получил — публичного аналога card.wb.ru у него нет,
    квота Ozon в MPStats считается отдельно от WB и не выбрана.
  Сверка источников за 08–11.08.2026 по 280+ общим артикулам: расхождений
  0–1 %. На 12.08 разошлись 52 из 284 ровно в отношении 1.25 и 1.43 — это
  волна СПП (20 % и 30 %), см. проект 55: размер СПП задаёт склад отгрузки,
  и «правильного» числа на весь день не существует ни у одного источника.

Листы одной таблицы:
  - первый лист книги               — WB, цена wallet_price (с WB-Кошельком)
  - лист с «ozon» в имени (если есть) — Ozon, цена ozon_card_price (с Ozon Картой)
Раскладка листа: A=название, B=артикул(nmID/SKU), C=бренд, D..=даты DD.MM (свежая слева).

Логика по каждому листу: узнать последнюю дату MPStats -> вставить недостающие
столбцы слева (история не трогается) -> заполнить; пустой ответ MPStats никогда
не затирает старые значения. Конкурентов в строки добавляют руками — скрипт
подхватывает любые новые строки.

Ручные колонки людей не трогаются (правило с 30.07.2026):
  - новые даты вставляются ПЕРЕД первой датированной колонкой, а не жёстко в D,
    поэтому вспомогательные колонки слева от блока дат («Средняя» и т.п.) стоят
    на месте, а не уползают вправо с каждым прогоном;
  - пишем только в колонки, у которых в шапке разобранная дата: колонка без даты
    внутри блока дат остаётся как есть (раньше её содержимое затиралось — живая
    формула превращалась в замороженное число);
  - колонка артикула ищется ПО ШАПКЕ (31.07.2026): в книге автохимии менеджер
    завёл слева «Прогрев» и «Прогрев к-во», и всё, что считало «артикул = B»,
    стало бы читать не ту колонку. Ручные колонки печатаются в лог каждым
    прогоном — видно, что именно скрипт обязан сохранить.

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

# Резервный источник цены WB — публичная карточка WB (без ключа, без квоты).
# Цена с WB-кошельком = floor(price.product / 100 * 0.98) — ровно та колонка,
# которую ведут менеджеры (сверка с MPStats — см. историю версий, v2.0.0).
CARD_URL = "https://card.wb.ru/cards/v4/detail"
CARD_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}
DEST_MOSCOW = "-1257786"
WALLET_K = 0.98
CARD_BATCH = 100        # больше 100 артикулов за запрос card.wb.ru не отдаёт

# Три состояния, которые нельзя смешивать (та же логика, что в проекте 34):
# цены нет, потому что товара нет в продаже; карточки нет вовсе; запрос не
# прошёл. Последнее — дырка замера, а не факт о товаре, поэтому в таблицу не
# пишется: ячейка остаётся такой, какой была.
STATE_NONE = "нет в наличии"
STATE_GONE = "нет карточки"

MP_LIMIT = {"hit": False}   # взводится, когда MPStats ответил «превышен лимит»

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
    SA = json.load(open(sa_path, encoding="utf-8")); now = int(time.time())
    a_ = jwt.encode({"iss": SA["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
        SA["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": a_}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]

def api(path, tok, method="GET", body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, method=method)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 429/5xx у Google Sheets — транзиентные (сегодня утренний прогон
            # упал на разовом 503); ретраим с backoff, 4xx (кроме 429) — сразу
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
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
            if e.code == 429:
                # Суточная квота и минутный троттлинг у MPStats отвечают
                # одинаково — 429; отличаем по телу. Квоту ретраить незачем:
                # до полуночи ответ не изменится, а ретраи съедают прогон.
                try:
                    msg = json.loads(e.read() or b"{}").get("message", "")
                except Exception:
                    msg = ""
                if "лимит" in msg.lower():
                    MP_LIMIT["hit"] = True
                    return {}
                time.sleep(1.0 * (i + 1)); continue
            if e.code in (500, 502, 503): time.sleep(1.0 * (i + 1)); continue
            return {}
        except Exception:
            time.sleep(0.7 * (i + 1))
    out = {}
    if isinstance(rows, list):
        for r in rows:
            d = r.get("data"); v = r.get(field) or r.get("final_price")
            if d and v: out[d] = round(v)
    return out

def wb_live_prices(arts):
    """{артикул: цена с кошельком} с card.wb.ru, батчами по 100.

    Резерв для WB, когда MPStats недоступен. Отдаёт цену «сейчас», а не
    закрытый день, поэтому колонка пишется за СЕГОДНЯ. Артикул, которого нет
    в ответе (карточка удалена) или без цены (нет в продаже), в словарь не
    попадает — в таблице такая ячейка останется пустой, а не занулится.
    """
    out = {}
    for i in range(0, len(arts), CARD_BATCH):
        chunk = arts[i:i + CARD_BATCH]
        ok = False
        qs = urllib.parse.urlencode({"appType": "1", "curr": "rub", "spp": "30",
                                     "dest": DEST_MOSCOW, "nm": ";".join(chunk)})
        data = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(CARD_URL + "?" + qs, headers=CARD_HEADERS)
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                # HTTP 200 с пустым телом — штатный ответ WB на мёртвые
                # артикулы, а не сбой: ретраить нечего.
                data = json.loads(body) if body.strip() else {}
                ok = True
                break
            except Exception:
                if attempt < 3: time.sleep(1.0 * (attempt + 1))
        if not ok:
            continue                      # батч не прошёл — молчим, а не врём
        seen = set()
        for p in (data or {}).get("products") or []:
            nm = str(p["id"]); seen.add(nm)
            kop = None
            for size in p.get("sizes") or []:
                pr = (size.get("price") or {}).get("product")
                if pr: kop = pr; break
            out[nm] = int(kop / 100 * WALLET_K) if kop else STATE_NONE  # int = floor
        for nm in chunk:
            if nm not in seen:
                out[nm] = STATE_GONE
        time.sleep(0.2)
    return out

def as_int(x):
    x = re.sub(r"[^\d]", "", str(x))
    return int(x) if x else ""

def col_by(hdr, words, default):
    """Индекс колонки по слову в шапке. Раскладка ищется ПО ИМЕНАМ, а не по
    буквам: менеджеры заводят слева от дат свои колонки («Прогрев» и
    «Прогрев к-во» в книге автохимии, 31.07.2026), и всё, что завязано на
    «артикул = B», после этого читает не ту колонку."""
    for i, h in enumerate(hdr):
        if any(w in str(h).strip().lower() for w in words):
            return i
    return default


def date_cols(hdr, today, first=None):
    """{индекс колонки: iso-дата} по шапке — только там, где дата разобралась."""
    lo = FIRST_DATE_COL - 1 if first is None else first
    out = {}
    for i, v in enumerate(hdr):
        if i >= lo and str(v).strip():
            iso = hdr_to_iso(str(v), today)
            if iso: out[i] = iso
    return out

def runs_of(idxs):
    """Подряд идущие индексы -> список (начало, конец). Нужен, чтобы писать
    только в датированные колонки и перепрыгивать чужие."""
    runs = []
    for i in sorted(idxs):
        if runs and i == runs[-1][1] + 1: runs[-1][1] = i
        else: runs.append([i, i])
    return [(a, b) for a, b in runs]

def process_tab(sheet_id, tok, props, mp_token, mp_kind, field, workers, gaps=True):
    """Один лист: догнать даты + заполнить пустые. Возвращает None или ошибку."""
    title, gid = props["title"], props["sheetId"]
    q = "'" + title.replace("'", "''") + "'"; qurl = urllib.parse.quote(q)
    today = date.today()

    hdr0 = api(f"{sheet_id}/values/{qurl}!A1:BZ1?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [[]])[0]
    i_art = col_by(hdr0, ("артикул", "nmid", "sku"), 1)
    rows = api(f"{sheet_id}/values/{qurl}!A2:{col_letter(i_art)}5000"
               f"?valueRenderOption=FORMATTED_VALUE", tok).get("values", [])
    arts = [(r + 2, row[i_art].strip()) for r, row in enumerate(rows)
            if len(row) > i_art and row[i_art].strip().isdigit()]
    if not arts:
        print(f"[{title}] нет строк с артикулами — пропуск"); return None

    # последняя дата у MPStats (проба по первым артикулам)
    lat, probe_hist = None, {}
    for _, probe in arts[:5]:
        h = mp_history(probe, mp_token, mp_kind, field)
        if h: lat, probe_hist = max(h.keys()), h; break
    live = None
    if lat:
        lat = datetime.strptime(lat, "%Y-%m-%d").date()
    else:
        why = ("исчерпал суточный лимит запросов" if MP_LIMIT["hit"]
               else "не ответил на пробы")
        if mp_kind != "wb":
            return f"[{title}] MPStats {why}"
        # WB: у публичной карточки WB ни ключа, ни квоты — берём цену оттуда.
        live = wb_live_prices([a for _, a in arts])
        n_price = sum(1 for v in live.values() if isinstance(v, int))
        if not n_price:
            return f"[{title}] MPStats {why}, card.wb.ru тоже не отдал цен"
        lat = today
        print(f"[{title}] MPStats {why} — беру живую цену с card.wb.ru: "
              f"{n_price} цен из {len(arts)} артикулов "
              f"(нет в наличии: {sum(1 for v in live.values() if v == STATE_NONE)}, "
              f"нет карточки: {sum(1 for v in live.values() if v == STATE_GONE)}), "
              f"колонка за {lat:%d.%m}")

    hdr = hdr0
    cols0 = date_cols(hdr, today, first=i_art + 1)
    existing = [datetime.strptime(v, "%Y-%m-%d").date() for v in cols0.values()]
    newest = max(existing) if existing else (lat - timedelta(days=1))
    # вставляем ПЕРЕД первой датированной колонкой: всё, что человек завёл левее
    # блока дат, остаётся на своём месте
    # Дат ещё нет — встаём сразу за последней заполненной колонкой шапки, а не
    # жёстко в D: иначе новая дата врезалась бы в середину ручного блока.
    tail0 = max((i for i, h in enumerate(hdr) if str(h).strip()), default=FIRST_DATE_COL - 2) + 1
    insert_at = min(cols0) if cols0 else max(FIRST_DATE_COL - 1, i_art + 1, tail0)
    kept = [str(h).strip() for h in hdr[:insert_at] if str(h).strip()]
    src = "card.wb.ru" if live is not None else "MPStats"
    print(f"[{title}] в таблице по {newest}, у {src} по {lat}, строк {len(arts)}, "
          f"блок дат с {col_letter(insert_at)}; ручные колонки слева "
          f"({len(kept)}): {', '.join(kept) or '—'}")

    missing = []
    d = lat
    while d > newest:
        missing.append(d); d -= timedelta(days=1)
    if live is not None and len(missing) > 1:
        # У card.wb.ru истории нет: колонки за пропущенные дни остались бы
        # пустыми навсегда. Заводим только сегодняшнюю, дырка видна как дырка.
        print(f"[{title}] пропущенные дни ({len(missing) - 1}) колонками не завожу — "
              f"у card.wb.ru нет истории; догонит MPStats, когда вернётся квота")
        missing = [lat]
    if missing:
        n = len(missing)
        api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
            {"insertDimension": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": insert_at, "endIndex": insert_at + n},
                "inheritFromBefore": False}}]})
        last_new = col_letter(insert_at + n - 1)
        api(sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
            "data": [{"range": f"{q}!{col_letter(insert_at)}1:{last_new}1",
                      "values": [[x.strftime('%d.%m') for x in missing]]}]})
        print(f"[{title}] добавлены даты: {[x.strftime('%d.%m') for x in missing]}")

    # Дыры ВНУТРИ блока дат. Обычная вставка идёт только слева и пропущенные дни,
    # оставшиеся позади свежей колонки, не догоняет никогда: `while d > newest`
    # их не видит. А остаться без данных на несколько дней — штатный случай
    # (выбранная квота, упавший прогон), поэтому долив обязан быть в самой
    # логике, а не в разовом скрипте. Даты берём из окна MPStats (30 дней): всё,
    # что он отдаёт и чего нет в шапке, а самой старой колонки книга не теряет.
    holes = []
    if gaps and live is None and probe_hist:
        have = {datetime.strptime(v, "%Y-%m-%d").date() for v in cols0.values()}
        have |= set(missing)
        oldest = min(have) if have else lat
        holes = sorted((datetime.strptime(d, "%Y-%m-%d").date() for d in probe_hist
                        if datetime.strptime(d, "%Y-%m-%d").date() not in have
                        and datetime.strptime(d, "%Y-%m-%d").date() > oldest))
    for hole in holes:                       # от старой к новой: индексы не плывут
        cur = api(f"{sheet_id}/values/{qurl}!A1:BZ1?valueRenderOption=FORMATTED_VALUE",
                  tok).get("values", [[]])[0]
        cmap = date_cols(cur, today, first=i_art + 1)
        older = [c for c, iso in cmap.items()
                 if datetime.strptime(iso, "%Y-%m-%d").date() < hole]
        at = min(older) if older else max(cmap) + 1
        api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
            {"insertDimension": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": at, "endIndex": at + 1}, "inheritFromBefore": False}}]})
        api(sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
            "data": [{"range": f"{q}!{col_letter(at)}1:{col_letter(at)}1",
                      "values": [[hole.strftime('%d.%m')]]}]})
    if holes:
        print(f"[{title}] долив дыр внутри блока дат: "
              f"{[x.strftime('%d.%m') for x in reversed(holes)]}")

    # полная заливка окна дат (существующее не затирается пустотой)
    hdr = api(f"{sheet_id}/values/{qurl}!A1:BZ1?valueRenderOption=FORMATTED_VALUE",
              tok).get("values", [[]])[0]
    col_iso = date_cols(hdr, today, first=i_art + 1)
    lo, hi = min(col_iso), max(col_iso)
    newest_col = max(col_iso, key=lambda c: col_iso[c])
    last = col_letter(hi)
    # чужие колонки внутри блока дат: пишем ВОКРУГ них, содержимое не трогаем
    runs = runs_of(col_iso)
    alien = [col_letter(c) for c in range(lo, hi + 1) if c not in col_iso]
    if alien:
        print(f"[{title}] колонки без даты внутри блока дат: {', '.join(alien)} "
              f"— не трогаем (заливка идёт {len(runs)} диапазонами)")
    data = api(f"{sheet_id}/values/{qurl}!A2:{last}5000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])
    todo = []
    for r, row in enumerate(data):
        art = row[i_art].strip() if len(row) > i_art else ""
        if not art.isdigit(): continue
        need = (missing or holes
                or not str(row[newest_col] if len(row) > newest_col else "").strip())
        if need: todo.append((r + 2, art, row))
    print(f"[{title}] к заливке: {len(todo)} строк")

    lat_iso = lat.isoformat()

    def fetch(item):
        rownum, art, row = item
        if live is not None:
            v = live.get(art)
            h = {lat_iso: v} if v is not None else {}
        else:
            h = mp_history(art, mp_token, mp_kind, field)
        out = []
        for a, b in runs:
            vals = []
            for ci in range(a, b + 1):
                v = h.get(col_iso[ci])
                if v is None:  # MPStats молчит — оставляем то, что уже в таблице
                    v = as_int(row[ci]) if len(row) > ci else ""
                vals.append(v if v is not None else "")
            out.append((a, b, vals))
        return rownum, out

    updates, filled = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for rownum, out in ex.map(fetch, todo):
            for a, b, vals in out:
                filled += sum(1 for v in vals if v != "")
                updates.append({"range": f"{q}!{col_letter(a)}{rownum}:{col_letter(b)}{rownum}",
                                "values": [vals]})
    for i in range(0, len(updates), 60):
        api(sheet_id + "/values:batchUpdate", tok, "POST",
            {"valueInputOption": "USER_ENTERED", "data": updates[i:i + 60]})
    print(f"[{title}] залито ячеек: {filled} (источник: {src})")
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", required=True)
    ap.add_argument("--sa", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-gap-fill", action="store_true",
                    help="не доливать пропущенные дни внутри блока дат")
    a = ap.parse_args()

    K = load_keys(a.keys)
    mp_token = K.get("MPSTATS_TOKEN", "")
    if not mp_token:
        print("ERROR: нет MPSTATS_TOKEN"); sys.exit(1)
    tok = token_of(a.sa)
    meta = api(a.sheet_id + "?fields=sheets.properties(sheetId,title,index)", tok)
    sheets = sorted((s["properties"] for s in meta["sheets"]), key=lambda p_: p_.get("index", 0))

    errors = []
    err = process_tab(a.sheet_id, tok, sheets[0], mp_token, "wb", "wallet_price",
                      a.workers, gaps=not a.no_gap_fill)
    if err: errors.append(err)
    oz_tab = next((p_ for p_ in sheets if "ozon" in p_["title"].lower()
                   or "озон" in p_["title"].lower()), None)
    if oz_tab:
        err = process_tab(a.sheet_id, tok, oz_tab, mp_token, "oz", "ozon_card_price",
                          a.workers, gaps=not a.no_gap_fill)
        if err: errors.append(err)
    else:
        print("Листа Ozon нет — только WB")

    if errors:
        print("ОШИБКИ:", "; ".join(errors)); sys.exit(1)
    print("DONE")

if __name__ == "__main__":
    main()

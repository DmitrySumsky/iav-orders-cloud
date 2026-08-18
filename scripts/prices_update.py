#!/usr/bin/env python3
"""ОТЧЁТ ПО ЦЕНАМ WB + Ozon v3.0.0 — 18.08.2026
  ПЯТЬ КОПИЙ ОДНОГО КОДА В РАЗНЫХ ПРОЕКТАХ — ПЕРЕЕЗД НА ОБЩЕЕ ЯДРО mp-core
  • Обход публичной витрины, клиент платной аналитики, разбор шапки листа,
    ретраи и три состояния замера переехали в библиотеку `mpcore` (тег
    v0.1.0, 42 теста). Здесь остался только сценарий: что и куда писать.
  • Поведение не менялось намеренно: сверено с прежней версией на боевых
    книгах — состав дат, ручные колонки, значения ячеек совпадают.
  • Ставится по ТЕГУ, а не с ветки: коммит в ядро не должен уронить всех
    потребителей разом.

v2.1.0 — 18.08.2026
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
import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from mpcore import datesheet as ds
from mpcore import mpstats, sheets, states, wb_card


def load_keys(paths):
    """Ключи из одного или нескольких файлов «КЛЮЧ=значение». Последний побеждает."""
    out = {}
    for path in paths.split(","):
        path = path.strip()
        if not path:
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip()
    return out


def as_int(x):
    digits = re.sub(r"[^\d]", "", str(x))
    return int(digits) if digits else ""


def process_tab(book, props, client, workers, gaps=True, live_fallback=False):
    """Один лист: догнать даты, долить пропуски, заполнить пустое.

    Возвращает None или строку ошибки. Сценарий здесь, механика — в ядре.
    """
    title, tab_id = props["title"], props["sheetId"]
    today = date.today()

    header = book.header(title)
    i_art = ds.find_column(header, ("артикул", "nmid", "sku"), default=1)
    rows = book.values(title, f"A2:{ds.col_letter(i_art)}5000")
    items = [(r + 2, row[i_art].strip()) for r, row in enumerate(rows)
             if len(row) > i_art and row[i_art].strip().isdigit()]
    if not items:
        print(f"[{title}] нет строк с артикулами — пропуск")
        return None
    articles = [a for _, a in items]

    # Свежая дата источника: набор дат у него один на все позиции, поэтому
    # хватает пробы по первым — и она же показывает, каких дней не хватает.
    latest, probe = client.latest_date(articles)
    live = None
    if latest is None:
        why = client.why_silent()
        if not live_fallback:
            return f"[{title}] {why}"
        # Публичная витрина не знает истории, но не знает и квоты.
        live = wb_card.prices(articles)
        prices_found = sum(1 for v in live.values() if states.is_price(v))
        if not prices_found:
            return f"[{title}] {why}, публичная витрина тоже не отдала цен"
        latest = today
        print(f"[{title}] {why} — беру живую цену с витрины: {prices_found} цен "
              f"из {len(items)} артикулов "
              f"(нет в наличии: {sum(1 for v in live.values() if v == states.STATE_NONE)}, "
              f"нет карточки: {sum(1 for v in live.values() if v == states.STATE_GONE)}), "
              f"колонка за {latest:%d.%m}")

    cols0 = ds.date_columns(header, today, first=i_art + 1)
    newest = max(cols0.values()) if cols0 else None
    insert_at = ds.insert_position(header, cols0, i_art)
    manual = [str(h).strip() for h in header[:insert_at] if str(h).strip()]
    source = "витрина" if live is not None else "аналитика"
    print(f"[{title}] в таблице по {newest}, у источника ({source}) по {latest}, "
          f"строк {len(items)}, блок дат с {ds.col_letter(insert_at)}; "
          f"ручные колонки слева ({len(manual)}): {', '.join(manual) or '—'}")

    missing = ds.missing_dates(newest, latest)
    if live is not None and len(missing) > 1:
        # Колонки за прошлые дни витрина заполнить не сможет никогда —
        # пустая колонка посреди блока дат хуже видимой дырки.
        print(f"[{title}] пропущенные дни ({len(missing) - 1}) колонками не завожу — "
              f"у витрины нет истории; догонит аналитика, когда вернётся квота")
        missing = [latest]
    if missing:
        book.insert_columns(tab_id, insert_at, len(missing))
        last = ds.col_letter(insert_at + len(missing) - 1)
        book.update([{"range": sheets.a1(title, ds.col_letter(insert_at), last, 1),
                      "values": [[d.strftime("%d.%m") for d in reversed(missing)]]}],
                    raw=True)
        print(f"[{title}] добавлены даты: "
              f"{[d.strftime('%d.%m') for d in reversed(missing)]}")

    holes = []
    if gaps and live is None:
        have = set(cols0.values()) | set(missing)
        holes = ds.gap_dates(have, client.available_dates(probe))
    for hole in holes:                      # от старой к новой: индексы не плывут
        current = ds.date_columns(book.header(title), today, first=i_art + 1)
        at = ds.hole_position(current, hole)
        book.insert_columns(tab_id, at, 1)
        letter = ds.col_letter(at)
        book.update([{"range": sheets.a1(title, letter, letter, 1),
                      "values": [[hole.strftime("%d.%m")]]}], raw=True)
    if holes:
        print(f"[{title}] долив пропусков внутри блока дат: "
              f"{[d.strftime('%d.%m') for d in reversed(holes)]}")

    col_dates = ds.date_columns(book.header(title), today, first=i_art + 1)
    lo, hi = min(col_dates), max(col_dates)
    newest_col = max(col_dates, key=lambda c: col_dates[c])
    runs = ds.runs_of(col_dates)
    alien = [ds.col_letter(c) for c in range(lo, hi + 1) if c not in col_dates]
    if alien:
        print(f"[{title}] колонки без даты внутри блока дат: {', '.join(alien)} "
              f"— не трогаем (заливка идёт {len(runs)} диапазонами)")

    data = book.values(title, f"A2:{ds.col_letter(hi)}5000")
    todo = []
    for r, row in enumerate(data):
        article = row[i_art].strip() if len(row) > i_art else ""
        if not article.isdigit():
            continue
        empty = not str(row[newest_col] if len(row) > newest_col else "").strip()
        if missing or holes or empty:
            todo.append((r + 2, article, row))
    print(f"[{title}] к заливке: {len(todo)} строк")

    latest_iso = latest.isoformat()

    def fetch(item):
        rownum, article, row = item
        if live is not None:
            value = live.get(article)
            history = {latest_iso: value} if value is not None else {}
        else:
            history = client.history(article)
        out = []
        for a, b in runs:
            columns = list(range(a, b + 1))
            values = ds.row_values(row, col_dates, history, columns=columns)
            # Прежнее содержимое возвращается строкой из таблицы — приводим
            # к числу, иначе ячейка меняет тип на ровном месте.
            values = [as_int(v) if isinstance(v, str) and v.strip().isdigit() else v
                      for v in values]
            out.append((a, b, values))
        return rownum, out

    updates, filled = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rownum, out in pool.map(fetch, todo):
            for a, b, values in out:
                filled += sum(1 for v in values if v != "")
                updates.append({"range": sheets.a1(title, ds.col_letter(a),
                                                   ds.col_letter(b), rownum),
                                "values": [values]})
    book.update(updates)
    print(f"[{title}] залито ячеек: {filled} (источник: {source})")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", required=True)
    ap.add_argument("--sa", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-gap-fill", action="store_true",
                    help="не доливать пропущенные дни внутри блока дат")
    args = ap.parse_args()

    keys = load_keys(args.keys)
    token = keys.get("MPSTATS_TOKEN", "")
    if not token:
        print("ERROR: нет MPSTATS_TOKEN")
        sys.exit(1)

    book = sheets.Sheets(args.sheet_id, sheets.access_token(args.sa))
    tabs = book.tabs()
    gaps = not args.no_gap_fill

    errors = []
    # Первый лист книги — WB. У него есть бесплатный резерв, поэтому квота
    # платной аналитики не останавливает сбор.
    wb_client = mpstats.Client(token, mpstats.KIND_WB)
    err = process_tab(book, tabs[0], wb_client, args.workers,
                      gaps=gaps, live_fallback=True)
    if err:
        errors.append(err)

    ozon_tab = next((t for t in tabs if "ozon" in t["title"].lower()
                     or "озон" in t["title"].lower()), None)
    if ozon_tab:
        # Отдельный клиент: квоты контуров считаются раздельно, и выбранная
        # квота одной площадки не должна гасить соседнюю.
        ozon_client = mpstats.Client(token, mpstats.KIND_OZON)
        err = process_tab(book, ozon_tab, ozon_client, args.workers, gaps=gaps)
        if err:
            errors.append(err)
    else:
        print("Листа Ozon нет — только WB")

    if errors:
        print("ОШИБКИ:", "; ".join(errors))
        sys.exit(1)
    print("DONE")


if __name__ == "__main__":
    main()

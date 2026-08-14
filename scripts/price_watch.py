#!/usr/bin/env python3
"""PRICE WATCH v2.1.0 — 14.08.2026. Монитор цен: событие по конкретному конкуренту.

История версий (новое сверху, старое не переписывать):

v2.1.0 — 14.08.2026
  «ПЕРЕЙДЁМ НА КОНТРОЛЬ ПО ЭТОЙ ТАБЛИЦЕ, КОНТРОЛИРУЕМ ТОЛЬКО ЖЁЛТЫХ» — решение
  пользователя сразу после v2.0.0. Рабочей стала книга «Анализ конкурентов
  (цены) все бренды», лист «Цены»: там строка = КАРТОЧКА конкурента, а не бренд,
  и менеджер жёлтой заливкой в колонке «Бренд конкурента» сам отмечает, за кем
  следим (254 карточки из 686; наши бренды выделены своими цветами).
  • Наблюдение задаётся РАЗМЕТКОЙ КНИГИ, а не списком имён в настройках: цвет
    ячейки бренда читается вместе со значениями, жёлтая = под контролем. Покрасил
    менеджер новую строку — она под наблюдением со следующего прогона, без кода.
  • Событие и состояние теперь по КАРТОЧКЕ (группа × артикул конкурента): у
    одного бренда в группе бывает несколько карточек с разной ценой, и «VitaMeal
    упал» без артикула нечего проверять.
  • Фасовка входит в ключ группы (колонка «Капсул»): «Magnesium Chelate 120» и
    «…240» — разные рынки, сравнивать их между собой нельзя.
  • Свои бренды опознаются как конкуренты — по префиксу («Sunshine Nutrition»,
    «4Me Nutrition» в новой книге против «SUNSHINE», «4ME» в настройке), иначе
    наши же карточки попали бы в наблюдение.
  • Книга монитора отвязана от книг ежедневного обновления цен: свой ключ
    PRICE_WATCH_SHEETS (пусто = прежний PRICES_GSHEET_ID). Иначе новая книга
    попала бы под prices_update, который ведёт свои колонки дат.
  • Разметки нет вовсе (старые книги) — работает прежний путь v2.0.0 по именам
    брендов из «Конкуренты под наблюдением» / «Колонки конкурентов».

v2.0.0 — 14.08.2026
  «ЭТО КАША, Я УЖЕ НЕ СМОТРЮ» — голосовое Артура 14.08.2026. Прежний монитор
  каждый час присылал СОСТОЯНИЕ («мы дороже минимума по 43 позициям из 124»):
  список надо читать целиком, решать по нему нечего, и его перестали открывать
  и он, и менеджеры. Дословно: «если бы он точечно давал инфу — вот этот
  конкурент резко опустил цену и стал дешевле — это бы здорово работало».
  • Режим по умолчанию сменён на СОБЫТИЙНЫЙ (настройка «Режим сигнала»:
    события / обзор). Событие ровно одно: **наблюдаемый конкурент уронил цену
    на N % и стал дешевле нас**. Нет события — нет сообщения.
  • Наблюдаем не всех: настройка «Конкуренты под наблюдением» (пусто = берём
    «Колонки конкурентов»). Смысл — те 2–3 бренда, по которым реально ходят.
  • Порог события — своя настройка «Падение конкурента, %» (5): он про ДВИЖЕНИЕ
    чужой цены, а прежний «Порог, %» — про наш разрыв с рынком, это разные вещи.
  • В сообщении то, чего раньше не было вовсе: имя конкурента, его было → стало,
    и наши позиции этой группы с текущим отставанием. Решение принимается из
    сообщения, без открытия таблицы.
  • Цены конкурентов хранятся между прогонами в новом листе «Конкуренты
    (наблюдение)»: группа × конкурент, цена, база сравнения, «дешевле нас».
    База поднимается сама, когда конкурент отыгрывает цену вверх, поэтому
    падение всегда меряется от последнего максимума, а не от цены год назад.
  • Анти-спам: после сигнала база = новая цена, повтор — только если упал ЕЩЁ
    на порог. Отдельной строкой «вернул цену», когда конкурент снова дороже нас.
  • Сводка в часы «Полный отчёт в часы» тоже стала короткой: сколько
    наблюдаемых конкурентов сейчас дешевле нас и кто именно (до 10 строк).
  • Прежний формат никуда не делся: «Режим сигнала» = обзор возвращает v1.2.0
    целиком (компактный/подробный, пороги в обе стороны, «дешевле всех»).

v1.2.0 — 06.08.2026
  «ПОВТОРЫ НЕ ТОЛЬКО ПО РОСТУ РАЗРЫВА, НО И ТРИ РАЗА В ДЕНЬ ЦЕЛИКОМ» — правка
  пользователя по итогам v1.1.0. Анти-спам хорош, пока сигнал приходит; но
  позиция, о которой уведомили утром и которая весь день висит дороже рынка,
  из чата исчезала — и «тихо» читалось как «всё в порядке».
  • Настройка «Полный отчёт в часы» (по умолчанию 9, 13, 16): в эти часы уходит
    ПОЛНАЯ картина по бренду, а не только новое, — как ручной `--force`, но по
    расписанию. Состояние при этом обновляется, поэтому обычные часы между
    сводками работают по-прежнему (повтор только при росте на REALERT_STEP п.п.).
  • Сводка уходит и когда сигналов нет: «✅ Все позиции в рамках порога». Это и
    есть контроль — молчание монитора перестало быть неотличимым от поломки.
  • Рабочее окно по умолчанию 9–16 МСК (было 8–17), крон `0 6-13 * * *`.

v1.1.0 — 06.08.2026
  СООБЩЕНИЕ БЫЛО НЕЧИТАЕМЫМ — голосовые Артура 06.08.2026: «очень мало
  информативная штука», «чтобы выглядело просто: проверь омегу и артикул, без
  лишней информации, чтобы глаз не нагружать». Главное, за чем следят, — что мы
  не стоим дороже конкурентов; «сильно дешевле» оставлено (менеджер может
  ошибиться и уронить цену).
  • Компактный формат сообщения (настройка «Формат сообщения», по умолчанию
    «компактный»): строка на позицию «маркер +X% · товар · артикул · наша цена
    (мин N ₽)», отсортировано от самого большого превышения. Убраны шапки
    товарных групп, строка «мин. … конкурентов N», строка «топ: …» и «% к якорю»
    — они и составляли основную массу текста. Прежний вид доступен настройкой
    «подробный».
  • Маркер остроты 🔴 ≥15 % / 🟠 ≥8 % / 🟡 ниже — «реально проблемный артикул»
    виден без чтения чисел.
  • В листе «Мониторинг цен» ячейка АРТИКУЛА у позиций «дороже» красится
    отдельно от строки: тёмно-красная с белым жирным при ≥15 %, красная при
    меньшем разрыве (просьба Артура «перекрашивал ячейку в красный по тому
    артикулу, который нас беспокоит»).
  • Крон переведён на почасовой прогон 8:00–20:00 МСК (`price-watch.yml`),
    рабочее окно по-прежнему решает лист.
  • `send_chunked` режет длинный блок по строкам: в компактном виде весь список
    позиций — один блок, и у бренда с двумя десятками сигналов он перерастал
    лимит Telegram целиком (в подробном формате блоком была товарная группа).

v1.0.0 — 28.07–31.07.2026
  Исходный монитор: сравнение внутри товарной группы, порог в обе стороны,
  гистерезис и анти-спам по п.п., группы конкурентов А/Б, колонки конкурентов
  поимённо с артикулом в ячейке, разбивка рассылки по брендам, срочный порог
  вне рабочего окна.

Живая цена берётся НЕ из MPStats (там только дневной срез), а из публичного
card.wb.ru: `sizes[0].price.product / 100` = цена карточки, цена с WB-Кошельком
= floor(цена * 0.98) — сверено с MPStats, расхождений нет. До 100 артикулов
за запрос, без авторизации: весь лист (321 артикул) закрывается 4 запросами.

Товарная группа = значение колонки A (тянется вниз, пустая строка = разделитель).
Внутри группы наши бренды сравниваются с минимумом конкурентов и с «дороже
всех», а якорные конкуренты показываются ПОИМЁННО отдельными колонками.
Медианы убраны 30.07.2026 по просьбе менеджера: он берёт самого дешёвого,
а медиана усредняет и рисует рынок дороже, чем он есть.
Порог, состав групп А/Б и получатели живут в листе «Мониторинг цен» этой же
книги — он же хранит состояние (что уже отправлено), поэтому почасовые
прогоны не коммитят ничего в репозиторий.

Использование:
  python3 price_watch.py --keys api_keys.txt[,extra] --sa google_sa.json \
      --sheet-id <ID> [--dry-run] [--force]
Печатает DONE при успехе.
"""
import argparse, html, json, math, os, re, sys, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
import jwt

BASE = "https://sheets.googleapis.com/v4/spreadsheets/"
MON_TITLE = "Мониторинг цен"
# v2.0.0. Память по чужим ценам: событие «упал на N %» невозможно посчитать без
# прошлой цены, а лист мониторинга хранит наши позиции, а не конкурентов.
COMP_TITLE = "Конкуренты (наблюдение)"
COMP_COLS = ["Группа", "Конкурент", "Артикул", "Цена", "База сравнения",
             "Дешевле нас", "Наша мин. цена", "Последнее событие", "Обновлено"]
MSK = timezone(timedelta(hours=3))
# Раскладка колонок: слева фиксированные, в середине — конкуренты ПОИМЁННО
# (состав ведёт менеджер настройкой «Колонки конкурентов»), справа служебные.
# Колонки «Медиана»/«% к медиане» убраны 30.07.2026. Имя самого дешёвого
# конкурента осталось («Мин. конкурент»), рядом с ним — группа минимума (А/Б).
# В каждой ячейке с конкурентом стоит его АРТИКУЛ: менеджер копирует его прямо
# из ячейки и ищет карточку в поиске WB (правка Артура 31.07.2026).
COLS_HEAD = ["Артикул", "Товар (группа)", "Бренд", "Наша цена"]
COLS_TAIL = ["Мин. конкурент", "Цена мин.", "% к мин.", "Группа мин.",
             "Дешевле нас", "Статус", "Обновлено", "% при уведомлении"]
DEFAULTS = {"Порог, %": "5", "Получатели TG": "", "Часы работы (МСК)": "9-16",
            "Дни недели": "пн-пт", "Срочный порог, %": "",
            "Полный отчёт в часы": "9, 13, 16",
            "Включён": "да", "Наши бренды": "NATURI, SUNSHINE, Health Form, 4ME, VEXOR, ORZAX",
            "Якоря (группа А)": "Healthis, VitaMeal, PWR",
            "Группа Б (не якорные)": "Miosuperfood, Miopharm, MISHIDO, GLS",
            "Колонки конкурентов": "Healthis, VitaMeal, PWR, Miosuperfood, GLS",
            "Сигнал без группы Б": "нет",
            "Разбивать по брендам": "нет", "Чаты по брендам": "",
            "Формат сообщения": "компактный",
            # v2.0.0. Событийный режим: сообщение только когда наблюдаемый
            # конкурент уронил цену и стал дешевле нас. «обзор» = прежний v1.2.0.
            "Режим сигнала": "события",
            "Конкуренты под наблюдением": "",
            "Падение конкурента, %": "5",
            "Событий в сообщении, максимум": "10",
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
        "дорос до этого значения. «Полный отчёт в часы»: в перечисленные часы "
        "приходит ВСЯ текущая картина по бренду, а не только новое — для "
        "контроля; если всё в рамках порога, придёт короткое «всё в порядке». "
        "Пусто = сводок нет, только новые сигналы. "
        "«Якоря (группа А)» — конкуренты, по которым "
        "работает ценовое правило (стоять на 15–20 % ниже); «Группа Б» — "
        "конкуренты второго эшелона: они остаются в таблице и в сообщениях, но "
        "помечены отдельно, и настройкой «Сигнал без группы Б» = да их можно "
        "выключить из расчёта минимума. «Колонки конкурентов» — чьи цены показывать "
        "отдельными колонками листа (имя пишется как в колонке «Бренд» таблицы цен, "
        "можно коротко: Miosuperfood поймает «Miosuperfood (Миофарм)»); конкурент, "
        "которого в этой книге нет ни разу, колонку не получает. В ячейке "
        "конкурента рядом с ценой стоит его артикул — копируйте прямо из ячейки. "
        "«Формат сообщения»: компактный (по умолчанию) — строка на позицию "
        "«маркер +X% · товар · артикул · наша цена (мин N ₽)», самое большое "
        "превышение сверху; подробный — прежний вид с разбором по товарным "
        "группам, топ-конкурентами и процентом к якорю. "
        "«Чаты по брендам»: "
        "NATURI=-100…:5, SUNSHINE=-100…:7 — пусто = берётся из ключей отчёта. "
        "«Тест: всё в чат» — репетиция рассылки: разбивка по брендам включается "
        "принудительно, но все сообщения уходят в указанный чат с пометкой, куда "
        "они пойдут в бою; состояние при этом не помечается. "
        "«Режим сигнала»: события (по умолчанию) — сообщение приходит ТОЛЬКО когда "
        "наблюдаемый конкурент уронил цену на «Падение конкурента, %» и стал дешевле "
        "нас; в сообщении его имя, было → стало и наши позиции этой группы. "
        "обзор — прежний вид: вся текущая картина «мы дороже/дешевле рынка». "
        "«Конкуренты под наблюдением» — за чьей ценой следим (пусто = «Колонки "
        "конкурентов»); держите тут 2–3 бренда, по которым реально принимаете решения. "
        "Цены конкурентов между прогонами лежат на листе «Конкуренты (наблюдение)»: "
        "там же база сравнения — от неё считается падение, и она сама поднимается, "
        "когда конкурент отыгрывает цену вверх")
# повторное уведомление по той же позиции — только если разрыв вырос на столько п.п.
REALERT_STEP = 3.0
# Гистерезис: вход в сигнал по порогу, выход — когда разрыв ужался до половины
# порога. Симметричная петля шириной в половину порога; на нуле выходить нельзя —
# при пороге 5% это давало бы «липкую» зону в 5 п.п., позиция висела бы в сигнале
# годами. Ширина петли считается от порога, поэтому его правка не ломает логику.
HYST_FRAC = 0.5
# сколько товарных групп разбирать подробно, остальные — одной строкой
DETAIL_GROUPS = 12
# Площадка в заголовке. Монитор — WB по построению: живая цена берётся из
# card.wb.ru, ссылки ведут на wildberries.ru, лист Ozon в сравнение не идёт
# (там только наши SKU, конкурентов нет). Метка стоит ПЕРВОЙ строкой и первым
# словом: в списке чатов и в пуше видно только начало, а читателю из Ozon-отдела
# нужно понять «моё/не моё», не открывая сообщение (запрос Владимира 30.07.2026).
MP_LABEL = "ВБ"

# порядок строк в листе: самое горячее наверх. «Дороже» — риск потерять продажи,
# «дешевле» — недобранная маржа; первое срочнее, поэтому идёт выше
RANK = {"дороже": 0, "дешевле": 1, "ок": 2, "нет конкурентов": 3, "нет цены": 4}
# ширины колонок листа (px): фиксированные — конкуренты — служебные.
# последняя (тех. поле «% при уведомлении») прячется
W_HEAD = [95, 300, 105, 90]
W_COMP = 135          # цена + артикул конкурента в одной ячейке
W_TAIL = [200, 90, 85, 100, 100, 105, 105, 120]
# Заливка строки по разрыву с минимумом конкурента. Красная шкала — мы дороже
# (чем краснее, тем срочнее), зелёная — мы дешевле всех с большим отрывом
# (можно поднять цену и остаться самыми дешёвыми). Границы в %.
BANDS_UP = [(15.0, "#E06666", True), (8.0, "#EA9999", False),
            (3.0, "#F4CCCC", False), (0.0, "#FCE8E6", False)]
BANDS_DOWN = [(20.0, "#93C47D", True), (12.0, "#B6D7A8", False),
              (0.0, "#D9EAD3", False)]
WHITE, GRAY, BLACK = "#FFFFFF", "#EFEFEF", "#000000"
# v1.1.0. Ячейка АРТИКУЛА у позиций «дороже» красится отдельно от строки: строка
# показывает остроту фоном, а глазу нужен один якорь, за который цепляться, —
# сам артикул (просьба Артура 06.08.2026). Формат: (граница %, фон, текст, жирный).
ART_BANDS = [(15.0, "#CC0000", WHITE, True), (0.0, "#E06666", BLACK, True)]
# Маркер остроты в сообщении: «реально проблемный» видно до чтения чисел
SEV_MARKS = [(15.0, "🔴"), (8.0, "🟠"), (0.0, "🟡")]


def sev_mark(d_min):
    """v1.1.0. Кружок остроты по превышению над минимумом конкурентов."""
    for edge, mark in SEV_MARKS:
        if d_min >= edge:
            return mark
    return SEV_MARKS[-1][1]


def art_style(s):
    """v1.1.0. Оформление ячейки артикула: не «дороже» — как вся строка (None)."""
    if s["status"] != "дороже" or not isinstance(s["d_min"], (int, float)):
        return None
    for edge, bg, fg, bold in ART_BANDS:
        if s["d_min"] >= edge:
            return bg, fg, bold
    return None

esc = lambda s: html.escape(str(s), quote=True)


class Layout:
    """Раскладка колонок листа под текущий состав конкурентов.

    Колонок конкурентов может быть сколько угодно (их задаёт менеджер), поэтому
    индексы служебных полей СЧИТАЮТСЯ, а не забиты числами — иначе добавленный
    конкурент молча сдвигает «Статус» и состояние читается не из той ячейки.
    """

    def __init__(self, comp_cols):
        self.comp = list(comp_cols)
        self.cols = COLS_HEAD + self.comp + COLS_TAIL
        self.widths = W_HEAD + [W_COMP] * len(self.comp) + W_TAIL
        self.i_price = 3
        self.i_comp0 = len(COLS_HEAD)
        n = len(COLS_HEAD) + len(self.comp)
        (self.i_who, self.i_min, self.i_dmin, self.i_grp, self.i_cheaper,
         self.i_status, self.i_upd, self.i_pts) = range(n, n + len(COLS_TAIL))

    def __len__(self):
        return len(self.cols)


def split_list(raw):
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def comp_cell(pa):
    """Ячейка колонки конкурента: «цена · артикул».

    Артикул нужен рядом с ценой, потому что менеджер ищет чужую карточку в
    поиске WB копипастом из этой самой ячейки (просьба Артура 31.07.2026).
    Ячейка от этого становится текстовой — рублёвый формат к ней не применяем.
    """
    if not pa:
        return ""
    price, art = pa
    return f"{price} ₽ · {art}"


def is_watch_color(hexcolor):
    """v2.1.0. Жёлтая заливка ячейки бренда = «эту карточку контролируем».

    Оттенок задаёт менеджер руками, поэтому не сравниваем с одним #FFFF00, а
    берём жёлтую гамму: красный и зелёный высокие и близки, синий заметно ниже.
    Белый, серый и «фирменные» цвета наших брендов (зелёный, розовый, синий,
    фиолетовый) под это условие не подходят.
    """
    if not hexcolor:
        return False
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return r > 200 and g > 180 and b < 160 and abs(r - g) < 60


def hex_of(color):
    if not color:
        return None
    return "#%02X%02X%02X" % tuple(round(color.get(k, 0) * 255)
                                   for k in ("red", "green", "blue"))


def read_grid(sheet_id, tok, title, last_col="J", last_row=2000):
    """v2.1.0. Значения ВМЕСТЕ с цветом фона: наблюдение задаётся разметкой книги.

    Возвращает (строки значений, строки цветов) — одинаковой длины, цвет None
    там, где заливки нет. Один запрос вместо двух: values + цвета приходят
    одним rowData.
    """
    rng = urllib.parse.quote(f"'{title}'!A1:{last_col}{last_row}")
    d = api(f"{sheet_id}?ranges={rng}&fields=sheets(data(rowData(values("
            f"formattedValue,effectiveFormat.backgroundColor))))", tok)
    rows = (d.get("sheets") or [{}])[0].get("data", [{}])[0].get("rowData", [])
    vals, cols = [], []
    for row in rows:
        cells = row.get("values", [])
        vals.append([c.get("formattedValue", "") for c in cells])
        cols.append([hex_of(c.get("effectiveFormat", {}).get("backgroundColor"))
                     for c in cells])
    return vals, cols


def norm_brand(s):
    return re.sub(r"[^0-9a-zа-я]+", "", str(s).lower())


def brand_in(brand, names):
    """Какому имени из настроек соответствует бренд строки. None — никакому.

    Менеджер пишет короткое имя («Miosuperfood», «PWR»), а в колонке «Бренд»
    таблицы цен стоит «Miosuperfood (Миофарм)», «PWR ultimate power», «Mishido»
    в другом регистре — поэтому сравнение по префиксу нормализованной строки,
    а не по равенству.
    """
    b = norm_brand(brand)
    for n in names:
        n2 = norm_brand(n)
        if n2 and (b == n2 or b.startswith(n2)):
            return n
    return None


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


def row_style(s):
    """Цвет и жирность строки листа по её статусу и разрыву с минимумом."""
    status, d_min = s["status"], s["d_min"]
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


def decorate(sheet_id, tok, gid, styles, art_styles, need_rows, has_alerts, L):
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
            for i, w in enumerate(L.widths)]
    reqs.append({"updateDimensionProperties": {           # тех. поле анти-спама
        "range": {"sheetId": gid, "dimension": "COLUMNS",
                  "startIndex": L.i_pts, "endIndex": L.i_pts + 1},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})

    body = {"startRowIndex": FIRST_DATA_ROW - 1, "endRowIndex": need_rows,
            "startColumnIndex": 0, "endColumnIndex": len(L)}
    # цвет текста тоже сбрасываем: у бывшей «горячей» ячейки артикула он белый,
    # и без сброса белые цифры остались бы на белом фоне следующего прогона
    reqs.append({"repeatCell": {"range": {"sheetId": gid, **body},
        "cell": {"userEnteredFormat": {"backgroundColor": rgb(WHITE),
                                       "textFormat": {"bold": False,
                                                      "foregroundColor": rgb(BLACK)}}},
        "fields": "userEnteredFormat(backgroundColor,"
                  "textFormat.bold,textFormat.foregroundColor)"}})

    band_start, band_style, i = 0, None, 0
    for i, st in enumerate(styles):
        if band_style is None:
            band_style = st
        elif st != band_style:
            reqs.append(paint(gid, FIRST_DATA_ROW - 1 + band_start,
                              FIRST_DATA_ROW - 1 + i, band_style, L))
            band_start, band_style = i, st
    if styles and band_style is not None:
        reqs.append(paint(gid, FIRST_DATA_ROW - 1 + band_start,
                          FIRST_DATA_ROW - 1 + len(styles), band_style, L))

    # v1.1.0. Ячейка артикула поверх строки. Строки уже отсортированы по остроте,
    # поэтому «дороже» идут подряд и вся покраска укладывается в 1–2 запроса.
    band_start, band_style = 0, None
    for i, st in enumerate(art_styles + [None]):
        if st == band_style:
            continue
        if band_style is not None:
            reqs.append(paint_art(gid, FIRST_DATA_ROW - 1 + band_start,
                                  FIRST_DATA_ROW - 1 + i, band_style))
        band_start, band_style = i, st

    # Рублёвый формат — только «наша цена» и «цена мин.»: в колонках конкурентов
    # с 31.07.2026 лежит текст «цена · артикул», числовой формат к нему неприменим
    # (и молча съел бы артикул при попытке разобрать ячейку как число).
    for cols, pattern in (((L.i_price, L.i_price + 1), '#,##0" ₽"'),
                          ((L.i_min, L.i_min + 1), '#,##0" ₽"'),
                          ((L.i_dmin, L.i_dmin + 1), '0.0"%"')):
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
                  "endColumnIndex": len(L)},
        "cell": {"userEnteredFormat": {
            "backgroundColor": rgb("#F4CCCC" if has_alerts else "#D9EAD3"),
            "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}})

    api(sheet_id + ":batchUpdate", tok, "POST", {"requests": reqs})


def paint_art(gid, r0, r1, style):
    """v1.1.0. Заливка ячейки артикула (колонка A) на диапазоне строк."""
    bg, fg, bold = style
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": 0, "endColumnIndex": 1},
        "cell": {"userEnteredFormat": {"backgroundColor": rgb(bg),
                                       "textFormat": {"bold": bold,
                                                      "foregroundColor": rgb(fg)}}},
        "fields": "userEnteredFormat(backgroundColor,"
                  "textFormat.bold,textFormat.foregroundColor)"}}


def paint(gid, r0, r1, style, L):
    color, bold = style
    return {"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1,
                  "startColumnIndex": 0, "endColumnIndex": len(L)},
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
    SA = json.load(open(sa_path, encoding="utf-8")); now = int(time.time())
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
    """Лист «Мониторинг цен»: создать при отсутствии, прочитать настройки и состояние.

    Возвращает (gid, настройки, состояние, строка старой шапки, старые заголовки).
    Раскладку НЕ перекладывает: состав колонок зависит от настроек И от данных
    книги, которые читаются позже, — этим занимается layout_sheet().

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
        return None, d, {}, None, []
    if not props:
        print(f"Лист «{MON_TITLE}» не найден — создаю")
        try:
            res = api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
                {"addSheet": {"properties": {"title": MON_TITLE,
                                             "gridProperties": {"rowCount": 500,
                                                                "columnCount": 30}}}}]})
            props = res["replies"][0]["addSheet"]["properties"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            props = find_sheet(sheet_id, tok, MON_TITLE)
            if not props:
                raise
            print("  лист уже был создан (ответ на создание потерялся) — продолжаю")

    q = urllib.parse.quote("'" + MON_TITLE + "'")
    vals = api(f"{sheet_id}/values/{q}!A1:AZ2000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])

    # где шапка таблицы стоит СЕЙЧАС: раскладка могла быть сделана прошлой
    # версией скрипта — с другим числом настроек и другим составом колонок
    old_head, old_cols = None, []
    for idx, row in enumerate(vals[:40], 1):
        if row and row[0].strip() == COLS_HEAD[0]:
            old_head, old_cols = idx, [str(c).strip() for c in row]
            break

    cfg = dict(DEFAULTS)
    for row in vals[:(old_head - 1) if old_head else 40]:
        if len(row) > 1 and row[0].strip() in DEFAULTS:
            cfg[row[0].strip()] = row[1].strip()
    if not cfg["Получатели TG"].strip():
        cfg["Получатели TG"] = tg_default

    state = {}
    if old_head:
        # Колонки состояния ищем ПО ИМЕНИ заголовка, а не по номеру: состав
        # колонок теперь подвижен (у каждого якорного конкурента своя), а
        # «уже уведомляли» обязано пережить перестройку листа — иначе первый же
        # прогон после релиза отправит всю базу заново как новые сигналы.
        i_st = old_cols.index("Статус") if "Статус" in old_cols else None
        i_pt = (old_cols.index("% при уведомлении")
                if "% при уведомлении" in old_cols else None)

        def cell(row, i):
            return str(row[i]).strip() if (i is not None and len(row) > i) else ""

        for row in vals[old_head:]:
            art = (str(row[0]).strip() if row else "")
            # ключ — пара «артикул + группа»: один и тот же nmID конкурента (и наш)
            # может стоять сразу в нескольких товарных группах (боевой случай VEXOR)
            grp = (str(row[1]).strip() if len(row) > 1 else "")
            if art.isdigit():
                state[(art, grp)] = {"статус": cell(row, i_st),
                                     "пункты": as_num(cell(row, i_pt))}
    return props["sheetId"], cfg, state, old_head, old_cols


def ensure_comp_state(sheet_id, tok, sheets, dry=False):
    """v2.0.0. Лист «Конкуренты (наблюдение)» — память по чужим ценам.

    Ключ строки — «группа + конкурент»: один и тот же бренд стоит в разных
    товарных группах с разными карточками, и падение считается внутри группы.
    Возвращает (gid, {(группа, конкурент): {цена, база, дешевле, событие}}).
    При dry=True лист не создаётся: сухой прогон ничего не должен писать.
    """
    props = next((p for p in sheets if p["title"] == COMP_TITLE), None)
    if not props:
        if dry:
            print(f"  dry-run: листа «{COMP_TITLE}» нет — считаю, что памяти пока нет")
            return None, {}
        print(f"Лист «{COMP_TITLE}» не найден — создаю")
        try:
            res = api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
                {"addSheet": {"properties": {"title": COMP_TITLE,
                                             "gridProperties": {"rowCount": 500,
                                                                "columnCount": len(COMP_COLS)}}}}]})
            props = res["replies"][0]["addSheet"]["properties"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            props = find_sheet(sheet_id, tok, COMP_TITLE)
            if not props:
                raise
            print("  лист уже был создан (ответ на создание потерялся) — продолжаю")

    q = urllib.parse.quote("'" + COMP_TITLE + "'")
    vals = api(f"{sheet_id}/values/{q}!A1:I5000?valueRenderOption=FORMATTED_VALUE",
               tok).get("values", [])
    head = [str(c).strip() for c in (vals[0] if vals else [])]
    idx = {name: head.index(name) for name in COMP_COLS if name in head}
    state = {}

    def cell(row, name):
        i = idx.get(name)
        return str(row[i]).strip() if (i is not None and len(row) > i) else ""

    for row in vals[1:]:
        g, comp = (str(row[0]).strip() if row else ""), cell(row, "Конкурент")
        art = cell(row, "Артикул")
        if not g or not comp:
            continue
        rec = {
            "price": as_num(cell(row, "Цена")),
            "base": as_num(cell(row, "База сравнения")),
            "under": cell(row, "Дешевле нас").lower().startswith("да"),
            "event": cell(row, "Последнее событие"),
        }
        # v2.1.0. Ключ зависит от способа наблюдения: по карточке (артикул) в
        # книге с разметкой и по бренду в книгах без неё. Пишем под обоими —
        # переключение способа не должно стирать историю.
        state[(g, comp)] = rec
        if art:
            state[(g, art)] = rec
    return props["sheetId"], state


def write_comp_state(sheet_id, tok, gid, rows, now_s):
    """v2.0.0. Перезапись листа памяти: строка = группа × наблюдаемый конкурент."""
    q = urllib.parse.quote("'" + COMP_TITLE + "'")
    api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": gid,
                           "gridProperties": {"rowCount": len(rows) + 40,
                                              "columnCount": len(COMP_COLS)}},
            "fields": "gridProperties(rowCount,columnCount)"}},
        {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"updateSheetProperties": {"properties": {"sheetId": gid,
                                                  "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}}]})
    api(f"{sheet_id}/values/{q}!A2:I5000:clear", tok, "POST", {})
    api(sheet_id + "/values:batchUpdate", tok, "POST", {
        "valueInputOption": "USER_ENTERED",
        "data": [{"range": f"'{COMP_TITLE}'!A1", "values": [COMP_COLS]},
                 {"range": f"'{COMP_TITLE}'!A2", "values": rows}] if rows else
                [{"range": f"'{COMP_TITLE}'!A1", "values": [COMP_COLS]}]})


def layout_sheet(sheet_id, tok, gid, cfg, L, old_head, old_cols, dry=False):
    """Верх листа: блок настроек, строка «Сейчас», шапка таблицы.

    Пишет, только если раскладка разъехалась — сменилось число настроек или
    состав колонок конкурентов. При dry=True не трогает ничего (см. ensure_monitor).
    """
    if old_head == HEAD_ROW and old_cols == L.cols:
        return
    why = ("шапка {} → строка {}".format(old_head or "отсутствует", HEAD_ROW)
           if old_head != HEAD_ROW else "сменился состав колонок конкурентов")
    if dry:
        print(f"  dry-run: раскладку не трогаю ({why})")
        return
    # Перекладываем верх листа: настройки записываем ТЕКУЩИМИ значениями
    # (иначе правки пользователя сбросятся на дефолты), состояние уже прочитано
    # раньше, а данные всё равно переписываются каждый прогон.
    print(f"  раскладка: {why}")
    q = urllib.parse.quote("'" + MON_TITLE + "'")
    # ширину гарантируем ДО записи: у листа могло быть меньше колонок, чем нужно
    # сейчас, и values.update ответил бы 400 «beyond the last requested column»
    api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": gid, "gridProperties": {"columnCount": len(L)}},
            "fields": "gridProperties.columnCount"}}]})
    api(f"{sheet_id}/values/{q}!A1:AZ2000:clear", tok, "POST", {})
    blank = [""] * len(L)
    # строки пишем на всю ширину: values.update трогает только переданные
    # ячейки, и остатки прежней раскладки иначе переживут перезапись
    rows = [["Настройки мониторинга цен", "", NOTE] + [""] * (len(L) - 3)]
    rows += [[k, cfg[k]] + [""] * (len(L) - 2) for k in DEFAULTS]
    rows.append(list(blank))
    rows.append(["Сейчас", ""] + [""] * (len(L) - 2))
    rows.append(list(L.cols))
    assert len(rows) == HEAD_ROW, (len(rows), HEAD_ROW)
    api(sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
        "data": [{"range": f"'{MON_TITLE}'!A1", "values": rows}]})
    api(sheet_id + ":batchUpdate", tok, "POST", {"requests": [
        # сбросить заливку прежней раскладки: старая строка «Сейчас» иначе
        # останется розовой уже на месте обычной настройки
        {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0,
                                  "endRowIndex": HEAD_ROW, "startColumnIndex": 0,
                                  "endColumnIndex": len(L)},
                        "cell": {"userEnteredFormat": {"backgroundColor": rgb(WHITE),
                                                       "textFormat": {"bold": False}}},
                        "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}},
        {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": HEAD_ROW - 1,
                                  "endRowIndex": HEAD_ROW},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat.bold"}},
        {"updateSheetProperties": {"properties": {"sheetId": gid,
                                                  "gridProperties": {"frozenRowCount": HEAD_ROW}},
                                   "fields": "gridProperties.frozenRowCount"}}]})


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

    gid, cfg, prev, old_head, old_cols = ensure_monitor(
        a.sheet_id, tok, sheets, K.get("PRICE_WATCH_TG_CHATS", ""), dry=a.dry_run)
    thr_pct = as_num(cfg["Порог, %"]) or 5.0
    ours = {b.strip().lower() for b in cfg["Наши бренды"].split(",") if b.strip()}
    # Группы конкурентов ведёт менеджер в листе, а не код: якоря (группа А) —
    # те, по кому работает ценовое правило «стоять на 15–20 % ниже», группа Б —
    # второй эшелон, который менеджер из правил исключил, но из таблицы не убрал.
    anchors = split_list(cfg["Якоря (группа А)"])
    group_b = split_list(cfg["Группа Б (не якорные)"])
    comp_cols_cfg = split_list(cfg["Колонки конкурентов"]) or anchors
    skip_b = cfg["Сигнал без группы Б"].strip().lower() in ("да", "yes", "1", "true")
    default_targets = parse_targets(cfg["Получатели TG"])
    split_brands = cfg["Разбивать по брендам"].strip().lower() in ("да", "yes", "1", "true")
    # Репетиция перед боевой рассылкой: разбивка считается включённой, но всё
    # уходит в один тестовый чат с пометкой, куда сообщение пойдёт в бою.
    # Состояние не помечается — после теста боевой прогон шлёт всё как в первый раз.
    # v1.1.0. Компактный вид по умолчанию; «подробный» в ячейке возвращает прежний
    compact = not cfg["Формат сообщения"].strip().lower().startswith("подроб")
    # v2.0.0. Событийный режим — основной: сообщение только про движение чужой
    # цены. «обзор» возвращает прежнее поведение целиком.
    event_mode = not cfg["Режим сигнала"].strip().lower().startswith("обзор")
    watch_names = split_list(cfg["Конкуренты под наблюдением"])
    drop_pct = as_num(cfg["Падение конкурента, %"]) or 5.0
    # Потолок разбора в сообщении: в книге, где конкурентов сотни (автохимия),
    # день с общим падением рынка иначе превращает событийный сигнал в ту же кашу.
    ev_limit = int(as_num(cfg["Событий в сообщении, максимум"]) or 10)
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
    if event_mode:
        print(f"режим сигнала: события — падение конкурента от {drop_pct}% "
              f"с уходом ниже нашей цены; наблюдаем: "
              f"{watch_names or comp_cols_cfg or '—'}")
    else:
        print(f"режим сигнала: обзор, формат {'компактный' if compact else 'подробный'}")
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

    # v1.2.0. Часы полной сводки: анти-спам молчит по позиции, о которой уже
    # уведомили, и висящая весь день «дороже рынка» пропадала из чата — тишина
    # читалась как «всё хорошо». В эти часы уходит вся текущая картина по бренду
    # (то же, что ручной --force), включая «всё в порядке», если сигналов нет.
    # Вне рабочего окна сводок нет: там работает только срочный порог.
    digest_hours = {int(x) for x in re.findall(r"\d+", cfg["Полный отчёт в часы"])}
    digest = a.force or (datetime.now(MSK).hour in digest_hours and not urgent_only)
    if digest:
        print("полная сводка: "
              + ("запрошена ключом --force" if a.force
                 else f"час {datetime.now(MSK).hour}:00 в списке {sorted(digest_hours)}"))

    # ----- товарные группы с первого листа книги (WB) -----
    # v2.1.0. Читаем значения ВМЕСТЕ с заливкой: в рабочей книге наблюдение за
    # конкурентом задаётся жёлтой ячейкой бренда, а не списком имён.
    wb_title = sheets[0]["title"]
    rows, colors = read_grid(a.sheet_id, tok, wb_title.replace("'", "''"))
    # Колонки ищем ПО ШАПКЕ, а не по буквам A/B/C: менеджеры заводят слева от дат
    # свои колонки (в книге автохимии это «Прогрев» и «Прогрев к-во», 31.07.2026),
    # и жёсткое «бренд = C» тихо превращает бренд в «да» — наших позиций
    # находится ноль, лист мониторинга обнуляется вместе с состоянием.
    head = [str(x).strip().lower() for x in (rows[0] if rows else [])]

    def col_by(words, default):
        for i, h in enumerate(head):
            if any(w in h for w in words):
                return i
        return default

    i_name = col_by(("название", "товар"), 0)
    i_art = col_by(("артикул", "nmid", "sku"), 1)
    i_brand = col_by(("бренд",), 2)
    # v2.1.0. Фасовка («Капсул») — не примечание, а условие сравнения: в рабочей
    # книге у конкурентов в одной товарной группе банки на 60/90/120/240, и
    # ценник конкурента с 60 капсулами «дешевле» нашего 120 всегда. Поэтому
    # сравниваем ЦЕНУ ЗА КАПСУЛУ (менеджер руками делает ровно это), а в
    # сообщении показываем оба числа.
    i_pack = col_by(("капсул", "фасовк", "объём", "объем", "таблет"), None)
    if (i_name, i_art, i_brand) != (0, 1, 2) or i_pack is not None:
        print(f"[{wb_title}] раскладка: название={col_letter(i_name)}, "
              f"артикул={col_letter(i_art)}, бренд={col_letter(i_brand)}"
              + (f", фасовка={col_letter(i_pack)}" if i_pack is not None else ""))
    ours_names = split_list(cfg["Наши бренды"])
    items, group = [], None
    for n, r in enumerate(rows[1:], start=1):
        cell = lambda i: (str(r[i]).strip() if (i is not None and len(r) > i) else "")
        name, art, brand = cell(i_name), cell(i_art), cell(i_brand)
        if name:
            group = name
        if not art.isdigit():
            continue
        pack = cell(i_pack)
        # «120», «Хелат 240», «говяжий 155» — берём первое число; нет числа —
        # сравнение остаётся по цене карточки
        m_pack = re.search(r"\d+", pack)
        crow = colors[n] if n < len(colors) else []
        mark = crow[i_brand] if len(crow) > i_brand else None
        items.append({"group": group or "(без группы)",
                      "pack": int(m_pack.group()) if m_pack else None,
                      "art": art, "brand": brand,
                      # своё имя бренда пишется в книгах по-разному («Sunshine
                      # Nutrition» против «SUNSHINE» в настройке) — сравниваем по
                      # префиксу, иначе наши карточки уедут в конкуренты
                      "ours": bool(brand_in(brand, ours_names)),
                      "marked": is_watch_color(mark)})
    marked_n = sum(1 for i in items if i["marked"] and not i["ours"])
    print(f"[{wb_title}] групп {len(set(i['group'] for i in items))}, "
          f"артикулов {len(items)}, наших {sum(1 for i in items if i['ours'])}, "
          f"помечено жёлтым (под контролем): {marked_n}")

    t0 = time.time()
    live = wb_live([i["art"] for i in items])
    print(f"card.wb.ru: {len(live)} живых цен из {len(items)} за {time.time() - t0:.1f} c")
    if not live:
        print("ОШИБКА: ни одной живой цены — прогон не засчитан"); sys.exit(1)

    # ----- сравнение внутри группы -----
    groups = {}
    for i in items:
        groups.setdefault(i["group"], []).append(i)

    # колонку получает только тот конкурент, который в этой книге реально есть:
    # у таблицы автохимии свои конкуренты, и четыре пустых колонки БАДовых
    # якорей были бы там мусором
    comp_brands = [i["brand"] for i in items if not i["ours"]]
    comp_cols = [c for c in comp_cols_cfg if any(brand_in(b, [c]) for b in comp_brands)]
    dropped = [c for c in comp_cols_cfg if c not in comp_cols]
    if dropped:
        print(f"  колонки конкурентов без данных в этой книге — не показываю: {dropped}")
    L = Layout(comp_cols)
    print(f"  колонки конкурентов: {comp_cols or '—'}; якоря (А): {anchors or '—'}; "
          f"группа Б: {group_b or '—'}"
          + (", группа Б исключена из расчёта минимума" if skip_b else ""))
    layout_sheet(a.sheet_id, tok, gid, cfg, L, old_head, old_cols, dry=a.dry_run)

    # v2.0.0. Наблюдаемые конкуренты: настройка, а по умолчанию — те же, что
    # показаны колонками. Их цены надо разложить по группам ДО событий, поэтому
    # имена участвуют в общем пуле сопоставления брендов.
    # Пусто в настройке — берём колонки; их тоже нет (книга автохимии: там свои
    # конкуренты, и БАДовые имена ей не подходят) — наблюдаем всех конкурентов
    # книги. Событие всё равно редкое: нужно и падение на порог, и уход ниже нас.
    watch = watch_names or comp_cols or sorted({b.strip() for b in comp_brands if b.strip()})
    name_pool = list(dict.fromkeys(comp_cols + anchors + group_b + watch))
    group_ctx = {}

    def unit_row(i):
        """v2.1.0. Строка для сравнения: ценник + цена за капсулу.

        Фасовки нет — «за единицу» равно ценнику, и сравнение работает как
        раньше (книги, где в группе стоят одинаковые банки).
        """
        price = live[i["art"]]
        pack = i.get("pack") or 0
        return {"art": i["art"], "brand": i["brand"], "price": price,
                "pack": pack or None, "unit": (price / pack) if pack else price}

    cur, alerts, recovered = {}, [], []
    for g, lst in groups.items():
        mine = [i for i in lst if i["ours"]]
        comp = [(i["brand"], live[i["art"]], i["art"]) for i in lst
                if not i["ours"] and i["art"] in live]
        # цена бренда из справочника в этой группе (если карточек несколько —
        # самая дешёвая: сравниваем с лучшим предложением конкурента). Артикул
        # едет вместе с ценой: он и есть то, что менеджер копирует из ячейки.
        bprice = {}
        for b, p, art in comp:
            name = brand_in(b, name_pool)
            if name and p < bprice.get(name, (10 ** 9, ""))[0]:
                bprice[name] = (p, art)
        # v2.0.0. Контекст группы для событий: чужие цены поимённо и наши позиции
        # с ценами — из них строится строка «мы: NATURI 1 390 ₽ (+17 %)».
        group_ctx[g] = {"comp": dict(bprice),
                        "ours": [unit_row(i) for i in mine if i["art"] in live],
                        # v2.1.0. Помеченные карточки конкурентов этой группы:
                        # наблюдение ведётся по карточке, а не по бренду
                        "cards": [unit_row(i) for i in lst
                                  if i["marked"] and not i["ours"] and i["art"] in live]}
        anch_prices = [bprice[x][0] for x in anchors if x in bprice]
        # Минимум считается по всем конкурентам. Настройкой «Сигнал без группы Б»
        # менеджер может выкинуть из него второй эшелон — тогда сигнал живёт по
        # тем же брендам, по которым работает его ценовое правило.
        base = [c for c in comp if not brand_in(c[0], group_b)] if skip_b else comp
        if not base:
            base = comp
        for i in mine:
            st = {"group": g, "brand": i["brand"], "price": live.get(i["art"]),
                  "min_who": "", "min": None, "min_art": "", "d_min": None,
                  "min_grp": "", "cheaper": None, "status": "нет цены",
                  "top": False, "cols": bprice, "anch": None, "d_anch": None}
            if st["price"] and base:
                mn = min(base, key=lambda x: x[1])
                st["min_who"], st["min"], st["min_art"] = mn[0], mn[1], mn[2]
                st["min_grp"] = ("А" if brand_in(mn[0], anchors)
                                 else "Б" if brand_in(mn[0], group_b) else "прочий")
                st["d_min"] = round((st["price"] / mn[1] - 1) * 100, 1)
                st["cheaper"] = sum(1 for c in base if c[1] < st["price"])
                st["comp_n"] = len(base)
                st["top"] = st["cheaper"] == len(base) and len(base) > 0
                if anch_prices:
                    # ценовое правило Артура: стоять на 15–20 % ниже якорей,
                    # поэтому считаем от самого дешёвого якоря
                    st["anch"] = min(anch_prices)
                    st["d_anch"] = round((st["price"] / st["anch"] - 1) * 100, 1)

            key = (i["art"], g)
            was = prev.get(key, {})
            was_st, was_pts = was.get("статус", ""), was.get("пункты")
            # «уже уведомляли» = не просто статус в листе, а записанные п.п. разрыва:
            # если отправка в TG упала, пункты не проставились и сигнал повторится
            notified = was_st in ("дороже", "дешевле") and was_pts is not None

            if st["price"] and base:
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
                if (digest or not notified or grew) and \
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

    # ----- v2.0.0. События по наблюдаемым конкурентам -----
    # Единственное событие, ради которого монитор существует после 14.08.2026:
    # НАБЛЮДАЕМЫЙ конкурент уронил цену и стал дешевле нас. Всё остальное —
    # состояние, а состояние никто не читает (голосовое Артура).
    comp_gid, comp_prev, comp_rows = None, {}, []
    events, back, undercut_now = [], [], []
    # v2.1.0. Разметка книги главнее настроек: покрасил менеджер ячейку бренда
    # жёлтым — карточка под контролем, и список имён в настройках не нужен.
    marked_mode = any(i["marked"] and not i["ours"] for i in items)
    if event_mode:
        print("наблюдение: " + ("жёлтые карточки листа" if marked_mode
                                else f"бренды из настроек {watch or '—'}"))
        comp_gid, comp_prev = ensure_comp_state(a.sheet_id, tok, sheets, dry=a.dry_run)
        for g in sorted(group_ctx):
            ctx = group_ctx[g]
            # сравнение внутри группы — по цене за капсулу: банки разной фасовки
            # иначе несопоставимы (60 капсул конкурента «дешевле» наших 120)
            ours_list = sorted(ctx["ours"], key=lambda x: x["unit"])
            our_best = ours_list[0] if ours_list else None
            our_min = our_best["unit"] if our_best else None
            # v2.1.0. Есть разметка книги — наблюдаем помеченные КАРТОЧКИ; нет
            # разметки (старые книги) — прежний путь по именам брендов.
            if marked_mode:
                watched = [(c["brand"], c, c["art"]) for c in ctx["cards"]]
            else:
                watched = [(n, {"price": ctx["comp"][n][0], "art": ctx["comp"][n][1],
                                "pack": None, "unit": ctx["comp"][n][0]}, n)
                           for n in watch if n in ctx["comp"]]
            for name, card, state_key in watched:
                price, art, unit = card["price"], card["art"], card["unit"]
                was = comp_prev.get((g, state_key), {})
                # база — от чего меряем падение. Нет памяти (первый прогон,
                # новая карточка) — база = сегодняшняя цена: сигнала не будет,
                # но со следующего прогона движение уже видно.
                base = was.get("base") or was.get("price") or price
                was_under = bool(was.get("under"))
                under = our_min is not None and unit < our_min
                drop = round((price / base - 1) * 100, 1) if base else 0.0
                dearer = [o for o in ours_list if o["unit"] > unit]
                kind = None
                if under and drop <= -drop_pct:
                    # «ушёл ещё ниже» — он и раньше был дешевле нас, но с прошлого
                    # сигнала уронил ещё на порог: это новая новость, а не повтор
                    kind = "стал дешевле" if not was_under else "ушёл ещё ниже"
                elif was_under and not under:
                    kind = "вернул цену"
                ev = {"group": g, "comp": name, "art": art, "price": price,
                      "pack": card.get("pack"), "unit": unit,
                      "base": base, "drop": drop, "under": under,
                      "our_min": our_min, "our_best": our_best, "dearer": dearer,
                      "brands": sorted({o["brand"] for o in (dearer or ours_list)}),
                      "kind": kind}
                if kind in ("стал дешевле", "ушёл ещё ниже"):
                    events.append(ev)
                elif kind == "вернул цену":
                    back.append(ev)
                if under:
                    undercut_now.append(ev)
                # База поднимается за конкурентом вверх и сбрасывается на текущую
                # цену после сигнала: следующий сигнал — только если упал ЕЩЁ на
                # порог, а не потому, что мы всё ещё помним прошлогодний максимум.
                new_base = price if (kind and kind != "вернул цену") else max(base, price)
                comp_rows.append([g, name, art, price, new_base,
                                  "да" if under else "нет",
                                  our_min if our_min is not None else "",
                                  (f"{now_s} {kind}" if kind else was.get("event", "")),
                                  now_s])
        print(f"под наблюдением карточек: {len(comp_rows)}, "
              f"дешевле нас сейчас: {len(undercut_now)}, событий: {len(events)}, "
              f"вернули цену: {len(back)}")

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

    def wb_url(art):
        return f"https://www.wildberries.ru/catalog/{art}/detail.aspx"

    def build_events(part_events, part_back, part_watch, brands):
        """v2.0.0. Сообщение-событие: кто уронил цену, было → стало, кого задело.

        Читается сверху вниз без таблицы: имя конкурента, движение его цены,
        наши позиции этой группы и на сколько мы теперь дороже. Заказ Артура
        14.08.2026 дословно: «вот этот конкурент резко опустил цену и стал
        дешевле — это бы здорово работало».
        """
        head_brand = ", ".join(brands)[:60] if brands else "все бренды"
        lines = []
        if part_events:
            ordered = sorted(part_events, key=lambda e: e["drop"])
            shown, rest = ordered[:ev_limit], ordered[ev_limit:]
            lines.append(f"📉 <b>{MP_LABEL} · Конкурент уронил цену — {now_s} МСК</b>")
            lines.append(f"<i>{esc(head_brand)}</i>"
                         + (f" · всего падений: {len(ordered)}" if rest else ""))
            lines.append("")
            for ev in shown:
                mark = sev_mark(abs(ev["drop"]))
                # он и до этого стоял дешевле нас — значит новость в том, что
                # уронил ещё; без пометки это читается как «уже присылали»
                again = " · упал ещё" if ev["kind"] == "ушёл ещё ниже" else ""
                lines.append(f"{mark} <b>{esc(ev['comp'])}</b>{again} · "
                             f"<a href=\"{wb_url(ev['art'])}\">{esc(ev['group'])}</a>")
                pack = (f" · {ev['pack']} шт, {ev['unit']:.1f} ₽/шт"
                        if ev.get("pack") else "")
                lines.append(f"было {ev['base']:.0f} ₽ → <b>{ev['price']:.0f} ₽</b> "
                             f"({ev['drop']:+.0f}%){pack} · <code>{ev['art']}</code>")
                if ev["dearer"]:
                    # наши позиции, которые теперь дороже него, — по ним и решение.
                    # Процент считается по цене за штуку: у нас и у него банки
                    # разной фасовки, и разница ценников сама по себе ничего не значит
                    who = " · ".join(
                        f"{esc(o['brand'])} <code>{o['art']}</code> {o['price']:.0f} ₽"
                        + (f"/{o['pack']}" if o.get("pack") else "")
                        + f" ({(o['unit'] / ev['unit'] - 1) * 100:+.0f}%)"
                        for o in ev["dearer"][:4])
                    lines.append(f"мы дороже: {who}")
                else:
                    lines.append("мы всё ещё дешевле его")
                lines.append("")
            if rest:
                # хвост — одной строкой: он нужен как факт «упало ещё столько-то»,
                # разбирать его в чате никто не будет
                tail = " · ".join(f"{esc(e['comp'])} {esc(e['group'])} "
                                  f"{e['drop']:+.0f}%" for e in rest[:8])
                more = f" и ещё {len(rest) - 8}" if len(rest) > 8 else ""
                lines.append(f"Ещё падения: {tail}{more}")
                lines.append("")
        if part_back:
            names = " · ".join(f"{esc(e['comp'])} ({esc(e['group'])}) "
                               f"{e['price']:.0f} ₽" for e in part_back[:6])
            more = f" и ещё {len(part_back) - 6}" if len(part_back) > 6 else ""
            lines.append(f"✅ Вернули цену выше нашей: {names}{more}")
            lines.append("")
        if digest:
            # Контрольный срез в часы сводки: короткий, иначе он превращается в
            # ту самую «кашу», ради ухода от которой сделан событийный режим.
            u = sorted(part_watch, key=lambda e: -(e["our_min"] / e["unit"] - 1)
                       if (e["our_min"] and e["unit"]) else 0)
            lines.append(f"📊 <b>{MP_LABEL} · Контроль {now_s} МСК</b> — "
                         f"дешевле нас сейчас: {len(u)}")
            for ev in u[:10]:
                gap = ((ev["our_min"] / ev["unit"] - 1) * 100) if ev["our_min"] else 0
                mine = ev.get("our_best") or {}
                lines.append(f"• {esc(ev['comp'])} · {esc(ev['group'])} "
                             f"{ev['price']:.0f} ₽"
                             + (f"/{ev['pack']}" if ev.get("pack") else "")
                             + f" (мы {mine.get('price', 0):.0f} ₽"
                             + (f"/{mine['pack']}" if mine.get("pack") else "")
                             + f", {gap:+.0f}%)")
            if len(u) > 10:
                lines.append(f"…и ещё {len(u) - 10}")
            if not u:
                lines.append("✅ Ни один наблюдаемый конкурент не стоит дешевле нас")
            lines.append("")
        lines.append(f"<a href=\"https://docs.google.com/spreadsheets/d/{a.sheet_id}/edit\">"
                     f"Таблица цен {MP_LABEL}</a>")
        return "\n".join(lines), f"📉 <b>{MP_LABEL} · {esc(head_brand)}</b>"

    def build_compact(part_alerts, part_recovered, scope):
        """v1.1.0. Одна строка на позицию, самое большое превышение сверху.

        Формат родился из голосовых Артура 06.08.2026: «чтобы выглядело просто —
        проверь омегу и артикул, без лишней информации». Поэтому в строке ровно
        то, по чему принимают решение: насколько мы дороже (и маркер остроты),
        что за товар, какой артикул и от какой цены отталкиваться. Разбор по
        товарным группам, топ-конкуренты и процент к якорю остались в подробном
        формате и в самом листе.
        """
        lines, keys = [], set()
        over = sum(1 for s in scope if s["status"] == "дороже")
        under = sum(1 for s in scope if s["status"] == "дешевле")
        brands = sorted({s["brand"] for s in scope})
        head_brand = (brands[0] if len(brands) == 1 else ", ".join(brands)[:60])
        # v1.2.0. «сводка» в шапке: читатель должен понимать, что это контрольный
        # срез за час X, а не «вот прямо сейчас всё это стало плохо»
        mark = " · сводка" if digest else ""
        lines.append(f"📊 <b>{MP_LABEL} · {esc(head_brand)} — {now_s} МСК{mark}</b>")
        lines.append(f"дороже: {over} из {len(scope)} · дешевле рынка: {under} "
                     f"· порог {thr_pct}%")
        lines.append("")

        def row(s, key, kind, mark):
            # артикул моноширинным: тап в Telegram = «скопировать», дальше поиск
            # карточки на WB (тот же приём, что в подробном формате)
            url = f"https://www.wildberries.ru/catalog/{key[0]}/detail.aspx"
            grew = "📈" if kind == "рост" else ""
            top = " ‼️" if s["top"] else ""
            keys.add(key)
            return (f"{mark} <b>{s['d_min']:+}%</b> "
                    f"<a href=\"{url}\">{esc(s['group'])}</a> "
                    f"<code>{key[0]}</code> {s['price']} ₽ "
                    f"(мин {s['min']} ₽){top}{grew}")

        up = sorted([x for x in part_alerts if x[1]["status"] == "дороже"],
                    key=lambda x: -x[1]["d_min"])
        if up:
            lines.append(f"<b>ПРОВЕРЬ ЦЕНУ — {len(up)}</b>")
            lines += [row(s, key, kind, sev_mark(s["d_min"])) for key, s, kind in up]
            lines.append("")
        # «сильно дешевле» оставлено сознательно: Артур сначала предложил убрать,
        # тут же передумал — менеджер может ошибиться и уронить цену (голосовое 3)
        down = sorted([x for x in part_alerts if x[1]["status"] == "дешевле"],
                      key=lambda x: x[1]["d_min"])
        if down:
            lines.append(f"<b>ДЕШЕВЛЕ ВСЕХ — {len(down)}</b>")
            lines += [row(s, key, kind, "💰") for key, s, kind in down]
            lines.append("")
        if part_recovered:
            # возврат к рынку — новостью, а не списком: действий он не требует
            names = ", ".join(f"{esc(s['group'])} <code>{key[0]}</code>"
                              for key, s, _ in part_recovered[:6])
            more = f" и ещё {len(part_recovered) - 6}" if len(part_recovered) > 6 else ""
            lines.append(f"✅ Вернулись к рынку: {len(part_recovered)} — {names}{more}")
            keys |= {key for key, *_ in part_recovered}
            lines.append("")
        if not (up or down or part_recovered):
            # сводка без единого сигнала — тоже сообщение: молчание монитора
            # иначе неотличимо от его поломки, а это и есть «для контроля»
            lines.append(f"✅ Все позиции в рамках порога — {len(scope)} шт")
            lines.append("")
        lines.append(f"<a href=\"https://docs.google.com/spreadsheets/d/{a.sheet_id}/edit\">"
                     f"Таблица цен {MP_LABEL}</a>")
        return "\n".join(lines), keys, f"📊 <b>{MP_LABEL} · {esc(head_brand)}</b>"

    def build_message(part_alerts, part_recovered, scope):
        """Текст для одного адресата + ключи, которые в него вошли, + короткая
        шапка для продолжений (длинное сообщение уходит несколькими)."""
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
                # медиана убрана 30.07.2026: менеджер ориентируется на самого
                # дешёвого, а медиана рисует рынок дороже, чем он есть
                b_mark = " (группа Б)" if s0["min_grp"] == "Б" else ""
                # артикул конкурента моноширинным: в Telegram тап по нему =
                # «скопировать», дальше менеджер ищет карточку в WB
                lines.append(f"мин. {esc(s0['min_who'])} <code>{esc(s0['min_art'])}</code> "
                             f"{s0['min']} ₽{b_mark} · "
                             f"конкурентов {s0.get('comp_n', 0)}")
                if s0["cols"]:
                    # топ-конкуренты поимённо — вместо безымянного «мин. конкурент»
                    lines.append("топ: " + " · ".join(
                        f"{esc(c)} <code>{esc(s0['cols'][c][1])}</code> "
                        f"{s0['cols'][c][0]} ₽"
                        for c in comp_cols if c in s0["cols"]))
                for key, s, kind in sorted(entries, key=lambda x: -sign * x[1]["d_min"]):
                    mark = "📈 " if kind == "рост" else ""
                    flag = " ‼️ дороже всех" if (sign > 0 and s["top"]) else ""
                    url = f"https://www.wildberries.ru/catalog/{key[0]}/detail.aspx"
                    # артикул отдельным словом и моноширинным: в Telegram по нему
                    # тап = «скопировать», а из текста ссылки копировать неудобно
                    anch = (f", {s['d_anch']:+}% к якорю" if s["d_anch"] is not None else "")
                    lines.append(f"{mark}• <a href=\"{url}\">{esc(s['brand'])}</a> "
                                 f"<code>{key[0]}</code> {s['price']} ₽ — "
                                 f"{s['d_min']:+}% к мин.{anch}{flag}")
                    keys.add(key)
                lines.append("")
            tail = ordered[DETAIL_GROUPS:]
            if tail:
                lines.append(f"<b>Ещё {sum(len(e) for _, e in tail)} позиций (кратко):</b>")
                for gname, entries in tail:
                    for key, s, kind in sorted(entries, key=lambda x: -sign * x[1]["d_min"]):
                        lines.append(f"• {esc(gname)} — {esc(s['brand'])} "
                                     f"<code>{key[0]}</code> {s['price']} ₽ "
                                     f"({s['d_min']:+}% к мин. {s['min']} ₽)")
                        keys.add(key)
                lines.append("")

        brands = sorted({s["brand"] for s in scope})
        head_brand = (brands[0] if len(brands) == 1 else ", ".join(brands)[:60])
        over = sum(1 for s in scope if s["status"] == "дороже")
        under = sum(1 for s in scope if s["status"] == "дешевле")
        lines.append(f"📊 <b>{MP_LABEL} · {esc(head_brand)} — цены на {now_s} МСК"
                     f"{' · сводка' if digest else ''}</b>")
        lines.append(f"дороже конкурентов: {over} из {len(scope)} · "
                     f"дешевле рынка: {under} · порог {thr_pct}%")
        lines.append("")
        if not part_alerts and not part_recovered:
            lines.append(f"✅ Все позиции в рамках порога — {len(scope)} шт")
            lines.append("")
        section("⚠️ <b>СТАЛИ ДОРОЖЕ</b> — {n} позиций по {g} товарам",
                [x for x in part_alerts if x[1]["status"] == "дороже"], 1)
        section("💰 <b>СИЛЬНО ДЕШЕВЛЕ ВСЕХ</b> — {n} позиций по {g} товарам, "
                "можно поднять цену",
                [x for x in part_alerts if x[1]["status"] == "дешевле"], -1)
        if part_recovered:
            lines.append(f"✅ <b>Вернулись к рынку: {len(part_recovered)}</b>")
            for key, s, was_st in part_recovered:
                lines.append(f"• {esc(s['group'])} — {esc(s['brand'])} "
                             f"<code>{key[0]}</code> {s['price']} ₽ "
                             f"(было «{was_st}», сейчас {s['d_min']:+}% к мин. {s['min']} ₽)")
                keys.add(key)
            lines.append("")
        lines.append(f"<a href=\"https://docs.google.com/spreadsheets/d/{a.sheet_id}/edit\">"
                     f"Таблица цен {MP_LABEL}</a>")
        return "\n".join(lines), keys, f"📊 <b>{MP_LABEL} · {esc(head_brand)}</b>"

    def send_chunked(targets, text, cont_head=""):
        LIM = 3500                # лимит Telegram — 4096 символов на сообщение
        chunks, buf = [], ""
        # v1.1.0. Блок сам может не влезть: в компактном формате весь список
        # позиций — ОДИН блок без пустых строк, и у большого бренда он перерастал
        # лимит целиком (в подробном формате блоком была товарная группа, всегда
        # короткая). Поэтому длинный блок дополнительно режется по строкам.
        blocks = []
        for block in text.split("\n\n"):
            if len(block) <= LIM:
                blocks.append(block); continue
            part = ""
            for line in block.split("\n"):
                if part and len(part) + len(line) + 1 > LIM:
                    blocks.append(part); part = line
                else:
                    part = (part + "\n" + line) if part else line
            if part:
                blocks.append(part)
        for block in blocks:
            if buf and len(buf) + len(block) + 2 > LIM:
                chunks.append(buf); buf = block
            else:
                buf = (buf + "\n\n" + block) if buf else block
        if buf:
            chunks.append(buf)
        parts = [c for c in chunks if c.strip()]
        for n, c in enumerate(parts):
            # Метка площадки нужна в КАЖДОМ сообщении: заголовок попадает только
            # в первое, а в чат их приходит несколько подряд — без этого
            # продолжение снова читается как «непонятно про что».
            if n and cont_head:
                c = f"{cont_head} — продолжение {n + 1}/{len(parts)}\n\n" + c
            if not tg_send(tg_token, targets, c):
                return False
        return True

    def addr_of(t):
        return ", ".join(c + (":" + th if th else "") for c, th in t) or "—"

    sent_keys = set()
    if event_mode:
        # Маршрут события — бренды НАШИХ позиций этой группы: сигнал про чужую
        # цену нужен тому, кто отвечает за наш товар рядом с ней.
        routes = {}

        def bucket(brand):
            k = brand.strip() if test_targets else tuple(targets_for(brand))
            return routes.setdefault(k, {"e": [], "b": [], "w": [], "brands": set(),
                                         "seen": set()})

        def put(ev, slot):
            for b in ev["brands"]:
                r = bucket(b)
                r["brands"].add(b)
                if (slot, id(ev)) not in r["seen"]:
                    r["seen"].add((slot, id(ev)))
                    r[slot].append(ev)

        for ev in events:
            put(ev, "e")
        for ev in back:
            put(ev, "b")
        for ev in undercut_now:
            put(ev, "w")
        if digest:
            for brand in sorted({s["brand"] for s in cur.values()}):
                bucket(brand)["brands"].add(brand)
        if not (events or back or digest):
            print("событий нет — сообщения не отправлялись")
            routes = {}

        for key, data in routes.items():
            if not (data["e"] or data["b"] or digest):
                continue
            text, cont_head = build_events(data["e"], data["b"], data["w"],
                                           sorted(data["brands"]))
            if test_targets:
                targets, real = list(test_targets), targets_for(key)
                text = (f"🧪 <b>ТЕСТ рассылки.</b> Бренд <b>{html.escape(key)}</b>, "
                        f"в бою уйдёт в <code>{addr_of(real)}</code>\n\n" + text)
            else:
                targets = list(key)
            who = addr_of(targets)
            if a.dry_run:
                print(f"\n----- сообщение для {who} (dry-run, не отправлено) -----")
                print(text)
                continue
            if not tg_token or not targets:
                print(f"ВНИМАНИЕ: некуда слать ({who}) — сообщение пропущено")
                continue
            send_chunked(list(targets), text, cont_head)
    elif alerts or recovered or digest:
        # раскладываем сигналы по адресатам: у каждого чата своё сообщение и
        # свои счётчики, чтобы бренду не прилетала чужая статистика
        # ключ маршрута — адресат; в тестовом режиме адресат у всех один, поэтому
        # группируем по бренду, иначе репетиция слепила бы всё в одно сообщение
        def route_key(brand):
            return brand.strip() if test_targets else tuple(targets_for(brand))

        # v1.2.0. Состав брендов маршрута ведём отдельно: в час сводки маршрут
        # может не иметь НИ ОДНОГО сигнала, и вывести бренд из списка сигналов
        # (как раньше) уже нельзя — сообщение осталось бы без охвата и без шапки
        routes, route_brands = {}, {}

        def route_add(brand):
            k = route_key(brand)
            routes.setdefault(k, {"a": [], "r": []})
            route_brands.setdefault(k, set()).add(brand)
            return k

        for item in alerts:
            routes[route_add(item[1]["brand"])]["a"].append(item)
        for item in recovered:
            routes[route_add(item[1]["brand"])]["r"].append(item)
        if digest:
            # сводку получает каждый бренд книги, даже тот, у кого всё в порядке
            for brand in sorted({s["brand"] for s in cur.values()}):
                route_add(brand)

        def addr(t):
            return ", ".join(c + (":" + th if th else "") for c, th in t) or "—"

        for key, data in routes.items():
            scope = [s for s in cur.values() if s["brand"] in route_brands[key]]
            build = build_compact if compact else build_message
            text, keys, cont_head = build(data["a"], data["r"], scope)
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
            if send_chunked(list(targets), text, cont_head) and not test_targets:
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
        out.append([art, s["group"], s["brand"], s["price"] or ""]
                   + [comp_cell(s["cols"].get(c)) for c in comp_cols]
                   + [f"{s['min_who']} {s['min_art']}".strip(),
                      s["min"] if s["min"] is not None else "",
                      s["d_min"] if s["d_min"] is not None else "",
                      s["min_grp"],
                      s["cheaper"] if s["cheaper"] is not None else "",
                      s["status"], now_s, pts if pts is not None else ""])

    top_n = sum(1 for s in cur.values() if s["status"] == "дороже" and s["top"])
    no_price = sum(1 for s in cur.values() if s["status"] == "нет цены")
    b_min = sum(1 for s in cur.values() if s["min_grp"] == "Б")
    summary = (f"дороже конкурентов: {total_over} из {len(cur)}"
               + (f" · дороже ВСЕХ в группе: {top_n}" if top_n else "")
               + f" · сильно дешевле рынка: {total_under}"
               + (f" · без цены (нет в наличии): {no_price}" if no_price else "")
               + (f" · минимум держит группа Б: {b_min}" if b_min else "")
               + f" · порог {thr_pct}% · обновлено {now_s} МСК")

    need_rows = FIRST_DATA_ROW + len(out) + 20
    last = col_letter(len(L) - 1)
    api(a.sheet_id + ":batchUpdate", tok, "POST", {"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": gid,
                                                  "gridProperties": {"rowCount": need_rows,
                                                                     "columnCount": len(L)}},
                                   "fields": "gridProperties(rowCount,columnCount)"}}]})
    api(f"{a.sheet_id}/values/'{urllib.parse.quote(MON_TITLE)}'!A{FIRST_DATA_ROW}:{last}2000:clear",
        tok, "POST", {})
    api(a.sheet_id + "/values:batchUpdate", tok, "POST", {"valueInputOption": "USER_ENTERED",
        "data": [{"range": f"'{MON_TITLE}'!A{SUMMARY_ROW}", "values": [["Сейчас", summary]]},
                 {"range": f"'{MON_TITLE}'!A{FIRST_DATA_ROW}", "values": out}]})
    decorate(a.sheet_id, tok, gid, [row_style(s) for _, s in order],
             [art_style(s) for _, s in order], need_rows, bool(total_over), L)
    print(f"лист «{MON_TITLE}»: записано {len(out)} строк, наверху — {out[0][1] if out else '—'}")
    # v2.0.0. Память по чужим ценам пишется ВСЕГДА в событийном режиме, даже
    # когда событий не было: без свежей базы следующий прогон меряет падение от
    # устаревшей цены и либо промолчит, либо выдаст выдуманный обвал.
    if event_mode and comp_gid:
        write_comp_state(a.sheet_id, tok, comp_gid, comp_rows, now_s)
        print(f"лист «{COMP_TITLE}»: {len(comp_rows)} пар «группа × конкурент», "
              f"дешевле нас {sum(1 for r in comp_rows if r[5] == 'да')}")
    print("DONE")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Отправка сводки отчёта в Telegram: картинка-сводка + (опц.) Excel-файл.

Картинка генерируется из данных (PIL): итоги WB/Ozon/Всего c дельтами
и топ-5 роста/падения по артикулам. Без браузера и скриншотов.

Использование:
  python3 send_telegram.py --state <state.json> --keys <api_keys.txt> \
      [--chat-id <id>] [--file <отчёт.xlsx>] [--sheet-url <ссылка на таблицу>]
chat-id по умолчанию — TELEGRAM_CHAT_ID из api_keys.txt.
"""
import argparse, json, os, sys, urllib.request, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import norm, load_map, base_art
from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser()
p.add_argument("--state", required=True)
p.add_argument("--keys", required=True)
p.add_argument("--chat-id", default="")
p.add_argument("--file", default="")
p.add_argument("--sheet-url", default="")
a = p.parse_args()

K = {}
for line in open(a.keys, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); K[k] = v.strip()
TOK = K.get("TELEGRAM_BOT_TOKEN", "")

S = json.load(open(a.state))
MAP = load_map(os.path.dirname(os.path.abspath(a.state)), __import__("re").sub(r"[^A-Z0-9]", "", S["brand"].upper()))
Y, P = S["yest"], S["prev"]
ddmm = lambda iso: f"{iso[8:10]}.{iso[5:7]}"
BRAND = S["brand"]
import re as _re
PREFIX = _re.sub(r"[^A-Z0-9]", "", BRAND.upper())

# Получатели: --chat-id ИЛИ (общий TELEGRAM_CHAT_ID + брендовый <PREFIX>_TG_CHATS).
# Формат: chat_id или chat_id:thread_id (подветка), несколько — через запятую.
raw = a.chat_id or ",".join(x for x in (K.get("TELEGRAM_CHAT_ID", ""),
                                        K.get(f"{PREFIX}_TG_CHATS", "")) if x)
TARGETS = []
for part in raw.split(","):
    part = part.strip()
    if not part: continue
    if ":" in part.lstrip("-"):
        cid, thr = part.rsplit(":", 1)
        TARGETS.append((cid, thr))
    else:
        TARGETS.append((part, None))
if not TOK or not TARGETS:
    print("ERROR: нет TELEGRAM_BOT_TOKEN / получателей"); sys.exit(1)

# ---------- агрегаты (фильтр активных — как в build_excel) ----------
def wb_active(nm):
    nm = str(nm)
    return S.get("wb_stocks", {}).get(nm, 0) > 0 or S.get("wb_orders14", {}).get(nm, 0) > 0
def oz_active(offer, sku):
    return (S.get("oz_stocks", {}) or {}).get(offer, 0) > 0 or \
           (S.get("oz_orders14", {}) or {}).get(str(sku), 0) > 0

wb_y = wb_p = oz_y = oz_p = 0
agg = {}
if S.get("has_wb"):
    for c in S["wb_cards"]:
        if not wb_active(c["nmID"]): continue
        f = S["wb_funnel"].get(str(c["nmID"]), {})
        oy, op = f.get(Y, {}).get("orders", 0), f.get(P, {}).get("orders", 0)
        wb_y += oy; wb_p += op
        g = agg.setdefault(base_art(c["vendorCode"], MAP), [0, 0]); g[0] += oy; g[1] += op
if S.get("has_oz"):
    for sku, v in (S.get("ozon") or {}).items():
        if not oz_active(v.get("offer_id", ""), sku): continue
        oy, op = v.get(Y, {}).get("orders", 0), v.get(P, {}).get("orders", 0)
        oz_y += oy; oz_p += op
        g = agg.setdefault(base_art(v.get("offer_id") or v["name"], MAP), [0, 0]); g[0] += oy; g[1] += op

movers = [(k, g[0], g[0] - g[1]) for k, g in agg.items() if abs(g[0] - g[1]) > 0]
top_up = sorted([m for m in movers if m[2] > 0], key=lambda m: -m[2])[:5]
top_dn = sorted([m for m in movers if m[2] < 0], key=lambda m: m[2])[:5]

# ---------- картинка ----------
W = 900
GREEN, RED, DARK, GRAY, BG = (0, 128, 60), (200, 30, 50), (20, 40, 70), (110, 110, 110), (255, 255, 255)
def font(sz, bold=False):
    for path in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",):
        if os.path.exists(path): return ImageFont.truetype(path, sz)
    return ImageFont.load_default()
F_H1, F_H2, F_T, F_S = font(34, True), font(26, True), font(22), font(22, True)

rows_n = max(len(top_up), 1) + max(len(top_dn), 1)
HH = 210 + 80 + rows_n * 34 + 90
img = Image.new("RGB", (W, HH), BG)
d = ImageDraw.Draw(img)
def pct(y_, p_): return "" if p_ == 0 else f"{(y_-p_)/p_*100:+.1f}%"
def line(y_, p_): return f"{y_:,}".replace(",", " ") + f"  ({y_-p_:+}, {pct(y_,p_) or '—'})"

d.rectangle([0, 0, W, 64], fill=(31, 78, 120))
d.text((24, 14), f"{BRAND} — заказы за {ddmm(Y)} (vs {ddmm(P)})", font=F_H1, fill=BG)
y = 84
for label, vy, vp in ([("WB", wb_y, wb_p)] if S.get("has_wb") else []) + \
                     ([("Ozon", oz_y, oz_p)] if S.get("has_oz") else []) + \
                     [("ВСЕГО", wb_y + oz_y, wb_p + oz_p)]:
    delta = vy - vp
    col = GREEN if delta > 0 else RED if delta < 0 else GRAY
    d.text((24, y), label, font=F_H2, fill=DARK)
    d.text((140, y), line(vy, vp), font=F_H2, fill=col)
    y += 42
y += 14
def block(title, items, col):
    global y
    d.text((24, y), title, font=F_S, fill=DARK); y += 34
    if not items:
        d.text((40, y), "—", font=F_T, fill=GRAY); y += 34
    for name, tot, delta in items:
        nm = name if len(name) <= 52 else name[:50] + "…"
        d.text((40, y), nm, font=F_T, fill=(50, 50, 50))
        d.text((W - 200, y), f"{tot}  ({delta:+})", font=F_T, fill=col)
        y += 34
block("Топ рост:", top_up, GREEN)
y += 10
block("Топ падение:", top_dn, RED)
d.text((24, HH - 40), "Только активные артикулы · WB+Ozon · источник: API площадок",
       font=font(17), fill=GRAY)
img_path = f"/tmp/tg_{BRAND}_{ddmm(Y)}.png"
img.save(img_path)

# ---------- отправка ----------
def multipart(url, fields, file_field, file_path, mime):
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    fname = os.path.basename(file_path)
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
             f"filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
    body += open(file_path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

caption = f"{BRAND}: {wb_y + oz_y:,} заказов за {ddmm(Y)} ({(wb_y+oz_y)-(wb_p+oz_p):+} к {ddmm(P)})".replace(",", " ")
if a.sheet_url:
    caption += f"\nТаблица: {a.sheet_url}"
for cid, thr in TARGETS:
    fields = {"chat_id": cid, "caption": caption}
    if thr: fields["message_thread_id"] = thr
    r = multipart(f"https://api.telegram.org/bot{TOK}/sendPhoto", fields, "photo", img_path, "image/png")
    print(f"photo → {cid}{':'+thr if thr else ''}:", "OK" if r.get("ok") else r)
    if a.file and os.path.exists(a.file):
        fields = {"chat_id": cid}
        if thr: fields["message_thread_id"] = thr
        r = multipart(f"https://api.telegram.org/bot{TOK}/sendDocument", fields, "document", a.file,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        print(f"file → {cid}{':'+thr if thr else ''}:", "OK" if r.get("ok") else r)

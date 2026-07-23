#!/usr/bin/env python3
"""Отправка сводки «Общая» в Telegram картинкой (как у брендовых отчётов).

Картинка (PIL): итоги WB/Ozon/ВСЕГО с дельтами к прошлому дню + таблица по
брендам — заказы за вчера, за позавчера, дельта и % (зелёный/красный).
Данные — из svod_summary.json, который пишет svod_report.py.

Использование:
  python3 svod_telegram.py --summary state/svod_summary.json --keys api_keys.txt[,extra] \
      [--chat-id <id[:topic]>] [--no-send]
Получатели по умолчанию — SVOD_TG_CHATS (chat_id[:topic] через запятую).
Печатает OK при успешной отправке; --no-send — только сохранить картинку.
"""
import argparse, json, os, sys, tempfile, urllib.request, uuid

from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser()
p.add_argument("--summary", required=True)
p.add_argument("--keys", required=True)
p.add_argument("--chat-id", default="")
p.add_argument("--no-send", action="store_true")
a = p.parse_args()

K = {}
for path in a.keys.split(","):
    path = path.strip()
    if not path or not os.path.exists(path): continue
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); K[k.strip()] = v.strip()

S = json.load(open(a.summary, encoding="utf-8"))
Y, P = S["date"], S["prev"]
ddmm = lambda iso: f"{iso[8:10]}.{iso[5:7]}"
brands = S["brands"]
for b in brands:
    b["tot_y"] = b["wb_y"] + b["oz_y"]
    b["tot_p"] = b["wb_p"] + b["oz_p"]
brands.sort(key=lambda b: -b["tot_y"])
wb_y = sum(b["wb_y"] for b in brands); wb_p = sum(b["wb_p"] for b in brands)
oz_y = sum(b["oz_y"] for b in brands); oz_p = sum(b["oz_p"] for b in brands)

# ---------- картинка ----------
W = 1000
GREEN, RED, DARK, GRAY, BG = (0, 128, 60), (200, 30, 50), (20, 40, 70), (110, 110, 110), (255, 255, 255)
HDR = (31, 78, 120)

def font(sz, bold=False):
    for path in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
                 rf"C:\Windows\Fonts\arial{'bd' if bold else ''}.ttf"):
        if os.path.exists(path): return ImageFont.truetype(path, sz)
    return ImageFont.load_default()

F_H1, F_H2, F_T, F_S = font(34, True), font(26, True), font(22), font(22, True)
F_SMALL = font(17)

def fmt(n): return f"{n:,}".replace(",", " ")
def pct(y_, p_): return "" if p_ == 0 else f"{(y_-p_)/p_*100:+.1f}%"
def dline(y_, p_):
    return f"{fmt(y_)}  ({y_-p_:+}, {pct(y_, p_) or '—'})"

ROW_H = 38
HH = 64 + 20 + 3 * 42 + 26 + 40 + 40 + len(brands) * ROW_H + 14 + ROW_H + 56
img = Image.new("RGB", (W, HH), BG)
d = ImageDraw.Draw(img)

d.rectangle([0, 0, W, 64], fill=HDR)
d.text((24, 14), f"ОБЩАЯ — заказы за {ddmm(Y)} (vs {ddmm(P)})", font=F_H1, fill=BG)

y = 84
for label, vy, vp in (("WB", wb_y, wb_p), ("Ozon", oz_y, oz_p), ("ВСЕГО", wb_y + oz_y, wb_p + oz_p)):
    delta = vy - vp
    col = GREEN if delta > 0 else RED if delta < 0 else GRAY
    d.text((24, y), label, font=F_H2, fill=DARK)
    d.text((140, y), dline(vy, vp), font=F_H2, fill=col)
    y += 42
y += 26

# таблица по брендам: Бренд | WB | Ozon | Всего | Пред. день | Δ (%)
X_NAME, X_WB, X_OZ, X_TOT, X_PREV, X_D = 24, 420, 530, 650, 780, 976
d.text((X_NAME, y), "По брендам:", font=F_S, fill=DARK)
y += 40
d.text((X_NAME, y), "Бренд", font=F_SMALL, fill=GRAY)
for x, t in ((X_WB, "WB"), (X_OZ, "Ozon"), (X_TOT, "Всего"), (X_PREV, ddmm(P)), (X_D, "Δ (%)")):
    d.text((x, y), t, font=F_SMALL, fill=GRAY, anchor="ra")
y += 26
d.line([24, y - 4, W - 24, y - 4], fill=(220, 220, 220), width=1)
for b in brands:
    delta = b["tot_y"] - b["tot_p"]
    col = GREEN if delta > 0 else RED if delta < 0 else GRAY
    d.text((X_NAME, y), b["name"], font=F_T, fill=(50, 50, 50))
    d.text((X_WB, y), fmt(b["wb_y"]), font=F_T, fill=(50, 50, 50), anchor="ra")
    d.text((X_OZ, y), fmt(b["oz_y"]), font=F_T, fill=(50, 50, 50), anchor="ra")
    d.text((X_TOT, y), fmt(b["tot_y"]), font=F_S, fill=DARK, anchor="ra")
    d.text((X_PREV, y), fmt(b["tot_p"]), font=F_T, fill=GRAY, anchor="ra")
    d.text((X_D, y), f"{delta:+} ({pct(b['tot_y'], b['tot_p']) or '—'})", font=F_S, fill=col, anchor="ra")
    y += ROW_H
d.line([24, y + 2, W - 24, y + 2], fill=(220, 220, 220), width=1)
y += 14
delta = (wb_y + oz_y) - (wb_p + oz_p)
col = GREEN if delta > 0 else RED if delta < 0 else GRAY
d.text((X_NAME, y), "ИТОГО", font=F_S, fill=DARK)
d.text((X_WB, y), fmt(wb_y), font=F_S, fill=DARK, anchor="ra")
d.text((X_OZ, y), fmt(oz_y), font=F_S, fill=DARK, anchor="ra")
d.text((X_TOT, y), fmt(wb_y + oz_y), font=F_S, fill=DARK, anchor="ra")
d.text((X_PREV, y), fmt(wb_p + oz_p), font=F_S, fill=GRAY, anchor="ra")
d.text((X_D, y), f"{delta:+} ({pct(wb_y + oz_y, wb_p + oz_p) or '—'})", font=F_S, fill=col, anchor="ra")

note = "Свод «Общая» · WB+Ozon · сравнение с предыдущим днём"
if S.get("errors"): note += " · ⚠ неполные данные"
d.text((24, HH - 34), note, font=F_SMALL, fill=GRAY)

img_path = os.path.join(tempfile.gettempdir(), f"tg_svod_{ddmm(Y)}.png")
img.save(img_path)
print("img:", img_path)
if a.no_send:
    print("NO SEND"); sys.exit(0)

# ---------- отправка ----------
TOK = K.get("TELEGRAM_BOT_TOKEN", "")
raw = a.chat_id or K.get("SVOD_TG_CHATS", "")
TARGETS = []
for part in raw.split(","):
    part = part.strip()
    if not part: continue
    if ":" in part.lstrip("-"):
        cid, thr = part.rsplit(":", 1)
        # топик 1 форума = «General»: Telegram требует НЕ слать message_thread_id
        # (иначе sendPhoto → 400 «message thread not found»)
        TARGETS.append((cid, None if thr.strip() == "1" else thr))
    else:
        TARGETS.append((part, None))
if not TOK or not TARGETS:
    print("ERROR: нет TELEGRAM_BOT_TOKEN / получателей"); sys.exit(1)

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

caption = (f"📊 Свод «Общая»: {fmt(wb_y + oz_y)} заказов за {ddmm(Y)} "
           f"({delta:+} к {ddmm(P)})")
if S.get("sheet_id"):
    caption += f"\nТаблица: https://docs.google.com/spreadsheets/d/{S['sheet_id']}/edit"
ok_all = True
for cid, thr in TARGETS:
    fields = {"chat_id": cid, "caption": caption}
    if thr: fields["message_thread_id"] = thr
    r = multipart(f"https://api.telegram.org/bot{TOK}/sendPhoto", fields, "photo", img_path, "image/png")
    good = bool(r.get("ok"))
    ok_all = ok_all and good
    print(f"photo → {cid}{':'+thr if thr else ''}:", "OK" if good else r)
sys.exit(0 if ok_all else 1)

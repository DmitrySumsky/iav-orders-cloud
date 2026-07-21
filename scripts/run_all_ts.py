#!/usr/bin/env python3
"""Облачный оркестратор v2: TrueStats-ядро + каскад воронки, изоляция брендов.

Маршрутизация по бренду:
  есть <PREFIX>_TS_TOKEN  -> collect_ts (TrueStats, минуты) + history_ts
  нет (ORZAX, LOVE&DOVE)  -> старый collect.py + history.py (прямые API)
Дальше одинаково: build_excel -> push_gsheet (если есть SA) -> send_telegram.

Отказоустойчивость:
  - сбой одного бренда НЕ трогает остальные (изоляция + финальный ретрай);
  - ядро TS-брендов не зависит от лимитов WB: воронка не пришла — отчёт ушёл;
  - при сбоях шлётся алерт в служебный Telegram (TELEGRAM_CHAT_ID);
  - анти-дубль отправки: state/sent_<BRAND>_<дата>.json.

Env: BRANDS, SKIP_TG, HISTORY_DAYS (дефолт 8), TIME_BUDGET (для старого пути).
Коды выхода: 0 — все ок, 1 — есть ошибки.
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYS = os.path.join(ROOT, "api_keys.txt")
SA = os.path.join(ROOT, "google_sa.json")
STATE = os.path.join(ROOT, "state")
REPORTS = os.path.join(ROOT, "reports")
BRANDS = os.environ.get("BRANDS", "NATURI,4ME,HEALTH FORM,SUNSHINE,VEXOR,ORZAX,LOVE&DOVE").split(",")
HISTORY_DAYS = os.environ.get("HISTORY_DAYS", "8")

K = {}
for line in open(KEYS, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); K[k.strip()] = v.strip()

def sa_valid():
    try:
        return bool(json.load(open(SA)).get("client_email"))
    except Exception:
        return False

def tg_alert(text):
    """Служебное уведомление о сбое (не валит прогон, если само упало)."""
    bot, chat = K.get("TELEGRAM_BOT_TOKEN"), K.get("TELEGRAM_CHAT_ID")
    if not bot or not chat: return
    try:
        body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{bot}/sendMessage", data=body),
            timeout=30).read()
    except Exception as e:
        print(f"алерт не отправлен: {e}")

def run_until_done(args, max_runs=25):
    """Резюмируемые скрипты печатают DONE. Между повторами пауза."""
    for i in range(max_runs):
        r = subprocess.run(args, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if out: print(out[-2000:], flush=True)
        if r.returncode != 0: return False
        if "DONE" in out: return True
        time.sleep(60 if "429" in out else 25)
    return False

def process(brand):
    """Полный конвейер одного бренда. Возвращает None или текст ошибки."""
    prefix = re.sub(r"[^A-Z0-9]", "", brand.upper())
    use_ts = bool(K.get(f"{prefix}_TS_TOKEN"))
    has_keys = use_ts or K.get(f"{prefix}_WB_TOKEN") or \
               (K.get(f"{prefix}_OZON_CLIENT_ID") and K.get(f"{prefix}_OZON_API_KEY"))
    if not has_keys:
        print("нет ключей — пропуск"); return None

    keys_arg = KEYS
    if use_ts:
        if not run_until_done(["python3", f"{HERE}/collect_ts.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE], max_runs=4):
            return "collect_ts"
        if not run_until_done(["python3", f"{HERE}/history_ts.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE,
                               "--days", HISTORY_DAYS], max_runs=4):
            return "history_ts"
    else:
        if not run_until_done(["python3", f"{HERE}/collect.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE]):
            return "collect"
        if not run_until_done(["python3", f"{HERE}/history.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE,
                               "--days", HISTORY_DAYS]):
            return "history"

    states = sorted(f for f in os.listdir(STATE) if f.startswith(prefix + "_2"))
    if not states: return "нет state"
    state_f = os.path.join(STATE, states[-1])

    r = subprocess.run(["python3", f"{HERE}/build_excel.py", "--state", state_f,
                        "--outdir", REPORTS], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr[-500:])
    if "VERIFY OK" not in r.stdout: return "excel"
    xlsx = [l.split("saved ", 1)[1] for l in r.stdout.splitlines() if l.startswith("saved ")][0]

    sheet_id = K.get(f"{prefix}_GSHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""
    if sheet_id and sa_valid():
        r = subprocess.run(["python3", f"{HERE}/push_gsheet.py", "--state", state_f,
                            "--history", os.path.join(STATE, f"history_{prefix}.json"),
                            "--sa", SA, "--sheet-id", sheet_id], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr[-500:])
        if "VERIFY OK" not in r.stdout:
            # не валим бренд: TG с Excel важнее; таблица могла быть не расшарена на SA
            warnings.append(f"{brand}: Google Sheet не обновлён")
    elif sheet_id:
        print("SA недоступен — Google Sheet пропущен")

    sent_flag = os.path.join(STATE, "sent_" + os.path.basename(state_f))
    if os.environ.get("SKIP_TG"):
        print("SKIP_TG — отправка отложена")
    elif os.path.exists(sent_flag):
        print("TG уже отправлен за эту дату — пропуск")
    elif K.get("TELEGRAM_BOT_TOKEN") and (K.get("TELEGRAM_CHAT_ID") or K.get(f"{prefix}_TG_CHATS")):
        args = ["python3", f"{HERE}/send_telegram.py", "--state", state_f, "--keys", KEYS,
                "--file", xlsx]
        if sheet_url: args += ["--sheet-url", sheet_url]
        r = subprocess.run(args, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr[-500:])
        if "OK" not in r.stdout: return "telegram"
        open(sent_flag, "w").write("sent")
    return None

brand_list = [b.strip() for b in BRANDS if b.strip()]
failed, warnings = {}, []
for idx, brand in enumerate(brand_list):
    if idx > 0: time.sleep(10)
    print(f"\n=== {brand} ===", flush=True)
    try:
        err = process(brand)
    except Exception as e:
        err = f"exception: {e}"
    if err:
        print(f"ОШИБКА {brand}: {err}"); failed[brand] = err

# финальный ретрай упавших (лимиты могли отдышаться)
if failed:
    print(f"\n=== ретрай упавших: {list(failed)} ===", flush=True)
    time.sleep(120)
    for brand in list(failed):
        print(f"\n=== retry {brand} ===", flush=True)
        try:
            err = process(brand)
        except Exception as e:
            err = f"exception: {e}"
        if err: failed[brand] = err
        else: failed.pop(brand)

# сводный отчёт «Общая» (позиции × бренды) — после всех брендов
if K.get("SVOD_GSHEET_ID"):
    print("\n=== Сводный отчёт «Общая» ===", flush=True)
    if sa_valid():
        r = subprocess.run(["python3", f"{HERE}/svod_report.py", "--keys", KEYS, "--sa", SA],
                           capture_output=True, text=True)
        print((r.stdout + r.stderr).strip()[-1500:])
        if "DONE" not in r.stdout: failed["СВОД"] = "svod_report"
    else:
        print("SA недоступен — свод пропущен")

# отчёт по ценам WB+Ozon (MPStats) — независим от брендовых отчётов
if K.get("PRICES_GSHEET_ID"):
    print("\n=== Отчёт по ценам (MPStats) ===", flush=True)
    if sa_valid():
        r = subprocess.run(["python3", f"{HERE}/prices_update.py", "--keys", KEYS,
                            "--sa", SA, "--sheet-id", K["PRICES_GSHEET_ID"]],
                           capture_output=True, text=True)
        print((r.stdout + r.stderr).strip()[-1500:])
        if "DONE" not in r.stdout: failed["ЦЕНЫ"] = "prices_update"
    else:
        print("SA недоступен — цены пропущены")

print("\nИТОГ:", "все бренды OK" if not failed else f"ошибки: {failed}")
if warnings: print("предупреждения:", "; ".join(warnings))
if failed or warnings:
    parts = []
    if failed: parts.append("сбой: " + ", ".join(f"{b} ({e})" for b, e in failed.items()))
    if warnings: parts.append("предупреждения: " + "; ".join(warnings))
    tg_alert("⚠️ Отчёт по заказам: " + " | ".join(parts) + ". Детали в GitHub Actions.")
sys.exit(1 if failed else 0)

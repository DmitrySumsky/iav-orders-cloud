#!/usr/bin/env python3
"""Облачный оркестратор: полный конвейер отчёта по всем брендам.

Для каждого бренда из BRANDS:
  collect (до DONE) -> history (до DONE) -> Excel -> Google Sheet -> Telegram.
Бренды без каких-то ключей/настроек пропускают соответствующие шаги.
Коды выхода: 0 — все бренды ок, 1 — есть ошибки (см. лог).
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYS = os.path.join(ROOT, "api_keys.txt")
SA = os.path.join(ROOT, "google_sa.json")
STATE = os.path.join(ROOT, "state")
REPORTS = os.path.join(ROOT, "reports")
BRANDS = os.environ.get("BRANDS", "NATURI,VEXOR,ORZAX,LOVE&DOVE,SUNSHINE").split(",")
HISTORY_DAYS = os.environ.get("HISTORY_DAYS", "30")

K = {}
for line in open(KEYS, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); K[k] = v.strip()

def run_until_done(args, max_runs=60):
    """Скрипты резюмируемые и печатают DONE в конце."""
    for i in range(max_runs):
        r = subprocess.run(args, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if out: print(out[-2000:])
        if r.returncode != 0:
            return False
        if "DONE" in out:
            return True
    return False

failed = []
for brand in [b.strip() for b in BRANDS if b.strip()]:
    prefix = re.sub(r"[^A-Z0-9]", "", brand.upper())
    print(f"\n=== {brand} ===")
    has_keys = K.get(f"{prefix}_WB_TOKEN") or (K.get(f"{prefix}_OZON_CLIENT_ID") and K.get(f"{prefix}_OZON_API_KEY"))
    if not has_keys:
        print("нет ключей — пропуск"); continue

    if not run_until_done(["python3", f"{HERE}/collect.py", "--brand", brand,
                           "--keys", KEYS, "--state-dir", STATE]):
        print(f"ОШИБКА collect {brand}"); failed.append(brand); continue
    if not run_until_done(["python3", f"{HERE}/history.py", "--brand", brand,
                           "--keys", KEYS, "--state-dir", STATE, "--days", HISTORY_DAYS]):
        print(f"ОШИБКА history {brand}"); failed.append(brand); continue

    # имя state-файла = самый свежий для бренда
    states = sorted(f for f in os.listdir(STATE) if f.startswith(prefix + "_2"))
    if not states:
        print("нет state — пропуск"); failed.append(brand); continue
    state_f = os.path.join(STATE, states[-1])

    r = subprocess.run(["python3", f"{HERE}/build_excel.py", "--state", state_f,
                        "--outdir", REPORTS], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr[-500:])
    if "VERIFY OK" not in r.stdout:
        print(f"ОШИБКА excel {brand}"); failed.append(brand); continue
    xlsx = [l.split("saved ", 1)[1] for l in r.stdout.splitlines() if l.startswith("saved ")][0]

    sheet_id = K.get(f"{prefix}_GSHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""
    if sheet_id and os.path.exists(SA):
        r = subprocess.run(["python3", f"{HERE}/push_gsheet.py", "--state", state_f,
                            "--history", os.path.join(STATE, f"history_{prefix}.json"),
                            "--sa", SA, "--sheet-id", sheet_id], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr[-500:])
        if "VERIFY OK" not in r.stdout:
            print(f"ОШИБКА gsheet {brand}"); failed.append(brand)

    if K.get("TELEGRAM_BOT_TOKEN") and (K.get("TELEGRAM_CHAT_ID") or K.get(f"{prefix}_TG_CHATS")):
        args = ["python3", f"{HERE}/send_telegram.py", "--state", state_f, "--keys", KEYS,
                "--file", xlsx]
        if sheet_url: args += ["--sheet-url", sheet_url]
        r = subprocess.run(args, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr[-500:])

print("\nИТОГ:", "все бренды OK" if not failed else f"ошибки: {failed}")
sys.exit(1 if failed else 0)

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

# Консоль Windows по умолчанию cp1251: «×», «→», «✅» роняли бы прогон на печати.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

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
        return bool(json.load(open(SA, encoding="utf-8")).get("client_email"))
    except Exception:
        return False

# Пункт управления: настройки из таблицы перекрывают api_keys; подскрипты
# получают объединённый файл ключей. Время крона синхронизируется само.
sys.path.insert(0, HERE)
from control_panel import load_settings, sync_cron, write_dashboard
if sa_valid():
    overrides = load_settings(SA, K)
    if overrides:
        K.update(overrides)
        merged = os.path.join(ROOT, "api_keys_merged.txt")
        with open(merged, "w", encoding="utf-8") as f:
            f.write(open(KEYS, encoding="utf-8").read())
            f.write("\n# --- оверрайды из пункта управления ---\n")
            for k, v in overrides.items(): f.write(f"{k}={v}\n")
        KEYS = merged
    sync_cron(K)
    if K.get("BRANDS") and "BRANDS" not in os.environ:
        BRANDS = K["BRANDS"].split(",")
    if K.get("HISTORY_DAYS"): HISTORY_DAYS = K["HISTORY_DAYS"]

def tg_send(chats, text):
    """Отправка текста в чаты вида 'chat_id[:topic],...' ботом системы."""
    bot = K.get("TELEGRAM_BOT_TOKEN")
    if not bot or not chats: return False
    ok = True
    for pair in str(chats).split(","):
        pair = pair.strip()
        if not pair: continue
        cid, _, topic = pair.partition(":")
        params = {"chat_id": cid, "text": text}
        # топик 1 форума = «General»: слать без message_thread_id (иначе 400)
        if topic and topic.strip() != "1": params["message_thread_id"] = topic
        try:
            body = urllib.parse.urlencode(params).encode()
            urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{bot}/sendMessage", data=body),
                timeout=30).read()
        except Exception as e:
            print(f"TG {cid}: не отправлено ({e})"); ok = False
    return ok

# Windows-консоль по умолчанию cp1251: дочерний print("→"/"×") падал бы UnicodeEncodeError,
# а разбор его вывода — UnicodeDecodeError. Явный utf-8 в обе стороны.
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=CHILD_ENV, **kw)

def tg_alert(text):
    """Служебное уведомление о сбое (не валит прогон, если само упало)."""
    tg_send(K.get("TELEGRAM_CHAT_ID", ""), text)

def run_until_done(args, max_runs=25, deadline_sec=1500):
    """Резюмируемые скрипты печатают DONE. Между повторами пауза.
    deadline_sec — потолок по времени: если МП висит (таймауты по минуте),
    один бренд не должен съесть весь лимит джоба."""
    t0 = time.time()
    for i in range(max_runs):
        r = run(args)
        out = (r.stdout + r.stderr).strip()
        # показываем и начало вывода — по нему видно, какой шаг успел пройти
        if out: print(out if len(out) <= 2200 else out[:600] + "\n…\n" + out[-1600:], flush=True)
        if r.returncode != 0: return False
        if "DONE" in out: return True
        if time.time() - t0 > deadline_sec:
            print(f"не уложились в {deadline_sec // 60} мин — сдаёмся"); return False
        time.sleep(60 if "429" in out else 25)
    return False

def process(brand):
    """Полный конвейер одного бренда. Возвращает None или текст ошибки."""
    prefix = re.sub(r"[^A-Z0-9]", "", brand.upper())
    st = STATUS.setdefault(brand, {"Сбор данных": "—", "Google-таблица": "—",
                                   "Telegram": "—", "Детали": ""})
    use_ts = bool(K.get(f"{prefix}_TS_TOKEN"))
    has_keys = use_ts or K.get(f"{prefix}_WB_TOKEN") or \
               (K.get(f"{prefix}_OZON_CLIENT_ID") and K.get(f"{prefix}_OZON_API_KEY"))
    if not has_keys:
        print("нет ключей — пропуск"); st["Детали"] = "нет ключей"; return None

    keys_arg = KEYS
    if use_ts:
        if not run_until_done(["python3", f"{HERE}/collect_ts.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE], max_runs=4):
            st["Сбор данных"] = "❌"; return "collect_ts"
        if not run_until_done(["python3", f"{HERE}/history_ts.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE,
                               "--days", HISTORY_DAYS], max_runs=4):
            st["Сбор данных"] = "❌"; return "history_ts"
    else:
        if not run_until_done(["python3", f"{HERE}/collect.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE]):
            st["Сбор данных"] = "❌"; return "collect"
        if not run_until_done(["python3", f"{HERE}/history.py", "--brand", brand,
                               "--keys", keys_arg, "--state-dir", STATE,
                               "--days", HISTORY_DAYS]):
            st["Сбор данных"] = "❌"; return "history"
    st["Сбор данных"] = "✅"

    states = sorted(f for f in os.listdir(STATE) if f.startswith(prefix + "_2"))
    if not states: return "нет state"
    state_f = os.path.join(STATE, states[-1])

    r = run(["python3", f"{HERE}/build_excel.py", "--state", state_f,
                        "--outdir", REPORTS])
    print(r.stdout.strip() or r.stderr[-500:])
    if "VERIFY OK" not in r.stdout:
        st["Детали"] = "Excel не собрался"; return "excel"
    xlsx = [l.split("saved ", 1)[1] for l in r.stdout.splitlines() if l.startswith("saved ")][0]

    sheet_id = K.get(f"{prefix}_GSHEET_ID", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""
    if sheet_id and sa_valid():
        r = run(["python3", f"{HERE}/push_gsheet.py", "--state", state_f,
                            "--history", os.path.join(STATE, f"history_{prefix}.json"),
                            "--sa", SA, "--sheet-id", sheet_id])
        print(r.stdout.strip() or r.stderr[-500:])
        if "VERIFY OK" not in r.stdout:
            # не валим бренд: TG с Excel важнее; таблица могла быть не расшарена на SA
            warnings.append(f"{brand}: Google Sheet не обновлён")
            st["Google-таблица"] = "❌ не обновлена"
        else:
            st["Google-таблица"] = "✅"
    elif sheet_id:
        print("SA недоступен — Google Sheet пропущен"); st["Google-таблица"] = "нет SA"

    sent_flag = os.path.join(STATE, "sent_" + os.path.basename(state_f))
    if os.environ.get("SKIP_TG"):
        print("SKIP_TG — отправка отложена"); st["Telegram"] = "⏸ отложена"
    elif os.path.exists(sent_flag):
        print("TG уже отправлен за эту дату — пропуск"); st["Telegram"] = "✅ (ранее)"
    elif K.get("TELEGRAM_BOT_TOKEN") and (K.get("TELEGRAM_CHAT_ID") or K.get(f"{prefix}_TG_CHATS")):
        args = ["python3", f"{HERE}/send_telegram.py", "--state", state_f, "--keys", KEYS,
                "--file", xlsx]
        if sheet_url: args += ["--sheet-url", sheet_url]
        r = run(args)
        print(r.stdout.strip() or r.stderr[-500:])
        if "OK" not in r.stdout:
            st["Telegram"] = "❌"; return "telegram"
        st["Telegram"] = "✅"
        open(sent_flag, "w", encoding="utf-8").write("sent")
    return None

brand_list = [b.strip() for b in BRANDS if b.strip()]
failed, warnings, STATUS = {}, [], {}
T_RUN = time.time()
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
    st = STATUS.setdefault("Свод «Общая»", {"Сбор данных": "—", "Google-таблица": "—",
                                            "Telegram": "—", "Детали": ""})
    if sa_valid():
        r = run(["python3", f"{HERE}/svod_report.py", "--keys", KEYS, "--sa", SA,
                            "--state-dir", STATE])
        print((r.stdout + r.stderr).strip()[-1500:])
        if "DONE" not in r.stdout:
            failed["СВОД"] = "svod_report"
            st["Сбор данных"] = st["Google-таблица"] = "❌"
        else:
            st["Сбор данных"] = st["Google-таблица"] = "✅"
            # оповещение картинкой (итоги + разбивка по брендам), как у брендовых отчётов
            summary_f = os.path.join(STATE, "svod_summary.json")
            day = ""
            try:
                sm = json.load(open(summary_f, encoding="utf-8"))
                day = sm.get("date", "")
                # площадка отдала ноль при живом предыдущем дне — данные неполные,
                # сводка уходит с пометкой, но мы должны узнать об этом сразу
                for e in sm.get("errors") or []:
                    warnings.append(f"Свод: {e}")
            except Exception:
                pass
            sent_flag = os.path.join(STATE, f"sent_SVOD_{day}.json")
            if os.environ.get("SKIP_TG"):
                print("SKIP_TG — сводка отложена"); st["Telegram"] = "⏸ отложена"
            elif day and os.path.exists(sent_flag):
                print("сводка уже отправлена за эту дату — пропуск"); st["Telegram"] = "✅ (ранее)"
            elif day and K.get("SVOD_TG_CHATS"):
                r2 = run(["python3", f"{HERE}/svod_telegram.py", "--summary", summary_f,
                                     "--keys", KEYS])
                print((r2.stdout + r2.stderr).strip()[-800:])
                if r2.returncode == 0 and "OK" in r2.stdout:
                    st["Telegram"] = "✅"
                    open(sent_flag, "w", encoding="utf-8").write("sent")
                else:
                    st["Telegram"] = "❌"; failed["СВОД"] = "svod_telegram"
    else:
        print("SA недоступен — свод пропущен"); st["Google-таблица"] = "нет SA"

# цены WB по позициям в той же книге свода — читают «Маппинг позиций»,
# поэтому идут ПОСЛЕ svod_report (он этот лист и дополняет за прогон)
if K.get("SVOD_GSHEET_ID"):
    print("\n=== Цены WB по позициям ===", flush=True)
    st = STATUS.setdefault("Цены свода", {"Сбор данных": "—", "Google-таблица": "—",
                                          "Telegram": "—", "Детали": ""})
    if sa_valid():
        r = run(["python3", f"{HERE}/svod_prices.py", "--keys", KEYS, "--sa", SA])
        print((r.stdout + r.stderr).strip()[-1200:])
        if "DONE" not in r.stdout:
            failed["ЦЕНЫ СВОДА"] = "svod_prices"
            st["Сбор данных"] = st["Google-таблица"] = "❌"
        else:
            st["Сбор данных"] = st["Google-таблица"] = "✅"
    else:
        print("SA недоступен — цены свода пропущены"); st["Google-таблица"] = "нет SA"

# отчёт по ценам WB+Ozon (MPStats) — независим от брендовых отчётов
if K.get("PRICES_GSHEET_ID"):
    print("\n=== Отчёт по ценам (MPStats) ===", flush=True)
    st = STATUS.setdefault("Цены WB+Ozon", {"Сбор данных": "—", "Google-таблица": "—",
                                            "Telegram": "—", "Детали": ""})
    if sa_valid():
        # PRICES_GSHEET_ID — одна или несколько таблиц через запятую (БАДы, автохимия)
        ids = [s.strip() for s in K["PRICES_GSHEET_ID"].split(",") if s.strip()]
        ok, filled = True, []
        for sid in ids:
            r = run(["python3", f"{HERE}/prices_update.py", "--keys", KEYS,
                                "--sa", SA, "--sheet-id", sid])
            print((r.stdout + r.stderr).strip()[-1500:])
            if "DONE" not in r.stdout: ok = False
            filled += [l.strip() for l in r.stdout.splitlines() if "залито ячеек" in l]
        if not ok:
            failed["ЦЕНЫ"] = "prices_update"
            st["Сбор данных"] = st["Google-таблица"] = "❌"
        else:
            st["Сбор данных"] = st["Google-таблица"] = "✅"
            st["Детали"] = "; ".join(filled)[:200]
    else:
        print("SA недоступен — цены пропущены"); st["Google-таблица"] = "нет SA"

# дашборд пункта управления — статус каждого шага последнего прогона
if sa_valid() and K.get("CONTROL_GSHEET_ID"):
    mins = int((time.time() - T_RUN) // 60)
    info = ("без ошибок" if not failed else f"ошибки: {', '.join(failed)}") + f", {mins} мин"
    dash_rows = [[name, s.get("Сбор данных", "—"), s.get("Google-таблица", "—"),
                  s.get("Telegram", "—"),
                  (s.get("Детали", "") + (" | " + failed.get(name, "") if name in failed else "")).strip(" |")]
                 for name, s in STATUS.items()]
    write_dashboard(SA, K, info, dash_rows)

print("\nИТОГ:", "все бренды OK" if not failed else f"ошибки: {failed}")
if warnings: print("предупреждения:", "; ".join(warnings))
if (failed or warnings) and not os.environ.get("SKIP_TG"):
    parts = []
    if failed: parts.append("сбой: " + ", ".join(f"{b} ({e})" for b, e in failed.items()))
    if warnings: parts.append("предупреждения: " + "; ".join(warnings))
    tg_alert("⚠️ Отчёт по заказам: " + " | ".join(parts) + ". Детали в GitHub Actions.")
sys.exit(1 if failed else 0)

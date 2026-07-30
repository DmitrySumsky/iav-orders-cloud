#!/usr/bin/env python3
"""Пункт управления системой отчётов — таблица CONTROL_GSHEET_ID (папка 0033).

Лист «Настройки»: Параметр | Значение | Комментарий. Значения перекрывают
api_keys при каждом прогоне (пустое значение = не перекрывать). Меняются без
кода: чаты/ветки TG по брендам, id таблиц, время крона, флаги.
Лист «Дашборд»: статус последнего прогона по каждому шагу.

Особые параметры:
  CRON_TIME (ЧЧ:ММ МСК) — при изменении время в cron-job.org правится само
  (нужен CRONJOB_API_KEY и CRONJOB_JOB_ID в ключах).
"""
import json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))
SETTINGS, DASH = "Настройки", "Дашборд"

# параметр -> комментарий (порядок = порядок строк при первом заполнении)
SEED = [
    ("BRANDS", "NATURI,4ME,HEALTH FORM,SUNSHINE,VEXOR,ORZAX,LOVE&DOVE", "Бренды и порядок прогона"),
    ("CRON_TIME", "07:30", "Время боевого запуска, МСК (правится само в cron-job.org)"),
    ("HISTORY_DAYS", "8", "Глубина истории для листа «Общее»"),
    ("TELEGRAM_CHAT_ID", "", "Служебный чат для алертов о сбоях"),
    ("NATURI_TG_CHATS", "", "Чаты отчёта NATURI (chat_id:топик через запятую)"),
    ("4ME_TG_CHATS", "", "Чаты отчёта 4ME"),
    ("HEALTHFORM_TG_CHATS", "", "Чаты отчёта Health Form"),
    ("SUNSHINE_TG_CHATS", "", "Чаты отчёта SUNSHINE"),
    ("VEXOR_TG_CHATS", "", "Чаты отчёта VEXOR"),
    ("ORZAX_TG_CHATS", "", "Чаты отчёта ORZAX"),
    ("LOVEDOVE_TG_CHATS", "", "Чаты отчёта LOVE&DOVE"),
    ("SVOD_TG_CHATS", "", "Куда слать сводку «Общая»"),
    ("NATURI_GSHEET_ID", "", "Таблица отчёта NATURI"),
    ("4ME_GSHEET_ID", "", "Таблица отчёта 4ME"),
    ("HEALTHFORM_GSHEET_ID", "", "Таблица отчёта Health Form"),
    ("SUNSHINE_GSHEET_ID", "", "Таблица отчёта SUNSHINE"),
    ("VEXOR_GSHEET_ID", "", "Таблица отчёта VEXOR"),
    ("ORZAX_GSHEET_ID", "", "Таблица отчёта ORZAX"),
    ("LOVEDOVE_GSHEET_ID", "", "Таблица отчёта LOVE&DOVE"),
    ("SVOD_GSHEET_ID", "", "Таблица свода «Общая»"),
    ("PRICES_GSHEET_ID", "", "Таблица аналитики цен"),
]

def _auth(sa_file):
    import jwt
    SA = json.load(open(sa_file)); now = int(time.time())
    a = jwt.encode({"iss": SA["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600},
        SA["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": a}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=body), timeout=30).read())["access_token"]

def _api(sheet_id, tok, path="", payload=None, method=None, tries=5):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    # 429/5xx и сетевые сбои у Google — транзиентные, ретраим с backoff
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < tries - 1:
                time.sleep(min(30, 3 * (2 ** attempt))); continue
            raise

def _ensure_sheets(sheet_id, tok):
    meta = _api(sheet_id, tok, "?fields=sheets.properties(sheetId,title)")
    have = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    reqs = []
    for i, name in enumerate((SETTINGS, DASH)):
        if name not in have:
            reqs.append({"addSheet": {"properties": {"title": name, "index": i}}})
    if reqs:
        r = _api(sheet_id, tok, ":batchUpdate", {"requests": reqs}, "POST")
        for rep in r["replies"]:
            p = rep["addSheet"]["properties"]; have[p["title"]] = p["sheetId"]
    return have

def load_settings(sa_file, K):
    """Читает «Настройки» из пункта управления; при первом запуске заполняет лист
    текущими значениями из K. Возвращает dict-оверрайды (может быть пустым)."""
    cid = K.get("CONTROL_GSHEET_ID", "")
    if not cid: return {}
    try:
        tok = _auth(sa_file)
        have = _ensure_sheets(cid, tok)
        q = urllib.parse.quote(f"'{SETTINGS}'")
        rows = _api(cid, tok, f"/values/{q}!A2:B200").get("values", [])
        if not rows:  # первый запуск — сеем текущие значения
            seeded = [[k, K.get(k, dflt), c] for k, dflt, c in SEED]
            _api(cid, tok, f"/values/{q}!A1?valueInputOption=RAW",
                 {"values": [["Параметр", "Значение", "Комментарий"]] + seeded}, "PUT")
            _api(cid, tok, ":batchUpdate", {"requests": [
                {"repeatCell": {"range": {"sheetId": have[SETTINGS], "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"backgroundColor": {"red": .12, "green": .3, "blue": .47},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
                {"updateDimensionProperties": {"range": {"sheetId": have[SETTINGS], "dimension": "COLUMNS",
                    "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 220}, "fields": "pixelSize"}},
                {"updateDimensionProperties": {"range": {"sheetId": have[SETTINGS], "dimension": "COLUMNS",
                    "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 420}, "fields": "pixelSize"}},
                {"updateDimensionProperties": {"range": {"sheetId": have[SETTINGS], "dimension": "COLUMNS",
                    "startIndex": 2, "endIndex": 3}, "properties": {"pixelSize": 420}, "fields": "pixelSize"}},
                {"updateSheetProperties": {"properties": {"sheetId": have[SETTINGS],
                    "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}}]}, "POST")
            print("Пункт управления: лист «Настройки» заполнен текущими значениями")
            return {}
        out = {}
        for r in rows:
            k = (r[0] if r else "").strip()
            v = (r[1] if len(r) > 1 else "").strip()
            if k and v: out[k] = v
        print(f"Пункт управления: настроек применено {len(out)}")
        return out
    except Exception as e:
        print(f"Пункт управления недоступен ({e}) — работаю по api_keys")
        return {}

def sync_cron(K):
    """CRON_TIME из настроек -> cron-job.org (если задан ключ API)."""
    want = K.get("CRON_TIME", "").strip()
    cj, jid = K.get("CRONJOB_API_KEY", ""), K.get("CRONJOB_JOB_ID", "")
    if not (want and cj and jid and ":" in want): return
    try:
        hh, mm = [int(x) for x in want.split(":", 1)]
        H = {"Authorization": "Bearer " + cj, "Content-Type": "application/json"}
        req = urllib.request.Request(f"https://api.cron-job.org/jobs/{jid}", headers=H)
        cur = json.loads(urllib.request.urlopen(req, timeout=30).read())["jobDetails"]["schedule"]
        if cur.get("hours") == [hh] and cur.get("minutes") == [mm]: return
        req = urllib.request.Request(f"https://api.cron-job.org/jobs/{jid}", method="PATCH",
            data=json.dumps({"job": {"schedule": {"timezone": "Europe/Moscow", "hours": [hh],
                "minutes": [mm], "mdays": [-1], "months": [-1], "wdays": [-1]}}}).encode(), headers=H)
        urllib.request.urlopen(req, timeout=30).read()
        print(f"Пункт управления: время крона изменено на {want} МСК")
    except Exception as e:
        print(f"Синхронизация крона не удалась: {e}")

def write_dashboard(sa_file, K, run_info, rows):
    """Перезаписывает «Дашборд»: шапка прогона + строки [шаг, сбор, таблица, TG, детали]."""
    cid = K.get("CONTROL_GSHEET_ID", "")
    if not cid: return
    try:
        tok = _auth(sa_file)
        have = _ensure_sheets(cid, tok)
        gid = have[DASH]
        q = urllib.parse.quote(f"'{DASH}'")
        now = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
        header = [[f"Последний прогон: {now} МСК — {run_info}"],
                  [],
                  ["Шаг", "Сбор данных", "Google-таблица", "Telegram", "Детали"]]
        _api(cid, tok, ":batchUpdate", {"requests": [
            {"updateCells": {"range": {"sheetId": gid}, "fields": "userEnteredValue"}}]}, "POST")
        _api(cid, tok, f"/values/{q}!A1?valueInputOption=RAW",
             {"values": header + rows}, "PUT")
        _api(cid, tok, ":batchUpdate", {"requests": [
            {"mergeCells": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": 5}, "mergeType": "MERGE_ALL"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": .12, "green": .3, "blue": .47},
                    "horizontalAlignment": "CENTER",
                    "textFormat": {"bold": True, "fontSize": 12,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
            {"repeatCell": {"range": {"sheetId": gid, "startRowIndex": 2, "endRowIndex": 3},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": .85, "green": .85, "blue": .85},
                    "textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"}},
            {"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 200}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 1, "endIndex": 4}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 4, "endIndex": 5}, "properties": {"pixelSize": 420}, "fields": "pixelSize"}},
            {"updateSheetProperties": {"properties": {"sheetId": gid,
                "gridProperties": {"frozenRowCount": 3}}, "fields": "gridProperties.frozenRowCount"}}]}, "POST")
        print("Пункт управления: дашборд обновлён")
    except Exception as e:
        print(f"Дашборд не обновлён: {e}")

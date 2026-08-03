#!/usr/bin/env python3
"""Локальный прогон ежедневного отчёта — замена облачного daily-report.yml.

Нужен, пока у аккаунта нет минут GitHub Actions (лимит выедается до 1-го числа).
Делает ровно то же, что workflow: собирает секреты в файлы у корня репо, гонит
run_all_ts.py, коммитит накопленную историю state/ и убирает секреты за собой.

Запуск:  python scripts/run_local.py [--skip-tg] [--brands "NATURI,4ME"] [--no-push]
Пути к ключам переопределяются: LOCAL_KEYS, LOCAL_KEYS_EXTRA, LOCAL_SA.
"""
import argparse, base64, os, shutil, subprocess, sys, datetime

# Консоль Windows по умолчанию cp1251: «×», «→» и прочее из вывода конвейера
# роняли бы сам драйвер (UnicodeEncodeError) и обрывали дочерний процесс.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.path.dirname(ROOT)                     # 21.orders-cloud
CS = os.path.dirname(WORK)                       # рабочая папка проектов

KEYS_MAIN = os.environ.get("LOCAL_KEYS", os.path.join(WORK, "api_keys.txt"))
KEYS_EXTRA = os.environ.get("LOCAL_KEYS_EXTRA", os.path.join(WORK, "api_keys_extra.txt"))
SA_SRC = os.environ.get("LOCAL_SA", os.path.join(CS, "29.dds-digitize", "dds-ganza-539c06976455.json"))

KEYS_OUT = os.path.join(ROOT, "api_keys.txt")
SA_OUT = os.path.join(ROOT, "google_sa.json")
MERGED = os.path.join(ROOT, "api_keys_merged.txt")
LOGDIR = os.path.join(ROOT, "logs")


def git(*args, token=None, check=False):
    """git в репо; при наличии токена ходит по HTTP без интерактивного логина."""
    cmd = ["git", "-C", ROOT]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd += ["-c", "credential.helper=", "-c", f"http.extraheader=AUTHORIZATION: basic {basic}"]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(cmd + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    if out.strip():
        print(f"git {args[0]}: {out.strip()[:400]}")
    if check and r.returncode:
        raise SystemExit(f"git {args[0]} упал")
    return r.returncode == 0


def find_token():
    """Токен для push: сначала gh CLI, потом реестр github_keys.txt."""
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    path = os.path.join(WORK, "github_keys.txt")
    try:
        for line in open(path, encoding="utf-8"):
            if line.lower().startswith("github classic:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def write_secrets():
    """Тот же порядок, что в workflow: основной реестр + extra в конец (последняя строка побеждает)."""
    main = open(KEYS_MAIN, encoding="utf-8").read()
    extra = open(KEYS_EXTRA, encoding="utf-8").read()
    with open(KEYS_OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(main.rstrip("\n") + "\n" + extra.rstrip("\n") + "\n")
    shutil.copyfile(SA_SRC, SA_OUT)


def clean_secrets():
    for p in (KEYS_OUT, SA_OUT, MERGED):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tg", action="store_true", help="собрать данные без отправки в TG")
    ap.add_argument("--brands", default="", help="бренды через запятую (пусто = как в пункте управления)")
    ap.add_argument("--no-push", action="store_true", help="не коммитить и не пушить историю")
    a = ap.parse_args()

    token = find_token()
    if not a.no_push:
        git("pull", "--rebase", "origin", "main", token=token)

    os.makedirs(LOGDIR, exist_ok=True)
    log = os.path.join(LOGDIR, f"local_{datetime.date.today():%Y-%m-%d}.log")

    env = dict(os.environ, TIME_BUDGET="86400", HISTORY_DAYS="8", PYTHONIOENCODING="utf-8")
    if a.skip_tg:
        env["SKIP_TG"] = "1"
    if a.brands:
        env["BRANDS"] = a.brands

    write_secrets()
    try:
        with open(log, "a", encoding="utf-8") as lf:
            lf.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} локальный прогон =====\n")
            lf.flush()
            p = subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "run_all_ts.py")],
                                 cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace")
            for line in p.stdout:
                sys.stdout.write(line)
                lf.write(line)
                lf.flush()
            rc = p.wait()
    finally:
        clean_secrets()

    if not a.no_push:
        git("add", "state/", token=token)
        if not git("diff", "--cached", "--quiet", token=token):
            git("commit", "-m", f"история за {datetime.date.today():%Y-%m-%d} (локальный прогон)", token=token)
            git("push", "origin", "main", token=token)

    print(f"код выхода конвейера: {rc}; лог: {log}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

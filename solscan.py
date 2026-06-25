#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solscan.py — удобный CLI к Solscan Pro API (free-уровень, префикс /playground/).

Токен берётся из переменной окружения SOLSCAN_TOKEN. Если она не задана —
скрипт завершится с подсказкой. Получить бесплатный ключ: https://pro-api.solscan.io

Примеры:
    python solscan.py transfers So11111111111111111111111111111111111111112
    python solscan.py defi    <address> -n 20
    python solscan.py token   EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    python solscan.py ttransfers <token_mint>
    python solscan.py tx      <signature>
    python solscan.py raw account/transfer address=<addr> page_size=20

Везде можно добавить --json, чтобы получить сырой JSON.
"""
import os
import sys
import csv
import json
import time
import argparse
import datetime as dt

# На Windows консоль часто cp1252 — принудительно переключаем вывод на UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import requests
except ImportError:
    sys.exit("Нужен пакет requests:  pip install requests")

BASE = "https://pro-api.solscan.io/playground"

# Токен Solscan Pro API. Задаётся ТОЛЬКО через переменную окружения SOLSCAN_TOKEN.
# В репозитории намеренно нет встроенного ключа — не коммитьте свой токен.
TOKEN = os.environ.get("SOLSCAN_TOKEN", "")
if not TOKEN:
    sys.exit(
        "Не задан токен Solscan. Установите переменную окружения SOLSCAN_TOKEN:\n"
        "  Windows (PowerShell):  $env:SOLSCAN_TOKEN=\"ваш_токен\"\n"
        "  Linux/macOS:           export SOLSCAN_TOKEN=ваш_токен\n"
        "Бесплатный ключ: https://pro-api.solscan.io"
    )

# page_size, который принимает API
VALID_PAGE_SIZES = [10, 20, 30, 40, 60, 100]


def _clamp_page_size(n):
    """Подбирает ближайший допустимый page_size >= n (или максимум 100)."""
    for v in VALID_PAGE_SIZES:
        if n <= v:
            return v
    return 100


def call(endpoint, params=None):
    """Сырой GET-запрос к API. Возвращает разобранный JSON или падает с понятной ошибкой."""
    url = f"{BASE}/{endpoint.lstrip('/')}"
    r = requests.get(url, headers={"token": TOKEN}, params=params or {}, timeout=30)
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"[{r.status_code}] не-JSON ответ: {r.text[:200]}")
    if not data.get("success", False):
        err = data.get("errors", {})
        sys.exit(f"[{r.status_code}] Ошибка API {err.get('code','')}: {err.get('message','')}")
    return data.get("data")


def _ts(unix):
    if not unix:
        return ""
    return dt.datetime.fromtimestamp(int(unix), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _short(s, head=6, tail=6):
    s = str(s or "")
    return s if len(s) <= head + tail + 1 else f"{s[:head]}…{s[-tail:]}"


def _amount(raw, decimals):
    try:
        return int(raw) / (10 ** int(decimals or 0))
    except (TypeError, ValueError):
        return raw


def export_csv(rows, path):
    """Пишет список словарей в CSV. Колонки = объединение всех ключей (порядок первой строки + новые в конце)."""
    rows = rows or []
    if not rows:
        print("Нет данных для экспорта."); return
    cols = list(rows[0].keys())
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig — чтобы Excel видел кириллицу
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"Сохранено {len(rows)} строк → {path}")


def _maybe_csv(data, args):
    """Если задан --csv — пишет и возвращает True (значит дальше печатать таблицу не надо)."""
    if getattr(args, "csv", None):
        export_csv(data, args.csv)
        return True
    return False


# ---------- команды ----------

def cmd_transfers(args):
    data = call("account/transfer", {
        "address": args.address,
        "page": args.page,
        "page_size": _clamp_page_size(args.n),
        "sort_by": "block_time",
        "sort_order": "desc",
    })
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False)); return
    if _maybe_csv(data, args):
        return
    print(f"Переводы {_short(args.address)} (последние {len(data)}):\n")
    for t in data[:args.n]:
        amt = _amount(t.get("amount"), t.get("token_decimals"))
        flow = "→" if t.get("flow") == "out" else "←"
        print(f"  {_ts(t.get('block_time'))}  {flow} {amt:>18,.4f}  "
              f"{_short(t.get('token_address'))}  "
              f"from {_short(t.get('from_address'))} to {_short(t.get('to_address'))}")


def cmd_defi(args):
    data = call("account/defi/activities", {
        "address": args.address,
        "page": args.page,
        "page_size": _clamp_page_size(args.n),
        "sort_by": "block_time",
        "sort_order": "desc",
    })
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False)); return
    if _maybe_csv(data, args):
        return
    print(f"DeFi-активность {_short(args.address)} (последние {len(data)}):\n")
    for a in data[:args.n]:
        print(f"  {_ts(a.get('block_time'))}  {a.get('activity_type','')}  "
              f"{_short(a.get('trans_id'))}")


def cmd_token(args):
    d = call("token/meta", {"address": args.address})
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False)); return
    print(f"Токен: {d.get('name','?')} ({d.get('symbol','?')})")
    print(f"  mint:      {d.get('address')}")
    print(f"  decimals:  {d.get('decimals')}")
    print(f"  supply:    {d.get('supply')}")
    if d.get("price") is not None:
        print(f"  price:     ${d.get('price')}")
    if d.get("market_cap") is not None:
        print(f"  mcap:      ${d.get('market_cap'):,}" if isinstance(d.get('market_cap'), (int, float)) else f"  mcap:      {d.get('market_cap')}")
    if d.get("holder") is not None:
        print(f"  holders:   {d.get('holder')}")


def cmd_ttransfers(args):
    data = call("token/transfer", {
        "address": args.address,
        "page": args.page,
        "page_size": _clamp_page_size(args.n),
        "sort_by": "block_time",
        "sort_order": "desc",
    })
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False)); return
    if _maybe_csv(data, args):
        return
    print(f"Переводы токена {_short(args.address)} (последние {len(data)}):\n")
    for t in data[:args.n]:
        amt = _amount(t.get("amount"), t.get("token_decimals"))
        print(f"  {_ts(t.get('block_time'))}  {amt:>18,.4f}  "
              f"from {_short(t.get('from_address'))} to {_short(t.get('to_address'))}")


def cmd_tx(args):
    d = call("transaction/actions", {"tx": args.signature})
    print(json.dumps(d, indent=2, ensure_ascii=False))


def notify_sound():
    """Звуковой сигнал. На Windows — winsound, иначе — терминальный bell."""
    try:
        import winsound
        winsound.Beep(880, 180)
        winsound.Beep(1175, 180)
    except Exception:
        try:
            sys.stdout.write("\a"); sys.stdout.flush()
        except Exception:
            pass


def notify_toast(title, message):
    """Всплывающее уведомление Windows (balloon). Неблокирующее, тихо игнорирует ошибки."""
    try:
        import subprocess
        ps = (
            "[reflection.assembly]::loadwithpartialname('System.Windows.Forms')|Out-Null;"
            "[reflection.assembly]::loadwithpartialname('System.Drawing')|Out-Null;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.BalloonTipTitle=$env:NTITLE;$n.BalloonTipText=$env:NMSG;"
            "$n.Visible=$true;$n.ShowBalloonTip(5000);Start-Sleep -Seconds 6;$n.Dispose()"
        )
        env = dict(os.environ, NTITLE=str(title), NMSG=str(message))
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def call_safe(endpoint, params):
    """Как call(), но вместо sys.exit возвращает (data, None) или (None, 'текст ошибки')."""
    url = f"{BASE}/{endpoint.lstrip('/')}"
    try:
        r = requests.get(url, headers={"token": TOKEN}, params=params or {}, timeout=30)
    except requests.RequestException as e:
        return None, f"сеть: {e}"
    try:
        data = r.json()
    except ValueError:
        return None, f"[{r.status_code}] не-JSON"
    if not data.get("success", False):
        err = data.get("errors", {})
        return None, f"[{r.status_code}] {err.get('code','')} {err.get('message','')}".strip()
    return data.get("data"), None


def cmd_watch(args):
    """Мониторинг кошелька: каждые N секунд опрашивает переводы и печатает только новые.
    Опционально дозаписывает новые переводы в CSV (--csv). Ctrl+C для выхода."""
    src = "account/defi/activities" if args.defi else "account/transfer"
    kind = "DeFi-активность" if args.defi else "переводы"
    print(f"Мониторю {kind} {_short(args.address)} каждые {args.interval}с. Ctrl+C — стоп.\n")

    seen = set()
    first = True
    backoff = 0  # текущая дополнительная пауза при ошибках (экспоненциальная)
    BACKOFF_MAX = 300  # потолок паузы, секунд
    # Если пишем CSV — заголовок поставим при первой реальной строке.
    csv_started = os.path.exists(args.csv) if args.csv else False

    try:
        while True:
            data, err = call_safe(src, {
                "address": args.address, "page": 1, "page_size": 40,
                "sort_by": "block_time", "sort_order": "desc",
            })
            if err is not None:
                backoff = min(backoff * 2 if backoff else args.interval, BACKOFF_MAX)
                print(f"  [предупреждение] {err}; повтор через {args.interval + backoff}с")
                time.sleep(args.interval + backoff)
                continue
            backoff = 0  # успех — сбрасываем паузу
            data = data or []

            # На первом проходе только запоминаем текущее состояние (не спамим историей).
            new = [r for r in data if r.get("trans_id") not in seen]
            for r in data:
                seen.add(r.get("trans_id"))

            if first:
                first = False
                print(f"  базовое состояние: {len(data)} последних записей запомнено, жду новые…")
            elif new:
                for r in reversed(new):  # от старых к новым
                    if args.defi:
                        line = f"  + {_ts(r.get('block_time'))}  {r.get('activity_type','')}  {_short(r.get('trans_id'))}"
                    else:
                        amt = _amount(r.get("amount"), r.get("token_decimals"))
                        flow = "→ OUT" if r.get("flow") == "out" else "← IN "
                        line = (f"  + {_ts(r.get('block_time'))}  {flow} {amt:>16,.4f}  "
                                f"{_short(r.get('token_address'))}  "
                                f"from {_short(r.get('from_address'))} to {_short(r.get('to_address'))}")
                    print(line)
                if args.csv:
                    mode = "a" if csv_started else "w"
                    with open(args.csv, mode, newline="", encoding="utf-8-sig") as f:
                        cols = list(new[0].keys())
                        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                        if not csv_started:
                            w.writeheader(); csv_started = True
                        for r in reversed(new):
                            w.writerow({k: r.get(k, "") for k in cols})
                    print(f"    (+{len(new)} дозаписано в {args.csv})")

                # Уведомления о новых событиях.
                if args.sound:
                    notify_sound()
                if args.notify:
                    latest = new[0]
                    if args.defi:
                        msg = f"{len(new)} новых: {latest.get('activity_type','')}"
                    else:
                        amt = _amount(latest.get("amount"), latest.get("token_decimals"))
                        direction = "OUT" if latest.get("flow") == "out" else "IN"
                        msg = f"{len(new)} новых. {direction} {amt:,.4f}"
                    notify_toast(f"Solscan: {_short(args.address)}", msg)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nОстановлено.")


def cmd_raw(args):
    params = {}
    for kv in args.params:
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    d = call(args.endpoint, params)
    print(json.dumps(d, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="CLI к Solscan Pro API (free / playground)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("-n", type=int, default=10, help="сколько записей (по умолч. 10)")
        sp.add_argument("--page", type=int, default=1, help="страница")
        sp.add_argument("--json", action="store_true", help="вывести сырой JSON")
        sp.add_argument("--csv", metavar="FILE", help="сохранить результат в CSV-файл")

    sp = sub.add_parser("transfers", help="переводы по адресу кошелька"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_transfers)
    sp = sub.add_parser("defi", help="DeFi-активность адреса"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_defi)
    sp = sub.add_parser("token", help="метаданные токена"); sp.add_argument("address"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_token)
    sp = sub.add_parser("ttransfers", help="переводы по mint токена"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_ttransfers)
    sp = sub.add_parser("tx", help="разбор транзакции по сигнатуре"); sp.add_argument("signature"); sp.set_defaults(func=cmd_tx)
    sp = sub.add_parser("watch", help="мониторинг кошелька в реальном времени")
    sp.add_argument("address")
    sp.add_argument("--interval", type=int, default=30, help="опрос каждые N секунд (по умолч. 30)")
    sp.add_argument("--defi", action="store_true", help="следить за DeFi-активностью, а не переводами")
    sp.add_argument("--csv", metavar="FILE", help="дозаписывать новые события в CSV")
    sp.add_argument("--sound", action="store_true", help="звуковой сигнал при новом событии")
    sp.add_argument("--notify", action="store_true", help="всплывающее уведомление Windows при новом событии")
    sp.set_defaults(func=cmd_watch)
    sp = sub.add_parser("raw", help="произвольный вызов: raw <endpoint> key=val ..."); sp.add_argument("endpoint"); sp.add_argument("params", nargs="*"); sp.set_defaults(func=cmd_raw)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

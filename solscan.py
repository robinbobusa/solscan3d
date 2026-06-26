#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solscan.py — a handy CLI for the Solscan Pro API (free tier, /playground/ prefix).

The token is read from the SOLSCAN_TOKEN environment variable. If it is not set, the
script exits with a hint. Get a free key: https://pro-api.solscan.io

Examples:
    python solscan.py transfers So11111111111111111111111111111111111111112
    python solscan.py defi    <address> -n 20
    python solscan.py token   EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    python solscan.py ttransfers <token_mint>
    python solscan.py tx      <signature>
    python solscan.py raw account/transfer address=<addr> page_size=20

Add --json to any command to get the raw JSON.
"""
import os
import sys
import csv
import json
import time
import argparse
import datetime as dt

# On Windows the console is often cp1252 — force the output streams to UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import requests
except ImportError:
    sys.exit("The requests package is required:  pip install requests")

BASE = "https://pro-api.solscan.io/playground"

# Solscan Pro API token. Provided ONLY through the SOLSCAN_TOKEN environment variable.
# There is intentionally no embedded key in this repo — do not commit your token.
TOKEN = os.environ.get("SOLSCAN_TOKEN", "")
if not TOKEN:
    sys.exit(
        "SOLSCAN_TOKEN is not set. Define the SOLSCAN_TOKEN environment variable:\n"
        "  Windows (PowerShell):  $env:SOLSCAN_TOKEN=\"your_token\"\n"
        "  Linux/macOS:           export SOLSCAN_TOKEN=your_token\n"
        "Free key: https://pro-api.solscan.io"
    )

# page_size values the API accepts
VALID_PAGE_SIZES = [10, 20, 30, 40, 60, 100]


def _clamp_page_size(n):
    """Pick the smallest valid page_size >= n (or 100 at most)."""
    for v in VALID_PAGE_SIZES:
        if n <= v:
            return v
    return 100


def call(endpoint, params=None):
    """Raw GET request to the API. Returns parsed JSON or exits with a clear error."""
    url = f"{BASE}/{endpoint.lstrip('/')}"
    r = requests.get(url, headers={"token": TOKEN}, params=params or {}, timeout=30)
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"[{r.status_code}] non-JSON response: {r.text[:200]}")
    if not data.get("success", False):
        err = data.get("errors", {})
        sys.exit(f"[{r.status_code}] API error {err.get('code','')}: {err.get('message','')}")
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
    """Write a list of dicts to CSV. Columns = union of all keys (first row's order, new keys appended)."""
    rows = rows or []
    if not rows:
        print("No data to export."); return
    cols = list(rows[0].keys())
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig so Excel reads Unicode
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"Saved {len(rows)} rows → {path}")


def _maybe_csv(data, args):
    """If --csv is set, write the file and return True (so the table isn't printed afterwards)."""
    if getattr(args, "csv", None):
        export_csv(data, args.csv)
        return True
    return False


# ---------- commands ----------

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
    print(f"Transfers for {_short(args.address)} (latest {len(data)}):\n")
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
    print(f"DeFi activity for {_short(args.address)} (latest {len(data)}):\n")
    for a in data[:args.n]:
        print(f"  {_ts(a.get('block_time'))}  {a.get('activity_type','')}  "
              f"{_short(a.get('trans_id'))}")


def cmd_token(args):
    d = call("token/meta", {"address": args.address})
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False)); return
    print(f"Token: {d.get('name','?')} ({d.get('symbol','?')})")
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
    print(f"Token transfers for {_short(args.address)} (latest {len(data)}):\n")
    for t in data[:args.n]:
        amt = _amount(t.get("amount"), t.get("token_decimals"))
        print(f"  {_ts(t.get('block_time'))}  {amt:>18,.4f}  "
              f"from {_short(t.get('from_address'))} to {_short(t.get('to_address'))}")


def cmd_tx(args):
    d = call("transaction/actions", {"tx": args.signature})
    print(json.dumps(d, indent=2, ensure_ascii=False))


def notify_sound():
    """Audible signal. On Windows uses winsound, otherwise the terminal bell."""
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
    """Windows balloon notification. Non-blocking, silently ignores errors."""
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
    """Like call(), but instead of sys.exit returns (data, None) or (None, 'error text')."""
    url = f"{BASE}/{endpoint.lstrip('/')}"
    try:
        r = requests.get(url, headers={"token": TOKEN}, params=params or {}, timeout=30)
    except requests.RequestException as e:
        return None, f"network: {e}"
    try:
        data = r.json()
    except ValueError:
        return None, f"[{r.status_code}] non-JSON"
    if not data.get("success", False):
        err = data.get("errors", {})
        return None, f"[{r.status_code}] {err.get('code','')} {err.get('message','')}".strip()
    return data.get("data"), None


def cmd_watch(args):
    """Wallet monitor: every N seconds polls transfers and prints only the new ones.
    Optionally appends new transfers to CSV (--csv). Ctrl+C to exit."""
    src = "account/defi/activities" if args.defi else "account/transfer"
    kind = "DeFi activity" if args.defi else "transfers"
    print(f"Monitoring {kind} for {_short(args.address)} every {args.interval}s. Ctrl+C to stop.\n")

    seen = set()
    first = True
    backoff = 0  # current extra pause on errors (exponential)
    BACKOFF_MAX = 300  # pause ceiling, seconds
    # If writing CSV, the header is added on the first real row.
    csv_started = os.path.exists(args.csv) if args.csv else False

    try:
        while True:
            data, err = call_safe(src, {
                "address": args.address, "page": 1, "page_size": 40,
                "sort_by": "block_time", "sort_order": "desc",
            })
            if err is not None:
                backoff = min(backoff * 2 if backoff else args.interval, BACKOFF_MAX)
                print(f"  [warning] {err}; retrying in {args.interval + backoff}s")
                time.sleep(args.interval + backoff)
                continue
            backoff = 0  # success — reset the pause
            data = data or []

            # On the first pass just record the current state (don't spam with history).
            new = [r for r in data if r.get("trans_id") not in seen]
            for r in data:
                seen.add(r.get("trans_id"))

            if first:
                first = False
                print(f"  baseline: remembered {len(data)} latest records, waiting for new ones…")
            elif new:
                for r in reversed(new):  # oldest to newest
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
                    print(f"    (+{len(new)} appended to {args.csv})")

                # Notifications about new events.
                if args.sound:
                    notify_sound()
                if args.notify:
                    latest = new[0]
                    if args.defi:
                        msg = f"{len(new)} new: {latest.get('activity_type','')}"
                    else:
                        amt = _amount(latest.get("amount"), latest.get("token_decimals"))
                        direction = "OUT" if latest.get("flow") == "out" else "IN"
                        msg = f"{len(new)} new. {direction} {amt:,.4f}"
                    notify_toast(f"Solscan: {_short(args.address)}", msg)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_raw(args):
    params = {}
    for kv in args.params:
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    d = call(args.endpoint, params)
    print(json.dumps(d, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="CLI for the Solscan Pro API (free / playground)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("-n", type=int, default=10, help="how many records (default 10)")
        sp.add_argument("--page", type=int, default=1, help="page")
        sp.add_argument("--json", action="store_true", help="print raw JSON")
        sp.add_argument("--csv", metavar="FILE", help="save the result to a CSV file")

    sp = sub.add_parser("transfers", help="transfers for a wallet address"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_transfers)
    sp = sub.add_parser("defi", help="DeFi activity for an address"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_defi)
    sp = sub.add_parser("token", help="token metadata"); sp.add_argument("address"); sp.add_argument("--json", action="store_true"); sp.set_defaults(func=cmd_token)
    sp = sub.add_parser("ttransfers", help="transfers by token mint"); sp.add_argument("address"); add_common(sp); sp.set_defaults(func=cmd_ttransfers)
    sp = sub.add_parser("tx", help="parse a transaction by signature"); sp.add_argument("signature"); sp.set_defaults(func=cmd_tx)
    sp = sub.add_parser("watch", help="real-time wallet monitoring")
    sp.add_argument("address")
    sp.add_argument("--interval", type=int, default=30, help="poll every N seconds (default 30)")
    sp.add_argument("--defi", action="store_true", help="watch DeFi activity instead of transfers")
    sp.add_argument("--csv", metavar="FILE", help="append new events to CSV")
    sp.add_argument("--sound", action="store_true", help="audible signal on a new event")
    sp.add_argument("--notify", action="store_true", help="Windows toast notification on a new event")
    sp.set_defaults(func=cmd_watch)
    sp = sub.add_parser("raw", help="arbitrary call: raw <endpoint> key=val ..."); sp.add_argument("endpoint"); sp.add_argument("params", nargs="*"); sp.set_defaults(func=cmd_raw)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

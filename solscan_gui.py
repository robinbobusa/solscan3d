#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solscan_gui.py — local server + 3D GUI for Solscan.

Run:
    python solscan_gui.py
A browser opens with an iPhone-style form (electric gray): enter Solana
addresses, keep a list, and build an interactive 3D graph of relationships
(who sent what to whom) with smooth curved links animating flow direction.

The token is taken from solscan.py (the SOLSCAN_TOKEN env var) and never reaches
the browser — all requests to Solscan are made by this Python process.
"""
import os
import sys
import json
import time
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import solscan  # reuse call_safe / _clamp_page_size / TOKEN

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "solscan_ui.html")
HOST = "127.0.0.1"
PORT = 8765


def build_graph(addresses, limit):
    """Build a graph from transfers: nodes = addresses, edges = aggregated from→to flows."""
    monitored = {a for a in addresses}
    nodes = {}
    links = {}
    errors = []

    def node(a):
        if a not in nodes:
            nodes[a] = {
                "id": a,
                "label": (a[:4] + "…" + a[-4:]) if len(a) > 9 else a,
                "vol": 0.0, "inflow": 0.0, "outflow": 0.0,
                "count": 0, "monitored": a in monitored,
            }
        return nodes[a]

    for addr in addresses:
        data = err = None
        for attempt in range(2):  # one auto-retry on 429
            data, err = solscan.call_safe("account/transfer", {
                "address": addr, "page": 1,
                "page_size": solscan._clamp_page_size(limit),
                "sort_by": "block_time", "sort_order": "desc",
            })
            if err and "429" in err and attempt == 0:
                time.sleep(2)
                continue
            break
        if err is not None:
            errors.append(f"{addr[:6]}…{addr[-4:]}: {err}")
            continue
        for t in (data or [])[:limit]:
            frm, to = t.get("from_address"), t.get("to_address")
            if not frm or not to:
                continue
            try:
                val = float(t.get("value") or 0)
                if not val:
                    val = int(t.get("amount", 0)) / (10 ** int(t.get("token_decimals") or 0))
            except (TypeError, ValueError):
                val = 0.0
            nf, nt = node(frm), node(to)
            nf["vol"] += val; nt["vol"] += val
            nf["outflow"] += val; nt["inflow"] += val
            nf["count"] += 1; nt["count"] += 1
            tok = t.get("token_address") or ""
            key = f"{frm}|{to}|{tok}"
            if key not in links:
                links[key] = {"source": frm, "target": to, "token": tok,
                              "token_label": (tok[:4] + "…" + tok[-4:]) if len(tok) > 9 else tok,
                              "value": 0.0, "count": 0, "time": t.get("time")}
            links[key]["value"] += val
            links[key]["count"] += 1

    return {"nodes": list(nodes.values()), "links": list(links.values()),
            "errors": errors, "monitored": list(monitored)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        # Cache the libraries (fast reloads), but not HTML/API.
        self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # so it also works from file://
        self.end_headers()
        try:
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            try:
                with open(HTML_PATH, encoding="utf-8") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, json.dumps({"error": "solscan_ui.html not found"}))
            return

        # Local libraries (three / spritetext / force-graph) — no CDN.
        if u.path.startswith("/lib/"):
            safe = os.path.basename(u.path)  # no directory traversal
            fp = os.path.join(HERE, "lib", safe)
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    self._send(200, f.read(), "application/javascript; charset=utf-8", cache=True)
            else:
                self._send(404, json.dumps({"error": "lib not found"}))
            return

        if u.path == "/api/graph":
            raw = q.get("addresses", [""])[0]
            addrs = [a.strip() for a in raw.split(",") if a.strip()]
            try:
                limit = max(1, min(100, int(q.get("limit", ["40"])[0])))
            except ValueError:
                limit = 40
            if not addrs:
                self._send(400, json.dumps({"error": "no addresses"}))
                return
            try:
                g = build_graph(addrs, limit)
            except Exception as e:  # noqa
                self._send(500, json.dumps({"error": str(e)}))
                return
            self._send(200, json.dumps(g, ensure_ascii=False))
            return

        self._send(404, json.dumps({"error": "not found"}))


def main():
    if not os.path.exists(HTML_PATH):
        sys.exit(f"Interface file missing: {HTML_PATH}")

    url = f"http://{HOST}:{PORT}/"
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        # Port busy — almost certainly the server is already running in another window.
        print(f"Port {PORT} is busy — the server seems to be already running.", flush=True)
        print(f"Just open it in your browser:  {url}", flush=True)
        webbrowser.open(url)
        return

    print("=" * 52, flush=True)
    print(f"  Solscan 3D GUI is running", flush=True)
    print(f"  Open in your browser:  {url}", flush=True)
    print(f"  (the token stays on the server, never goes to the browser)", flush=True)
    print(f"  Stop with Ctrl+C", flush=True)
    print("=" * 52, flush=True)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()

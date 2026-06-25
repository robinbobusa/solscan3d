#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solscan_gui.py — локальный сервер + 3D-GUI для Solscan.

Запуск:
    python solscan_gui.py
Откроется браузер с формой в стиле iPhone (электрический серый):
вводишь Solana-адреса, ведёшь список, строишь интерактивный 3D-граф связей
(кто кому что отправлял) гибкими изогнутыми линиями с анимацией направления потока.

Токен берётся из solscan.py (env SOLSCAN_TOKEN или встроенный fallback) и НЕ попадает
в браузер — все запросы к Solscan делает этот Python-процесс.
"""
import os
import sys
import json
import time
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import solscan  # переиспользуем call_safe / _clamp_page_size / TOKEN

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "solscan_ui.html")
HOST = "127.0.0.1"
PORT = 8765


def build_graph(addresses, limit):
    """Строит граф из переводов: узлы = адреса, рёбра = агрегированные потоки from→to."""
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
        for attempt in range(2):  # один авто-повтор при 429
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
    def log_message(self, *a):  # тишина в консоли
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        # Библиотеки кэшируем (быстрый перезагруз), HTML/API — нет.
        self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # чтобы работало и из file://
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
                self._send(500, json.dumps({"error": "solscan_ui.html не найден"}))
            return

        # Локальные библиотеки (three / spritetext / force-graph) — без CDN.
        if u.path.startswith("/lib/"):
            safe = os.path.basename(u.path)  # без выхода из каталога
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
                self._send(400, json.dumps({"error": "нет адресов"}))
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
        sys.exit(f"Нет файла интерфейса: {HTML_PATH}")

    url = f"http://{HOST}:{PORT}/"
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        # Порт занят — почти наверняка сервер уже запущен в другом окне.
        print(f"Порт {PORT} занят — похоже, сервер уже работает.", flush=True)
        print(f"Просто открой в браузере:  {url}", flush=True)
        webbrowser.open(url)
        return

    print("=" * 52, flush=True)
    print(f"  Solscan 3D GUI запущен", flush=True)
    print(f"  Открой в браузере:  {url}", flush=True)
    print(f"  (токен остаётся на сервере, в браузер не уходит)", flush=True)
    print(f"  Остановить — Ctrl+C", flush=True)
    print("=" * 52, flush=True)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
        httpd.shutdown()


if __name__ == "__main__":
    main()

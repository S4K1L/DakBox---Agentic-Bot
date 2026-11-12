"""Serve the stand-in websites on local ports so the import can be tried in the app.

  DAKBOX_ALLOW_PRIVATE_FETCH=1 .venv/bin/uvicorn app.main:app --port 4001      (lets Dakbox open local addresses: never in production)
  .venv/bin/python -m tools.fake_site_server

Then in Dakbox: Connections, Store, and use  localhost:4012 (Shopify), localhost:4013 (WooCommerce), localhost:4014 (ordinary site).
Its images are served from the same ports, which also shows that product photos on another website load in the app.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from tools.fake_site import FakeWeb

PORTS = {4012: "shopify.test", 4013: "woo.test", 4014: "pages.test"}
web = FakeWeb(origin=lambda host: f"http://localhost:{next(p for p, h in PORTS.items() if h == host)}")


def make(host: str):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            r = web.handler(httpx.Request("GET", f"http://{host}{self.path}"))
            self.send_response(r.status_code)
            for k, v in r.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "content-encoding"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(r.content)))
            self.end_headers()
            self.wfile.write(r.content)

        def log_message(self, *a):
            pass
    return H


if __name__ == "__main__":
    servers = [ThreadingHTTPServer(("127.0.0.1", p), make(h)) for p, h in PORTS.items()]
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print("Stand-in websites: Shopify :4012, WooCommerce :4013, ordinary site :4014")
    servers[0].serve_forever()

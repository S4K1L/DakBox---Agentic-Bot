"""Stand-in websites for the product import: a Shopify store, a WooCommerce store, an ordinary site with a sitemap and
schema.org product pages, and a few awkward ones. Shaped like the real thing (public /products.json, the WooCommerce Store API,
JSON-LD on product pages) but written from public documentation, never checked against a real shop.

Tests use FakeWeb.handler as an httpx transport. fake_site_server.py serves the same sites on local ports.
"""
from __future__ import annotations

import json
from typing import Callable

import httpx

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" fill="{bg}"/><text x="200" y="215" font-size="34" text-anchor="middle" font-family="sans-serif" fill="#223">{label}</text></svg>'
COLORS = {"tent": "#f6d7b0", "bottle": "#c3d5f5", "boot": "#e2d4be", "jacket": "#cadfd0", "mug": "#e6e9f4"}


class FakeWeb:
    def __init__(self, origin: Callable[[str], str] = lambda host: f"https://{host}"):
        self.origin = origin
        self.requests: list[str] = []
        self.shopify = [
            {"id": 11, "title": "Ridgeline Tent 2P", "handle": "ridgeline-tent-2p", "body_html": "<p>Two-person <b>tent</b>, 3 seasons.</p><script>alert(1)</script>",
             "images": [{"src": "{img}/tent.svg"}], "variants": [
                 {"id": 111, "title": "Green", "price": "12500.00", "sku": "RT-GRN", "available": True},
                 {"id": 112, "title": "Orange", "price": "12500.00", "sku": "RT-ORG", "available": False}]},
            {"id": 12, "title": "Trail Bottle 2L", "handle": "trail-bottle-2l", "body_html": "Steel bottle", "images": [{"src": "{img}/bottle.svg"}],
             "variants": [{"id": 121, "title": "Default Title", "price": "1450.00", "sku": "", "available": True}]},
            {"id": 13, "title": "Free sample", "handle": "free-sample", "body_html": "", "images": [], "variants": [{"id": 131, "title": "Default Title", "price": "0.00", "sku": "FREE", "available": True}]},
        ]
        self.shopify_currency = "BDT"
        self.woo = [
            {"id": 21, "name": "Summit Jacket &amp; Shell", "sku": "SJ-1", "type": "simple", "permalink": "{o}/product/summit-jacket/", "short_description": "<p>Waterproof</p>",
             "description": "", "prices": {"price": "950000", "currency_code": "BDT", "currency_minor_unit": 2}, "images": [{"src": "{img}/jacket.svg"}], "is_in_stock": True, "low_stock_remaining": 4},
            {"id": 22, "name": "Camp Mug", "sku": "", "type": "variable", "permalink": "{o}/product/camp-mug/", "short_description": "", "description": "Enamel mug",
             "prices": {"price": "45000", "currency_code": "BDT", "currency_minor_unit": 2}, "images": [{"src": "{img}/mug.svg"}], "is_in_stock": False, "low_stock_remaining": None},
        ]
        # an ordinary site: path -> html
        self.pages: dict[str, str] = {}
        self._build_pages()

    # -- builders
    def _build_pages(self):
        o = self.origin("pages.test")
        img = f"{o}/img"
        ld = lambda d: f'<script type="application/ld+json">{json.dumps(d)}</script>'
        self.pages = {
            "/": '<html><head><title>Pages Shop</title></head><body><a href="/products/trail-boot">Boot</a> <a href="/about">About</a></body></html>',
            "/products/trail-boot": f'<html><head><link rel="canonical" href="{o}/products/trail-boot">{ld({"@context": "https://schema.org", "@type": "Product", "name": "Trail Boot", "sku": "TB-9", "description": "Leather boot", "image": [f"{img}/boot.svg"], "offers": {"@type": "Offer", "price": "6,990.00", "priceCurrency": "BDT", "availability": "https://schema.org/InStock"}})}</head><body>x</body></html>',
            "/products/rain-jacket": f'<html><head>{ld({"@graph": [{"@type": "WebPage"}, {"@type": ["Product"], "name": "Rain Jacket", "image": "/img/jacket.svg", "offers": [{"@type": "Offer", "price": 4200, "priceCurrency": "BDT", "availability": "OutOfStock"}]}]})}</head></html>',
            "/products/og-only": f'<html><head><meta property="og:title" content="OG Lantern"><meta property="og:image" content="{img}/mug.svg"><meta property="product:price:amount" content="990"><meta property="product:price:currency" content="BDT"></head></html>',
            "/products/no-data": "<html><head><title>Coming soon</title></head><body>No price here</body></html>",
            "/products/secret-item": f'<html><head>{ld({"@type": "Product", "name": "Secret", "offers": {"price": "10", "priceCurrency": "BDT"}})}</head></html>',
            "/category/boots": f'<html><head>{ld({"@type": "Product", "name": "Not a product page", "offers": {"price": "1"}})}</head></html>',
        }
        self.sitemap = "<urlset>" + "".join(f"<url><loc>{o}{p}</loc></url>" for p in ("/products/trail-boot", "/products/rain-jacket", "/products/og-only", "/products/no-data", "/products/secret-item", "/category/boots", "/about")) + "</urlset>"
        self.robots = f"User-agent: *\nDisallow: /products/secret-item\nSitemap: {o}/sitemap.xml\n"

    # -- http
    def _json(self, data, status=200):
        return httpx.Response(status, json=data)

    def handler(self, req: httpx.Request) -> httpx.Response:
        host, path, q = req.url.host.removeprefix("www."), req.url.path, dict(req.url.params)
        self.requests.append(f"{host}{path}")
        if host == "plainhttp.test" and req.url.scheme == "https":     # a small shop without a certificate
            raise httpx.ConnectError("no TLS here")
        o = self.origin(host)
        sub = lambda s: s.replace("{img}", f"{o}/img").replace("{o}", o)
        if path.startswith("/img/"):
            name = path.rsplit("/", 1)[-1].removesuffix(".svg")
            return httpx.Response(200, text=SVG.format(bg=COLORS.get(name, "#eee"), label=name.title()), headers={"content-type": "image/svg+xml"})
        if host in ("shopify.test", "usd.test", "plainhttp.test"):
            if path == "/products.json":
                page = int(q.get("page", "1"))
                prods = json.loads(sub(json.dumps(self.shopify))) if page == 1 else []
                return self._json({"products": prods})
            if path == "/cart.js":
                return self._json({"currency": "USD" if host == "usd.test" else self.shopify_currency})
            return httpx.Response(404)
        if host == "woo.test":
            if path == "/wp-json/wc/store/v1/products":
                return self._json(json.loads(sub(json.dumps(self.woo))) if q.get("page", "1") == "1" else [])
            return httpx.Response(404)
        if host == "pages.test":
            if path == "/robots.txt":
                return httpx.Response(200, text=self.robots)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=self.sitemap)
            if path in self.pages:
                return httpx.Response(200, text=self.pages[path], headers={"content-type": "text/html; charset=utf-8"})
            return httpx.Response(404)
        if host == "blocked.test":
            return httpx.Response(403, text="no")
        if host == "empty.test":   # a shop that draws its products with JavaScript: nothing to read
            if path == "/sitemap.xml":
                return httpx.Response(200, text=f"<urlset><url><loc>{o}/products/a</loc></url></urlset>")
            return httpx.Response(200, text="<html><body><div id='app'></div><script src='/app.js'></script></body></html>")
        if host == "redirect.test":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        if host == "big.test":
            return httpx.Response(200, content=b"x" * 3_500_000)
        return httpx.Response(404)

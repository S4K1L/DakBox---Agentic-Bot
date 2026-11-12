"""Bring a product list into Dakbox from a website the owner points us at.

Three ways in, tried in this order, so no keys are needed for the common cases:
  1. Shopify stores publish /products.json.
  2. WooCommerce (WordPress) stores publish the Store API at /wp-json/wc/store/v1/products.
  3. Any other site: read its sitemap, open the product pages and read the structured data (schema.org JSON-LD, or
     Open Graph tags) that shops publish for Google.
A site that shows its products only through JavaScript, hides them behind a login, or asks bots to stay out cannot be read;
the owner is told so and can add products by hand.

Safety, because the owner types an address and this server fetches it:
  - Only http/https, no credentials in the address, only the normal web ports.
  - Every address (and every redirect hop) must resolve to a public internet address: never localhost, a private network,
    or a cloud metadata address. DAKBOX_ALLOW_PRIVATE_FETCH=1 lifts this for a local stand-in site; never set it in production.
  - Responses are size-capped, time-limited, and the number of pages is capped.
  - robots.txt is honoured when reading ordinary pages.
  - Text from the site is never trusted: it is stripped of markup, length-limited, and stored as data.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as htmllib
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from . import db

UA = "DakboxCatalogBot/1.0 (product import requested by the shop owner)"
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 4
MAX_API_PRODUCTS = 2000
MAX_PAGES = 150          # ordinary product pages read per import
PAGE_CONCURRENCY = 6
TIMEOUT = 15.0
CACHE_TTL = 600

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject a stand-in website here."""
    global _transport
    _transport = t


class CatalogError(Exception):
    """A problem worth showing to the owner as is."""


# ---------------------------------------------------------------- data
@dataclass
class Item:
    source_id: str                 # stable per product on that site (variant id, product id, or page address)
    name: str
    price: int | None              # whole taka (or whatever the site's currency is, see Found.currency)
    sku: str | None = None
    variant: str | None = None
    description: str | None = None
    image: str | None = None
    url: str | None = None
    in_stock: bool | None = None   # None: the site does not say
    qty: int | None = None         # only when the site really publishes a number


@dataclass
class Found:
    kind: str                      # shopify | woo | page | pages
    origin: str                    # https://shop.example
    host: str
    items: list[Item] = field(default_factory=list)
    currency: str | None = None
    complete: bool = False         # the list is the site's whole catalogue (so missing products can be noticed)
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0               # pages looked at that were not products
    url: str = ""                  # the address that was actually opened (http or https)


KIND_LABEL = {"shopify": "Shopify store", "woo": "WooCommerce store", "page": "Product page", "pages": "Website with product data"}


# ---------------------------------------------------------------- addresses and safe fetching
def normalize(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw or len(raw) > 500 or re.search(r"\s", raw):
        raise CatalogError("Type the address of your website, for example myshop.com.")
    if "://" not in raw:
        raw = "https://" + raw
    u = urlparse(raw)
    if u.scheme not in ("http", "https"):
        raise CatalogError("Only http and https addresses can be used.")
    if u.username or u.password:
        raise CatalogError("Leave the username and password out of the address.")
    host = (u.hostname or "").lower().rstrip(".")
    if not host or "." not in host and not _allow_private():
        raise CatalogError("That does not look like a website address.")
    if u.port not in (None, 80, 443) and not _allow_private():
        raise CatalogError("Only normal website addresses (no custom port) can be used.")
    netloc = host + (f":{u.port}" if u.port else "")
    return urlunparse((u.scheme, netloc, u.path or "/", "", u.query, ""))


def _allow_private() -> bool:
    return os.environ.get("DAKBOX_ALLOW_PRIVATE_FETCH") == "1"


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


async def _host_ok(host: str) -> None:
    """Refuse anything that is not a public internet address."""
    if _allow_private():
        return
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            raise CatalogError("That website could not be found. Check the address.") from None
        ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    if not ips or any(not ip.is_global for ip in ips):
        raise CatalogError("That address is not a public website, so Dakbox will not open it.")


@dataclass
class Resp:
    status: int
    url: str
    text: str
    headers: dict


async def _get(client: httpx.AsyncClient, url: str, accept: str = "*/*") -> Resp:
    """One GET with redirects followed by hand, every hop checked. Never raises for HTTP errors; status 0 means unreachable."""
    for _ in range(MAX_REDIRECTS + 1):
        await _host_ok(urlparse(url).hostname or "")
        try:
            async with client.stream("GET", url, headers={"Accept": accept}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    if urlparse(url).scheme not in ("http", "https"):
                        return Resp(0, url, "", {})
                    continue
                buf, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        return Resp(413, url, "", dict(r.headers))
                    buf.append(chunk)
                body = b"".join(buf).decode(r.encoding or "utf-8", errors="replace")
                return Resp(r.status_code, url, body, dict(r.headers))
        except (httpx.HTTPError, UnicodeError, LookupError):
            return Resp(0, url, "", {})
    return Resp(0, url, "", {})


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=_transport, follow_redirects=False, headers={"User-Agent": UA})


def _json(r: Resp):
    if r.status != 200:
        return None
    try:
        return json.loads(r.text)
    except ValueError:
        return None


# ---------------------------------------------------------------- small parsers
_TAGS = re.compile(r"<[^>]+>")


def clean_text(s, limit: int = 500) -> str | None:
    if not isinstance(s, str):
        return None
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"</?(p|br|div|li|ul|ol|h[1-6]|tr|td|table|section)\b[^>]*>", " ", s, flags=re.I)   # block tags separate words, inline ones (b, i, a) do not
    s = _TAGS.sub("", s)
    s = " ".join(htmllib.unescape(s).split())
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s or None


def parse_price(v) -> int | None:
    """'1,450.00', '৳ 1450', 1450, '1.450,00' -> 1450. Whole units, rounded."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        s = re.sub(r"[^\d.,]", "", str(v))
        if not s or not re.search(r"\d", s):
            return None
        if "," in s and "." in s:
            dec = "," if s.rfind(",") > s.rfind(".") else "."
            s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
        elif "," in s:
            s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) and s.count(",") == 1 else s.replace(",", "")
        elif s.count(".") > 1:
            s = s.replace(".", "")
        try:
            n = float(s)
        except ValueError:
            return None
    if n <= 0 or n > 1e9:
        return None
    return int(n + 0.5)


def _abs_image(u, base: str) -> str | None:
    if isinstance(u, dict):
        u = u.get("url") or u.get("contentUrl")
    if isinstance(u, list):
        u = next((x for x in u if x), None)
        if isinstance(u, dict):
            u = u.get("url")
    if not isinstance(u, str) or not u.strip():
        return None
    u = urljoin(base, u.strip())
    if urlparse(u).scheme not in ("http", "https") or len(u) > 500:
        return None
    return u


def _stock_from_schema(v) -> bool | None:
    if isinstance(v, dict):
        v = v.get("@id") or v.get("name")
    t = str(v or "").rsplit("/", 1)[-1].lower()
    if t in ("instock", "limitedavailability", "onlineonly", "instoreonly"):
        return True
    if t in ("outofstock", "soldout", "discontinued"):
        return False
    return None


# ---------------------------------------------------------------- Shopify and WooCommerce
async def _try_shopify(client, origin: str, host: str) -> Found | None:
    first = _json(await _get(client, f"{origin}/products.json?limit=250&page=1", "application/json"))
    if not isinstance(first, dict) or not isinstance(first.get("products"), list) or not first["products"]:
        return None
    f = Found("shopify", origin, host, complete=True)
    pages, page = [first["products"]], 1
    while len(pages[-1]) >= 250 and sum(len(p) for p in pages) < MAX_API_PRODUCTS:
        page += 1
        d = _json(await _get(client, f"{origin}/products.json?limit=250&page={page}", "application/json"))
        if not isinstance(d, dict) or not d.get("products"):
            break
        pages.append(d["products"])
    products = [p for pg in pages for p in pg if isinstance(p, dict)]
    if len(products) >= MAX_API_PRODUCTS:
        products, f.truncated, f.complete = products[:MAX_API_PRODUCTS], True, False
        f.warnings.append(f"This store has more than {MAX_API_PRODUCTS} products; the first {MAX_API_PRODUCTS} are used.")
    for p in products:
        title = clean_text(p.get("title"), 100)
        if not title:
            continue
        imgs = p.get("images") if isinstance(p.get("images"), list) else []
        src = p["image"].get("src") if isinstance(p.get("image"), dict) else None
        src = src or (imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else None)
        img = _abs_image(src, origin)
        desc = clean_text(p.get("body_html"))
        url = f"{origin}/products/{p.get('handle')}" if p.get("handle") else None
        variants = [v for v in (p.get("variants") or []) if isinstance(v, dict)]
        for v in variants:
            vt = clean_text(v.get("title"), 100)
            multi = len(variants) > 1 and vt and vt.lower() != "default title"
            f.items.append(Item(
                source_id=f"shopify:{v.get('id')}", name=title, variant=vt if multi else None, price=parse_price(v.get("price")),
                sku=(v.get("sku") or None), description=desc, image=img, url=url,
                in_stock=bool(v["available"]) if "available" in v else None))
    cur = _json(await _get(client, f"{origin}/cart.js", "application/json"))
    if isinstance(cur, dict) and isinstance(cur.get("currency"), str):
        f.currency = cur["currency"].upper()
    return f


async def _try_woo(client, origin: str, host: str) -> Found | None:
    base = None
    for b in (f"{origin}/wp-json/wc/store/v1/products", f"{origin}/?rest_route=/wc/store/v1/products"):
        sep = "&" if "?" in b else "?"
        d = _json(await _get(client, f"{b}{sep}per_page=100&page=1", "application/json"))
        if isinstance(d, list) and d and isinstance(d[0], dict) and "prices" in d[0]:
            base, first = b, d
            break
    if not base:
        return None
    sep = "&" if "?" in base else "?"
    rows, page = list(first), 1
    while len(first) >= 100 and len(rows) < MAX_API_PRODUCTS:
        page += 1
        d = _json(await _get(client, f"{base}{sep}per_page=100&page={page}", "application/json"))
        if not isinstance(d, list) or not d:
            break
        rows += d
        first = d
    f = Found("woo", origin, host, complete=True)
    if len(rows) >= MAX_API_PRODUCTS:
        rows, f.truncated, f.complete = rows[:MAX_API_PRODUCTS], True, False
        f.warnings.append(f"This store has more than {MAX_API_PRODUCTS} products; the first {MAX_API_PRODUCTS} are used.")
    variable = 0
    for p in rows:
        if not isinstance(p, dict):
            continue
        name = clean_text(p.get("name"), 100)
        pr = p.get("prices") or {}
        if not name:
            continue
        try:
            minor = int(pr.get("currency_minor_unit", 2))
            price = parse_price(int(pr.get("price")) / (10 ** minor))
        except (TypeError, ValueError):
            price = None
        f.currency = f.currency or (str(pr.get("currency_code")).upper() if pr.get("currency_code") else None)
        if p.get("type") == "variable":
            variable += 1
        imgs = p.get("images") or []
        qty = p.get("low_stock_remaining")
        f.items.append(Item(
            source_id=f"woo:{p.get('id')}", name=name, price=price, sku=(p.get("sku") or None),
            description=clean_text(p.get("short_description") or p.get("description")),
            image=_abs_image(imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else None, origin), url=p.get("permalink"),
            in_stock=bool(p["is_in_stock"]) if "is_in_stock" in p else None, qty=qty if isinstance(qty, int) and qty >= 0 else None))
    if variable:
        f.warnings.append(f"{variable} products come in several variations; each is added once, at its lowest price.")
    return f


# ---------------------------------------------------------------- ordinary pages
class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.canonical: str | None = None
        self.title = ""
        self._in_ld = self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ld, self._buf = True, []
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k and "content" in a:
                self.meta.setdefault(k, a["content"])
        elif tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonical = a.get("href") or None
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld.append("".join(self._buf))
            self._in_ld = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title and len(self.title) < 200:
            self.title += data


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _is_type(n: dict, name: str) -> bool:
    t = n.get("@type")
    return name in t if isinstance(t, list) else t == name


def _offer(o) -> tuple[int | None, str | None, bool | None]:
    """Cheapest in-stock offer (or the cheapest at all): price, currency, availability."""
    offers = o if isinstance(o, list) else [o]
    cands = []
    for x in offers:
        if not isinstance(x, dict):
            continue
        spec = x.get("priceSpecification") if isinstance(x.get("priceSpecification"), dict) else {}
        raw = next((v for v in (x.get("price"), x.get("lowPrice"), spec.get("price")) if v not in (None, "")), None)
        price = parse_price(raw)
        if price is None:
            continue
        cur = x.get("priceCurrency") or spec.get("priceCurrency")
        cands.append((price, str(cur).upper() if cur else None, _stock_from_schema(x.get("availability"))))
    if not cands:
        return None, None, None
    pool = [c for c in cands if c[2] is not False] or cands      # prefer offers that can be bought
    return min(pool, key=lambda c: c[0])


def extract_page(markup: str, url: str) -> tuple[Item | None, str | None, _Page]:
    """The product a page describes, if it describes one. Also returns the currency the page states."""
    p = _Page()
    try:
        p.feed(markup)
    except Exception:  # noqa: BLE001 - broken HTML must not stop an import
        pass
    canon = urljoin(url, p.canonical) if p.canonical else url
    if urlparse(canon).netloc != urlparse(url).netloc:
        canon = url
    canon = urlunparse(urlparse(canon)._replace(fragment="", query=""))
    for raw in p.ld:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for n in _walk(data):
            if not _is_type(n, "Product") or not n.get("name"):
                continue
            price, cur, avail = _offer(n.get("offers"))
            if price is None:
                continue
            sku = n.get("sku") or n.get("mpn")
            return Item(
                source_id=canon, name=clean_text(n.get("name"), 100) or "", price=price, sku=str(sku)[:60] if sku else None,
                description=clean_text(n.get("description")), image=_abs_image(n.get("image"), url), url=canon, in_stock=avail), cur, p
    m = p.meta
    price = parse_price(m.get("product:price:amount") or m.get("og:price:amount"))
    if price is not None and m.get("og:title"):
        cur = (m.get("product:price:currency") or m.get("og:price:currency") or "").upper() or None
        avail = m.get("product:availability") or m.get("og:availability") or ""
        stock = False if re.search(r"out.?of.?stock|sold.?out", avail, re.I) else (True if re.search(r"in.?stock|available", avail, re.I) else None)
        return Item(source_id=canon, name=clean_text(m["og:title"], 100) or "", price=price, description=clean_text(m.get("og:description")),
                    image=_abs_image(m.get("og:image"), url), url=canon, in_stock=stock), cur, p
    return None, None, p


_PRODUCT_PATH = re.compile(r"/(products?|p|items?|shop|store|catalog|goods|buy)/[^/?#]+", re.I)
_NOT_PRODUCT = re.compile(r"/(category|categories|tag|tags|cart|checkout|account|login|blog|page|collections?)(/|$)", re.I)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _same_site(a: str, b: str) -> bool:
    ha, hb = (urlparse(a).hostname or "").removeprefix("www."), (urlparse(b).hostname or "").removeprefix("www.")
    return ha == hb


def _looks_like_product(url: str, sitemap_hint: bool) -> bool:
    path = urlparse(url).path
    if _NOT_PRODUCT.search(path):
        return False
    return sitemap_hint or bool(_PRODUCT_PATH.search(path))


async def _sitemap_urls(client, origin: str, robots_text: str) -> list[str]:
    cands = [m.strip() for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_text)]
    cands += [f"{origin}{p}" for p in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/product-sitemap.xml")]
    seen, out, queue = set(), [], [(c, 0) for c in dict.fromkeys(cands)]
    reads = 0
    while queue and reads < 12 and len(out) < 5000:
        u, depth = queue.pop(0)
        if u in seen or u.endswith(".gz") or not _same_site(u, origin):
            continue
        seen.add(u)
        r = await _get(client, u, "application/xml,text/xml")
        reads += 1
        if r.status != 200 or "<loc" not in r.text.lower():
            continue
        locs = _LOC.findall(r.text)
        if "<sitemapindex" in r.text.lower():
            kids = [(k, depth + 1) for k in locs if depth < 2]
            kids.sort(key=lambda kd: "product" not in kd[0].lower())     # product sitemaps first
            queue = kids + queue
        else:
            hint = "product" in u.lower()
            out += [(x, hint) for x in locs]
    # (url, hint) pairs from sitemaps whose own address mentions products count in full; others need a product-looking path
    return [x for x, hint in out if _same_site(x, origin) and _looks_like_product(x, hint)]


async def _try_pages(client, start_url: str, origin: str, host: str) -> Found:
    first = await _get(client, start_url, "text/html")
    if first.status in (401, 403):
        raise CatalogError("That website does not let Dakbox read it (it answered 'not allowed'). Add your products by hand instead.")
    if first.status != 200:
        raise CatalogError("That website could not be opened. Check the address and try again.")
    item, cur, page = extract_page(first.text, first.url)
    if item:
        f = Found("page", origin, host, items=[item], currency=cur)
        return f
    robots_resp = await _get(client, f"{origin}/robots.txt", "text/plain")
    robots_text = robots_resp.text if robots_resp.status == 200 else ""
    rp = RobotFileParser()
    rp.parse(robots_text.splitlines())
    urls = await _sitemap_urls(client, origin, robots_text)
    if not urls:
        urls = [urljoin(first.url, h) for h in page.links]
        urls = [u for u in urls if _same_site(u, origin) and _looks_like_product(u, False)]
    urls = list(dict.fromkeys(urlparse(u)._replace(fragment="", query="").geturl() for u in urls if urlparse(u).scheme in ("http", "https")))
    f = Found("pages", origin, host)
    if not urls:
        raise CatalogError("No product pages were found on that website. If it is a single product, paste that product's address. "
                           "Otherwise add the products by hand.")
    blocked = [u for u in urls if robots_text and not rp.can_fetch(UA, u)]
    if blocked:
        f.warnings.append(f"{len(blocked)} pages were skipped because the website's robots.txt asks bots to stay out.")
    skip_set = set(blocked)
    urls = [u for u in urls if u not in skip_set]
    if len(urls) > MAX_PAGES:
        f.truncated = True
        f.warnings.append(f"The site lists {len(urls)} product pages; the first {MAX_PAGES} are read.")
        urls = urls[:MAX_PAGES]
    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    currencies: list[str] = []

    async def one(u: str):
        async with sem:
            r = await _get(client, u, "text/html")
        if r.status != 200:
            return None
        it, c, _ = extract_page(r.text, r.url)
        if it and c:
            currencies.append(c)
        return it

    got = await asyncio.gather(*(one(u) for u in urls))
    seen = set()
    for it in got:
        if it and it.source_id not in seen:
            seen.add(it.source_id)
            f.items.append(it)
    f.skipped = len(urls) - len(f.items)
    if currencies:
        f.currency = max(set(currencies), key=currencies.count)
        if len(set(currencies)) > 1:
            f.warnings.append("The pages quote prices in more than one currency: " + ", ".join(sorted(set(currencies))) + ".")
    if not f.items:
        raise CatalogError("Product pages were found, but they do not publish product data Dakbox can read (name and price). "
                           "Shops that load products only with JavaScript cannot be read. Add the products by hand.")
    return f


# ---------------------------------------------------------------- discover (with a short cache so preview and import agree)
_cache: dict[tuple, tuple[float, Found]] = {}      # keyed by (business, address): one business never gets another's cached result


async def discover(raw_url: str, fresh: bool = False) -> Found:
    """Look at the site. A bare address (myshop.com) is tried with https first, then plain http for small shops without a certificate."""
    try:
        return await _discover(normalize(raw_url), fresh)
    except CatalogError as e:
        if "://" in raw_url or "could not be opened" not in str(e):
            raise
        return await _discover(normalize(raw_url).replace("https://", "http://", 1), fresh)


async def _discover(url: str, fresh: bool) -> Found:
    hit = _cache.get((db.current(), url))
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    origin = _origin(url)
    host = (urlparse(url).hostname or "").removeprefix("www.")
    async with _client() as client:
        await _host_ok(urlparse(url).hostname or "")
        path = urlparse(url).path
        found = None
        if not _PRODUCT_PATH.search(path):       # an address that names one product is read as that page
            found = await _try_shopify(client, origin, host) or await _try_woo(client, origin, host)
        if not found:
            found = await _try_pages(client, url, origin, host)
    found.url = url
    if found.currency and found.currency != "BDT":
        found.warnings.insert(0, f"Prices on this site are in {found.currency}, not Taka. Dakbox shows and charges them as Taka (৳), so they would be wrong.")
    elif not found.currency:
        found.warnings.insert(0, "The site does not say which currency its prices are in. Dakbox treats them as Taka (৳): check a few after importing.")
    if len(_cache) > 20:
        _cache.clear()
    _cache[(db.current(), url)] = (time.monotonic(), found)
    return found


# ---------------------------------------------------------------- save to the catalogue
_SKU_OK = re.compile(r"[^A-Za-z0-9._-]+")
_ART = (("bottle", ("bottle", "flask", "tumbler", "jug")), ("tent", ("tent", "camp")), ("boot", ("boot", "shoe", "sandal", "sneaker")), ("jacket", ("jacket", "coat", "hoodie", "shirt", "tee")))


def _art(name: str) -> str:
    n = name.lower()
    return next((k for k, words in _ART if any(w in n for w in words)), "box")


def _keywords(name: str, variant: str | None) -> str:
    words = re.findall(r"[a-z0-9]{3,}", f"{name} {variant or ''}".lower())
    return " ".join(dict.fromkeys(words))[:300]


def _new_sku(it: Item) -> str | None:
    h = hashlib.sha1(it.source_id.encode()).hexdigest()
    base = _SKU_OK.sub("-", (it.sku or "").strip()).strip("-._")[:30] or f"WEB-{h[:8].upper()}"
    for cand in (base, f"{base}-{h[:4]}"[:40], f"WEB-{h[:10].upper()}"):
        if not db.get("SELECT 1 FROM products WHERE lower(sku)=lower(?)", [cand]):
            return cand
    return None


def apply(found: Found, default_stock: int) -> dict:
    """Add new products and update the ones imported earlier. Returns counts for the owner."""
    from . import limits
    room = limits.products()["left"]                          # the plan's product limit: new products stop at it, updates always go through
    host, now = found.host, db.now()
    added = updated = 0
    skipped: dict[str, int] = {}
    seen: set[str] = set()

    def skip(why: str):
        skipped[why] = skipped.get(why, 0) + 1

    for it in found.items:
        name = (it.name or "").strip()[:100]
        if not name:
            skip("no name")
            continue
        if it.price is None or it.price > 10_000_000:
            skip("no usable price")
            continue
        seen.add(it.source_id)
        variant = (it.variant or "").strip()[:100] or None
        desc = (it.description or "")[:500] or None
        row = db.get("SELECT * FROM products WHERE source=? AND source_id=?", [host, it.source_id])
        if row:
            stock = row["stock"]
            if it.in_stock is False:
                stock = 0
            elif it.qty is not None:
                stock = min(it.qty, 1_000_000)
            elif it.in_stock and stock == 0:
                stock = default_stock
            db.run("UPDATE products SET name=?, variant=?, price=?, description=?, image=?, source_url=?, stock=?, synced_at=? WHERE id=?",
                   [name, variant, it.price, desc, it.image, it.url, stock, now, row["id"]])
            updated += 1
            continue
        if room is not None and added >= room:
            skip("over your plan's product limit")
            continue
        sku = _new_sku(it)
        if not sku:
            skip("could not make a unique SKU")
            continue
        stock = 0 if it.in_stock is False else (min(it.qty, 1_000_000) if it.qty is not None else default_stock)
        db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,description,keywords,image,source,source_id,source_url,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               [db.uid("p"), sku, name, variant, it.price, stock, 0, _art(name), desc, _keywords(name, variant), it.image, host, it.source_id, it.url, now])
        added += 1
    gone = 0
    if found.complete and seen:
        for r in db.all("SELECT id, source_id FROM products WHERE source=? AND stock>0", [host]):
            if r["source_id"] not in seen:
                db.run("UPDATE products SET stock=0, synced_at=? WHERE id=?", [now, r["id"]])
                gone += 1
    return {"added": added, "updated": updated, "skipped": sum(skipped.values()), "skippedWhy": skipped, "gone": gone}


# ---------------------------------------------------------------- connected websites
class CurrencyChanged(CatalogError):
    pass


def check_currency(found: Found, accepted: str | None) -> None:
    if found.currency and found.currency != "BDT" and found.currency != accepted:
        raise CurrencyChanged(f"Prices on this site are in {found.currency}, not Taka (BDT). Confirm that you want them copied as Taka numbers.")


def source_view(r) -> dict:
    n = db.get("SELECT COUNT(*) n FROM products WHERE source=?", [r["host"]])["n"]
    return {"id": r["id"], "host": r["host"], "url": r["url"], "kind": r["kind"], "kindLabel": KIND_LABEL.get(r["kind"], r["kind"]), "defaultStock": r["default_stock"],
            "currency": r["currency"], "createdAt": r["created_at"], "lastSyncAt": r["last_sync_at"], "lastCount": r["last_count"], "lastNote": r["last_note"],
            "lastError": r["last_error"], "products": n,
            "ordersCount": r["orders_count"], "ordersAt": r["orders_at"], "ordersError": r["orders_error"], "notifySms": bool(r["order_sms"]), "secretSet": bool(r["order_secret"])}


def _summary(res: dict) -> str:
    bits = [f"{res['added']} added", f"{res['updated']} updated"]
    if res["gone"]:
        bits.append(f"{res['gone']} no longer on the site (stock set to 0)")
    if res["skipped"]:
        bits.append(f"{res['skipped']} skipped")
    return ", ".join(bits)


async def connect(raw_url: str, default_stock: int, confirm_currency: bool) -> tuple[dict, Found, dict]:
    found = await discover(raw_url, fresh=False)
    if not confirm_currency:
        check_currency(found, None)
    accepted = found.currency if found.currency not in (None, "BDT") else None
    res = apply(found, default_stock)
    src = db.get("SELECT * FROM catalog_sources WHERE host=?", [found.host])
    now = db.now()
    if src:
        db.run("UPDATE catalog_sources SET url=?, kind=?, default_stock=?, currency=?, last_sync_at=?, last_count=?, last_note=?, last_error=NULL WHERE id=?",
               [found.url, found.kind, default_stock, accepted, now, res["added"] + res["updated"], _summary(res), src["id"]])
        sid = src["id"]
    else:
        sid = db.uid("cs")
        db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,currency,created_at,last_sync_at,last_count,last_note) VALUES(?,?,?,?,?,?,?,?,?,?)",
               [sid, found.host, found.url, found.kind, default_stock, accepted, now, now, res["added"] + res["updated"], _summary(res)])
    return source_view(db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])), found, res


async def sync(src) -> dict:
    """Read the site again and update prices, stock and new products. Records the outcome on the source either way."""
    try:
        found = await discover(src["url"], fresh=True)
        check_currency(found, src["currency"])
        res = apply(found, src["default_stock"])
    except CatalogError as e:
        db.run("UPDATE catalog_sources SET last_error=?, last_sync_at=? WHERE id=?", [str(e), db.now(), src["id"]])
        raise
    db.run("UPDATE catalog_sources SET kind=?, last_sync_at=?, last_count=?, last_note=?, last_error=NULL WHERE id=?",
           [found.kind, db.now(), res["added"] + res["updated"], _summary(res), src["id"]])
    return res


async def sync_all() -> None:
    """Background: keep every connected website's prices and stock fresh. One site failing never stops the others."""
    for src in db.all("SELECT * FROM catalog_sources"):
        try:
            await sync(src)
        except Exception:  # noqa: BLE001 - recorded on the source; the loop must go on
            pass

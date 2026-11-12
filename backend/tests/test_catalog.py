"""Importing a product list from a website: the three ways in (Shopify, WooCommerce, ordinary pages), re-sync without duplicates,
and the safety rules (public addresses only, size limits, robots.txt, currency). Websites are stand-ins shaped like the real ones
(tools/fake_site.py); none of this has been run against a real shop."""
import httpx
import pytest

from app import catalog_import as ci, db
from app.main import app
from tests.test_auth import H, member_token, setup_owner
from tools.fake_site import FakeWeb


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def web(monkeypatch):
    w = FakeWeb()
    ci.set_transport(httpx.MockTransport(w.handler))
    real = ci._host_ok

    async def ok(host):     # the stand-in domains do not exist in DNS; every other address goes through the real check
        if host.endswith(".test"):
            return
        await real(host)
    monkeypatch.setattr(ci, "_host_ok", ok)
    ci._cache.clear()
    db.run("DELETE FROM catalog_sources")
    db.run("DELETE FROM products WHERE source IS NOT NULL")
    yield w
    ci.set_transport(None)
    ci._cache.clear()


async def owner(http):
    return H(await setup_owner(http))


def product(sku):
    return db.get("SELECT * FROM products WHERE sku=?", [sku])


def by_source(host):
    return {r["source_id"]: r for r in db.all("SELECT * FROM products WHERE source=?", [host])}


# ---------------------------------------------------------------- small parsers
def test_prices_are_read_from_the_ways_shops_write_them():
    p = ci.parse_price
    assert [p("1,450.00"), p("৳ 1450"), p("1.450,00"), p(1450), p("12,345"), p(29.99)] == [1450, 1450, 1450, 1450, 12345, 30]
    assert p("0") is None and p("free") is None and p(None) is None and p(True) is None and p(-5) is None


def test_text_from_a_site_loses_its_markup_and_scripts():
    assert ci.clean_text("<p>Two <b>person</b> tent &amp; fly</p><script>alert(1)</script>") == "Two person tent & fly"
    assert len(ci.clean_text("x" * 900)) == 500


# ---------------------------------------------------------------- Shopify
async def test_a_shopify_store_is_found_previewed_and_imported(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "shopify.test"})).json()
    assert d["kind"] == "shopify" and d["currency"] == "BDT" and d["total"] == 4 and d["usable"] == 3
    assert d["outOfStock"] == 1 and d["connected"] is False
    assert db.get("SELECT COUNT(*) n FROM products WHERE source IS NOT NULL")["n"] == 0       # a preview saves nothing

    r = (await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test", "defaultStock": 8})).json()
    assert (r["added"], r["updated"], r["skipped"]) == (3, 0, 1) and r["skippedWhy"] == {"no usable price": 1}
    rows = by_source("shopify.test")
    green, orange, bottle = rows["shopify:111"], rows["shopify:112"], rows["shopify:121"]
    assert (green["name"], green["variant"], green["price"], green["sku"], green["stock"]) == ("Ridgeline Tent 2P", "Green", 12500, "RT-GRN", 8)
    assert orange["stock"] == 0                                    # the site says it is sold out
    assert bottle["variant"] is None and bottle["sku"].startswith("WEB-") and bottle["art"] == "bottle"
    assert green["image"] == "https://shopify.test/img/tent.svg" and green["source_url"] == "https://shopify.test/products/ridgeline-tent-2p"
    assert green["description"] == "Two-person tent, 3 seasons." and green["art"] == "tent"     # markup and script gone
    assert "tent" in green["keywords"]

    items = (await http.get("/api/products", headers=h)).json()["items"]
    assert any(i["sku"] == "RT-GRN" and i["image"] for i in items)
    src = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]
    assert src["host"] == "shopify.test" and src["kindLabel"] == "Shopify store" and src["products"] == 3 and "3 added" in src["lastNote"]


async def test_syncing_again_updates_without_duplicating_and_respects_local_stock(http, web):
    h = await owner(http)
    await http.post("/api/catalog/import", headers=h, json={"url": "https://www.shopify.test/", "defaultStock": 10})
    sid = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]["id"]
    db.run("UPDATE products SET stock=3 WHERE sku='RT-GRN'")              # the owner counted the shelf
    web.shopify[0]["variants"][0]["price"] = "11900.00"                   # price drops on the site
    web.shopify[0]["variants"][1]["available"] = True                     # the orange one is back
    web.shopify[1]["variants"][0]["available"] = False                    # the bottle sells out
    web.shopify.append({"id": 14, "title": "Camp Stool", "handle": "camp-stool", "body_html": "", "images": [], "variants": [{"id": 141, "title": "Default Title", "price": "990", "sku": "", "available": True}]})
    r = (await http.post(f"/api/catalog/sources/{sid}/sync", headers=h)).json()
    assert (r["added"], r["updated"], r["gone"]) == (1, 3, 0)
    assert db.get("SELECT COUNT(*) n FROM products WHERE source='shopify.test'")["n"] == 4          # same three + stool
    assert product("RT-GRN")["price"] == 11900 and product("RT-GRN")["stock"] == 3                  # price follows the site, counted stock stays
    assert product("RT-ORG")["stock"] == 10                                                          # was 0, site says available again
    assert by_source("shopify.test")["shopify:121"]["stock"] == 0

    web.shopify.pop(0)                                                                               # a product is removed from the site
    r = (await http.post(f"/api/catalog/sources/{sid}/sync", headers=h)).json()
    assert r["gone"] == 2 and product("RT-GRN")["stock"] == 0 and "no longer on the site" in r["source"]["lastNote"]
    assert product("RT-GRN") is not None                                                             # kept, because orders may refer to it


async def test_an_empty_site_answer_never_zeroes_the_whole_catalogue(http, web):
    h = await owner(http)
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    sid = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]["id"]
    web.shopify.clear()
    r = await http.post(f"/api/catalog/sources/{sid}/sync", headers=h)
    assert r.status_code == 400                       # nothing found: an error, not "everything is gone"
    assert product("RT-GRN")["stock"] > 0
    assert (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]["lastError"]


async def test_an_imported_sku_never_overwrites_an_existing_product(http, web):
    h = await owner(http)
    await http.post("/api/products", headers=h, json={"name": "My own tent", "sku": "RT-GRN", "price": 100, "stock": 1})
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    assert product("RT-GRN")["name"] == "My own tent" and product("RT-GRN")["source"] is None
    imported = by_source("shopify.test")["shopify:111"]
    assert imported["sku"].startswith("RT-GRN-") and imported["name"] == "Ridgeline Tent 2P"


# ---------------------------------------------------------------- WooCommerce
async def test_a_woocommerce_store_is_read_through_its_store_api(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "woo.test"})).json()
    assert d["kind"] == "woo" and d["total"] == 2 and any("several variations" in w for w in d["warnings"])
    await http.post("/api/catalog/import", headers=h, json={"url": "woo.test", "defaultStock": 5})
    rows = by_source("woo.test")
    jacket, mug = rows["woo:21"], rows["woo:22"]
    assert (jacket["name"], jacket["price"], jacket["sku"], jacket["stock"]) == ("Summit Jacket & Shell", 9500, "SJ-1", 4)   # minor units, entities, real stock number
    assert mug["price"] == 450 and mug["stock"] == 0 and mug["sku"].startswith("WEB-")
    assert jacket["image"] == "https://woo.test/img/jacket.svg"


# ---------------------------------------------------------------- ordinary websites
async def test_an_ordinary_site_is_read_from_its_sitemap_and_product_data(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "pages.test"})).json()
    assert d["kind"] == "pages" and d["total"] == 3 and d["currency"] == "BDT"
    assert any("robots.txt" in w for w in d["warnings"])
    assert not any("secret" in i["name"].lower() for i in d["items"])             # robots.txt asked us to stay out
    await http.post("/api/catalog/import", headers=h, json={"url": "pages.test", "defaultStock": 6})
    rows = by_source("pages.test")
    assert set(rows) == {"https://pages.test/products/trail-boot", "https://pages.test/products/rain-jacket", "https://pages.test/products/og-only"}
    boot = rows["https://pages.test/products/trail-boot"]
    assert (boot["name"], boot["price"], boot["sku"], boot["stock"], boot["art"]) == ("Trail Boot", 6990, "TB-9", 6, "boot")
    assert rows["https://pages.test/products/rain-jacket"]["stock"] == 0           # OutOfStock in the page data
    assert rows["https://pages.test/products/rain-jacket"]["image"] == "https://pages.test/img/jacket.svg"   # relative address made absolute
    assert rows["https://pages.test/products/og-only"]["price"] == 990              # Open Graph tags are enough


async def test_a_single_product_page_can_be_imported(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "https://pages.test/products/trail-boot"})).json()
    assert d["kind"] == "page" and d["total"] == 1 and d["items"][0]["name"] == "Trail Boot"


async def test_sites_that_cannot_be_read_say_so_plainly(http, web):
    h = await owner(http)
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "blocked.test"})
    assert r.status_code == 400 and "does not let Dakbox read it" in r.json()["detail"]
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "empty.test"})
    assert r.status_code == 400 and "JavaScript" in r.json()["detail"]
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "nothing-here.test"})
    assert r.status_code == 400 and "could not be opened" in r.json()["detail"]
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "big.test"})
    assert r.status_code == 400                     # larger than the size cap: never read into memory


# ---------------------------------------------------------------- currency
async def test_prices_in_another_currency_need_a_deliberate_yes(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "usd.test"})).json()
    assert d["currency"] == "USD" and "not Taka" in d["warnings"][0]
    r = await http.post("/api/catalog/import", headers=h, json={"url": "usd.test"})
    assert r.status_code == 409 and "USD" in r.json()["detail"]
    assert db.get("SELECT COUNT(*) n FROM products WHERE source='usd.test'")["n"] == 0
    assert (await http.post("/api/catalog/import", headers=h, json={"url": "usd.test", "confirmCurrency": True})).status_code == 200
    sid = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]["id"]
    assert (await http.post(f"/api/catalog/sources/{sid}/sync", headers=h)).status_code == 200      # accepted once, so later syncs go through


async def test_a_site_that_never_states_its_currency_is_flagged_not_blocked(http, web):
    h = await owner(http)
    web.pages["/products/trail-boot"] = web.pages["/products/trail-boot"].replace('"priceCurrency": "BDT"', '"priceX": 1')
    web.pages["/products/rain-jacket"] = web.pages["/products/rain-jacket"].replace('"priceCurrency": "BDT"', '"priceX": 1')
    web.pages["/products/og-only"] = web.pages["/products/og-only"].replace("product:price:currency", "x")
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "pages.test"})).json()
    assert d["currency"] is None and "does not say which currency" in d["warnings"][0]


# ---------------------------------------------------------------- safety
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "localhost", "http://[::1]/", "169.254.169.254", "http://10.0.0.5/", "192.168.1.1", "0.0.0.0",
                                 "http://user:pw@pages.test/", "ftp://pages.test/", "pages.test:6379", "file:///etc/passwd", "not a url", "intranet"])
async def test_addresses_that_are_not_public_websites_are_refused_before_any_request(http, monkeypatch, url):
    h = await owner(http)
    calls = []
    ci.set_transport(httpx.MockTransport(lambda r: calls.append(str(r.url)) or httpx.Response(200)))
    try:
        r = await http.post("/api/catalog/discover", headers=h, json={"url": url})
    finally:
        ci.set_transport(None)
    assert r.status_code == 400 and calls == [], (url, r.text, calls)


async def test_a_redirect_to_a_private_address_is_not_followed(http, web):
    h = await owner(http)
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "redirect.test"})
    assert r.status_code == 400
    assert not any("169.254" in x for x in web.requests)         # the metadata address was never requested


async def test_only_people_who_manage_products_can_connect_a_site(http, web):
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    assert (await http.post("/api/catalog/discover", headers=H(agent), json={"url": "shopify.test"})).status_code == 403
    assert (await http.post("/api/catalog/import", headers=H(agent), json={"url": "shopify.test"})).status_code == 403
    assert (await http.get("/api/catalog/sources", headers=H(agent))).status_code == 200            # staff may see what is connected
    assert (await http.get("/api/catalog/sources")).status_code == 401


async def test_disconnecting_stops_syncing_but_keeps_the_products(http, web):
    h = await owner(http)
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    sid = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]["id"]
    assert (await http.delete(f"/api/catalog/sources/{sid}", headers=h)).status_code == 200
    assert (await http.get("/api/catalog/sources", headers=h)).json()["items"] == []
    assert product("RT-GRN") is not None
    assert (await http.post(f"/api/catalog/sources/{sid}/sync", headers=h)).status_code == 404
    # connecting again links back to the same products instead of duplicating them
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    assert db.get("SELECT COUNT(*) n FROM products WHERE source='shopify.test'")["n"] == 3


async def test_background_sync_keeps_going_when_one_site_fails(http, web):
    h = await owner(http)
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    await http.post("/api/catalog/import", headers=h, json={"url": "woo.test"})
    web.shopify[0]["variants"][0]["price"] = "100"
    web.woo.clear()                                    # the Woo store now answers with nothing usable
    await ci.sync_all()
    assert product("RT-GRN")["price"] == 100
    srcs = {s["host"]: s for s in (await http.get("/api/catalog/sources", headers=h)).json()["items"]}
    assert srcs["woo.test"]["lastError"] and not srcs["shopify.test"]["lastError"]


async def test_imports_are_in_the_audit_log(http, web):
    h = await owner(http)
    await http.post("/api/catalog/import", headers=h, json={"url": "shopify.test"})
    rows = db.all("SELECT * FROM audit WHERE action='catalog.import'")
    assert len(rows) == 1 and rows[0]["target"] == "shopify.test" and "3 added" in rows[0]["detail"]


async def test_a_shop_without_https_is_found_over_plain_http_and_synced_the_same_way(http, web):
    h = await owner(http)
    d = (await http.post("/api/catalog/discover", headers=h, json={"url": "plainhttp.test"})).json()
    assert d["url"].startswith("http://plainhttp.test") and d["kind"] == "shopify"
    await http.post("/api/catalog/import", headers=h, json={"url": d["url"]})
    src = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]
    assert src["url"].startswith("http://")
    assert (await http.post(f"/api/catalog/sources/{src['id']}/sync", headers=h)).status_code == 200
    # an address typed with https:// is never quietly downgraded
    r = await http.post("/api/catalog/discover", headers=h, json={"url": "https://plainhttp.test"})
    assert r.status_code == 400

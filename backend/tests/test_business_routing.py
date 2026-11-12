"""Phase 3 of many businesses: every public door (Meta webhook, shop-order webhook, payment return/IPN, courier webhook, website chat) names its
business in the address and uses that business's own secrets; background jobs run for every business without one stopping the others;
caches and rate limits never cross. A request signed for business A must never be accepted at business B."""
import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app import catalog_import, db, jobs, meta, metacfg, payments, publicbiz, registry, sms
from app.main import app
from app.providers import common as pcommon
from app.secrets_store import seal
from app.routes import providers as provider_routes, webchat
from tests.conftest import make_channel, settle
from tools.fake_graph import sign, wa_text

SEC_A, SEC_B, SEC_D = "secret-for-alpha", "secret-for-beta", "secret-for-default"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def businesses():
    a, b = registry.create("Alpha Store", "alpha"), registry.create("Beta Store", "beta")
    for slug, sec in (("alpha", SEC_A), ("beta", SEC_B), ("default", SEC_D)):
        with db.business(slug):
            metacfg.update(app_secret_=sec, verify_token_=f"verify-{slug}")
    webchat._last.clear()
    yield a, b
    db.close_all()
    for r in registry.all_businesses():
        if r["slug"] != "default":
            registry.delete(r["id"])
    import os
    os.environ.pop("DAKBOX_STRICT_BUSINESS", None)


def conv_count(slug):
    with db.business(slug):
        return db.get("SELECT COUNT(*) n FROM conversations")["n"]


def mark(slug):
    """A row in the business's own database, to tell the databases apart."""
    with db.business(slug):
        return db.get("SELECT value FROM settings WHERE key='meta'") is not None


async def meta_hook(http, slug, payload, secret):
    raw = json.dumps(payload).encode()
    path = f"/webhooks/meta/{slug}" if slug else "/webhooks/meta"
    r = await http.post(path, content=raw, headers={"content-type": "application/json", "x-hub-signature-256": sign(raw, secret)})
    await settle()
    return r


# ---------------------------------------------------------------- Meta
async def test_the_meta_handshake_uses_each_businesss_own_verify_token(http):
    q = lambda t: {"hub.mode": "subscribe", "hub.verify_token": t, "hub.challenge": "777"}      # noqa: E731
    assert (await http.get("/webhooks/meta/alpha", params=q("verify-alpha"))).text == "777"
    assert (await http.get("/webhooks/meta/beta", params=q("verify-beta"))).text == "777"
    assert (await http.get("/webhooks/meta/alpha", params=q("verify-beta"))).status_code == 403     # B's token at A's address
    assert (await http.get("/webhooks/meta/beta", params=q("verify-alpha"))).status_code == 403
    assert (await http.get("/webhooks/meta", params=q("verify-default"))).text == "777"             # the original address is the default business
    assert (await http.get("/webhooks/meta", params=q("verify-alpha"))).status_code == 403


async def test_a_message_reaches_only_the_business_whose_address_and_secret_it_used(http, graph):
    for slug, pid in (("alpha", "PHONE-A"), ("beta", "PHONE-B")):
        with db.business(slug):
            graph.add_wa(pid)
            make_channel("wa", pid)
    p = wa_text("PHONE-A", "8801712340042", "hello from a customer")
    assert (await meta_hook(http, "beta", p, SEC_A)).status_code == 401                  # A's secret at B's address
    assert (await meta_hook(http, "alpha", p, SEC_B)).status_code == 401                 # B's secret at A's address
    assert (await meta_hook(http, None, p, SEC_A)).status_code == 401                    # and at the original address
    assert conv_count("alpha") == conv_count("beta") == 0
    assert (await meta_hook(http, "alpha", p, SEC_A)).status_code == 200
    assert conv_count("alpha") == 1 and conv_count("beta") == 0
    # a payload for A's phone number, sent correctly signed to B's address, finds no channel there and creates nothing
    assert (await meta_hook(http, "beta", p, SEC_B)).status_code == 200
    assert conv_count("beta") == 0 and conv_count("alpha") == 1
    with db.business("alpha"):
        assert db.get("SELECT COUNT(*) n FROM webhook_log")["n"] >= 1


async def test_unknown_and_suspended_businesses_and_strict_installs_have_no_public_doors(http):
    p = wa_text("PHONE-A", "8801712340042", "hi")
    assert (await meta_hook(http, "nope", p, SEC_A)).status_code == 404
    assert (await http.get("/webhooks/meta/nope", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"})).status_code == 404
    registry.set_status("alpha", "suspended")
    assert (await meta_hook(http, "alpha", p, SEC_A)).status_code == 404
    registry.set_status("alpha", "active")
    import os
    os.environ["DAKBOX_STRICT_BUSINESS"] = "1"
    assert (await meta_hook(http, None, p, SEC_D)).status_code == 404                    # the original addresses are off on a hosted install
    assert (await http.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-default", "hub.challenge": "1"})).status_code == 404
    assert (await http.post("/hooks/steadfast", content=b"{}")).status_code == 404
    assert (await http.post("/pay/sslcommerz/ipn")).status_code == 404
    assert (await http.post("/api/webchat/send", json={"sid": "a" * 20, "text": "hi"})).status_code == 404
    assert (await http.get("/widget")).status_code == 404
    assert (await meta_hook(http, "default", p, SEC_D)).status_code == 200               # but the default business has an address of its own name


# ---------------------------------------------------------------- shop orders
def shop_sig(raw, secret):
    import base64
    return base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()


async def test_shop_order_webhooks_are_per_business(http):
    for slug, sid, sec in (("alpha", "cs_alpha", "alpha-shop-secret"), ("beta", "cs_beta", "beta-shop-secret")):
        with db.business(slug):
            db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,created_at,order_secret) VALUES(?,?,?,?,?,?,?)", [sid, f"{slug}.shop.test", f"https://{slug}.shop.test/", "shopify", 10, db.now(), seal(sec)])
    order = {"id": 7001, "name": "#1", "currency": "BDT", "financial_status": "pending", "total_price": "500.00", "payment_gateway_names": ["Cash on Delivery (COD)"],
             "shipping_address": {"name": "Buyer One", "phone": "01712345678", "address1": "House 1, Road 2, Dhaka", "city": "Dhaka"},
             "line_items": [{"id": 1, "variant_id": 5, "title": "Thing", "quantity": 1, "price": "500.00", "total_discount": "0"}]}
    raw = json.dumps(order).encode()
    hdr = lambda sec: {"X-Shopify-Hmac-Sha256": shop_sig(raw, sec), "X-Shopify-Topic": "orders/create", "content-type": "application/json"}      # noqa: E731
    assert (await http.post("/webhooks/shop/beta/cs_alpha", content=raw, headers=hdr("alpha-shop-secret"))).status_code == 404      # A's source id at B's address
    assert (await http.post("/webhooks/shop/alpha/cs_beta", content=raw, headers=hdr("beta-shop-secret"))).status_code == 404
    assert (await http.post("/webhooks/shop/cs_alpha", content=raw, headers=hdr("alpha-shop-secret"))).status_code == 404         # the original address: the default business has no such source
    assert (await http.post("/webhooks/shop/alpha/cs_alpha", content=raw, headers=hdr("beta-shop-secret"))).status_code == 401    # right address, wrong business's secret
    r = await http.post("/webhooks/shop/alpha/cs_alpha", content=raw, headers=hdr("alpha-shop-secret"))
    assert r.status_code == 200 and r.json()["created"]
    with db.business("alpha"):
        assert db.get("SELECT COUNT(*) n FROM orders WHERE source='website'")["n"] == 1
    with db.business("beta"):
        assert db.get("SELECT COUNT(*) n FROM orders")["n"] == 0
    with db.business("default"):
        assert db.get("SELECT COUNT(*) n FROM orders WHERE source='website'")["n"] == 0
    with db.business("alpha"):
        src = db.get("SELECT * FROM catalog_sources WHERE id='cs_alpha'")
        from app import shop_orders
        assert shop_orders.webhook_path(src) == "/webhooks/shop/alpha/cs_alpha"
    with db.business("default"):
        assert shop_orders.webhook_path({"id": "cs_x"}) == "/webhooks/shop/cs_x"          # the default business keeps the original address


# ---------------------------------------------------------------- payments and the courier
async def test_payment_callbacks_run_in_the_business_named_in_the_address(http, monkeypatch):
    seen = []

    async def fake(provider, kind, params):
        seen.append((db.current(), provider, kind, params.get("tran_id")))
        return {"outcome": "unknown", "order": None}
    monkeypatch.setattr(payments, "handle_callback", fake)
    a, b = registry.resolve("alpha")["id"], registry.resolve("beta")["id"]
    await http.get("/pay/alpha/sslcommerz/cancel", params={"tran_id": "T1"})
    await http.post("/pay/beta/sslcommerz/ipn", data={"tran_id": "T2"})
    await http.get("/pay/sslcommerz/fail", params={"tran_id": "T3"})
    assert seen == [(a, "sslcommerz", "cancel", "T1"), (b, "sslcommerz", "ipn", "T2"), (registry.default_id(), "sslcommerz", "fail", "T3")]
    assert (await http.get("/pay/nope/sslcommerz/cancel")).status_code == 404
    assert (await http.get("/pay/alpha/unknownpay/cancel")).status_code == 404


def test_the_addresses_the_app_gives_to_gateways_and_couriers_name_the_business():
    with db.business("alpha"):
        urls = {u["label"].split(" ")[0]: u["url"] for u in provider_routes._urls("sslcommerz", "https://pub.example", {})}
        assert urls["Success"] == "https://pub.example/pay/alpha/sslcommerz/success" and urls["IPN"].endswith("/pay/alpha/sslcommerz/ipn")
        assert provider_routes._urls("steadfast", "https://pub.example", {})[0]["url"] == "https://pub.example/hooks/alpha/steadfast"
        assert metacfg.webhook_url().endswith("/webhooks/meta/alpha")
        assert publicbiz.seg() == "/alpha" and publicbiz.slug() == "alpha"
    with db.business("default"):
        assert provider_routes._urls("sslcommerz", "https://pub.example", {})[0]["url"] == "https://pub.example/pay/sslcommerz/success"       # unchanged: already configured at the gateway
        assert provider_routes._urls("steadfast", "https://pub.example", {})[0]["url"] == "https://pub.example/hooks/steadfast"
        assert metacfg.webhook_url().endswith("/webhooks/meta") and publicbiz.seg() == ""
    import os
    os.environ["DAKBOX_STRICT_BUSINESS"] = "1"
    try:
        with db.business("default"):
            assert publicbiz.seg() == "/default"
    finally:
        os.environ.pop("DAKBOX_STRICT_BUSINESS")


async def test_a_courier_webhook_only_works_with_the_secret_of_the_business_in_its_address(http):
    for slug, sec in (("alpha", "alpha-hook-secret"), ("beta", "beta-hook-secret")):
        with db.business(slug):
            pcommon.save("steadfast", {"api_key": "k", "secret_key": "s"}, {"mode": "live", "webhook_secret": sec}, "Steadfast")
    ok = await http.post("/hooks/alpha/steadfast", content=b'{"consignment_id": "1"}', headers={"authorization": "Bearer alpha-hook-secret"})
    assert ok.status_code == 200
    assert (await http.post("/hooks/alpha/steadfast", content=b"{}", headers={"authorization": "Bearer beta-hook-secret"})).status_code == 401
    assert (await http.post("/hooks/beta/steadfast", content=b"{}", headers={"authorization": "Bearer alpha-hook-secret"})).status_code == 401
    assert (await http.post("/hooks/steadfast", content=b"{}", headers={"authorization": "Bearer alpha-hook-secret"})).status_code == 401     # the default business has none
    assert (await http.post("/hooks/nope/steadfast", content=b"{}", headers={"authorization": "Bearer alpha-hook-secret"})).status_code == 404


# ---------------------------------------------------------------- website chat
async def test_website_chat_belongs_to_the_business_it_was_opened_for(http):
    sid = "abcdefghij0123456789x1"
    for slug in ("alpha", "beta"):
        with db.business(slug):
            db.run("UPDATE channels SET handle=? WHERE id='ch_web'", [slug])
    assert (await http.post("/api/webchat/send", json={"sid": sid, "text": "Do you have a saree?", "b": "alpha"})).status_code == 200
    await settle()
    assert conv_count("alpha") == 1 and conv_count("beta") == 0
    mine = (await http.get("/api/webchat/messages", params={"sid": sid, "b": "alpha"})).json()["items"]
    assert [m["text"] for m in mine if m["role"] == "me"] == ["Do you have a saree?"]
    assert (await http.get("/api/webchat/messages", params={"sid": sid, "b": "beta"})).json()["items"] == []           # B's chat with the same visitor id is empty
    assert (await http.get("/api/webchat/messages", params={"sid": sid})).json()["items"] == []                          # and so is the default business
    assert (await http.get("/api/webchat/messages", params={"sid": sid, "b": "nope"})).status_code == 404
    # the same visitor id may chat with two businesses at the same moment: the rate limit is per business
    assert (await http.post("/api/webchat/send", json={"sid": sid, "text": "hi", "b": "beta"})).status_code == 200
    assert (await http.post("/api/webchat/send", json={"sid": sid, "text": "again", "b": "beta"})).status_code == 429
    await settle()
    assert conv_count("beta") == 1


async def test_the_widget_page_names_its_business_and_escapes_the_name(http):
    with db.business("alpha"):
        from app.agent.tools import agent_settings
        db.set_setting("agent", {**agent_settings(), "storeName": "Alpha <b>&</b> Co"})
    html = (await http.get("/widget", params={"b": "alpha"})).text
    assert "Alpha &lt;b&gt;&amp;&lt;/b&gt; Co" in html and "<b>&</b>" not in html and "const B='alpha'" in html
    assert (await http.get("/widget", params={"b": "nope"})).status_code == 404
    assert "const B=''" in (await http.get("/widget")).text                               # the original page: the default business
    assert (await http.get("/widget", params={"b": "a b;<script>"})).status_code == 404                # anything that is not a business is refused, never echoed into the page


# ---------------------------------------------------------------- background jobs
async def test_a_job_runs_once_per_active_business_inside_that_business():
    registry.set_status("beta", "suspended")
    seen = []

    async def work():
        seen.append(db.current())
    res = await jobs.for_each_business("t", work)
    assert sorted(res["ok"]) == ["alpha", "default"] and res["failed"] == {} and registry.resolve("beta")["id"] not in seen
    assert set(seen) == {registry.resolve("alpha")["id"], registry.default_id()}


async def test_a_broken_or_slow_business_never_stops_the_others():
    async def work():
        slug = registry.resolve(db.current())["slug"]
        if slug == "alpha":
            raise RuntimeError("boom")
        if slug == "beta":
            await asyncio.sleep(5)
        db.set_setting("ran", slug)
    res = await jobs.for_each_business("t", work, timeout=0.3)
    assert res["failed"] == {"alpha": "RuntimeError", "beta": "timed out"} and res["ok"] == ["default"]
    with db.business("default"):
        assert db.get_setting("ran") == "default"
    for s in ("alpha", "beta"):
        with db.business(s):
            assert db.get_setting("ran") is None


async def test_the_timers_do_their_work_in_every_business(monkeypatch):
    calls = []

    async def due():
        calls.append(("due", registry.resolve(db.current())["slug"]))

    async def reports():
        calls.append(("reports", registry.resolve(db.current())["slug"]))

    async def poll():
        calls.append(("poll", registry.resolve(db.current())["slug"]))
        return 0

    async def sync_all():
        calls.append(("sync", registry.resolve(db.current())["slug"]))
    monkeypatch.setattr(sms, "process_due", due)
    monkeypatch.setattr(sms, "poll_reports", reports)
    from app import couriers
    monkeypatch.setattr(couriers, "poll_all", poll)
    monkeypatch.setattr(catalog_import, "sync_all", sync_all)
    await jobs.sms_tick()
    await jobs.poll_couriers()
    await jobs.sync_catalogs()
    for kind in ("due", "reports", "poll", "sync"):
        assert {s for k, s in calls if k == kind} == {"default", "alpha", "beta"}, kind


async def test_the_channel_recheck_uses_each_businesss_own_channels_and_tokens(monkeypatch, graph):
    for slug, pid in (("alpha", "PHONE-A"), ("beta", "PHONE-B")):
        with db.business(slug):
            graph.add_wa(pid)
            make_channel("wa", pid)
    checked = []

    async def check(c):
        checked.append((registry.resolve(db.current())["slug"], c["external_id"]))
    monkeypatch.setattr(meta, "check_channel", check)
    await jobs.recheck_channels()
    assert ("alpha", "PHONE-A") in checked and ("beta", "PHONE-B") in checked and ("alpha", "PHONE-B") not in checked and ("beta", "PHONE-A") not in checked


# ---------------------------------------------------------------- caches
def test_cached_results_never_cross_businesses():
    from app.catalog_import import Found
    found = Found("shopify", "https://x", "x")
    import time
    with db.business("alpha"):
        catalog_import._cache[(db.current(), "https://x/")] = (time.monotonic(), found)
        assert catalog_import._cache.get((db.current(), "https://x/")) is not None
    with db.business("beta"):
        assert catalog_import._cache.get((db.current(), "https://x/")) is None
    with db.business("alpha"):
        meta._tpl_cache[(db.current(), "ch1")] = (time.time(), [{"name": "t"}])
    with db.business("beta"):
        assert meta._tpl_cache.get((db.current(), "ch1")) is None
    catalog_import._cache.clear()
    meta._tpl_cache.clear()

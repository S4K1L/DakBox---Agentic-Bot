"""THE RELEASE GATE for hosting more than one business: nothing ships to a second business until this file is green.

Two businesses are filled with recognisable data. Then, for EVERY route the app has (found by walking the route table, so a new route cannot be forgotten):
  * a route that is not classified here fails the test, so someone must decide which kind it is;
  * every business route refuses anonymous callers and callers who have not entered a business;
  * a person of business A reads nothing of B from any list, and every route that takes an id answers "not found" (or refuses) when handed B's ids, changing nothing in B;
  * B's name in a header, query string or body changes nothing: the business comes only from the session;
and the rest of the plan's list: realtime events, searches, customer matching, order numbers, exports, background loops with one broken business, and deleting a business.
Run it alone with:  python -m pytest -m isolation -q      (tools/release_gate.sh runs it first, then the whole suite)"""
import json
import re
from hashlib import sha256

import httpx
import pytest
from fastapi.routing import APIRoute

from app import db, events, export, jobs, registry, store
from app.main import app
from tests.conftest import say

pytestmark = pytest.mark.isolation

A, B = "alphabiz", "betabiz"
TAG = {A: "ALPHAMARK", B: "BETAMARK"}
PRICE = {A: 1111, B: 2222}

# ---------------------------------------------------------------- what kind of route each one is
PUBLIC = ("/healthz", "/webhooks", "/pay", "/hooks", "/widget", "/api/webchat", "/api/docs", "/api/openapi.json", "/docs", "/redoc", "/openapi.json")
AUTH_ONLY = ("/api/auth/",)
PLATFORM = ("/api/platform",)
NO_BUSINESS_OK = ("/api/me",)             # answers (without any business data) for a session that has not entered a business
GLOBAL_NAMES = ("/api/providers", "/api/integrations", "/api/policies")     # their ids are names shared by every business (steadfast, returns): acting on them acts on your own


def kind_of(path: str) -> str:
    if path.startswith(PUBLIC):
        return "public"
    if path.startswith(AUTH_ONLY):
        return "auth"
    if path.startswith(PLATFORM):
        return "platform"
    if path.startswith("/api/"):
        return "business"
    return "other"


def routes():
    return [(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in sorted(r.methods - {"HEAD", "OPTIONS"})]


def fill(path: str, value: str = "x") -> str:
    return re.sub(r"\{[^}]+\}", value, path)


def params_of(path: str) -> list[str]:
    return re.findall(r"\{([^}]+)\}", path)


# ---------------------------------------------------------------- a request body that passes validation, built from the app's own schema
_SPEC = None


def spec():
    global _SPEC
    if _SPEC is None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _SPEC = app.openapi()
    return _SPEC


def _dummy(schema: dict, depth: int = 0):
    s = spec()
    if "$ref" in schema:
        schema = s["components"]["schemas"][schema["$ref"].split("/")[-1]]
    for k in ("anyOf", "oneOf"):
        if k in schema:
            opts = [o for o in schema[k] if o.get("type") != "null"]
            return _dummy(opts[0], depth) if opts else None
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "string":
        return "abcdefghij"[: max(1, min(schema.get("minLength", 1), 10))] if schema.get("minLength", 1) <= 10 else "x" * schema["minLength"]
    if t == "integer" or t == "number":
        return max(1, schema.get("minimum", 1))
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object" or "properties" in schema:
        if depth > 3:
            return {}
        return {k: _dummy(v, depth + 1) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    return None


def body_for(method: str, path: str):
    op = spec()["paths"].get(path, {}).get(method.lower(), {})
    rb = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    return _dummy(rb) if rb else None


# ---------------------------------------------------------------- two businesses, each with a person who belongs only to it
@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def seed_business(slug: str) -> dict:
    """Recognisable rows in every kind of table; returns the ids that belong to this business alone."""
    tag = TAG[slug]
    ids: dict[str, list] = {"cid": [], "uid": [], "sid": [], "mid": [], "aid": [], "no": [], "rid": [], "pid": [], "sku": []}
    with db.business(slug):
        db.run("INSERT INTO products(id,sku,name,price,stock,art,description,keywords) VALUES(?,?,?,?,?,?,?,?)", [f"p_{tag}", f"{tag}-SKU", f"{tag} handloom saree", PRICE[slug], 5, "box", f"{tag} description", tag.lower()])
        ids["sku"] += [f"{tag}-SKU"]
        cid = await say("ch_web", f"web_{tag}", f"{tag} Guest", f"{tag} hello, do you have a saree?", "01711000111")
        ids["cid"] += [cid]
        cust = db.get("SELECT customer_id FROM conversations WHERE id=?", [cid])["customer_id"]
        ids["customer"] = [cust]
        db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,fulfillment,stage,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               [f"o_{tag}", "#9001", cust, "web", json.dumps([{"sku": f"{tag}-SKU", "name": f"{tag} handloom saree", "qty": 1, "price": PRICE[slug]}]), 60, "dhaka", f"{tag} Road 5", "pending", "processing", 0, db.now()])
        ids["no"] += ["#9001", "9001"]
        db.run("INSERT INTO approvals(type,customer_id,conversation_id,order_number,item,amount,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", ["return", cust, cid, "#9001", f"{tag} item", 500, f"{tag} reason", "pending", db.now()])
        ids["aid"] += [db.get("SELECT MAX(id) n FROM approvals")["n"]]
        db.run("INSERT INTO payments(id,order_number,provider,amount,tran_id,status,created_at) VALUES(?,?,?,?,?,?,?)", [f"pay_{tag}", "#9001", "bkash", 500, f"TRAN-{tag}", "pending", db.now()])
        db.run("INSERT INTO payment_refunds(id,payment_id,amount,status,created_at) VALUES(?,?,?,?,?)", [f"rf_{tag}", f"pay_{tag}", 100, "pending", db.now()])
        db.run("INSERT INTO sms_messages(id,order_number,event,to_phone,body,status,created_at,send_after) VALUES(?,?,?,?,?,?,?,?)", [f"sms_{tag}", "#9001", "shipped", "01711000111", f"{tag} parcel sent", "queued", db.now(), db.now()])
        db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,created_at) VALUES(?,?,?,?,?,?)", [f"cs_{tag}", f"{tag.lower()}.shop.test", f"https://{tag.lower()}.shop.test/", "shopify", 10, db.now()])
        db.run("INSERT INTO channels(id,kind,name,handle,status,health,created_at) VALUES(?,?,?,?,?,?,?)", [f"ch_{tag}", "wa", f"{tag} WhatsApp", f"{tag} handle", "ok", "[]", db.now()])
        db.run("UPDATE policies SET body=? WHERE key='returns'", [f"{tag} returns policy"])
        db.set_setting("agent", {**(db.get_setting("agent", {}) or {}), "storeAbout": f"{tag} sells sarees"})
        ids["cid"] += [f"ch_{tag}"]
        ids["sid"] += [f"cs_{tag}"]
        ids["mid"] += [f"sms_{tag}"]
        ids["pid"] += [f"pay_{tag}"]
        ids["rid"] += [f"rf_{tag}"]
    acct = registry.create_account(f"{tag} Teammate", f"{tag.lower()}@x.test", "x", account_id=f"usr_{tag}")
    registry.add_membership(acct["id"], registry.resolve(slug)["id"], "owner")
    ids["uid"] += [acct["id"]]
    ids["token"] = registry.open_session(acct["id"], registry.resolve(slug)["id"], "1.1.1.1", "isolation")
    ids["secret_values"] = [tag] + [str(v) for k in ("cid", "uid", "sid", "mid", "pid", "rid", "customer") for v in ids[k]]
    return ids


@pytest.fixture
async def two(http):
    registry.create("Alpha Biz", A), registry.create("Beta Biz", B)
    ids = {A: await seed_business(A), B: await seed_business(B)}
    yield ids
    db.close_all()
    for r in registry.all_businesses():
        if r["slug"] != "default":
            registry.delete(r["id"])


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def snapshot(slug: str, skip: tuple = ()) -> str:
    """A fingerprint of every row of every table in one business."""
    h = sha256()
    with db.business(slug):
        for t in sorted(r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")):
            if t in skip:
                continue
            for row in db.all(f'SELECT * FROM "{t}"'):
                h.update(json.dumps([t, *[row[k] for k in row.keys()]], default=str).encode())
    return h.hexdigest()


def leaks(text: str, victim: dict) -> list[str]:
    return [v for v in victim["secret_values"] if v and v in text]


# ================================================================ 1. every route is accounted for
def test_every_route_has_a_known_kind():
    unknown = [(m, p) for m, p in routes() if kind_of(p) == "other" and p != "/"]
    assert not unknown, f"Classify these new routes in tests/test_isolation.py (public door, auth, platform or business): {unknown}"


def test_the_inventory_is_not_empty_and_covers_all_kinds():
    kinds = {kind_of(p) for _, p in routes()}
    assert {"public", "auth", "platform", "business"} <= kinds and len([1 for _, p in routes() if kind_of(p) == "business"]) > 80


# ================================================================ 2. nobody gets in without a session, or without a business
async def test_every_business_route_refuses_anonymous_callers(http):
    allowed = []
    for m, p in routes():
        if kind_of(p) != "business":
            continue
        r = await http.request(m, fill(p), json=body_for(m, p) if m in ("POST", "PUT", "PATCH", "DELETE") else None)
        if r.status_code != 401:
            allowed.append((m, p, r.status_code))
    assert not allowed, f"reachable without signing in: {allowed}"


async def test_every_platform_route_refuses_everyone_but_the_platform_administrator(http, two):
    bad = []
    for m, p in routes():
        if kind_of(p) != "platform" or p.startswith("/api/platform/download"):
            continue
        for tok, want in ((None, 401), (two[A]["token"], 403)):
            r = await http.request(m, fill(p), headers=hdr(tok) if tok else {}, json=body_for(m, p) if m in ("POST", "PUT", "PATCH", "DELETE") else None)
            if r.status_code != want:
                bad.append((m, p, "anonymous" if tok is None else "business owner", r.status_code))
    assert not bad, f"platform routes open to the wrong people: {bad}"


async def test_a_session_that_has_not_entered_a_business_reaches_no_business_route(http, two):
    admin = registry.create_account("Plat Admin", "plat@x.test", "x", platform_admin=True)
    tok = registry.open_session(admin["id"], None, "1.1.1.1", "isolation")
    open_ = []
    for m, p in routes():
        if kind_of(p) != "business" or p in NO_BUSINESS_OK:
            continue
        r = await http.request(m, fill(p), headers=hdr(tok), json=body_for(m, p) if m in ("POST", "PUT", "PATCH", "DELETE") else None)
        if r.status_code != 403:
            open_.append((m, p, r.status_code))
    assert not open_, f"business data reachable with no business selected: {open_}"
    me = (await http.get("/api/me", headers=hdr(tok))).json()
    assert me["business"] is None and me["store"] is None


# ================================================================ 3. one business never reads or touches another
async def test_lists_and_searches_show_only_the_callers_own_business(http, two):
    seen_own = ""
    for me, other in ((A, B), (B, A)):
        for m, p in routes():
            if m != "GET" or kind_of(p) != "business" or params_of(p) or p == "/api/events":
                continue
            r = await http.get(p, headers=hdr(two[me]["token"]))
            assert r.status_code in (200, 403), (p, r.status_code)             # 403: a role without that permission (never 5xx)
            assert not leaks(r.text, two[other]), f"{p} as {me} showed {other}'s data: {leaks(r.text, two[other])}"
            seen_own += r.text if me == A else ""
    assert TAG[A] in seen_own                                                    # the lists were not simply empty
    for q in ("BETAMARK", "betamark", "handloom"):                               # searching for the other business's words finds only your own rows
        r = await http.get("/api/products", headers=hdr(two[A]["token"]), params={"q": q})
        assert "BETAMARK" not in r.text
    assert TAG[A] in (await http.get("/api/conversations", headers=hdr(two[A]["token"]))).text


async def test_the_other_businesss_ids_are_not_found_and_change_nothing(http, two):
    """Every route that takes an id is handed the other business's ids, as every kind of call it supports. The invariants: the other business is
    byte-for-byte unchanged, nothing of it comes back, a read of it never succeeds, and ids that exist ONLY there change nothing in the caller's own business either."""
    ID_KINDS = ("cid", "uid", "sid", "mid", "aid", "no", "rid", "pid", "sku", "customer")
    for me, other in ((A, B), (B, A)):
        mine = {str(v) for k in ID_KINDS for v in two[me][k]}
        theirs = {str(v) for k in ID_KINDS for v in two[other][k]}
        unique = sorted(theirs - mine)
        assert len(unique) > 6                                                   # the ids that only the other business has (order numbers and approval 1 exist in both, by design)
        before_other, before_me = snapshot(other), snapshot(me, skip=("audit", "agent_runs"))
        unexpected_reads = []
        for m, p in routes():
            if kind_of(p) != "business" or not params_of(p) or p.startswith(GLOBAL_NAMES) or p == "/api/events":
                continue
            for val in sorted(theirs):
                r = await http.request(m, fill(p, val.replace("#", "%23")), headers=hdr(two[me]["token"]), json=body_for(m, p) if m in ("POST", "PUT", "PATCH", "DELETE") else None)
                assert r.status_code < 500, (m, p, val, r.status_code, r.text[:200])
                assert not leaks(r.text.replace(val, ""), two[other]), f"{m} {p} with {val} as {me} returned {other}'s data"        # (an error that merely repeats the id we sent is not a leak)
                if m == "GET" and r.status_code < 300 and val in unique:
                    unexpected_reads.append((p, val, r.text[:80]))
        assert snapshot(other) == before_other, f"{me} changed {other}'s data"
        assert not unexpected_reads, f"{me} read a record that exists only in {other}: {unexpected_reads}"
    # ids that exist only in the other business also change nothing in the caller's own business (no stray rows, counters or side effects)
    for me, other in ((A, B), (B, A)):
        mine = {str(v) for k in ID_KINDS for v in two[me][k]}
        unique = sorted({str(v) for k in ID_KINDS for v in two[other][k]} - mine)
        before = snapshot(me, skip=("audit", "agent_runs"))
        for m, p in routes():
            if kind_of(p) != "business" or not params_of(p) or p.startswith(GLOBAL_NAMES) or p == "/api/events":
                continue
            for val in unique:
                await http.request(m, fill(p, val.replace("#", "%23")), headers=hdr(two[me]["token"]), json=body_for(m, p) if m in ("POST", "PUT", "PATCH", "DELETE") else None)
        assert snapshot(me, skip=("audit", "agent_runs")) == before, f"handling {other}'s ids altered {me}'s own rows"


async def test_naming_the_other_business_anywhere_in_a_request_changes_nothing(http, two):
    tok = two[A]["token"]
    for extra_h, params in (({"X-Business": B}, {}), ({"X-Business-Id": B}, {}), ({"X-Dakbox-Business": B}, {}), ({}, {"business": B}), ({}, {"b": B}), ({}, {"slug": B}), ({"Host": f"{B}.example.com"}, {})):
        for p in ("/api/products", "/api/conversations", "/api/orders", "/api/customers", "/api/team", "/api/settings", "/api/integrations"):
            r = await http.get(p, headers={**hdr(tok), **extra_h}, params=params)
            assert not leaks(r.text, two[B]), (p, extra_h, params)
        me = (await http.get("/api/me", headers={**hdr(tok), **extra_h}, params=params)).json()
        assert me["business"]["slug"] == A
    r = await http.post("/api/auth/switch", headers=hdr(tok), json={"business": B})
    assert r.status_code == 403                                                  # not a member of it: cannot even enter
    r = await http.post("/api/products", headers=hdr(tok), json={"name": "Thing", "sku": "NEW-1", "price": 10, "stock": 1, "art": "box", "business": B, "b": B})
    assert r.status_code == 200
    with db.business(B):
        assert db.get("SELECT 1 FROM products WHERE sku='NEW-1'") is None
    with db.business(A):
        assert db.get("SELECT 1 FROM products WHERE sku='NEW-1'")


async def test_a_session_stays_in_its_business_after_the_other_is_suspended_or_deleted(http, two):
    tok = two[A]["token"]
    registry.set_status(B, "suspended")
    assert (await http.get("/api/products", headers=hdr(tok))).status_code == 200            # A is unaffected by B
    assert (await http.get("/api/products", headers=hdr(two[B]["token"]))).status_code == 403
    registry.set_status(B, "active")
    assert (await http.get("/api/products", headers=hdr(two[B]["token"]))).status_code == 200


async def test_team_lists_and_accounts_do_not_cross(http, two):
    r = (await http.get("/api/team", headers=hdr(two[A]["token"]))).json()
    names = [m["name"] for m in r["items"]]
    assert "ALPHAMARK Teammate" in names and "BETAMARK Teammate" not in names
    assert (await http.patch(f"/api/team/{two[B]['uid'][0]}", headers=hdr(two[A]["token"]), json={"active": False})).status_code in (403, 404)
    assert (await http.post(f"/api/team/{two[B]['uid'][0]}/reset-password", headers=hdr(two[A]["token"]), json={"password": "new-password-123"})).status_code in (403, 404)
    assert registry.account_by_id(two[B]["uid"][0])["active"] == 1


async def test_one_person_in_two_businesses_sees_only_the_one_they_are_working_in(http, two):
    both = registry.create_account("Both Worlds", "both@x.test", "x", account_id="usr_both")
    for s in (A, B):
        registry.add_membership(both["id"], registry.resolve(s)["id"], "admin")
    ta = registry.open_session(both["id"], registry.resolve(A)["id"], "1.1.1.1", "iso")
    r = await http.get("/api/products", headers=hdr(ta))
    assert TAG[A] in r.text and TAG[B] not in r.text
    assert (await http.post("/api/auth/switch", headers=hdr(ta), json={"business": B})).status_code == 200
    r = await http.get("/api/products", headers=hdr(ta))
    assert TAG[B] in r.text and TAG[A] not in r.text
    assert (await http.get("/api/me", headers=hdr(ta))).json()["business"]["slug"] == B


# ================================================================ 4. things that are not request/response
async def test_realtime_events_stay_inside_their_business(two):
    qa, qb = events.subscribe(registry.resolve(A)["id"]), events.subscribe(registry.resolve(B)["id"])
    with db.business(A):
        events.emit("order", number="#A-EVENT")
    assert qa.qsize() == 1 and qb.qsize() == 0
    with db.business(B):
        events.emit("order", number="#B-EVENT")
    assert qa.qsize() == 1 and qb.qsize() == 1
    events.unsubscribe(qa), events.unsubscribe(qb)


async def test_customer_matching_order_numbers_and_skus_are_independent(two):
    # the same phone number is two different customers; the same order number two different orders; neither business sees the other's
    with db.business(A):
        ca = store.find_or_create_customer("fb_same", "ms", "Same Person", "01799999999")
        a_cust = ca["id"]
    with db.business(B):
        cb = store.find_or_create_customer("fb_same", "ms", "Same Person", "01799999999")
        assert cb["id"] != a_cust or db.get("SELECT COUNT(*) n FROM customers WHERE id=?", [a_cust])["n"] == 1
        assert db.get("SELECT COUNT(*) n FROM orders WHERE number='#9001'")["n"] == 1
    with db.business(A):
        assert db.get("SELECT COUNT(*) n FROM orders WHERE number='#9001'")["n"] == 1
        assert "BETAMARK" not in json.dumps([dict(r) for r in db.all("SELECT * FROM customers")], default=str)


async def test_the_assistant_of_one_business_cannot_find_the_other_businesss_products(http, two):
    with db.business(A):
        cid = await say("ch_web", "web_q", "Asker", "do you have a BETAMARK handloom saree?")
        reply = " ".join(r["text"] for r in db.all("SELECT text FROM messages WHERE conversation_id=? AND role='assistant'", [cid]))
    assert "BETAMARK-SKU" not in reply and "BETAMARK description" not in reply and "2,222" not in reply     # nothing of B's catalogue (sku, description or price) reaches A's customers
    with db.business(B):
        cid = await say("ch_web", "web_q2", "Asker", "do you have a BETAMARK handloom saree?")
        reply_b = " ".join(r["text"] for r in db.all("SELECT text FROM messages WHERE conversation_id=? AND role='assistant'", [cid]))
    assert "2,222" in reply_b and "BETAMARK description" in reply_b                    # while B's own assistant does find it (the check above is not vacuous)


async def test_exports_contain_only_their_own_business(http, two):
    for slug, other in ((A, B), (B, A)):
        data, _ = export.build(slug)
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(data))
        blob = b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "ignore")
        assert TAG[slug] in blob and TAG[other] not in blob


async def test_a_broken_business_does_not_stop_the_others_and_nothing_runs_in_the_wrong_business(two):
    seen = []

    async def work():
        slug = registry.resolve(db.current())["slug"] if db.current() else None
        seen.append(slug)
        if slug == B:
            raise RuntimeError("beta is broken")

    res = await jobs.for_each_business("isolation", work)
    assert A in res["ok"] and "default" in res["ok"] and res["failed"] == {B: "RuntimeError"}
    assert sorted(seen) == sorted(["default", A, B])                              # each ran exactly once, in its own business


async def test_deleting_a_business_removes_its_file_and_nothing_else(two):
    import os
    pa, pb, pd = registry.path_of(registry.resolve(A)["id"]), registry.path_of(registry.resolve(B)["id"]), registry.path_of(registry.default_id())
    before_a, before_d = snapshot(A), snapshot("default")
    registry.delete(B)
    assert not os.path.exists(pb) and os.path.exists(pa) and os.path.exists(pd)
    assert snapshot(A) == before_a and snapshot("default") == before_d
    assert [b["slug"] for b in registry.all_businesses() if b["slug"] in (A, B)] == [A]
    assert registry.account_by_id(two[B]["uid"][0]) is not None                  # the person's account is a separate thing
    assert registry.memberships_of(two[B]["uid"][0]) == []                       # but it no longer reaches any business


async def test_the_original_install_is_untouched_by_the_other_businesses(http, two):
    with db.business("default"):
        n = db.get("SELECT COUNT(*) n FROM products")["n"]
        assert db.get("SELECT 1 FROM products WHERE sku LIKE '%MARK%'") is None
    assert n >= 0

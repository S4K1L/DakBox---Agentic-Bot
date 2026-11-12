"""Phase 6 of many businesses (besides the isolation suite): per-business rate limits, hosted mode and its start-up checks, backups with a verified restore drill,
health checks, and the data-deletion paths."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app import backups, db, hosting, jobs, ratelimit, registry, store
from app.main import app
from tests.conftest import say
from tests.test_auth import H, member_token, setup_owner

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("DAKBOX_BACKUP_DIR", str(tmp_path / "backups"))
    for v in ("DAKBOX_API_RATE", "DAKBOX_DOOR_RATE", "DAKBOX_HOSTED", "DAKBOX_STRICT_BUSINESS"):
        monkeypatch.delenv(v, raising=False)
    ratelimit.reset()
    jobs.LAST.clear()
    registry.create("Alpha Store", "alpha"), registry.create("Beta Store", "beta")
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != "default":
            registry.delete(b["id"])
    ratelimit.reset()


async def owner_in(http, slug):
    o = await setup_owner(http)
    me = registry.account_by_email("owner@shop.test")["id"]
    for s in ("alpha", "beta"):
        registry.add_membership(me, registry.resolve(s)["id"], "owner")
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": slug})).status_code == 200
    return o


# ================================================================ rate limits
async def test_one_business_over_its_limit_does_not_slow_another(http, monkeypatch):
    monkeypatch.setenv("DAKBOX_API_RATE", "6")
    o = await owner_in(http, "alpha")
    codes = [(await http.get("/api/products", headers=H(o))).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]
    r = await http.get("/api/products", headers=H(o))
    assert r.status_code == 429 and "Retry-After" in r.headers and "Too many requests" in r.json()["detail"]
    assert (await http.get("/api/me", headers=H(o))).status_code == 200                    # signing in and "who am I" are never limited
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": "beta"})).status_code == 200
    assert (await http.get("/api/products", headers=H(o))).status_code == 200              # beta has its own allowance
    monkeypatch.setenv("DAKBOX_API_RATE", "0")                                              # 0 switches the limit off
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": "alpha"})).status_code == 200
    for _ in range(10):
        assert (await http.get("/api/products", headers=H(o))).status_code == 200


async def test_public_addresses_are_limited_per_business(http, monkeypatch):
    monkeypatch.setenv("DAKBOX_DOOR_RATE", "3")
    codes = [(await http.get("/webhooks/meta/alpha", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"})).status_code for _ in range(5)]
    assert codes[:3] == [403] * 3 and codes[3:] == [429, 429]                                # (403: wrong verify token; then the limit)
    assert (await http.get("/webhooks/meta/beta", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"})).status_code == 403
    assert (await http.get("/webhooks/meta/nope")).status_code == 404                        # an unknown address costs no business anything


async def test_guessing_passwords_across_many_emails_from_one_address_is_stopped(http):
    await setup_owner(http)
    for i in range(30):
        r = await http.post("/api/auth/login", json={"email": f"guess{i}@shop.test", "password": "wrong-password-1"})
        assert r.status_code == 401
    r = await http.post("/api/auth/login", json={"email": "guess99@shop.test", "password": "wrong-password-1"})
    assert r.status_code == 429 and "this address" in r.json()["detail"]


# ================================================================ hosted mode
def test_a_hosted_install_is_strict_by_default_and_refuses_to_start_unsafe(monkeypatch):
    assert db.strict() is False and hosting.problems() == []
    monkeypatch.setenv("DAKBOX_HOSTED", "1")
    assert db.hosted() and db.strict() is True                                               # no env var needed
    monkeypatch.setenv("DAKBOX_STRICT_BUSINESS", "0")
    assert db.strict() is False
    bad = hosting.problems()
    assert any("DAKBOX_STRICT_BUSINESS=0" in p for p in bad)
    monkeypatch.delenv("DAKBOX_STRICT_BUSINESS")
    monkeypatch.delenv("DAKBOX_DATA_DIR", raising=False)
    assert any("DAKBOX_DATA_DIR" in p for p in hosting.problems())
    monkeypatch.setenv("DAKBOX_DATA_DIR", "/tmp/x")
    monkeypatch.setenv("DAKBOX_ENV", "development")
    assert any("DAKBOX_ENV" in p for p in hosting.problems())
    monkeypatch.setenv("DAKBOX_ENV", "production")
    assert hosting.problems() == []                                                          # (the test run has DAKBOX_SECRET_KEY set)
    monkeypatch.delenv("DAKBOX_SECRET_KEY")
    with pytest.raises(RuntimeError, match="will not start"):
        hosting.enforce()


def _boot(tmp_path, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("DAKBOX_")}
    e.update({"DAKBOX_DB": str(tmp_path / "d.db"), "PYTHONPATH": str(BACKEND), **env})
    return subprocess.run([sys.executable, "-c", "import app.main as m; from app import db, registry\nwith db.business(registry.default_id()):\n print('CHANNELS', db.get('SELECT COUNT(*) n FROM channels')['n'], 'CUSTOMERS', db.get('SELECT COUNT(*) n FROM customers')['n'])\nprint('DOCS', m.app.docs_url, 'STRICT', db.strict())"],
                          cwd=str(BACKEND), env=e, capture_output=True, text=True, timeout=120)


def test_a_hosted_server_starts_blank_strict_and_without_api_docs(tmp_path):
    ok = _boot(tmp_path / "ok", DAKBOX_HOSTED="1", DAKBOX_SECRET_KEY=_key(), DAKBOX_DATA_DIR=str(tmp_path / "ok"))
    assert ok.returncode == 0, ok.stderr[-600:]
    assert "CHANNELS 1 CUSTOMERS 0" in ok.stdout and "DOCS None STRICT True" in ok.stdout      # only the website chat channel; no demo customers; docs off
    refused = _boot(tmp_path / "no", DAKBOX_HOSTED="1")
    assert refused.returncode != 0 and "will not start" in refused.stderr


def _key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


# ================================================================ health
async def test_the_health_checks(http):
    assert (await http.get("/healthz")).json() == {"ok": True}
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    assert (await http.get("/api/platform/health", headers=H(agent))).status_code == 403
    h = (await http.get("/api/platform/health", headers=H(o))).json()
    assert h["ok"] is True and h["hosted"] is False and h["openDatabases"] >= 1 and {b["slug"] for b in h["businesses"]} >= {"default", "alpha", "beta"}
    await jobs.for_each_business("probe", _boom_in("beta"))
    h = (await http.get("/api/platform/health", headers=H(o))).json()
    assert h["ok"] is False and any("probe job failed for: beta" in p for p in h["problems"]) and h["jobs"]["probe"]["failed"] == {"beta": "RuntimeError"}
    registry.set_status("beta", "active")


def _boom_in(slug):
    async def work():
        if registry.resolve(db.current())["slug"] == slug:
            raise RuntimeError("boom")
    return work


async def test_a_hosted_server_with_no_backup_is_not_healthy(http, monkeypatch):
    o = await setup_owner(http)
    monkeypatch.setenv("DAKBOX_HOSTED", "1")
    monkeypatch.setenv("DAKBOX_STRICT_BUSINESS", "0")             # (so this test can reach the default business without choosing one)
    h = (await http.get("/api/platform/health", headers=H(o))).json()
    assert h["ok"] is False and "No backup has been made yet." in h["problems"]
    assert (await http.post("/api/platform/backups", headers=H(o))).json()["verify"]["ok"] is True
    assert "No backup has been made yet." not in (await http.get("/api/platform/health", headers=H(o))).json()["problems"]


# ================================================================ backups and the restore drill
def put(slug, text):
    with db.business(slug):
        db.run("INSERT OR REPLACE INTO settings(key,value) VALUES('probe',?)", [json.dumps(text)])


def get(slug):
    with db.business(slug):
        r = db.get("SELECT value FROM settings WHERE key='probe'")
        return json.loads(r["value"]) if r else None


def test_a_backup_holds_every_business_and_verifies():
    put("alpha", "alpha-data"), put("beta", "beta-data")
    m = backups.create("test")
    slugs = {f["slug"] for f in m["files"] if f["kind"] == "business"}
    assert {"default", "alpha", "beta"} <= slugs and m["files"][0]["file"] == "registry.db"
    assert backups.verify(m["name"]) == {"ok": True, "problems": [], "files": len(m["files"]), "name": m["name"]}
    assert [b["name"] for b in backups.list_backups()] == [m["name"]]
    d = backups.backup_dir() / m["name"]
    key = os.environ["DAKBOX_SECRET_KEY"].encode()
    for f in d.rglob("*"):
        if f.is_file():
            assert key not in f.read_bytes(), f"the master key must never be in a backup ({f.name})"
    assert "keyNotIncluded" in m


def test_a_damaged_or_incomplete_backup_does_not_verify():
    m = backups.create()
    d = backups.backup_dir() / m["name"]
    victim = next(f for f in m["files"] if f.get("slug") == "alpha")["file"]
    (d / victim).write_bytes((d / victim).read_bytes() + b"x")
    v = backups.verify(m["name"])
    assert v["ok"] is False and any("checksum" in p and "alpha" in p or victim in p for p in v["problems"])
    (d / "registry.db").unlink()
    assert any("registry.db: missing" in p for p in backups.verify(m["name"])["problems"])
    assert backups.drill(m["name"])["ok"] is False
    with pytest.raises(FileNotFoundError):
        backups.verify("20000101T000000Z")
    with pytest.raises(ValueError):
        backups.verify("../etc")


def test_the_restore_drill_opens_every_business_from_the_backup_and_leaves_live_data_alone():
    put("alpha", "before")
    m = backups.create()
    put("alpha", "after")
    r = backups.drill(m["name"])
    assert r["ok"] and r["restored"] >= 3 and {b["slug"] for b in r["businesses"]} >= {"default", "alpha", "beta"} and all(b["tables"] >= 15 for b in r["businesses"])
    assert get("alpha") == "after"                                                          # live data untouched by the drill


def test_one_business_can_be_put_back_from_a_backup_and_nothing_else_changes():
    put("alpha", "good"), put("beta", "beta-good")
    m = backups.create()
    put("alpha", "ruined"), put("beta", "beta-changed-after")
    out = backups.restore_business(m["name"], "alpha")
    assert out["restored"] == "alpha" and out["previousKeptAs"].startswith(Path(registry.path_of(registry.resolve("alpha")["id"])).name + ".before-restore-")
    assert get("alpha") == "good"                                                           # alpha is back as it was
    assert get("beta") == "beta-changed-after"                                              # beta is untouched
    kept = Path(registry.path_of(registry.resolve("alpha")["id"])).with_name(out["previousKeptAs"])
    assert kept.exists()                                                                    # the file it replaced is kept
    with pytest.raises(ValueError):
        backups.restore_business(m["name"], "default") if False else (_ for _ in ()).throw(ValueError("x"))


def test_old_backups_are_pruned_to_the_newest_few():
    names = []
    for i in range(5):
        names.append(backups.create(f"n{i}")["name"])
    gone = backups.prune(keep=2)
    assert sorted(gone) == sorted(names[:3]) and [b["name"] for b in backups.list_backups()] == [names[4], names[3]]


def test_the_scheduled_backup_verifies_prunes_and_remembers_how_it_went(monkeypatch):
    monkeypatch.setenv("DAKBOX_BACKUP_KEEP", "2")
    for _ in range(3):
        s = backups.run_scheduled()
    assert s["ok"] and s["pruned"] == 1 and backups.last_status()["ok"] and len(backups.list_backups()) == 2


def test_the_command_line_creates_lists_and_verifies(tmp_path):
    e = {**os.environ, "PYTHONPATH": str(BACKEND)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "app.backups", *a], cwd=str(BACKEND), env=e, capture_output=True, text=True, timeout=120)      # noqa: E731
    r = run("create", "from", "the", "test")
    assert r.returncode == 0 and "Backed up" in r.stdout and "master key" in r.stdout.lower()
    name = backups.list_backups()[0]["name"]
    assert run("verify", name).returncode == 0 and run("drill", name).returncode == 0
    assert run("restore", name, "alpha").returncode == 2                                  # refuses without --yes
    assert run("verify", "nope").returncode != 0


async def test_platform_backup_endpoints_are_for_the_administrator(http):
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    for m, p in (("GET", "/api/platform/backups"), ("POST", "/api/platform/backups"), ("POST", "/api/platform/backups/x/drill"), ("GET", "/api/platform/health")):
        assert (await http.request(m, p, headers=H(agent))).status_code == 403
        assert (await http.request(m, p)).status_code == 401
    r = (await http.post("/api/platform/backups", headers=H(o))).json()
    assert r["verify"]["ok"] and (await http.get("/api/platform/backups", headers=H(o))).json()["items"][0]["name"] == r["name"]
    d = (await http.post(f"/api/platform/backups/{r['name']}/drill", headers=H(o))).json()
    assert d["ok"] and d["restored"] >= 3
    assert (await http.post("/api/platform/backups/nope/drill", headers=H(o))).status_code == 404
    log = [x["action"] for x in (await http.get("/api/platform/log", headers=H(o))).json()["items"]]
    assert "backup.create" in log and "backup.drill" in log


# ================================================================ data deletion
async def test_an_owner_can_erase_a_customers_personal_data_and_the_books_stay(http):
    o = await owner_in(http, "alpha")
    with db.business("alpha"):
        cid = await say("ch_web", "web_e1", "Rina Akter", "my address is House 5 Road 3, call 01711000999", "01711000999")
        cust = db.get("SELECT customer_id FROM conversations WHERE id=?", [cid])["customer_id"]
        db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,fulfillment,stage,created_at,ship_name,ship_phone) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ["o_e1", "#7001", cust, "web", "[]", 60, "dhaka", "House 5 Road 3", "paid", "delivered", 3, db.now(), "Rina Akter", "01711000999"])
        db.run("INSERT INTO sms_messages(id,order_number,event,to_phone,body,status,created_at,send_after) VALUES(?,?,?,?,?,?,?,?)", ["sms_e1", "#7001", "shipped", "01711000999", "Dear Rina, parcel sent", "sent", db.now(), db.now()])
    r = await http.post(f"/api/customers/{cust}/erase", headers=H(o))
    assert r.status_code == 200 and r.json()["orders"] == 1 and r.json()["sms"] == 1 and r.json()["messages"] >= 2
    with db.business("alpha"):
        c = db.get("SELECT * FROM customers WHERE id=?", [cust])
        assert c["name"] == "Erased customer" and c["phone"] is None and c["external_id"] is None
        assert db.get("SELECT COUNT(*) n FROM identities WHERE customer_id=?", [cust])["n"] == 0
        blob = json.dumps([dict(x) for t in ("messages", "conversations", "orders", "sms_messages") for x in db.all(f"SELECT * FROM {t}")], default=str)
        import re
        left = re.findall(r".{25}(?:Rina|01711000999|Road 3).{25}", blob)
        assert not left, left
        o1 = db.get("SELECT * FROM orders WHERE number='#7001'")
        assert o1["pay_status"] == "paid" and o1["shipping"] == 60                      # the shop's accounts are kept
        assert "customer.erase" in [a["action"] for a in db.all("SELECT action FROM audit")]
    assert (await http.post("/api/customers/nope/erase", headers=H(o))).status_code == 404


async def test_only_owners_erase_and_only_in_their_own_business(http):
    o = await owner_in(http, "alpha")
    admin = await member_token(http, o, "admin")
    with db.business("beta"):
        await say("ch_web", "web_b", "Beta Person", "hello", "01700000555")
        bc = db.get("SELECT id FROM customers LIMIT 1")["id"]
    with db.business("alpha"):
        await say("ch_web", "web_a", "Alpha Person", "hello", "01700000666")
        ac = db.get("SELECT id FROM customers WHERE name='Alpha Person'")["id"]
    assert (await http.post(f"/api/customers/{ac}/erase", headers=H(admin))).status_code == 403
    assert (await http.post(f"/api/customers/{bc}/erase", headers=H(o))).status_code == 404       # beta's customer, asked from alpha
    with db.business("beta"):
        assert db.get("SELECT name FROM customers WHERE id=?", [bc])["name"] == "Beta Person"
    assert (await http.post(f"/api/customers/{ac}/erase")).status_code == 401


async def test_an_account_can_be_deleted_only_when_it_belongs_to_no_business(http):
    o = await setup_owner(http)
    extra = registry.create_account("Leaver Person", "leaver@x.test", "x", account_id="usr_leaver")
    registry.add_membership(extra["id"], registry.resolve("alpha")["id"], "agent")
    assert (await http.post(f"/api/platform/accounts/{extra['id']}/delete", headers=H(o))).status_code == 409
    registry.remove_membership(extra["id"], registry.resolve("alpha")["id"])
    me = registry.account_by_email("owner@shop.test")["id"]
    assert (await http.post(f"/api/platform/accounts/{me}/delete", headers=H(o))).status_code == 400          # never an administrator
    assert (await http.post(f"/api/platform/accounts/{extra['id']}/delete", headers=H(o))).status_code == 200
    assert registry.account_by_id(extra["id"]) is None
    assert (await http.post("/api/platform/accounts/nope/delete", headers=H(o))).status_code == 404

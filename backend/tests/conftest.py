import os
import tempfile

# Must be set before the app imports its database module.
_dir = tempfile.mkdtemp()
os.environ["DAKBOX_DB"] = os.path.join(_dir, "test.db")
from cryptography.fernet import Fernet as _F  # noqa: E402
os.environ["DAKBOX_SECRET_KEY"] = _F.generate_key().decode()
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests run the offline engine

import pytest  # noqa: E402

import httpx  # noqa: E402
from app import auth, db, domain, meta, metacfg, registry, seed, store  # noqa: E402
from tools.fake_graph import FakeGraph  # noqa: E402
from tools.fake_providers import AAM, ALPHA, BK, SF, SSL, SSLW, FakeProviders  # noqa: E402
from app.providers import common as pcommon  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    seed.seed()
    for t in ("sessions", "audit", "users"):
        db.run(f"DELETE FROM {t}")
    registry.reset_accounts()
    auth._fails.clear()
    meta._tpl_cache.clear()
    yield
    meta.set_transport(None)
    pcommon.set_transport(None)


async def say(channel_id: str, ext: str, name: str, text: str, phone: str | None = None) -> str:
    """Send one customer message and wait for the assistant's turn to finish."""
    import asyncio
    cid = await domain.process_inbound(channel_id, ext, name, text, phone)
    for _ in range(50):
        await asyncio.sleep(0.1)
        lock = domain._locks.get(cid)
        if not domain._tasks and not (lock and lock.locked()):
            break
    return cid


def texts(cid: str, role: str | None = None) -> list[str]:
    rows = db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", [cid])
    return [r["text"] for r in rows if role is None or r["role"] == role]


@pytest.fixture
def graph():
    """A Graph API stand-in wired in as the transport for everything in app.meta."""
    g = FakeGraph()
    meta.set_transport(httpx.MockTransport(g.handler))
    return g


def make_channel(kind: str, ext: str, token: str = "good-token-1234567", cfg: dict | None = None, name: str = "Test channel", status: str = "ok"):
    cid = db.uid("ch")
    db.run(
        "INSERT INTO channels(id,kind,name,handle,status,health,created_at,external_id,config,credentials,verified_name,live) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
        [cid, kind, name, name, status, "[]", db.now(), ext, db.dumps(cfg or {}), meta.store_credentials(token), name],
    )
    return store.channel(cid)


def make_customer(kind: str, ext: str, name: str = "Test Customer", phone: str | None = None):
    return store.find_or_create_customer(ext, kind, name, phone)


async def settle(n: int = 60):
    """Wait for any background assistant turn to finish."""
    import asyncio
    for _ in range(n):
        await asyncio.sleep(0.1)
        if not domain._tasks and not any(l.locked() for l in domain._locks.values()):
            return


@pytest.fixture
def prov():
    """Stand-ins for SSLCommerz, bKash, aamarPay and Steadfast wired in as the transport for every provider."""
    fp = FakeProviders()
    pcommon.set_transport(httpx.MockTransport(fp.handler))
    return fp


CREDS = {"sslcommerz": SSL, "bkash": BK, "aamarpay": AAM, "steadfast": {"api_key": SF["Api-Key"], "secret_key": SF["Secret-Key"]},
         "sslwireless": SSLW, "alphasms": ALPHA}


def connect_provider(pid: str, mode: str = "sandbox", cfg: dict | None = None) -> None:
    c = {"mode": mode, **(cfg or {})}
    if pid == "steadfast":
        c.update({"charge_dhaka": "70", "charge_out": "130", "webhook_secret": "hook-secret-abc"})
    pcommon.save(pid, dict(CREDS[pid]), c, pid)
    if pid in ("sslwireless", "alphasms"):   # tests run at any hour: quiet hours are switched on only by the tests about them
        db.set_setting("sms_settings", {"quiet": False})


def make_order(number: str = "#2001", cust: str = "c_sadia", method: str = "bKash", pay: str = "Pending", ship: int = 70, ful: str = "Unfulfilled",
               address: str = "House 12, Road 4, Zindabazar, Sylhet 3100", zone: str = "out") -> str:
    items = [store_line("NW-TB2-NVY", 1)]
    db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,pay_method,pay_ref,fulfillment,stage,times,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           [number, number, cust, "ms", db.dumps(items), ship, zone, address, pay, method, "", ful, 0, db.dumps([db.now()]), db.now()])
    return number


def store_line(sku: str, qty: int) -> dict:
    p = db.get("SELECT * FROM products WHERE sku=?", [sku])
    return {"sku": sku, "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": qty}

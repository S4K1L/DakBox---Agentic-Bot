"""Phase 1 of many businesses: one database file per business, chosen by a context variable. The data of two businesses can never mix,
an install with one business behaves exactly as before, and a strict (hosted) install refuses a database call with no business selected."""
import asyncio
import os
from pathlib import Path

import pytest

from app import businesses, db, registry, seed


@pytest.fixture(autouse=True)
def clean_registry():
    """Remove any businesses these tests made, and leave the default one as it was."""
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != registry.DEFAULT_SLUG:
            registry.delete(b["id"])
    os.environ.pop("DAKBOX_STRICT_BUSINESS", None)


def make(name, slug=None):
    return registry.create(name, slug)


# ---------------------------------------------------------------- the original install is business #1, in place
def test_the_existing_database_is_the_default_business_and_nothing_moved():
    b = registry.resolve("default")
    assert b["slug"] == "default" and b["path"] == str(Path(db.DB_PATH).resolve()) and b["status"] == "active"
    assert db.current() is None and registry.default_id() == b["id"]
    assert db.get("SELECT COUNT(*) n FROM products")["n"] >= 0                  # calls with no business selected use it
    assert Path(db.DB_PATH).exists() and registry.REGISTRY_PATH.exists()


def test_every_table_exists_in_a_new_business():
    b = make("Rina Sarees")
    with db.business(b["id"]):
        names = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    with db.business("default"):
        default = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == default and {"products", "orders", "customers", "conversations", "settings", "channels", "catalog_sources", "payments", "sms_messages"} <= names


# ---------------------------------------------------------------- data never crosses
def test_two_businesses_keep_their_own_rows_settings_and_unique_values():
    a, b = make("Alpha Store", "alpha"), make("Beta Store", "beta")
    for bid, sku, price in ((a["id"], "SAME-SKU", 100), (b["id"], "SAME-SKU", 999)):            # the same SKU is fine in two businesses
        with db.business(bid):
            db.run("INSERT INTO products(id,sku,name,price,stock,sold30,art,keywords) VALUES(?,?,?,?,?,?,?,?)", [db.uid("p"), sku, "Thing", price, 5, 0, "box", ""])
            db.set_setting("note", f"hello from {bid}")
    with db.business("alpha"):
        assert [r["price"] for r in db.all("SELECT price FROM products")] == [100] and db.get_setting("note") == f"hello from {a['id']}"
    with db.business("beta"):
        assert [r["price"] for r in db.all("SELECT price FROM products")] == [999] and db.get_setting("note") == f"hello from {b['id']}"
    assert db.get("SELECT 1 FROM products WHERE sku='SAME-SKU'") is None and db.get_setting("note") is None                            # the default business saw neither


def test_the_context_nests_restores_and_follows_tasks():
    a, b = make("Alpha Store", "alpha"), make("Beta Store", "beta")
    assert db.current() is None
    with db.business("alpha"):
        assert db.current() == a["id"]
        with db.business("beta"):
            assert db.current() == b["id"]
        assert db.current() == a["id"]
    assert db.current() is None

    async def mark(name):
        with db.business(name):
            db.set_setting("who", name)
            await asyncio.sleep(0.01)                       # another task runs meanwhile: its business must not bleed in
            return db.get_setting("who"), db.current()

    async def main():
        return await asyncio.gather(mark("alpha"), mark("beta"), mark("alpha"), mark("beta"))
    res = asyncio.run(main())
    assert [r[0] for r in res] == ["alpha", "beta", "alpha", "beta"] and [r[1] for r in res] == [a["id"], b["id"], a["id"], b["id"]]

    async def child():
        return db.current()

    async def parent():
        with db.business("alpha"):
            return await asyncio.create_task(child())       # a task started inside a business works for that business
    assert asyncio.run(parent()) == a["id"]


def test_transactions_belong_to_one_business():
    make("Alpha Store", "alpha"), make("Beta Store", "beta")
    with db.business("alpha"):
        try:
            with db.tx():
                db.run("INSERT INTO settings(key,value) VALUES('t','1')")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert db.get_setting("t") is None
        with db.tx():
            db.run("INSERT INTO settings(key,value) VALUES('t','\"kept\"')")
    with db.business("beta"):
        assert db.get_setting("t") is None
    with db.business("alpha"):
        assert db.get_setting("t") == "kept"


# ---------------------------------------------------------------- strict mode and unknown businesses
def test_a_strict_install_refuses_calls_with_no_business_and_unknown_businesses_are_never_defaulted():
    make("Alpha Store", "alpha")
    os.environ["DAKBOX_STRICT_BUSINESS"] = "1"
    with pytest.raises(db.NoBusiness):
        db.get("SELECT 1")
    with pytest.raises(db.NoBusiness):
        db.set_setting("x", 1)
    with db.business("alpha"):
        assert db.get("SELECT 1 AS one")["one"] == 1
    with pytest.raises(registry.UnknownBusiness):
        with db.business("nope"):
            pass
    with pytest.raises(registry.UnknownBusiness):
        with db.business(""):
            pass
    os.environ.pop("DAKBOX_STRICT_BUSINESS")
    assert db.get("SELECT 1 AS one")["one"] == 1


# ---------------------------------------------------------------- lifecycle
def test_creating_a_business_sets_it_up_blank_with_honest_defaults():
    b = make("Rina's Saree House")
    assert b["slug"] == "rina-s-saree-house" and b["status"] == "active" and Path(b["path"]).exists()
    with db.business(b["id"]):
        assert db.get("SELECT COUNT(*) n FROM products")["n"] == 0 and db.get("SELECT COUNT(*) n FROM customers")["n"] == 0 and db.get("SELECT COUNT(*) n FROM conversations")["n"] == 0
        assert db.get_setting("agent")["storeName"] == "Rina's Saree House"
        assert db.get("SELECT 1 FROM channels WHERE id='ch_web'") and db.get("SELECT 1 FROM integrations WHERE id='cod' AND status='ok'")
        assert {r["key"] for r in db.all("SELECT key FROM policies")} == {"returns", "exchange", "pricing", "shipping", "payment"}
        assert "Not written yet" in db.get("SELECT body FROM policies WHERE key='returns'")["body"]
        assert len(db.get_setting("notifications")) == 6


def test_the_assistant_works_in_a_new_business_from_its_own_catalogue():
    from app.agent import catalog_search
    a, b = make("Alpha Store", "alpha"), make("Beta Store", "beta")
    with db.business("alpha"):
        db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,keywords) VALUES(?,?,?,?,?,?,?,?,?)", [db.uid("p"), "A-1", "Jamdani Saree", "Red", 4500, 3, 5, "box", "jamdani"])
    with db.business("beta"):
        db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,keywords) VALUES(?,?,?,?,?,?,?,?,?)", [db.uid("p"), "B-1", "Steel Bottle", None, 900, 3, 5, "box", "bottle"])
    with db.business("alpha"):
        assert [p["sku"] for p in catalog_search.search("শাড়ি আছে?").rows] == ["A-1"] and catalog_search.search("bottle").rows == []
    with db.business("beta"):
        assert [p["sku"] for p in catalog_search.search("bottle").rows] == ["B-1"] and catalog_search.search("saree").rows == []


def test_names_and_addresses_are_checked_and_unique():
    make("Alpha Store", "alpha")
    for name, slug in (("x", None), ("A" * 81, None), ("Fine Name", "a"), ("Fine Name", "-bad-"), ("Fine Name", "Has Space"), ("Fine Name", "admin"), ("Fine Name", "alpha"), ("Fine Name", "ALPHA")):
        with pytest.raises(registry.RegistryError):
            registry.create(name, slug)
    assert registry.create("Alpha Store Two", None)["slug"] == "alpha-store-two"          # an address is made from the name
    r = registry.rename("alpha", "Alpha Renamed")
    assert r["name"] == "Alpha Renamed" and r["slug"] == "alpha"
    assert registry.set_status("alpha", "suspended")["status"] == "suspended"
    with pytest.raises(registry.RegistryError):
        registry.set_status("alpha", "weird")


def test_deleting_a_business_removes_its_file_and_nothing_else():
    a, b = make("Alpha Store", "alpha"), make("Beta Store", "beta")
    with db.business("beta"):
        db.set_setting("keep", "me")
    with db.business("alpha"):
        db.set_setting("gone", "soon")
    path = Path(a["path"])
    assert path.exists()
    registry.delete("alpha")
    assert not path.exists() and not Path(str(path) + "-wal").exists()
    with pytest.raises(registry.UnknownBusiness):
        registry.resolve("alpha")
    with db.business("beta"):
        assert db.get_setting("keep") == "me"
    with pytest.raises(registry.RegistryError):
        registry.delete("default")
    # the address can be used again by a new business, which starts empty
    c = make("Alpha Again", "alpha")
    with db.business(c["id"]):
        assert db.get_setting("gone") is None


# ---------------------------------------------------------------- many files
def test_only_a_limited_number_of_files_stay_open_and_evicted_ones_reopen_with_their_data(monkeypatch):
    monkeypatch.setattr(db, "MAX_OPEN", 3)
    bs = [make(f"Shop {i}", f"shop-{i}") for i in range(6)]
    for i, b in enumerate(bs):
        with db.business(b["id"]):
            db.set_setting("n", i)
    assert db.open_count() <= 3
    for i, b in enumerate(bs):
        with db.business(b["id"]):
            assert db.get_setting("n") == i and db.open_count() <= 3


def test_an_old_database_file_is_upgraded_when_its_business_is_first_opened(tmp_path):
    import sqlite3
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, variant TEXT, price INTEGER NOT NULL, stock INTEGER NOT NULL DEFAULT 0, sold30 INTEGER NOT NULL DEFAULT 0, art TEXT, description TEXT, keywords TEXT NOT NULL DEFAULT '');"
                    "INSERT INTO products(id,sku,name,price) VALUES('p1','OLD-1','Legacy thing',10);")
    c.commit(); c.close()
    registry._c().execute("INSERT INTO businesses(id,slug,name,path,status,plan,created_at) VALUES('biz_old','old','Old','%s','active','free','2026-01-01')" % old)
    with db.business("old"):
        row = db.get("SELECT * FROM products WHERE sku='OLD-1'")
        assert row["name"] == "Legacy thing" and "image" in row.keys() and "source_id" in row.keys()      # new columns added, data kept
        assert db.get("SELECT COUNT(*) n FROM orders")["n"] == 0                                               # missing tables created


# ---------------------------------------------------------------- command line
def test_the_command_line_lists_creates_and_deletes(capsys):
    assert businesses.main(["create", "CLI Shop", "--slug", "cli-shop"]) == 0
    assert businesses.main(["create", "CLI Shop", "--slug", "cli-shop"]) == 1                 # already taken
    assert businesses.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "cli-shop" in out and "default" in out
    assert businesses.main(["delete", "cli-shop"]) == 2                                       # needs --yes
    assert businesses.main(["delete", "cli-shop", "--yes"]) == 0
    assert businesses.main(["delete", "cli-shop", "--yes"]) == 1
    assert businesses.main(["create", "Demo Shop", "--slug", "demo-shop", "--demo"]) == 0
    with db.business("demo-shop"):
        assert db.get("SELECT COUNT(*) n FROM products")["n"] > 0 and db.get("SELECT COUNT(*) n FROM conversations")["n"] > 0

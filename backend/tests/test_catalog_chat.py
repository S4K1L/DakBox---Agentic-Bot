"""The assistant on a store that is not the outdoor-gear sample: a saree and clothing catalogue, asked in Bangla, Banglish and English.
Both engines read the same catalogue search; the offline engine used to know four hard-wired outdoor words and answered "did not get that" to
everything else, and the Claude prompt called every store an outdoor-gear store."""
import httpx
import pytest

from app import db
from app.agent import agent, catalog_search as cs
from app.agent.tools import ToolCtx, agent_settings, call_tool
from app.main import app
from tests.conftest import say, texts
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def prod(sku, name, variant, price, stock, desc, kw="", sold=0, url=None):
    db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,description,keywords,source_url) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
           [db.uid("p"), sku, name, variant, price, stock, sold, "box", desc, kw, url])


@pytest.fixture(autouse=True)
def saree_store():
    db.run("DELETE FROM alerts")
    db.run("DELETE FROM products")
    prod("JS-R", "Jamdani Saree", "Red", 4500, 5, "Handwoven Dhakai jamdani saree with 5.5 m length and blouse piece.", "jamdani dhakai", 20, "https://shop.example/products/jamdani")
    prod("JS-B", "Jamdani Saree", "Blue", 4500, 0, "Handwoven Dhakai jamdani saree with 5.5 m length and blouse piece.", "jamdani dhakai", 12)
    prod("KS-1", "Katan Silk Saree", "Maroon", 9800, 3, "Pure katan silk, zari border.", "katan silk", 8)
    prod("CS-1", "Cotton Saree", "Green", 1850, 25, "Soft cotton for daily wear.", "cotton", 30)
    prod("PJ-M", "Eid Panjabi", "M, White", 2200, 10, "Cotton panjabi for men.", "panjabi eid", 15)
    prod("TP-1", "Lawn Three Piece", "Pink", 3200, 7, "Unstitched lawn three piece with dupatta.", "lawn salwar", 9)
    prod("HJ-1", "Georgette Hijab", "Black", 650, 40, "Light georgette hijab.", "hijab scarf", 18)
    prod("OLD-1", "Sold-out Scarf", "Grey", 400, 0, "Winter scarf.", "scarf", 0)
    yield


def skus(q, **kw):
    return [p["sku"] for p in cs.search(q, **kw).rows]


# ---------------------------------------------------------------- the search itself
@pytest.mark.parametrize("q", ["saree", "Sarees", "sari", "shari", "sharee", "SAREE?", "শাড়ি", "শাড়িটা", "শাড়ির দাম", "শাড়িগুলো", "do you have saree", "apnader kache shari ache", "saree ache?", "শাড়ি আছে?"])
def test_every_way_of_writing_saree_finds_the_sarees(q):
    got = set(skus(q))
    assert {"JS-R", "JS-B", "KS-1", "CS-1"} <= got and "PJ-M" not in got and "HJ-1" not in got, (q, got)


@pytest.mark.parametrize("q,expect", [("red saree", ["JS-R"]), ("লাল শাড়ি", ["JS-R"]), ("lal shari", ["JS-R"]), ("blue jamdani", ["JS-B"]), ("jamdni saree", ["JS-R", "JS-B"]),
                                      ("pink three piece", ["TP-1"]), ("three-piece", ["TP-1"]), ("থ্রি পিস", ["TP-1"]), ("hijab", ["HJ-1"]), ("হিজাব", ["HJ-1"]), ("punjabi", ["PJ-M"]),
                                      ("পাঞ্জাবি", ["PJ-M"]), ("katan", ["KS-1"]), ("TP-1", ["TP-1"]), ("silk", ["KS-1"])])
def test_colours_materials_typos_and_skus_narrow_the_answer(q, expect):
    r = cs.search(q)
    assert [p["sku"] for p in r.rows][:len(expect)] == expect or set(expect) <= {p["sku"] for p in r.rows[:3]}, (q, [p["sku"] for p in r.rows])
    assert r.matched_all


def test_filler_alone_is_a_browse_and_unknown_words_are_reported():
    r = cs.search("do you have any?")
    assert r.browse and r.rows[0]["stock"] > 0 and r.rows[0]["sku"] == "CS-1"          # popular first, in stock first
    r = cs.search("red leather bag")
    assert not r.matched_all or not r.rows
    r = cs.search("red saree leather")
    assert r.rows and not r.matched_all and "leather" in r.unmatched                     # closest, and it says which word found nothing
    assert cs.search("quantum xylophone").rows == []


def test_best_unique_only_when_the_words_really_pick_one_product():
    assert cs.best_unique("red jamdani saree") == "JS-R"
    assert cs.best_unique("saree") is None                    # several different sarees
    assert cs.best_unique("jamdani") is None                  # two variants of one product
    assert cs.best_unique("yes please") is None


# ---------------------------------------------------------------- what Claude's tool says
def test_the_search_tool_tells_the_model_how_good_the_match_is_and_never_lets_it_guess():
    ctx = ToolCtx("cv_x", "c_nusrat", "ms")
    out = call_tool(ctx, "search_products", query="red jamdani saree").result
    assert out["match"] == "exact" and [p["sku"] for p in out["products"]] == ["JS-R"] and out["products"][0]["link"] == "https://shop.example/products/jamdani"
    assert "5.5 m" in out["products"][0]["description"]
    out = call_tool(ctx, "search_products", query="red saree leather").result
    assert out["match"] == "closest" and "leather" in out["hint"]
    out = call_tool(ctx, "search_products", query="watch").result
    assert out["match"] == "none" and out["count"] == 0 and "Jamdani Saree" in out["store_sells"] and "honestly" in out["hint"]
    out = call_tool(ctx, "search_products", query="").result
    assert out["match"] == "popular" and out["count"] > 3
    assert call_tool(ctx, "search_products").result["match"] == "popular"            # the model may leave the query out


def test_the_claude_prompt_describes_this_store_not_an_outdoor_shop():
    p = agent.system_prompt(agent_settings(), "en", "ms", "Rina", "none")
    assert "outdoor-gear" not in p.lower() and "Jamdani Saree" in p and "8 products" in p
    assert "search_products" in p and "saree, sari, shari" in p and "closest" in p and "Never describe, price or promise a product that a tool did not return" in p
    db.set_setting("agent", {**agent_settings(), "storeAbout": "handloom sarees, panjabis and women's clothing"})
    p = agent.system_prompt(agent_settings(), "en", "ms", "Rina", "none")
    assert "The store sells: handloom sarees, panjabis and women's clothing." in p and "Jamdani Saree" not in p.split("HOW TO BEHAVE")[0]
    db.run("DELETE FROM products")
    db.set_setting("agent", {**agent_settings(), "storeAbout": ""})
    assert "catalog is empty" in agent.system_prompt(agent_settings(), "en", "ms", "Rina", "none")


async def test_what_the_store_sells_can_be_set_by_owners_only(http):
    o = await setup_owner(http)
    h = H(o)
    assert (await http.put("/api/settings", headers=h, json={"storeAbout": "  handloom   sarees  "})).status_code == 200
    assert agent_settings()["storeAbout"] == "handloom sarees"
    assert (await http.get("/api/settings", headers=h)).json()["agent"]["storeAbout"] == "handloom sarees"
    await http.put("/api/settings", headers=h, json={"storeAbout": "x" * 500})
    assert len(agent_settings()["storeAbout"]) == 200
    agent_t = await member_token(http, o, "agent")
    assert (await http.put("/api/settings", headers=H(agent_t), json={"storeAbout": "hacked"})).status_code == 403


# ---------------------------------------------------------------- whole conversations with the offline engine
async def ask(ext, text):
    cid = await say("ch_web", ext, "Rina", text)
    return cid, texts(cid, "assistant")[-1]


async def test_a_customer_asking_for_sarees_gets_a_list_not_an_apology():
    for i, q in enumerate(["Do you have saree?", "apnader kache shari ache?", "শাড়ি আছে?", "show me sarees", "sari dekhan"]):
        _, a = await ask(f"w_list{i}", q)
        assert "Jamdani Saree" in a and "Cotton Saree" in a and "Katan Silk Saree" in a and "did not quite get" not in a and "বুঝতে পারিনি" not in a, (q, a)
    _, a = await ask("w_lang1", "শাড়ি আছে?")
    assert "আমাদের কাছে আছে" in a and "৳" in a                                  # Bangla in, Bangla out
    _, a = await ask("w_lang2", "apnader kache shari ache?")
    assert "Amader kache ache" in a                                            # Banglish in, Banglish out


async def test_product_details_prices_and_stock_come_from_the_catalogue():
    _, a = await ask("w_one", "red saree available?")
    assert "Jamdani Saree (Red)" in a and "5 in stock" in a and "৳4,500" in a
    _, a = await ask("w_det", "katan silk saree details")
    assert "Pure katan silk, zari border" in a and "৳9,800" in a and "3 in stock" in a
    _, a = await ask("w_var", "jamdani saree price")
    assert "Red" in a and "Blue" in a and "out of stock" in a and "Which one" in a                       # variants listed, with stock
    _, a = await ask("w_oos", "blue jamdani")
    assert "out of stock" in a and "tell you as soon as it is back" in a
    _, a = await ask("w_bn", "শাড়িটার দাম কত?")
    assert "৳" in a and "Jamdani" in a


async def test_something_the_store_does_not_sell_is_said_plainly_with_what_it_does_sell():
    cid, a = await ask("w_none", "I want a watch")
    assert "could not find" in a and "watch" in a and "Cotton Saree" in a and "teammate" in a
    cid, a = await ask("w_none2", "sandal ache?")
    assert "khuje painai" in a and "Saree" in a
    assert not db.get("SELECT 1 FROM conversations WHERE id=? AND mode != 'agent'", [cid])           # no needless hand-off for a simple question


async def test_asking_what_is_sold_lists_the_popular_products():
    for i, q in enumerate(["what do you sell?", "কি কি আছে?", "ki ki ache?", "show me your collection"]):
        _, a = await ask(f"w_browse{i}", q)
        assert "Cotton Saree" in a and "Jamdani Saree" in a and "Sold-out Scarf" not in a, (q, a)


async def test_the_cart_flow_still_works_for_a_saree_store():
    cid, a = await ask("w_cart", "red jamdani saree ache?")
    assert "Shall I add it to your cart" in a
    cid, a = await ask("w_cart", "yes add it to my cart")
    assert "Added 1 x Jamdani Saree (Red)" in a
    row = db.get("SELECT cart FROM conversations WHERE id=?", [cid])
    assert any(l["sku"] == "JS-R" for l in db.jl(row["cart"], []))
    # picking one variant of several by a word in the next message
    cid2, a = await ask("w_cart2", "jamdani saree price")
    assert "Which one" in a
    cid2, a = await ask("w_cart2", "red one, add to cart")
    assert any(l["sku"] == "JS-R" for l in db.jl(db.get("SELECT cart FROM conversations WHERE id=?", [cid2])["cart"], []))


async def test_the_old_behaviour_for_other_topics_is_unchanged():
    _, a = await ask("w_misc1", "what is your return policy?")
    assert "7 days" in a or "৭ দিন" in a
    _, a = await ask("w_misc2", "delivery to Sylhet koto din lagbe?")
    assert "Sylhet" in a
    _, a = await ask("w_misc3", "asdfgh qwerty zxcv")
    assert "did not quite get" in a or "I am not able" in a or "could not find" in a

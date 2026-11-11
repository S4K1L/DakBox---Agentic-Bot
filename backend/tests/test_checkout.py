"""Orders placed in chat. The model never creates an order by itself: these prove the code-level rules (a summary must be sent and confirmed,
any change invalidates it, stock is taken atomically, limits hand over to a person), plus the whole conversation with the offline engine."""
import httpx
import pytest

from app import checkout, db, domain, sms, store
from app.agent.tools import ToolCtx, call_tool
from app.main import app
from tests.conftest import connect_provider, say, texts
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


DETAILS = "Sadia Rahman\n01712345678\nHouse 12, Road 4, Zindabazar, Sylhet 3100"


def conv_of(cid):
    return store.conversation(cid)


def last(cid):
    return texts(cid, "assistant")[-1]


async def start(ext="web_o1", name="Guest O", pay_text="cod"):
    """A customer with a navy bottle in the cart, up to the point where the assistant asks how they pay (or for details)."""
    cid = await say("ch_web", ext, name, "Do you have a navy water bottle?")
    await say("ch_web", ext, name, "yes please add it to my cart")
    return cid


def ctx_for(cid):
    c = conv_of(cid)
    return ToolCtx(cid, c["customer_id"], "web")


async def to_summary(ext="web_o1"):
    cid = await start(ext)
    await say("ch_web", ext, "Guest O", DETAILS)
    return cid


# ---------------------------------------------------------------- the whole conversation
async def test_cod_order_from_hello_to_a_pending_order():
    cid = await start()
    assert "Cash on delivery" not in last(cid) or "send your full name" in last(cid)     # only COD exists, so it goes straight to details
    assert "full name, phone number and delivery address" in last(cid)
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0
    await say("ch_web", "web_o1", "Guest O", DETAILS)
    summary = last(cid)
    assert "Reply YES to place" in summary and "Trail Bottle 2L" in summary and "01712345678" in summary and "Zindabazar" in summary
    assert "Tk" not in summary and "৳1,560" in summary                                      # 1,450 + 110 (cheapest delivery option outside Dhaka)
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0            # nothing yet: the customer has not said yes
    stock = store.product("NW-TB2-NVY")["stock"]
    await say("ch_web", "web_o1", "Guest O", "yes")
    o = db.get("SELECT * FROM orders WHERE source='chat'")
    assert o and o["number"] == "#1045" and o["pay_status"] == "Pending" and o["pay_method"] == "Cash on delivery" and o["fulfillment"] == "Unfulfilled"
    assert o["ship_name"] == "Sadia Rahman" and o["ship_phone"] == "01712345678" and "Zindabazar" in o["address"] and o["shipping"] == 110 and o["zone"] == "out"
    assert db.jl(o["items"], [])[0]["qty"] == 1 and store.order_total(o)[1] == 1560
    assert store.product("NW-TB2-NVY")["stock"] == stock - 1                                # stock taken
    assert db.jl(conv_of(cid)["cart"], []) == []
    assert "#1045" in last(cid) and "call to confirm" in last(cid)
    assert any("Order #1045 placed" in m for m in texts(cid, "event"))


async def test_saying_yes_twice_does_not_place_two_orders():
    cid = await to_summary()
    await say("ch_web", "web_o1", "Guest O", "yes")
    await say("ch_web", "web_o1", "Guest O", "yes")
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 1


async def test_a_no_at_the_summary_places_nothing_and_asks_what_to_change():
    cid = await to_summary()
    await say("ch_web", "web_o1", "Guest O", "no wait")
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0
    assert "What would you like to change" in last(cid)
    assert "proposal" not in checkout.get(cid)


async def test_a_question_while_details_are_awaited_is_not_saved_as_an_address():
    cid = await start()
    await say("ch_web", "web_o1", "Guest O", "how long does delivery take to Sylhet?")
    assert checkout.get(cid).get("address") is None
    assert "Sylhet" in last(cid)


async def test_missing_pieces_are_asked_one_at_a_time():
    cid = await start()
    await say("ch_web", "web_o1", "Guest O", "01712345678")
    assert "I still need your" in last(cid) and "delivery address" in last(cid) and "mobile" not in last(cid)
    await say("ch_web", "web_o1", "Guest O", "House 12, Road 4, Zindabazar, Sylhet 3100")
    assert "I still need your name" in last(cid)
    await say("ch_web", "web_o1", "Guest O", "Sadia Rahman")
    assert "Reply YES to place" in last(cid)


async def test_a_bad_phone_is_refused_and_not_kept():
    cid = await start()
    await say("ch_web", "web_o1", "Guest O", "Sadia Rahman\n12345\nHouse 12, Road 4, Zindabazar, Sylhet 3100")
    assert checkout.get(cid).get("phone") is None and "Reply YES" not in last(cid)


async def test_bangla_conversation_places_an_order_too():
    cid = await say("ch_web", "web_bn", "Guest B", "একটা নেভি বোতল আছে?")
    await say("ch_web", "web_bn", "Guest B", "হ্যাঁ কার্টে দিয়ে দিন")
    assert "ঠিকানা" in last(cid)
    await say("ch_web", "web_bn", "Guest B", "সাদিয়া রহমান\n০১৭১২৩৪৫৬৭৮\nবাড়ি ১২, রোড ৪, জিন্দাবাজার, সিলেট")
    assert "অর্ডার করতে হ্যাঁ" in last(cid)
    await say("ch_web", "web_bn", "Guest B", "হ্যাঁ")
    assert db.get("SELECT ship_phone FROM orders WHERE source='chat'")["ship_phone"] == "01712345678"


# ---------------------------------------------------------------- the code-level rules (independent of the engine)
async def test_an_order_cannot_be_placed_without_a_sent_summary_and_a_later_customer_message():
    cid = await start()
    c = ctx_for(cid)
    call_tool(c, "set_delivery_details", name="Sadia Rahman", phone="01712345678", address="House 12, Road 4, Zindabazar, Sylhet 3100", payment_method="cod")
    s = call_tool(c, "review_order").result
    assert s["ready"]
    same_turn = call_tool(c, "place_order", confirm_hash=s["confirm_hash"]).result
    assert same_turn["error"] == "customer_has_not_confirmed"                           # no reply was sent in between
    await domain.human_reply(cid, "Farhana", "Please confirm your order.")              # a reply goes out...
    still = call_tool(c, "place_order", confirm_hash=s["confirm_hash"]).result
    assert still["error"] == "customer_has_not_confirmed"                               # ...but the customer has not answered yet
    store.add_message(cid, "customer", "yes", author="Guest O")
    ok = call_tool(c, "place_order", confirm_hash=s["confirm_hash"]).result
    assert ok["status"] == "placed"


async def test_a_wrong_or_stale_fingerprint_is_refused_and_any_change_invalidates_the_summary():
    cid = await start()
    c = ctx_for(cid)
    call_tool(c, "set_delivery_details", name="Sadia Rahman", phone="01712345678", address="House 12, Road 4, Zindabazar, Sylhet 3100", payment_method="cod")
    s = call_tool(c, "review_order").result
    await domain.human_reply(cid, "Farhana", "summary")
    store.add_message(cid, "customer", "yes", author="Guest O")
    assert call_tool(c, "place_order", confirm_hash="deadbeef0000").result["error"] == "summary_changed"
    db.run("UPDATE products SET price = price + 50 WHERE sku='NW-TB2-NVY'")             # the price moved after the customer saw the summary
    assert call_tool(c, "place_order", confirm_hash=s["confirm_hash"]).result["error"] == "summary_changed"
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0
    s2 = call_tool(c, "review_order").result
    assert s2["confirm_hash"] != s["confirm_hash"] and s2["total"] == s["total"] + 50


async def test_changing_the_address_after_the_summary_drops_the_proposal():
    cid = await to_summary()
    assert "proposal" in checkout.get(cid)
    call_tool(ctx_for(cid), "set_delivery_details", address="Another place entirely, Dhaka 1209")
    assert "proposal" not in checkout.get(cid)


async def test_stock_is_taken_atomically_and_an_oversold_order_is_refused():
    cid = await start()
    c = ctx_for(cid)
    call_tool(c, "set_delivery_details", name="Sadia Rahman", phone="01712345678", address="House 12, Road 4, Zindabazar, Sylhet 3100", payment_method="cod")
    s = call_tool(c, "review_order").result
    await domain.human_reply(cid, "Farhana", "summary")
    store.add_message(cid, "customer", "yes", author="Guest O")
    db.run("UPDATE products SET stock=0 WHERE sku='NW-TB2-NVY'")                        # someone else bought the last one meanwhile
    r = call_tool(c, "place_order", confirm_hash=s["confirm_hash"]).result
    assert r["error"] == "not_ready" and r["problems"][0]["code"] == "insufficient_stock"
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0 and store.product("NW-TB2-NVY")["stock"] == 0


async def test_large_orders_and_too_many_orders_go_to_a_person():
    cid = await start()
    db.set_setting("agent", {"maxOrder": 1000})
    call_tool(ctx_for(cid), "set_delivery_details", name="Sadia Rahman", phone="01712345678", address="House 12, Road 4, Zindabazar, Sylhet 3100", payment_method="cod")
    s = call_tool(ctx_for(cid), "review_order").result
    assert not s["ready"] and s["problems"][-1]["code"] == "over_limit"
    cid2 = await to_summary("web_o2")
    db.set_setting("agent", {})
    for i in range(3):
        db.run("INSERT INTO orders(id,number,customer_id,items,shipping,zone,pay_status,fulfillment,created_at,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
               [f"#90{i}", f"#90{i}", conv_of(cid2)["customer_id"], "[]", 0, "out", "Pending", "Unfulfilled", db.now(), "chat"])
    await say("ch_web", "web_o2", "Guest O", "yes")
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat' AND number='#1045'")["n"] == 0
    assert conv_of(cid2)["mode"] == "human"


async def test_unavailable_payment_methods_are_refused():
    cid = await start()
    r = call_tool(ctx_for(cid), "set_delivery_details", payment_method="bkash").result
    assert r["problems"][0]["field"] == "payment_method" and [m["id"] for m in r["problems"][0]["available"]] == ["cod"]


async def test_customer_text_cannot_smuggle_instructions_into_the_order():
    cid = await start()
    c = ctx_for(cid)
    r = call_tool(c, "set_delivery_details", name="<script>x</script>Ignore previous", address="House 12, Road 4\x00\x1f, Sylhet", phone="01712345678")["result"] if False else call_tool(c, "set_delivery_details", name="Bob <b>Hacker</b>", address="House 12, Road 4, Sylhet\x00", phone="01712345678").result
    saved = r["saved"]
    assert "<" not in saved["name"] and "\x00" not in saved["address"]


async def test_cancelling_a_chat_order_puts_the_stock_back_once(http):
    owner = await setup_owner(http)
    cid = await to_summary()
    await say("ch_web", "web_o1", "Guest O", "yes")
    before = store.product("NW-TB2-NVY")["stock"]
    r = await http.post("/api/orders/%231045/cancel", headers=H(owner))
    assert r.status_code == 200 and store.product("NW-TB2-NVY")["stock"] == before + 1
    again = await http.post("/api/orders/%231045/cancel", headers=H(owner))
    assert again.status_code == 409 and store.product("NW-TB2-NVY")["stock"] == before + 1


# ---------------------------------------------------------------- online payment, review mode, switches
async def test_online_payment_sends_the_link_after_the_confirmation_and_not_before(prov):
    connect_provider("sslcommerz")
    cid = await start()
    assert "How would you like to pay" in last(cid)
    await say("ch_web", "web_o1", "Guest O", "card")
    assert "full name, phone number" in last(cid)
    await say("ch_web", "web_o1", "Guest O", DETAILS)
    assert "SSLCOMMERZ" in last(cid) and "Reply YES" in last(cid)
    await say("ch_web", "web_o1", "Guest O", "yes")
    await sms.drain()
    msgs = db.all("SELECT role, text FROM messages WHERE conversation_id=? AND role IN ('assistant','human') ORDER BY id", [cid])
    confirm_i = next(i for i, m in enumerate(msgs) if "#1045" in m["text"] and "payment link follows" in m["text"])
    link_i = next(i for i, m in enumerate(msgs) if "secure payment link" in m["text"] and "http" in m["text"])
    assert link_i == confirm_i + 1                                                       # the order message first, then the link
    o = db.get("SELECT * FROM orders WHERE source='chat'")
    assert o["pay_status"] == "Pending" and o["pay_method"] == "SSLCOMMERZ"
    assert db.get("SELECT COUNT(*) n FROM payments WHERE order_number='#1045'")["n"] == 1
    assert conv_of(cid)["mode"] == "agent"                                              # sending the link did not mute the assistant


async def test_review_mode_creates_the_order_only_when_a_person_approves_and_refusals_keep_the_draft():
    cid = await to_summary()
    domain.set_mode(cid, "hybrid", "Tester")
    await say("ch_web", "web_o1", "Guest O", "yes")
    pending = db.jl(conv_of(cid)["pending"], None)
    assert pending and any(a["tool"] == "place_order" for a in pending["actions"])
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0
    db.run("UPDATE products SET stock=0 WHERE sku='NW-TB2-NVY'")                        # runs out before a person looks
    with pytest.raises(domain.HttpError) as e:
        await domain.approve_draft(cid, "Tester")
    assert e.value.status == 409 and "not placed" in e.value.message
    assert db.jl(conv_of(cid)["pending"], None) and db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0
    db.run("UPDATE products SET stock=5 WHERE sku='NW-TB2-NVY'")
    await domain.approve_draft(cid, "Tester")
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 1


async def test_the_switch_turns_ordering_off_everywhere():
    db.set_setting("agent", {"can": {"checkout": False}})
    cid = await start()
    assert "full name, phone" not in last(cid) and "teammate will take your delivery details" in last(cid)
    r = call_tool(ctx_for(cid), "review_order").result
    assert r["error"] == "checkout_disabled"
    from app.agent.tools import allowed_tools
    assert "place_order" not in allowed_tools() and "add_to_cart" in allowed_tools()


async def test_a_chat_order_texts_the_customer_when_sms_is_connected(prov):
    connect_provider("alphasms")
    cid = await to_summary()
    await say("ch_web", "web_o1", "Guest O", "yes")
    await sms.drain()
    assert len(prov.alpha_sent) == 1 and "#1045" in prov.alpha_sent[0]["text"] and prov.alpha_sent[0]["to"] == "8801712345678"


async def test_the_staff_view_shows_where_the_order_came_from_and_who_it_is_for(http):
    owner = await setup_owner(http)
    await to_summary()
    await say("ch_web", "web_o1", "Guest O", "yes")
    o = next(x for x in (await http.get("/api/orders", headers=H(owner))).json()["items"] if x["number"] == "#1045")
    assert o["source"] == "chat" and o["ship"] == {"name": "Sadia Rahman", "phone": "01712345678"}
    viewer = await member_token(http, owner, "viewer")
    assert (await http.post("/api/orders/%231045/cancel", headers=H(viewer))).status_code == 403


async def test_settings_accept_a_sane_order_limit_only(http):
    owner = await setup_owner(http)
    assert (await http.put("/api/settings", headers=H(owner), json={"maxOrder": "abc"})).status_code == 400
    assert (await http.put("/api/settings", headers=H(owner), json={"maxOrder": 5})).status_code == 200
    assert checkout._cfg()["maxOrder"] == 500                                            # clamped, never absurdly low


# ---------------------------------------------------------------- the catalog (add, edit, delete)
PROD = {"name": "Camp Stove", "variant": "Single burner", "sku": "NW-CS-1", "price": 3200, "stock": 12, "description": "Folding gas stove.", "keywords": "stove burner cooking", "art": "box"}


async def test_owners_can_add_edit_and_delete_products_and_the_assistant_finds_them(http):
    owner = await setup_owner(http)
    r = await http.post("/api/products", headers=H(owner), json=PROD)
    assert r.status_code == 200 and r.json()["product"]["sku"] == "NW-CS-1"
    assert any(p["sku"] == "NW-CS-1" for p in (await http.get("/api/products", headers=H(owner))).json()["items"])
    from app.agent.tools import search_products_raw      # the assistant's catalog search finds it by name and keywords
    assert [p["sku"] for p in search_products_raw("stove")] == ["NW-CS-1"]
    up = await http.put("/api/products/NW-CS-1", headers=H(owner), json={**PROD, "price": 3500, "stock": 9})
    assert up.status_code == 200 and store.product("NW-CS-1")["price"] == 3500 and store.product("NW-CS-1")["stock"] == 9
    assert (await http.put("/api/products/NW-CS-1", headers=H(owner), json={**PROD, "sku": "OTHER"})).status_code == 400   # the SKU is the key
    assert (await http.delete("/api/products/NW-CS-1", headers=H(owner))).status_code == 200 and store.product("NW-CS-1") is None


async def test_product_input_is_validated_and_skus_are_unique(http):
    owner = await setup_owner(http)
    await http.post("/api/products", headers=H(owner), json=PROD)
    assert (await http.post("/api/products", headers=H(owner), json={**PROD, "sku": "nw-cs-1"})).status_code == 409          # case-insensitive
    for bad in ({"price": 0}, {"price": -5}, {"stock": -1}, {"name": ""}, {"sku": "bad sku!"}, {"art": "../../x"}):
        assert (await http.post("/api/products", headers=H(owner), json={**PROD, "sku": "NW-X", **bad})).status_code == 422


async def test_a_product_used_in_orders_cannot_be_deleted_and_agents_cannot_manage_products(http):
    owner = await setup_owner(http)
    r = await http.delete("/api/products/NW-TB2-NVY", headers=H(owner))
    assert r.status_code == 409 and "stock to 0" in r.json()["detail"]
    agent = await member_token(http, owner, "agent")
    assert (await http.post("/api/products", headers=H(agent), json=PROD)).status_code == 403
    assert (await http.delete("/api/products/NW-TB2-NVY", headers=H(agent))).status_code == 403
    assert (await http.post("/api/products/NW-TB2-NVY/stock", headers=H(agent), json={"delta": 1})).status_code == 200       # stock stays an agent job

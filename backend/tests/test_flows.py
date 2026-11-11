"""The rules that keep the assistant safe, checked end to end against the real domain code."""
from app import db, domain, store
from tests.conftest import say, texts


async def test_product_question_answers_with_live_stock_and_a_card():
    cid = await say("ch_web", "web_t1", "Guest A", "Do you have a navy water bottle?")
    reply = texts(cid, "assistant")[-1]
    assert "Trail Bottle 2L" in reply and "6 in stock" in reply
    meta = db.jl(db.all("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", [cid])[-1]["meta"], {})
    assert meta["product"] == "NW-TB2-NVY"


async def test_cart_changes_only_after_the_customer_confirms():
    cid = await say("ch_web", "web_t2", "Guest B", "Do you have a navy water bottle?")
    assert db.jl(store.conversation(cid)["cart"], []) == []
    await say("ch_web", "web_t2", "Guest B", "yes please add it to my cart")
    cart = db.jl(store.conversation(cid)["cart"], [])
    assert [(l["sku"], l["qty"]) for l in cart] == [("NW-TB2-NVY", 1)]


async def test_review_mode_stages_the_cart_change_until_a_person_approves():
    cid = await say("ch_web", "web_t3", "Guest C", "Do you have a navy water bottle?")
    domain.set_mode(cid, "hybrid", "Tester")
    await say("ch_web", "web_t3", "Guest C", "yes please add it to my cart")
    conv = store.conversation(cid)
    assert db.jl(conv["cart"], []) == []                       # nothing changed yet
    pending = db.jl(conv["pending"], None)
    assert pending and pending["actions"][0]["tool"] == "add_to_cart"
    n_before = len(texts(cid, "assistant"))
    await domain.approve_draft(cid, "Tester")
    assert len(db.jl(store.conversation(cid)["cart"], [])) == 1  # applied on approval
    assert len(texts(cid, "assistant")) == n_before + 1          # and the reply went out


async def test_order_details_are_private_until_the_phone_matches():
    cid = await say("ch_ms", "ms_t4", "Stranger", "where is my order #1042?")
    assert "last 4 digits" in texts(cid, "assistant")[-1]
    assert "SF-26110841" not in " ".join(texts(cid, "assistant"))   # no tracking leaked
    await say("ch_ms", "ms_t4", "Stranger", "9999")                 # wrong digits
    assert "SF-26110841" not in " ".join(texts(cid, "assistant"))
    await say("ch_ms", "ms_t4", "Stranger", "0007")                 # right digits for Rakib's order
    assert "SF-26110841" in " ".join(texts(cid, "assistant"))


async def test_refund_request_goes_to_a_person_and_never_gets_promised():
    # Mahin has no conversation yet, so this starts a fresh one on the web channel.
    before = db.get("SELECT COUNT(*) n FROM approvals WHERE order_number='#1044'")["n"]
    cid = await say("ch_web", "web_mahin", "Mahin Chowdhury", "my order #1044 bottle lid cracked, I want a refund")
    conv = store.conversation(cid)
    assert conv["mode"] == "human" and "return" in conv["handoff_reason"]
    assert db.get("SELECT COUNT(*) n FROM approvals WHERE order_number='#1044' AND status='pending'")["n"] == before + 1
    assert "refund has been" not in " ".join(texts(cid, "assistant")).lower()


async def test_anger_and_person_requests_hand_off():
    cid = await say("ch_ig", "ig_t6", "Angry", "this is a scam, give me a person")
    assert store.conversation(cid)["mode"] == "human"


async def test_a_human_cannot_message_through_a_closed_whatsapp_window():
    import pytest
    with pytest.raises(domain.HttpError) as e:
        await domain.human_reply("cv_tahmid", "Tester", "hello")
    assert e.value.status == 409


def _has_bangla_letters(s: str) -> bool:
    return any("\u0985" <= ch <= "\u09b9" for ch in s)  # letters only; the Taka sign is not Bangla script


async def test_bangla_in_bangla_banglish_in_banglish():
    bn = await say("ch_wa", "88017000", "Bn", "আসসালামু আলাইকুম, তাঁবু আছে?", "+88017000")
    assert _has_bangla_letters(texts(bn, "assistant")[-1])
    bl = await say("ch_ms", "ms_t8", "Bl", "bhai tent ta ache? delivery koto din lagbe?")
    assert not _has_bangla_letters(texts(bl, "assistant")[-1])
    assert "lage" in texts(bl, "assistant")[-1] or "ache" in texts(bl, "assistant")[-1]

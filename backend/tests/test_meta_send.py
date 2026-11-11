"""Outbound: every request Dakbox sends to Meta, checked against the shapes in Meta's docs."""
import httpx
import pytest

from app import db, meta
from tests.conftest import make_channel, make_customer


async def test_whatsapp_text_payload(graph):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922", cfg={"waba_id": "102290129340398"})
    cust = make_customer("wa", "8801712340042", phone="+8801712340042")
    r = await meta.send_text(ch, cust, "Hello Nusrat")
    assert r.delivery == "sent" and r.ext_id.startswith("wamid.")
    c = graph.calls[-1]
    assert c["method"] == "POST" and c["host"] == "graph.facebook.com" and c["path"] == "/v26.0/106540352242922/messages"
    assert c["token_in"] == "bearer" and c["token"] == "good-token-1234567"
    assert c["body"] == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "+8801712340042", "type": "text", "text": {"preview_url": False, "body": "Hello Nusrat"}}


async def test_whatsapp_username_only_users_are_addressed_by_bsuid(graph):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922")
    cust = make_customer("wa", "US.13491208655302741918")
    await meta.send_text(ch, cust, "hi")
    body = graph.calls[-1]["body"]
    assert body["recipient"] == "US.13491208655302741918" and "to" not in body


async def test_messenger_payload_uses_page_id_and_query_token(graph):
    graph.add_page("555000111")
    ch = make_channel("ms", "555000111")
    cust = make_customer("ms", "7777000111")
    r = await meta.send_text(ch, cust, "Hi there")
    assert r.delivery == "sent" and r.ext_id.startswith("m_")
    c = graph.calls[-1]
    assert c["path"] == "/v26.0/555000111/messages" and c["token_in"] == "query" and c["query"]["access_token"] == "good-token-1234567"
    assert c["body"] == {"recipient": {"id": "7777000111"}, "message": {"text": "Hi there"}, "messaging_type": "RESPONSE"}


async def test_instagram_login_and_page_paths_differ(graph):
    graph.add_ig("17841400000000000")
    login = make_channel("ig", "17841400000000000", cfg={"via": "instagram_login"})
    cust = make_customer("ig", "9990001")
    await meta.send_text(login, cust, "hello")
    c = graph.calls[-1]
    assert c["host"] == "graph.instagram.com" and c["path"] == "/v26.0/17841400000000000/messages" and c["token_in"] == "bearer"
    assert c["body"] == {"recipient": {"id": "9990001"}, "message": {"text": "hello"}}
    page = make_channel("ig", "17841400000000000", cfg={"via": "page"}, name="via page")
    await meta.send_text(page, cust, "hello")
    c = graph.calls[-1]
    assert c["host"] == "graph.facebook.com" and c["path"] == "/v26.0/me/messages" and c["token_in"] == "query"


async def test_long_messages_are_split_to_each_channels_limit(graph):
    graph.add_ig("17841400000000000")
    graph.add_wa("106540352242922")
    ig = make_channel("ig", "17841400000000000")
    bangla = " ".join(["আপনার অর্ডারটি প্রস্তুত হচ্ছে"] * 60)           # ~1,500 chars, ~4,000 bytes
    r = await meta.send_text(ig, make_customer("ig", "9990002"), bangla)
    sent = [m["text"] for m in graph.outbox if m["channel"] == "ig"]
    assert r.delivery == "sent" and r.parts == len(sent) > 1
    assert all(len(t.encode()) <= 1000 for t in sent)
    assert " ".join(sent).split() == bangla.split()                    # nothing lost, nothing cut mid-word
    wa = make_channel("wa", "106540352242922")
    await meta.send_text(wa, make_customer("wa", "8801700000009"), "word " * 1200)
    assert all(len(m["text"]) <= 4096 for m in graph.outbox if m["channel"] == "wa") and len([m for m in graph.outbox if m["channel"] == "wa"]) == 2


async def test_demo_channels_never_call_meta(graph):
    from app import store
    r = await meta.send_text(store.channel("ch_wa"), make_customer("wa", "8801700000010"), "hi")
    assert r.delivery == "simulated" and graph.calls == []


@pytest.mark.parametrize("text,kind", [("[[FAIL:190]]", "token"), ("[[FAIL:131047]]", "window"), ("[[FAIL:131026]]", "recipient"), ("[[FAIL:4]]", "rate")])
async def test_whatsapp_errors_are_classified(graph, text, kind):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922")
    r = await meta.send_text(ch, make_customer("wa", "8801700000011"), text)
    assert r.delivery == "failed" and r.kind == kind
    assert "good-token" not in (r.error or "")


async def test_messenger_window_error_code_10(graph):
    graph.add_page("555000111")
    ch = make_channel("ms", "555000111")
    r = await meta.send_text(ch, make_customer("ms", "7777000112"), "[[FAIL:10:2018278]]")
    assert r.kind == "window"


async def test_a_rejected_token_turns_the_channel_red_and_says_so(graph):
    graph.add_page("555000111")
    ch = make_channel("ms", "555000111", token="revoked-token-123456")  # accepted by the fake for lookups, then fails below
    db.run("UPDATE channels SET status='ok'")
    ch = make_channel("ms", "555000112", token="nonsense-token-9999")
    r = await meta.send_text(ch, make_customer("ms", "7777000113"), "hi")
    assert r.kind == "token"
    row = db.get("SELECT * FROM channels WHERE id=?", [ch["id"]])
    assert row["status"] == "danger" and "token" in row["alert"].lower() and row["last_error"]
    assert "nonsense-token" not in row["last_error"] + row["alert"]


async def test_network_failure_hides_urls_and_tokens(graph):
    def boom(request):
        raise httpx.ConnectError("could not connect to https://graph.facebook.com/?access_token=SECRET")
    meta.set_transport(httpx.MockTransport(boom))
    ch = make_channel("ms", "555000111", token="good-secret-token-1")
    r = await meta.send_text(ch, make_customer("ms", "7777000114"), "hi")
    assert r.delivery == "failed" and r.kind == "network"
    assert "SECRET" not in r.error and "graph.facebook" not in r.error and "good-secret" not in r.error


async def test_template_payload_positional_and_named(graph):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922", cfg={"waba_id": "102290129340398"})
    cust = make_customer("wa", "8801712340042", phone="+8801712340042")
    r = await meta.send_template(ch, cust, "order_update", "en", ["Nusrat", "#1042"], ["1", "2"])
    assert r.delivery == "sent"
    assert graph.calls[-1]["body"]["template"] == {"name": "order_update", "language": {"code": "en"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "Nusrat"}, {"type": "text", "text": "#1042"}]}]}
    await meta.send_template(ch, cust, "return_update", "bn", ["নুসরাত", "#1041"], ["name", "order"])
    params = graph.calls[-1]["body"]["template"]["components"][0]["parameters"]
    assert [p["parameter_name"] for p in params] == ["name", "order"]


async def test_wrong_parameter_count_is_rejected_by_meta_and_reported(graph):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922")
    r = await meta.send_template(ch, make_customer("wa", "8801700000012"), "order_update", "en", ["only one"], ["1"])
    assert r.delivery == "failed" and r.kind == "param"


async def test_only_approved_templates_are_offered(graph):
    graph.add_wa("106540352242922")
    ch = make_channel("wa", "106540352242922", cfg={"waba_id": "102290129340398"})
    names = [t["name"] for t in await meta.list_templates(ch)]
    assert names == ["order_update", "return_update"]                  # promo_draft is PENDING
    t = (await meta.list_templates(ch))[1]
    assert t["params"] == ["name", "order"] and "{{name}}" in t["body"]
    assert meta.render_template(t["body"], ["নুসরাত", "#1041"], t["params"]).count("#1041") == 1


async def test_connection_checks(graph):
    graph.add_wa("106540352242922", name="Northwind Outdoor")
    graph.add_ig("17841400000000000", username="northwind.outdoor")
    assert (await meta.validate("wa", "106540352242922", "good-token-1234567", waba_id="102290129340398"))["name"] == "Northwind Outdoor"
    with pytest.raises(meta.MetaError) as e:
        await meta.validate("wa", "106540352242922", "bad-token-12345678")
    assert e.value.kind == "token"
    with pytest.raises(meta.MetaError) as e:                           # IDs go into URL paths: only digits are allowed
        n = len(graph.calls)
        await meta.validate("wa", "../me/accounts", "good-token-1234567")
    assert e.value.kind == "param" and len(graph.calls) == n
    ok = await meta.validate("ig", "17841400000000000", "good-token-1234567")
    assert ok["name"] == "@northwind.outdoor"
    with pytest.raises(meta.MetaError) as e:
        await meta.validate("ig", "17841499999999999", "good-token-1234567")
    assert "northwind.outdoor" in e.value.message


async def test_subscribe_calls_match_the_docs(graph):
    graph.add_wa("106540352242922"); graph.add_page("555000111"); graph.add_ig("17841400000000000")
    wa = make_channel("wa", "106540352242922", cfg={"waba_id": "102290129340398"})
    assert (await meta.subscribe(wa))["ok"] and graph.calls[-1]["path"] == "/v26.0/102290129340398/subscribed_apps"
    ms = make_channel("ms", "555000111")
    assert (await meta.subscribe(ms))["ok"]
    assert graph.calls[-1]["path"] == "/v26.0/555000111/subscribed_apps" and graph.calls[-1]["query"]["subscribed_fields"] == "messages,message_deliveries,message_reads"
    ig = make_channel("ig", "17841400000000000")
    assert (await meta.subscribe(ig))["ok"] and graph.calls[-1]["host"] == "graph.instagram.com"

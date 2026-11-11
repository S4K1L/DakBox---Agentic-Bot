"""Conversation rules: inbound handling, the assistant's turn, drafts, takeover, templates."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from . import checkout, db, store
from .agent.agent import refresh_summary, run_agent, translate_for_staff
from .agent.tools import apply_handoff, apply_staged
from . import meta
from .events import emit
from .util import detect_lang


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


def window_open(conv, channel) -> bool:
    if channel["kind"] == "web":
        return True
    exp = db.parse_ts(conv["window_expires_at"])
    return bool(exp and exp > datetime.now(timezone.utc))


_MEDIA_LABEL = {"image": "Photo", "video": "Video", "audio": "Voice message", "document": "Document", "location": "Location",
                "reel": "Shared reel", "ig_reel": "Shared reel", "share": "Shared post", "story_mention": "Story mention"}


def _ack_for(lang: str, label: str) -> tuple[str, str]:
    en = f"Thanks, we received your {label.lower()}. A teammate will take a look and reply shortly."
    return {
        "bn": "ধন্যবাদ, আপনার পাঠানো ফাইলটি পেয়েছি। আমাদের একজন সহকর্মী শীঘ্রই দেখে উত্তর দেবেন।",
        "bl": "Dhonnobad, apnar pathano file ta peyechi. Amader ekjon sohokormi shighroi dekhe reply debe.",
    }.get(lang, en), en


async def process_inbound(channel_id: str, external_id: str, name: str, text: str, phone: str | None = None, translation: str | None = None,
                          ext_msg_id: str | None = None, media: dict | None = None) -> str:
    channel = store.channel(channel_id)
    if not channel:
        raise HttpError(400, "unknown channel")
    lang = detect_lang(text) if text else "en"
    cust = store.find_or_create_customer(external_id, channel["kind"], name, phone, lang)
    if text and cust["lang"] != lang and len(text) > 6:
        db.run("UPDATE customers SET lang=? WHERE id=?", [lang, cust["id"]])
    conv = store.find_or_create_conversation(cust["id"], channel_id)
    label = _MEDIA_LABEL.get(media["type"], "Attachment") if media else None
    shown = text or (f"[{label}]" + (f" {media['caption']}" if media and media.get("caption") else ""))
    tr = translation or (await translate_for_staff(text) if text else None)
    mid = store.add_message(conv["id"], "customer", shown, author=cust["name"], translation=tr, external_id=ext_msg_id, meta={"attachment": media["type"]} if media else None)
    if mid is None:
        return conv["id"]  # duplicate delivery: already handled
    if conv["status"] == "resolved":
        db.run("UPDATE conversations SET status='open' WHERE id=?", [conv["id"]])
    emit("channels")
    if media and not text:
        # The assistant cannot see photos or files (a damage claim, a screenshot of a payment): a person must.
        fresh = store.conversation(conv["id"])
        if fresh["mode"] != "human":
            apply_handoff(conv["id"], f"sent a {label.lower()}")
            ack, en = _ack_for(cust["lang"], label)
            await _send_assistant(store.conversation(conv["id"]), ack, None if cust["lang"] == "en" else en)
        return conv["id"]
    if conv["mode"] != "human":
        queue_respond(conv["id"])
    return conv["id"]


def queue_respond(conversation_id: str) -> None:
    """Answer in the background; turns for one conversation never overlap."""
    t = asyncio.create_task(_respond(conversation_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _respond(conversation_id: str) -> None:
    lock = _locks.setdefault(conversation_id, asyncio.Lock())
    async with lock:
        conv = store.conversation(conversation_id)
        if not conv or conv["mode"] == "human":
            return
        emit("typing", id=conversation_id, on=True)
        _ch, _cu = store.channel(conv["channel_id"]), store.customer(conv["customer_id"])
        if _ch["kind"] == "ms":
            t = asyncio.create_task(meta.typing_on(_ch, _cu))
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
        try:
            await asyncio.sleep(0.5 + random.random() * 0.5)
            conv = store.conversation(conversation_id)
            stage = conv["mode"] == "hybrid"
            out = await run_agent(conversation_id, stage)
            conv = store.conversation(conversation_id)
            if conv["mode"] == "human" and not stage and not conv["handoff_reason"]:
                return  # a teammate took over while the assistant was working
            if not out.text:
                return
            if stage:
                pending = {"text": out.text, "translation": out.translation, "actions": out.staged, "productSku": out.product_sku, "createdAt": db.now()}
                db.run("UPDATE conversations SET pending=? WHERE id=?", [db.dumps(pending), conversation_id])
                emit("conversation", id=conversation_id)
                emit("approvals")
            else:
                await _send_assistant(conv, out.text, out.translation, out.product_sku)
                if out.after:
                    await checkout.run_after(conversation_id, out.after)
            asyncio.create_task(refresh_summary(conversation_id))
        except Exception as e:  # keep the loop alive; the customer message stays visible to staff
            print("[respond]", repr(e))
            store.add_event(conversation_id, "alert", "The assistant could not reply", str(e)[:120], "warn")
        finally:
            emit("typing", id=conversation_id, on=False)


def _delivery_label(r) -> str:
    if r.delivery == "failed":
        return f"Failed: {r.error}"
    return "Simulated" if r.delivery == "simulated" else "Sent"


def _ext(channel, r) -> str | None:
    return f"{channel['id']}:{r.ext_id}" if getattr(r, "ext_id", None) else None


async def _send_assistant(conv, text: str, translation: str | None, product_sku: str | None = None) -> None:
    channel, cust = store.channel(conv["channel_id"]), store.customer(conv["customer_id"])
    r = await meta.send_text(channel, cust, text)
    store.add_message(conv["id"], "assistant", text, author="Assistant", translation=translation, meta={"product": product_sku} if product_sku else None,
                      delivery=_delivery_label(r), external_id=_ext(channel, r))
    if r.delivery == "failed":
        store.add_event(conv["id"], "alert", "The reply could not be sent", r.error, "warn")


# ---------------------------------------------------------------- staff actions
async def approve_draft(conversation_id: str, by: str, edited: str | None = None) -> None:
    conv = store.conversation(conversation_id)
    if not conv:
        raise HttpError(404, "not found")
    pending = db.jl(conv["pending"], None)
    if not pending:
        raise HttpError(409, "No draft to approve")
    if not window_open(conv, store.channel(conv["channel_id"])):
        raise HttpError(409, "The 24-hour window is closed. Send an approved template instead.")
    try:
        after = apply_staged(conversation_id, conv["customer_id"], pending["actions"])
    except checkout.CheckoutError as e:      # the draft stays pending: nothing was changed
        raise HttpError(409, f"The order was not placed: {checkout.explain(e)}") from None
    db.run("UPDATE conversations SET pending=NULL WHERE id=?", [conversation_id])
    if any(a["tool"] == "add_to_cart" for a in pending["actions"]):
        store.add_event(conversation_id, "check", f"{by} approved the cart change", "add_to_cart · approved", "ok")
    text = (edited or "").strip() or pending["text"]
    await _send_assistant(store.conversation(conversation_id), text, None if edited else pending.get("translation"), pending.get("productSku"))
    if after:
        await checkout.run_after(conversation_id, after)
    asyncio.create_task(refresh_summary(conversation_id))


def dismiss_draft(conversation_id: str) -> None:
    db.run("UPDATE conversations SET pending=NULL WHERE id=?", [conversation_id])
    emit("conversation", id=conversation_id)


async def human_reply(conversation_id: str, by: str, text: str, internal: bool = False) -> str | None:
    """Returns the delivery label ("Sent", "Simulated", or "Failed: ...")."""
    conv = store.conversation(conversation_id)
    if not conv:
        raise HttpError(404, "not found")
    if internal:
        store.add_event(conversation_id, "note", f"Note from {by}", text)
        return None
    channel = store.channel(conv["channel_id"])
    if not window_open(conv, channel):
        raise HttpError(409, "The 24-hour window is closed. Send an approved template instead.")
    if conv["mode"] == "agent":
        set_mode(conversation_id, "human", by)
    r = await meta.send_text(channel, store.customer(conv["customer_id"]), text)
    if r.delivery == "failed" and r.kind == "window":
        raise HttpError(409, r.error)  # Meta's clock disagrees with ours: nothing was sent, do not pretend it was
    label = _delivery_label(r)
    store.add_message(conversation_id, "human", text, author=by, delivery=label, external_id=_ext(channel, r))
    db.run("UPDATE conversations SET pending=NULL WHERE id=?", [conversation_id])
    return label


async def list_templates(conversation_id: str) -> list[dict]:
    conv = store.conversation(conversation_id)
    if not conv:
        raise HttpError(404, "not found")
    channel = store.channel(conv["channel_id"])
    if channel["kind"] != "wa":
        return []
    try:
        return await meta.list_templates(channel)
    except meta.MetaError as e:
        raise HttpError(502, e.message)


async def send_template(conversation_id: str, by: str, name: str, language: str, params: list[str]) -> str:
    conv = store.conversation(conversation_id)
    if not conv:
        raise HttpError(404, "not found")
    channel, cust = store.channel(conv["channel_id"]), store.customer(conv["customer_id"])
    if channel["kind"] != "wa":
        raise HttpError(400, "Templates are only used on WhatsApp")
    t = next((x for x in await list_templates(conversation_id) if x["name"] == name and x["language"] == language), None)
    if not t:
        raise HttpError(404, "That template is not approved for this number.")
    params = [p.strip() for p in params]
    if len(params) != len(t["params"]) or any(not p for p in params):
        raise HttpError(400, f"This template needs {len(t['params'])} value(s).")
    r = await meta.send_template(channel, cust, name, language, params, t["params"])
    if r.delivery == "failed":
        raise HttpError(502, r.error or "Meta rejected the template.")
    text = meta.render_template(t["body"], params, t["params"])
    label = "Simulated" if r.delivery == "simulated" else "Sent as template"
    store.add_message(conversation_id, "human", text, author=by, delivery=label, meta={"template": name}, external_id=_ext(channel, r))
    return label


def set_mode(conversation_id: str, mode: str, by: str) -> None:
    conv = store.conversation(conversation_id)
    if not conv or conv["mode"] == mode or mode not in ("agent", "hybrid", "human"):
        return
    db.run(
        "UPDATE conversations SET mode=?, pending=CASE WHEN ?='hybrid' THEN pending ELSE NULL END, handoff_reason=CASE WHEN ?='agent' THEN NULL ELSE handoff_reason END WHERE id=?",
        [mode, mode, mode, conversation_id],
    )
    if mode == "human":
        store.add_event(conversation_id, "user", f"{by} took over this conversation")
    elif mode == "agent":
        store.add_event(conversation_id, "spark", "Assistant is replying again")
    else:
        store.add_event(conversation_id, "spark", "Assistant drafts, a person approves")
    emit("conversation", id=conversation_id)
    if mode != "human":  # pick up a customer message that is still unanswered
        last = db.get("SELECT role FROM messages WHERE conversation_id=? AND role != 'event' ORDER BY id DESC LIMIT 1", [conversation_id])
        if last and last["role"] == "customer":
            queue_respond(conversation_id)


def resolve(conversation_id: str, by: str, on: bool = True) -> None:
    db.run("UPDATE conversations SET status=? WHERE id=?", ["resolved" if on else "open", conversation_id])
    if on:
        store.add_event(conversation_id, "check", f"{by} resolved the conversation", None, "ok")
    emit("conversation", id=conversation_id)

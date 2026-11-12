"""Offline engine: same tools and rules as the Claude engine, driven by simple intent rules.

It keeps the product usable with no API key, and is the fallback when the model API is unreachable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .. import checkout, db, store
from ..util import DISTRICTS, detect_lang, from_bn_digits, is_dhaka, taka, to_bn_digits
from . import catalog_search
from .tools import ToolCtx, call_tool


@dataclass
class EngineResult:
    text: str
    translation: str | None
    product_sku: str | None = None
    confidence: int = 90


ALIASES = {
    "bottle": re.compile(r"bottle|botol|বোতল|flask|water", re.I),
    "tent": re.compile(r"\btent\b|tabu|তাঁবু|তাবু|ridgeline", re.I),
    "jacket": re.compile(r"jacket|জ্যাকেট|jaket|alpine|shell", re.I),
    "boot": re.compile(r"\bboots?\b|\bshoes?\b|juta|জুতা|জুতো", re.I),
}
I = re.I
RX = {
    "human": re.compile(r"\b(person|human|agent|staff|manager|real person)\b|manush|মানুষ|কারো সাথে|কাউকে দিন|talk to someone", I),
    "damage": re.compile(r"crack|broken|damag|defect|wrong item|faulty|vege|bhenge|ভেঙ্গে|ভেঙে|নষ্ট", I),
    "refund_ask": re.compile(r"refund|রিফান্ড|ফেরত চাই|return korte chai|ফেরত দিতে চাই|exchange chai|replace", I),
    "complaint": re.compile(r"complain|scam|cheat|fraud|lawyer|legal|police|প্রতারণা|অভিযোগ|ঠকিয়ে|worst", I),
    "return_policy": re.compile(r"return|ফেরত|রিটার্ন|refund|exchange|এক্সচেঞ্জ", I),
    "order": re.compile(r"order|অর্ডার|track|ট্র্যাক|kothay|কোথায়|status|parcel|পার্সেল", I),
    "thanks": re.compile(r"thank|thanks|dhonnobad|dhonnobaad|ধন্যবাদ|thik ache|ঠিক আছে|shukriya|ok bhai|got it", I),
    "cart": re.compile(r"\bcart\b|কার্টে|কার্ট|add (it|one|this)|দিয়ে দিন|দিয়ে দাও|nibo|নিব|নেব|i('ll| will) take|take it|yes please|\bhaan?\b|\bji\b|হ্যাঁ", I),
    "notify": re.compile(r"notify|alert|let me know|jante chai|জানান|জানাবেন|back in stock|restock|janaben|janiye", I),
    "delivery": re.compile(r"deliver|ডেলিভারি|shipping|din lagbe|koto din|কত দিন|charge|courier", I),
    "payment": re.compile(r"bkash|nagad|\bcod\b|cash on|payment|পেমেন্ট|বিকাশ|ক্যাশ", I),
    "greeting": re.compile(r"assalam|আসসালামু|^hi\b|^hello|^hey|^salam", I),
    "waterproof": re.compile(r"waterproof|ওয়াটারপ্রুফ|পানি", I),
    "detail": re.compile(r"detail|description|describe|material|fabric|quality|length|width|weight|made of|about (it|this|the)|spec|বিস্তারিত|কাপড়|কেমন|মান|সাইজ|ডিটেইল|bistarito|kapor|kemon|details", I),
    "browse": re.compile(r"what (do|all|else) (you|u) (sell|have|offer)|what.{0,20}(products|items|collection|catalog)|(show|see|send).{0,15}(products|collection|catalog|items)|\b(catalog|catalogue|collection|new arrivals?|best ?sellers?)\b|ki ki (ache|bikri|paoa|pawa)|ki ki|কি কি আছে|কী কী আছে|কি কি বিক্রি|কালেকশন|ক্যাটালগ|কী কী পাওয়া|কিছু দেখান|kichu dekhan|sob product|সব পণ্য", I),
    "inquiry": re.compile(r"\b(have|has|available|in stock|price|cost|how much|show|looking|want|need|buy|get|sell|is there|do you)\b|ache\b|achhe|\base\b|koto|\bdam\b|dekhan|dekhao|chai\b|lagbe|kinbo|kinte|আছে|দাম|কত|দেখান|দেখাও|চাই|লাগবে|কিনব|কিনতে|পাওয়া যায়|পাব|\?", I),
    "policy_q": re.compile(r"\bpolicy\b|korte parbo|করতে পারব|ferot dewa jay|যাবে কি|can i return", I),
}


# ---------------------------------------------------------------- checkout conversation (state is read from the last thing we said)
YES = re.compile(r"^\W*(yes|yep|yeah|y|confirm(ed)?|ok(ay)?|sure|place it|place the order|go ahead|ji|jii|han|haan|hya|hyan|thik ache|thik|korun|kore din|kore den|হ্যাঁ|হ্যা|জি|ঠিক আছে|ঠিক|কনফার্ম|করুন|করে দিন|করে দেন)(?=\W|$)", I)
NO = re.compile(r"^\W*(no|nope|cancel|wait|change|na|nah|না|থামুন|বদল|চেঞ্জ)(?=\W|$)", I)
CHECKOUT = re.compile(r"check ?out|place (the |my |an? )?order|(order|ordar) (korbo|korte chai|dibo|nibo|kore den|kore dao)|want to order|(i'd|i would) like to order|অর্ডার (করব|করবো|করতে চাই|দিতে চাই|করে দিন)|confirm (my |the )?order", I)
S_METHOD = r"How would you like to pay|কীভাবে পেমেন্ট করবেন|Kibhabe payment korben"
S_DETAILS = r"I still need|full name, phone|আর যা লাগবে|পুরো নাম, ফোন|aro lagbe|pura naam, phone"
S_CONFIRM = r"Reply YES to place|অর্ডার করতে হ্যাঁ|Order korte hya"
LABEL_BN = {"Cash on delivery": "ক্যাশ অন ডেলিভারি", "bKash": "বিকাশ"}
FIELD_EN = {"name": "name", "phone": "mobile number", "address": "delivery address", "district": "district", "method": "payment method"}
FIELD_BN = {"name": "নাম", "phone": "মোবাইল নম্বর", "address": "ডেলিভারির ঠিকানা", "district": "জেলা", "method": "পেমেন্ট পদ্ধতি"}
FIELD_BL = {"name": "naam", "phone": "mobile number", "address": "delivery address", "district": "district", "method": "payment method"}


def _parse_details(raw: str) -> dict:
    """Pull a name, phone, address and payment method out of what the customer wrote. Anything unclear is left out and asked for again."""
    t = from_bn_digits(raw)
    out: dict = {}
    m = re.search(r"(?:\+?88)?01[3-9]\d{8}", re.sub(r"[ \-]", "", t))
    if m:
        out["phone"] = m.group()
    method = checkout.match_method(t)
    if method:
        out["payment_method"] = method
    ph = re.search(r"(?:\+?88)?[\s-]*0?1[3-9](?:[\s-]*\d){8}", t)
    pre = post = ""
    if ph:
        pre, post = t[:ph.start()], t[ph.end():]
    noise = r"\b(cod|cash on delivery|bkash|bikash|payment|card)\b|ক্যাশ অন ডেলিভারি|বিকাশ"
    body = re.sub(noise, " ", t, flags=I)
    body = re.sub(r"(?:\+?88)?[\s-]*0?1[3-9](?:[\s-]*\d){8}", " ", body)
    lines = [l.strip(" ,;।") for l in re.split(r"[\n;]+", body) if l.strip(" ,;।")]
    name = addr = None
    for l in list(lines):
        mm = re.match(r"(?:my\s+)?(?:full\s+)?(?:name|naam|nam|নাম)\s*(?:is|:|-)?\s*(.+)", l, I)
        if mm and not name:
            name = mm.group(1)
            lines.remove(l)
            continue
        mm = re.match(r"(?:delivery\s+|my\s+)?(?:address|thikana|ঠিকানা)\s*(?:is|:|-)?\s*(.+)", l, I)
        if mm and not addr:
            addr = mm.group(1)
            lines.remove(l)
    short = lambda x: bool(x) and len(x.split()) <= 4 and not re.search(r"\d", x) and len(x) <= 40 and not find_district_word(x)  # noqa: E731
    if ph and "\n" not in t and not name and not addr:
        # one line around the phone: "Sadia Rahman 01712345678 House 12, Road 4, Sylhet"
        p0 = re.sub(noise, " ", pre, flags=I).strip(" ,;।-")
        p1 = re.sub(noise, " ", post, flags=I).strip(" ,;।-")
        if short(p0) and p1:
            name, addr, lines = p0, p1, []
        elif short(p1) and p0:
            name, addr, lines = p1, p0, []
    if not (name and addr):
        if len(lines) == 1 and "," in lines[0]:
            lines = [x.strip() for x in lines[0].split(",") if x.strip()]
        if not name and len(lines) > 1 and short(lines[0]):
            name = lines.pop(0)
        if not addr and lines:
            addr = ", ".join(lines)
    if name:
        out["name"] = name
    if addr and len(addr) >= 3:
        out["address"] = re.sub(r"\s+", " ", addr)
    return out


def find_district_word(s: str) -> bool:
    return bool(checkout.find_district(s))


def _bn_digits(settings: dict, lang: str, text: str) -> str:
    """Bangla digits in Bangla replies, without touching product names like 'Ridgeline 3 Tent'."""
    if not (lang == "bn" and settings.get("bnDigits")):
        return text
    names = []
    for p in db.all("SELECT name, variant FROM products"):
        names += [p["name"], p["variant"] or ""]
    keep: list[str] = []
    out = text
    for n in sorted((n for n in names if n), key=len, reverse=True):
        if n in out:
            keep.append(n)
            out = out.replace(n, f"\x01{len(keep) - 1}\x02")
    out = to_bn_digits(out)
    return re.sub(r"\x01([০-৯0-9]+)\x02", lambda m: keep[int(from_bn_digits(m.group(1)))], out)


def _last_product_sku(history) -> str | None:
    for m in reversed(history):
        meta = db.jl(m["meta"], None)
        if meta and meta.get("product"):
            return meta["product"]
    return None


def _order_number(texts: list[str]) -> str | None:
    for t in reversed(texts):
        m = re.search(r"#?\b(1\d{3})\b", t)
        if m:
            return f"#{m.group(1)}"
    return None


def _product_from_text(text: str) -> str | None:
    """The one product the customer's words clearly point to (any catalogue), or None when it is unclear."""
    return catalog_search.best_unique(text)


def _stock_phrase(p) -> tuple[str, str, str]:
    n = p["stock"]
    if n == 0:
        return ("স্টকে নেই", "stock e nei", "out of stock")
    if n <= 3:
        return (f"মাত্র {n}টি আছে", f"matro {n}ta ache", f"only {n} left")
    return ("স্টকে আছে", "stock e ache", "in stock")


def _first_sentences(text: str | None, n: int = 2) -> str:
    parts = re.split(r"(?<=[.।!?])\s+", (text or "").strip())
    return " ".join(parts[:n]).strip()


def _one_product_reply(reply, name: str, variants: list, detail: bool, text: str, closest: bool, said: list[str]):
    p0 = variants[0]
    ins = [p for p in variants if p["stock"] > 0]
    desc = (p0["description"] or "").strip()
    d_en = f" {desc if detail else _first_sentences(desc, 1)}" if desc else ""
    pre_bn = pre_bl = pre_en = ""
    if closest and said:
        w = ", ".join(said)
        pre_bn, pre_bl, pre_en = f"\"{w}\" ঠিক মেলেনি, কাছাকাছি: ", f"\"{w}\" thik melenai, kachakachi: ", f"Nothing matched \"{w}\" exactly; the closest is: "
    if len(variants) == 1:
        p = variants[0]
        v = f" ({p['variant']})" if p["variant"] else ""
        if p["stock"] == 0:
            return reply(f"{pre_bn}দুঃখিত, {name}{v} এখন স্টকে নেই। স্টকে এলে আপনাকে জানাব?", f"{pre_bl}Dukkhito, {name}{v} ekhon stock e nei. Stock e ashle apnake janabo?",
                         f"{pre_en}{name}{v} is out of stock right now. I can tell you as soon as it is back. Would you like that?", product_sku=p["sku"])
        return reply(f"{pre_bn}জি, {name}{v} আছে। এখন স্টকে {p['stock']}টি আছে, দাম {taka(p['price'], True)}।{d_en if desc else ''} কার্টে যোগ করে দেব?",
                     f"{pre_bl}Ji, {name}{v} ache. Ekhon stock e {p['stock']}ta ache, dam {taka(p['price'])}.{d_en if desc else ''} Cart e add kore dei?",
                     f"{pre_en}Yes, the {name}{v} is available. {p['stock']} in stock at {taka(p['price'])}.{d_en} Shall I add it to your cart?", product_sku=p["sku"])
    opts_en = "; ".join(f"{p['variant'] or name} {taka(p['price'])}" + ("" if p["stock"] > 0 else " (out of stock)") for p in variants[:6])
    opts_bn = "; ".join(f"{p['variant'] or name} {taka(p['price'], True)}" + ("" if p["stock"] > 0 else " (স্টকে নেই)") for p in variants[:6])
    opts_bl = "; ".join(f"{p['variant'] or name} {taka(p['price'])}" + ("" if p["stock"] > 0 else " (stock e nei)") for p in variants[:6])
    tail_en = "Which one would you like?" if ins else "All of them are out of stock right now. Want me to tell you when one is back?"
    tail_bn = "কোনটি নেবেন?" if ins else "এখন সবই স্টকে নেই। স্টকে এলে জানাব?"
    tail_bl = "Kon ta nite chan?" if ins else "Ekhon sob stock e nei. Stock e ashle janabo?"
    return reply(f"{pre_bn}{name} পাওয়া যায়: {opts_bn}।{d_en if desc and detail else ''} {tail_bn}", f"{pre_bl}{name} paoa jay: {opts_bl}.{d_en if desc and detail else ''} {tail_bl}",
                 f"{pre_en}The {name} comes in: {opts_en}.{d_en if desc and detail else ''} {tail_en}", product_sku=(ins[0]["sku"] if len(ins) == 1 else None))


def _list_reply(reply, groups: list, closest: bool, said: list[str]):
    def one(name, vs, bn):
        lo = min(p["price"] for p in vs)
        price = taka(lo, bn)
        more = (f" ({len(vs)} {'টি অপশন' if bn else 'options'})" if len(vs) > 1 else (f" ({vs[0]['variant']})" if vs[0]["variant"] else ""))
        gone = " (out of stock)" if all(p["stock"] == 0 for p in vs) else ""
        return f"{name}{more} {'from ' if len(vs) > 1 and len({p['price'] for p in vs}) > 1 else ''}{price}{gone}"
    en = "; ".join(one(n, vs, False) for n, vs in groups)
    bn = "; ".join(one(n, vs, True) for n, vs in groups)
    pre_en = pre_bn = pre_bl = ""
    if closest and said:
        w = ", ".join(said)
        pre_bn, pre_bl, pre_en = f"\"{w}\" ঠিক মেলেনি। কাছাকাছি: ", f"\"{w}\" thik melenai. Kachakachi: ", f"Nothing matched \"{w}\" exactly. The closest: "
    return reply(f"{pre_bn}আমাদের কাছে আছে: {bn}। কোনটি সম্পর্কে জানতে চান?", f"{pre_bl}Amader kache ache: {bn}. Kon ta somporke jante chan?",
                 f"{pre_en}We have: {en}. Which one would you like to know more about?", confidence=85)


def run_offline(ctx: ToolCtx, history: list, settings: dict) -> EngineResult:
    last_c = next((m for m in reversed(history) if m["role"] == "customer"), None)
    raw = last_c["text"] if last_c else ""
    text = from_bn_digits(raw)
    lang = detect_lang(raw)
    if settings["replyLanguage"] == "bn":
        lang = "bn"
    elif settings["replyLanguage"] == "en":
        lang = "en"
    elif lang == "bl" and not settings["banglish"]:
        lang = "en"
    recent_langs = [detect_lang(m["text"]) for m in [m for m in history if m["role"] == "customer"][-3:]]
    if lang == "en" and len(text) < 12 and "bl" in recent_langs and not re.search(r"[a-z]{4,}", re.sub(r"thanks?|thank you|please|hello", "", text, flags=re.I)):
        lang = "bl"

    def reply(bn: str, bl: str, en: str, **kw) -> EngineResult:
        t = {"bn": bn, "bl": bl, "en": en}[lang]
        return EngineResult(_bn_digits(settings, lang, t), None if lang == "en" else en, kw.get("product_sku"), kw.get("confidence", 90))

    prior = [m for m in history if m["role"] != "event"]
    last_bot = next((m for m in reversed(prior) if m["role"] == "assistant"), None)
    bot_said = lambda rx: bool(last_bot and re.search(rx, last_bot["text"], I))  # noqa: E731
    customer_texts = [from_bn_digits(m["text"]) for m in history if m["role"] == "customer"][-10:]

    def order_reply(no: str, last4: str | None = None) -> EngineResult:
        out = call_tool(ctx, "get_order_status", order_number=no, phone_last4=last4)
        r = out.result
        if r.get("error") == "order_not_found":
            return reply(f"{no} নম্বরে কোনো অর্ডার পাইনি। নম্বরটি আবার দেখে লিখবেন?", f"{no} number e kono order pai ni. Number ta abar dekhe likhben?", f"I could not find order {no}. Could you check the number and send it again?")
        if r.get("error") == "verification_required":
            return reply("আপনার তথ্য নিরাপদ রাখতে অর্ডারে দেওয়া ফোন নম্বরের শেষ ৪ সংখ্যা লিখবেন?", "Apnar tothyo nirapod rakhte order e deya phone number er shesh 4 digit likhben?", "To keep your order private, please send the last 4 digits of the phone number on the order.")
        c, stat = r.get("courier"), r.get("fulfillment", "")
        bn_stat = {"In transit": "পথে আছে", "Delivered": "ডেলিভারি হয়েছে", "Cancelled": "বাতিল হয়েছে"}.get(stat, "প্রস্তুত হচ্ছে")
        bl_stat = {"In transit": "pothe ache", "Delivered": "delivery hoye geche", "Cancelled": "batil hoyeche"}.get(stat, "prostut hocche")
        return reply(
            f"আপনার {no} অর্ডারটি {bn_stat}।" + (f" কুরিয়ার {c['name']}, ট্র্যাকিং {c['tracking']}।" if c else ""),
            f"Apnar {no} order ta {bl_stat}." + (f" Courier {c['name']}, tracking {c['tracking']}." if c else ""),
            f"Your order {no} is {stat.lower()}." + (f" {c['name']}, tracking {c['tracking']}." if c else "") + (f" Estimated: {c['eta']}." if c and c.get("eta") else ""),
        )

    def ask_next(missing_fields: list[str] | None) -> tuple[str, str, str]:
        """The next question of checkout, in all three languages. `None` means: look at what is saved."""
        if not checkout.enabled():
            call_tool(ctx, "handoff_to_human", reason="order request")
            return ("একজন সহকর্মী শীঘ্রই আপনার ডেলিভারির তথ্য নিয়ে অর্ডার নিশ্চিত করবেন।", "Ekjon sohokormi shighroi apnar delivery tothyo niye order nishchit korben.", "A teammate will take your delivery details and confirm the order here shortly.")
        ck = checkout.get(ctx.conversation_id)
        miss = checkout.missing(ck) if missing_fields is None else missing_fields
        ms = checkout.methods()
        if "method" in miss and len(ms) == 1:
            call_tool(ctx, "set_delivery_details", payment_method=ms[0]["id"])
            miss = [f for f in miss if f != "method"]
        if "method" in miss:
            lab = [m["label"] for m in ms]
            return (f"কীভাবে পেমেন্ট করবেন: {' নাকি '.join(LABEL_BN.get(x, x) for x in lab)}?", f"Kibhabe payment korben: {' naki '.join(lab)}?", f"How would you like to pay: {' or '.join(lab)}?")
        if len(miss) == len(checkout.missing({})) - 1 or len(miss) >= 4:
            return ("অর্ডার করতে আপনার পুরো নাম, ফোন নম্বর আর ডেলিভারির ঠিকানা (বাড়ি, রাস্তা, এলাকা, জেলা) লিখে পাঠান।",
                    "Order korte apnar pura naam, phone number ar delivery address (bari, road, area, district) likhe pathan.",
                    "To order, please send your full name, phone number and delivery address (house, road, area, district).")
        return (f"আর যা লাগবে: {', '.join(FIELD_BN[f] for f in miss)}।", f"Aro lagbe: {', '.join(FIELD_BL[f] for f in miss)}.", f"I still need your {', '.join(FIELD_EN[f] for f in miss)}.")

    def present_summary() -> EngineResult:
        out = call_tool(ctx, "review_order")
        s = out.result
        if not s["ready"]:
            codes = {p["code"]: p for p in s["problems"]}
            if "over_limit" in codes or "too_many_units" in codes:
                call_tool(ctx, "handoff_to_human", reason="large order")
                return reply("এটা বড় অর্ডার, তাই একজন সহকর্মী আপনার সাথে কথা বলে নিশ্চিত করবেন। উনি শীঘ্রই এই চ্যাটে আসবেন।", "Eta boro order, tai ekjon sohokormi apnar sathe kotha bole nishchit korben. Uni shighroi ei chat e asben.", "That is a large order, so a teammate will confirm it with you. They will reply in this chat shortly.")
            if "insufficient_stock" in codes:
                x = codes["insufficient_stock"]
                return reply(f"দুঃখিত, {x['name']} এখন মাত্র {x['in_stock']}টি আছে। সংখ্যা কমিয়ে দেব?", f"Dukkhito, {x['name']} ekhon matro {x['in_stock']}ta ache. Songkha komiye dei?", f"Sorry, only {x['in_stock']} of the {x['name']} left. Shall I lower the quantity?")
            if "missing_details" in codes:
                n = ask_next(codes["missing_details"]["fields"])
                return reply(*n)
            return reply("অর্ডারটি এখন সম্পূর্ণ করা যাচ্ছে না। একজন সহকর্মীকে জানাচ্ছি।", "Order ta ekhon complete kora jachhe na. Ekjon sohokormi ke janachhi.", "I cannot complete this order right now. I am letting a teammate know.")
        ls_en = "; ".join(f"{l['qty']} x {l['name']}" + (f" ({l['variant']})" if l["variant"] else "") + f" {taka(l['price'] * l['qty'])}" for l in s["lines"])
        ls_bn = "; ".join(f"{l['qty']}টি {l['name']}" + (f" ({l['variant']})" if l["variant"] else "") + f" {taka(l['price'] * l['qty'], True)}" for l in s["lines"])
        who = f"{s['name']}, {s['phone']}, {s['address']}"
        mth = s["payment_method"]
        return reply(
            f"অর্ডারটি দেখে নিন: {ls_bn}। ডেলিভারি চার্জ {taka(s['delivery'], True)}, মোট {taka(s['total'], True)}, পেমেন্ট: {LABEL_BN.get(mth, mth)}। {who} ঠিকানায় পাঠানো হবে। অর্ডার করতে হ্যাঁ লিখুন, কিছু বদলাতে চাইলে জানান।",
            f"Order ta dekhe nin: {ls_en}. Delivery charge {taka(s['delivery'])}, mot {taka(s['total'])}, payment: {mth}. {who} e pathano hobe. Order korte hya likhun, kichu bodlate chaile janan.",
            f"Please check your order: {ls_en}. Delivery {taka(s['delivery'])}, total {taka(s['total'])}, payment: {mth}. Deliver to {who}. Reply YES to place the order, or tell me what to change.",
        )

    def after_saved(r: dict) -> EngineResult:
        if r.get("problems"):
            pr = r["problems"][0]
            if pr["field"] == "payment_method":
                lab = [m["label"] for m in pr["available"]]
                return reply(f"দুঃখিত, এখন শুধু {' বা '.join(LABEL_BN.get(x, x) for x in lab)} নেওয়া যাচ্ছে।", f"Dukkhito, ekhon shudhu {' ba '.join(lab)} neya jachhe.", f"Sorry, right now I can only take {' or '.join(lab)}.")
            f = pr["field"]
            return reply(f"{FIELD_BN[f]} ঠিক পাইনি। আবার লিখবেন?", f"{FIELD_BL[f]} thik pai ni. Abar likhben?", f"I could not use that {FIELD_EN[f]}: {pr['problem']}")
        miss = r["missing"]
        if "method" in miss and len(checkout.methods()) == 1:
            r2 = call_tool(ctx, "set_delivery_details", payment_method=checkout.methods()[0]["id"]).result
            miss = r2["missing"]
        if miss:
            return reply(*ask_next(miss))
        return present_summary()

    # 1. a person was asked for, or the customer is angry
    if RX["human"].search(text) or RX["complaint"].search(text):
        call_tool(ctx, "handoff_to_human", reason="complaint" if RX["complaint"].search(text) else "asked for a person")
        return reply("ঠিক আছে, আমি একজন সহকর্মীকে যুক্ত করছি। উনি শীঘ্রই এই চ্যাটে উত্তর দেবেন।", "Thik ache, ami ekjon sohokormi ke connect korchi. Uni khub shighroi ei chat e reply debe.", "Of course. I am bringing in a teammate, who will reply in this chat shortly.")

    # 2. damaged item or refund request on an order
    if (RX["damage"].search(text) or RX["refund_ask"].search(text)) and not RX["policy_q"].search(text):
        mine = db.all("SELECT number FROM orders WHERE customer_id = ? AND fulfillment = 'Delivered' ORDER BY created_at DESC", [ctx.customer_id])
        no = _order_number(customer_texts) or (mine[0]["number"] if mine else None)
        if no:
            call_tool(ctx, "request_return", order_number=no, kind="exchange" if re.search(r"exchange|এক্সচেঞ্জ", text, I) else "refund", reason=raw[:200])
            return reply(f"দুঃখিত, এটা শুনে খারাপ লাগল। আপনার {no} অর্ডারের অনুরোধটি আমাদের টিমের কাছে পাঠিয়েছি। অনুমোদন হলেই এখানে জানাব।", f"Eta shune kharap laglo. Apnar {no} order er request ta amader team er kache pathiyechi. Approve hole ekhanei janabo.", f"I am sorry to hear that. I have sent your request for order {no} to our team. We will update you here as soon as it is reviewed.")
        return reply("দুঃখিত! কোন অর্ডার নিয়ে সমস্যা? অর্ডার নম্বরটি (যেমন #১০৪২) লিখবেন?", "Dukkhito! Kon order niye somossha? Order number ta (jemon #1042) likhben?", "I am sorry about that! Which order is it? Please share the order number, for example #1042.")

    # 3. the customer is answering a "last 4 digits" question
    if bot_said(r"last 4 digits|শেষ ৪|শেষ 4|shesh 4") and re.fullmatch(r"\W*\d{4}\W*", text):
        no = _order_number(customer_texts[:-1])
        if no:
            return order_reply(no, re.search(r"\d{4}", text).group())

    cart_now = db.jl(store.conversation(ctx.conversation_id)["cart"], [])
    if cart_now and checkout.enabled():
        if bot_said(S_CONFIRM) and YES.match(text):
            ck = checkout.get(ctx.conversation_id)
            h = (ck.get("proposal") or {}).get("hash")
            res = call_tool(ctx, "place_order", confirm_hash=h or "none").result
            st = res.get("status")
            if st in ("placed", "already_placed", "staged_for_approval"):
                no, online = res.get("order"), bool(res.get("next", "").startswith("A secure"))
                num_bn, num_bl, num_en = (f" {no}", f" {no}", f" {no}") if no else ("", "", "")
                tot = res.get("total_text", "")
                return reply(
                    f"ধন্যবাদ! আপনার অর্ডার{num_bn} নিশ্চিত হয়েছে।" + (f" মোট {tot}।" if tot else "") + (" এই চ্যাটেই একটি নিরাপদ পেমেন্ট লিংক পাঠাচ্ছি, পেমেন্টের পর পাঠানো হবে।" if online else " পাঠানোর আগে আমাদের টিম ফোন করে নিশ্চিত করবে। কুরিয়ারকে ডেলিভারির সময় টাকা দেবেন।"),
                    f"Dhonnobad! Apnar order{num_bl} confirm hoyeche." + (f" Mot {tot}." if tot else "") + (" Ei chat e ekta nirapod payment link pathachhi, payment er pore pathano hobe." if online else " Pathanor age amader team phone kore confirm korbe. Courier ke delivery er shomoy taka diben."),
                    f"Thank you! Your order{num_en} is confirmed." + (f" Total {tot}." if tot else "") + (" A secure payment link follows in this chat; the order ships after payment." if online else " Our team will call to confirm before it ships. You pay the courier on delivery."),
                )
            if res.get("error") in ("summary_changed", "customer_has_not_confirmed"):
                return present_summary()
            call_tool(ctx, "handoff_to_human", reason="order could not be placed")
            return reply("অর্ডারটি এখন করা যাচ্ছে না, তাই একজন সহকর্মীকে যুক্ত করছি। উনি শীঘ্রই উত্তর দেবেন।", "Order ta ekhon kora jachhe na, tai ekjon sohokormi ke connect korchi. Uni shighroi reply debe.", "I could not place the order, so I am bringing in a teammate. They will reply shortly.")
        if bot_said(S_CONFIRM) and NO.match(text):
            call_tool(ctx, "set_delivery_details")
            return reply("ঠিক আছে, কী বদলাতে চান? পণ্যের সংখ্যা, ঠিকানা বা পেমেন্ট পদ্ধতি জানালে আমি ঠিক করে দেব।", "Thik ache, ki bodlate chan? Product er songkha, address ba payment method janale ami thik kore dibo.", "No problem. What would you like to change: the quantity, the address or the payment method?")
        if bot_said(S_METHOD) and checkout.match_method(text):
            return after_saved(call_tool(ctx, "set_delivery_details", payment_method=checkout.match_method(text)).result)
        if bot_said(S_DETAILS) or CHECKOUT.search(text):
            ck = checkout.get(ctx.conversation_id)
            miss0 = [f for f in checkout.missing(ck) if f != "method"]
            d = _parse_details(raw)
            asking = bool(re.search(r"\?|^(how|when|what|why|can|do|is|are|koto|kobe|kivabe|kemon)\b|কত|কবে|কিভাবে|কীভাবে", text.strip(), I))
            if bot_said(S_DETAILS) and len(miss0) == 1 and not d.get("phone") and not asking:
                f = miss0[0]
                if f == "name" and not re.search(r"\d", text) and len(text.split()) <= 5:
                    d = {"name": text}
                elif f == "address":
                    d = {"address": text}
                elif f == "district" and checkout.find_district(text):
                    d = {"district": checkout.find_district(text)}
                else:
                    d = {}
            elif bot_said(S_DETAILS) and asking and not d.get("phone"):
                d = {}
            elif bot_said(S_DETAILS) and d.get("name") and not d.get("address") and not d.get("phone") and "name" not in miss0:
                d = {}
            if d:
                return after_saved(call_tool(ctx, "set_delivery_details", **d).result)
            if CHECKOUT.search(text):
                return reply(*ask_next(None))

    # 4. order status
    if (RX["order"].search(text) and not RX["delivery"].search(re.sub(r"order|অর্ডার", "", text, flags=I))) or re.search(r"#\s?1\d{3}\b", text):
        no = _order_number([text])
        if no:
            return order_reply(no)
        mine = db.all("SELECT number FROM orders WHERE customer_id = ? ORDER BY created_at DESC", [ctx.customer_id])
        if mine and ctx.channel_kind == "wa":
            return order_reply(mine[0]["number"])
        return reply("অবশ্যই! আপনার অর্ডার নম্বরটি (যেমন #১০৪২) লিখবেন?", "Obosshoi! Apnar order number ta (jemon #1042) likhben?", "Happy to help. What is your order number, for example #1042?")

    # 5. thanks
    if RX["thanks"].search(text) and len(text) < 40:
        call_tool(ctx, "resolve_conversation")
        return reply("আপনাকেও ধন্যবাদ! আর কিছু লাগলে বলবেন।", "Apnakeo dhonnobad! Aro kichu lagle bolben.", "You are welcome! Message us any time you need something else.")

    sku = _product_from_text(text) or _last_product_sku(history)

    # 6. restock alert
    if RX["notify"].search(text) and sku:
        p = store.product(sku)
        call_tool(ctx, "create_restock_alert", sku=sku)
        sms_bn = "" if ctx.channel_kind == "wa" else "SMS-এর জন্য মোবাইল নম্বরটি দিয়ে রাখবেন।"
        sms_bl = "" if ctx.channel_kind == "wa" else "SMS er jonno mobile number ta diye rakhben."
        sms_en = "" if ctx.channel_kind == "wa" else "Please share your mobile number for the SMS."
        return reply(f"ঠিক আছে, {p['name']} স্টকে এলেই আপনাকে জানাব। {sms_bn}", f"Thik ache, {p['name']} stock e ashle apnake janabo. {sms_bl}", f"Done. I will message you as soon as the {p['name']} is back. {sms_en}", product_sku=sku)

    # 7. cart: the customer confirmed after a product was shown
    if RX["cart"].search(text) and _last_product_sku(history) and (bot_said(r"cart|কার্ট") or re.search(r"cart|কার্ট", text, I)):
        sku2 = _product_from_text(text) or _last_product_sku(history)
        p = store.product(sku2)
        qm = re.search(r"\b([2-9])\b\s*(ta|টি|pcs|piece|x)?", text, I)
        qty = min(10, int(qm.group(1))) if qm else 1
        if p["stock"] == 0:
            return reply(f"দুঃখিত, {p['name']} এখন স্টকে নেই। স্টকে এলে জানাব?", f"Dukkhito, {p['name']} ekhon stock e nei. Stock e ashle janabo?", f"Sorry, the {p['name']} is out of stock. Want me to tell you when it is back?", product_sku=sku2)
        out = call_tool(ctx, "add_to_cart", sku=sku2, qty=qty)
        sub = out.result.get("cart_subtotal", p["price"] * qty)
        v = p["variant"] or ""
        nxt = ask_next(None)
        return reply(
            f"জি, {qty}টি {p['name']} ({v}) কার্টে যোগ করেছি। সাবটোটাল {taka(sub, True)}। {nxt[0]}",
            f"Ji, {qty}ta {p['name']} ({v}) cart e add korechi. Subtotal {taka(sub)}. {nxt[1]}",
            f"Added {qty} x {p['name']} ({v}) to your cart. Subtotal {taka(sub)}. {nxt[2]}",
            product_sku=sku2,
        )

    # 8. delivery estimate
    district = next((d for d in DISTRICTS if d.lower() in text.lower()), None)
    if RX["delivery"].search(text) or (district and not RX["order"].search(text)):
        d = (district or "dhaka").capitalize()
        out = call_tool(ctx, "estimate_delivery", district=d)
        o = out.result["options"][0]
        dh = is_dhaka(d)
        return reply(
            f"{d} এ {o['courier']} দিয়ে সাধারণত {'১ দিন' if dh else '২ থেকে ৩ দিন'} লাগে, ডেলিভারি চার্জ {taka(o['charge'], True)}।",
            f"{d} e {o['courier']} diye shadharonoto {'1 din' if dh else '2 theke 3 din'} lage, delivery charge {taka(o['charge'])}.",
            f"Delivery to {d} with {o['courier']} usually takes {o['time']}, and the delivery charge is {taka(o['charge'])}.",
            product_sku=_product_from_text(text),
        )

    # 9. returns policy
    if RX["return_policy"].search(text):
        call_tool(ctx, "get_policy", topic="returns")
        return reply("ডেলিভারির ৭ দিনের মধ্যে ব্যবহার না করা পণ্য ফেরত বা এক্সচেঞ্জ করা যায়। ক্ষতিগ্রস্ত পণ্য হলে ছবি পাঠালে আমরা দ্রুত ব্যবস্থা নেব।", "Delivery er 7 din er moddhe ba-bohar kora hoy ni emon product return ba exchange kora jay. Damage hole chobi pathale amra druto bebostha nibo.", "Unused items can be returned or exchanged within 7 days of delivery. If an item arrived damaged, send us a photo and we will sort it out quickly.")

    # 10. payment
    if RX["payment"].search(text) and not _product_from_text(text):
        call_tool(ctx, "get_policy", topic="payment")
        return reply("আপনি ক্যাশ অন ডেলিভারি, বিকাশ, নগদ বা কার্ডে পেমেন্ট করতে পারবেন। অনলাইন পেমেন্টে আমরা শুধু অফিসিয়াল পেমেন্ট লিংক পাঠাই, আপনার পিন বা ওটিপি কাউকে দেবেন না।", "Apni cash on delivery, bKash, Nagad ba card e pay korte parben. Online payment e amra shudhu official payment link pathai, apnar PIN ba OTP kauke debena na.", "You can pay by cash on delivery, bKash, Nagad or card. For online payments we only send official payment links. Never share your PIN or OTP with anyone.")

    # 11. product questions, for whatever this store sells: one product, its variants, a short list, or an honest "we do not have that"
    sr = catalog_search.search(text)
    wants_list = bool(RX["browse"].search(text))
    if sr.rows and (sr.content or wants_list) and not (sr.browse and not wants_list):
        groups = catalog_search.group_by_name(sr.rows)
        detail = bool(RX["detail"].search(text))
        if sr.browse or len(groups) > 1 or not sr.matched_all and len(groups) > 1:
            return _list_reply(reply, groups[:4], closest=not sr.matched_all and not sr.browse, said=sr.unmatched)
        name, variants = groups[0]
        return _one_product_reply(reply, name, variants, detail, text, closest=not sr.matched_all, said=sr.unmatched)
    if sr.content and not sr.rows and (RX["inquiry"].search(text) or len(sr.content) <= 3 and not RX["thanks"].search(text)):
        ov = catalog_search.overview(5)
        lst = ", ".join(ov["examples"])
        asked = " ".join(sr.content[:3])
        return reply(
            f"দুঃখিত, \"{asked}\" আমাদের কালেকশনে খুঁজে পাইনি। আমাদের কাছে আছে: {lst}। এগুলোর মধ্যে কিছু দেখাব, নাকি একজন সহকর্মীকে জিজ্ঞেস করব?",
            f"Dukkhito, \"{asked}\" amader collection e khuje painai. Amader kache ache: {lst}. Egulor moddhe kichu dekhabo, naki ekjon sohokormi ke jiggesh korbo?",
            f"Sorry, I could not find \"{asked}\" in our collection. We have: {lst}. Shall I show you one of these, or ask a teammate?",
            confidence=70,
        )

    # 12. greeting
    if RX["greeting"].search(text.strip()) or len(text.strip()) < 4:
        s = settings["storeName"]
        return reply(f"ওয়ালাইকুম আসসালাম! আমি {s}-এর সহকারী। পণ্য খুঁজে দেওয়া, অর্ডারের অবস্থা বা রিটার্নের নিয়ম বলতে পারি। কী লাগবে?", f"Wa alaikum assalam! Ami {s} er assistant. Product khuje deya, order status ba return policy bolte pari. Ki lagbe?", f"Hello! I am the {s} assistant. I can find products, check an order, or explain our return policy. What do you need?")

    # 13. fallback; hand off if we already failed once in a row
    if last_bot and re.search(r"ঠিক বুঝতে পারিনি|thik bujhte parini|did not quite get", last_bot["text"], I):
        call_tool(ctx, "handoff_to_human", reason="low confidence")
        return reply("আমি ঠিক বুঝতে পারছি না, তাই একজন সহকর্মীকে যুক্ত করছি। উনি শীঘ্রই উত্তর দেবেন।", "Ami thik bujhte parchi na, tai ekjon sohokormi ke connect korchi. Uni shighroi reply debe.", "I am not able to help with this one, so I am bringing in a teammate. They will reply shortly.", confidence=40)
    return reply("আপনার কথাটা ঠিক বুঝতে পারিনি। পণ্য, অর্ডার, ডেলিভারি বা রিটার্ন নিয়ে জিজ্ঞেস করতে পারেন।", "Apnar kothata thik bujhte parini. Product, order, delivery ba return niye jiggesh korte paren.", "Sorry, I did not quite get that. You can ask me about a product, an order, delivery or returns.", confidence=45)


def summarize_offline(conversation_id: str) -> str:
    conv = store.conversation(conversation_id)
    if not conv:
        return ""
    cust = store.customer(conv["customer_id"])
    msgs = list(reversed(db.all("SELECT * FROM messages WHERE conversation_id = ? AND role='customer' ORDER BY id DESC LIMIT 2", [conversation_id])))
    last = " then ".join(f"“{(m['translation'] or m['text'])[:90]}”" for m in msgs)
    cart = db.jl(conv["cart"], [])
    bits = [f"{cust['name'].split()[0]} wrote {last or 'in'}."]
    if cart:
        bits.append("Cart: " + ", ".join(f"{l['qty']} x {l['name']}" for l in cart) + ".")
    if conv["handoff_reason"]:
        bits.append(f"Handed to a person: {conv['handoff_reason']}.")
    return " ".join(bits)

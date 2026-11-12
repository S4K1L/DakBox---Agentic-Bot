"""Finding products for a customer's words, whatever the store sells.

Customers write product words in Bangla script (শাড়ি), in Banglish (shari, sharee) and in English (saree, sari). This module:
- splits text into tokens that keep Bangla letters whole, drops question filler (do, you, have, ache, আছে, কত, দাম...),
- treats spellings of the same thing as one word (saree = sari = shari = শাড়ি; red = lal = লাল),
- tolerates plurals, common Bangla endings (শাড়িটা, শাড়ির, শাড়িগুলো) and one-letter typos,
- ranks by where a word matched (name, then keywords and variant, then description),
- prefers products that match every word the customer used, and says honestly when only close matches exist.
It never invents anything: it only ranks rows of the products table.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .. import db

_TOKEN = re.compile(r"[A-Za-z0-9ঀ-৿]+")
_JOINS = [(re.compile(r"three[\s\-_]*piece|3[\s\-_]*piece|থ্রি[\s\-_]*পিস"), "threepiece"), (re.compile(r"t[\s\-_]*shirt|টি[\s\-_]*শার্ট"), "tshirt"),
          (re.compile(r"hand[\s\-_]*bag|হ্যান্ড[\s\-_]*ব্যাগ"), "handbag"), (re.compile(r"mobile[\s\-_]*cover|phone[\s\-_]*case"), "phonecase")]

# Filler that says nothing about which product is meant.
STOP = set("""a an the and or of for to in on at is are was be it its this that these those do does did can could would will shall you your yours we our us i me my mine
have has had any some there here ok okay yes no please pls plz hi hello hey dear sir madam bhai apu vai sis show tell give send want wants wanna need needs looking look
see get buy purchase order price prices cost costs rate how much many what which kon koto kto kothay where when available availability stock instock stocks sell selling
about info information detail details more also too ache achhe ase asey ki kisu kichu kichhu ta ti tar er ar o amar amader apnar apnader apnara apnake amake
kache kase kachhe thakle achen achhen dekhte dekhbo jonno jonne pari paren parben bolun bolben jante janaben janan detail details description describe info bistarito spec specs quality material fabric
dam dame daam lagbe chai dekhan dekhao dekhaben dibo debo den din dao kinbo kinte kinbe nibo nite parbo paben pabo pawa jay hobe hoy hoye
আছে আছেন কত দাম দামে কি কী কিছু কিছ কোন কোনো কোনটা কোনটি চাই লাগবে লাগে দেখান দেখাও দেখাবেন দিন দেন দাও কিনব কিনতে কিনবো নিব নিতে পাব পাবো পাওয়া যায় যাবে হবে হয়
কাছে বিস্তারিত বিবরণ আপনাদের আপনার আপনারা আমার আমাদের আমাকে একটা একটি এই ওই এর ও আর তো না নাকি জন্য সাথে মধ্যে থেকে ভাই আপু স্যার
size sizes colour color colors colours piece pieces pcs pc one two three ta""".split())

# Words that mean the same thing. Each group becomes one key.
_GROUPS = [
    "saree sarees sari saris shari sharee sarree saaree sadi শাড়ি শাড়ী সাড়ি শাড়িগুলো",
    "panjabi punjabi panjabee punjabee পাঞ্জাবি পাঞ্জাবী পাঞ্জাবীগুলো",
    "threepiece salwar shalwar kameez kamiz suit সালোয়ার কামিজ থ্রিপিস",
    "kurti kurta কুর্তি কুর্তা",
    "lehenga lehnga লেহেঙ্গা",
    "orna orna dupatta odna ওড়না",
    "hijab hijaab হিজাব",
    "burqa burka borka burkha বোরকা বোরখা",
    "scarf stole স্কার্ফ",
    "shirt shirts shart শার্ট",
    "tshirt tee টিশার্ট",
    "pant pants trouser trousers jeans প্যান্ট জিন্স",
    "lungi lunggi লুঙ্গি",
    "shoe shoes juta juto জুতা জুতো জুতার",
    "sandal sandals chappal chapal slipper slippers স্যান্ডেল চপ্পল",
    "boot boots বুট",
    "bag bags handbag handbags purse ব্যাগ",
    "watch watches ghori ghoori ঘড়ি",
    "jewellery jewelry gohona gahana গহনা গয়না",
    "necklace মালা নেকলেস",
    "earring earrings কানের দুল",
    "ring আংটি",
    "bottle bottles botol flask বোতল ফ্লাস্ক",
    "tent tents tabu tabur তাঁবু তাবু",
    "jacket jackets jaket jaketer জ্যাকেট",
    "phonecase cover কভার",
    "mobile phone smartphone মোবাইল ফোন",
    "headphone headphones earphone earphones earbuds হেডফোন",
    "charger চার্জার",
    "cream lotion ক্রিম লোশন",
    "perfume attar আতর পারফিউম",
    "oil তেল tel",
    "honey মধু modhu",
    "ghee ঘি",
    "dates khejur খেজুর",
    "toy toys খেলনা",
    "book books বই boi",
    "red lal লাল", "blue neel nil নীল", "green sobuj shobuj সবুজ", "black kalo কালো", "white shada sada সাদা", "yellow holud হলুদ", "pink golapi গোলাপি গোলাপী",
    "orange komola কমলা", "purple beguni বেগুনি", "maroon মারুন", "grey gray ashe ছাই", "brown badami বাদামি", "navy নেভি", "gold golden সোনালি", "silver রুপালি",
    "cotton সুতি কটন", "silk সিল্ক রেশম", "jamdani jamdaani জামদানি", "katan কাতান", "lawn লন", "georgette জর্জেট", "muslin মসলিন", "linen লিনেন", "tangail টাঙ্গাইল",
]
_CANON: dict[str, str] = {}
for _i, _g in enumerate(_GROUPS):
    for _w in _g.split():
        _CANON.setdefault(_w, f"g{_i}")

_BN_ENDINGS = ("গুলো", "গুলি", "গুলা", "খানা", "খানি", "টার", "টির", "টাতে", "টায়", "টা", "টি", "ের", "েরা", "কে", "তে", "য়", "র", "ে")
_PUNCT_ZW = re.compile("[​‌‍﻿]")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower()
    t = _PUNCT_ZW.sub("", t)
    for rx, rep in _JOINS:
        t = rx.sub(rep, t)
    return t


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(norm(text))


def _variants(t: str) -> set[str]:
    """The word as written plus its likely base forms."""
    out = {t}
    if t.isascii():
        if len(t) > 3 and t.endswith("ies"):
            out.add(t[:-3] + "y")
        if len(t) > 3 and t.endswith("es"):
            out.add(t[:-2])
        if len(t) > 3 and t.endswith("s"):
            out.add(t[:-1])
        if len(t) > 4 and t.endswith("er"):         # Banglish "sharir"/"jacketer" style endings
            out.add(t[:-2])
        if len(t) > 4 and t.endswith("ta"):
            out.add(t[:-2])
    else:
        for e in _BN_ENDINGS:
            if len(t) > len(e) + 1 and t.endswith(e):
                out.add(t[: -len(e)])
                if e == "র" or e == "ের":
                    out.add(t[: -len(e)] + "ি")
    return out


def keys_of(t: str) -> set[str]:
    ks: set[str] = set()
    for v in _variants(t):
        ks.add(v)
        g = _CANON.get(v)
        if g:
            ks.add(g)
    return ks


def _dist1(a: str, b: str) -> bool:
    """Within one edit (insert, delete, replace, swap) of each other."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    s, l = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(s) and s[i] == l[i]:
        i += 1
    return s[i:] == l[i + 1:]


def content_tokens(text: str) -> list[str]:
    seen, out = set(), []
    for t in tokens(text):
        if t in STOP or t in seen or (len(t) < 2 and t.isascii()) or (t.isdigit() and len(t) < 4):
            continue
        seen.add(t)
        out.append(t)
    return out


@dataclass
class Result:
    rows: list = field(default_factory=list)
    content: list[str] = field(default_factory=list)
    matched_all: bool = False
    browse: bool = False              # no product word was used: these are simply the popular products
    unmatched: list[str] = field(default_factory=list)


_W_NAME, _W_KEY, _W_VARIANT, _W_SKU, _W_DESC = 6, 4, 4, 3, 1.5


def _fields(p) -> dict[str, set[str]]:
    def ks(text: str) -> set[str]:
        out: set[str] = set()
        for t in tokens(text):
            out |= keys_of(t)
        return out
    return {"name": ks(p["name"]), "kw": ks(p["keywords"] or ""), "variant": ks(p["variant"] or ""), "sku": ks(p["sku"]), "desc": ks(p["description"] or "")}


def _raw(p) -> set[str]:
    return {t for t in tokens(f"{p['name']} {p['variant'] or ''} {p['keywords'] or ''}") if len(t) >= 5}


def search(query: str, limit: int = 8) -> Result:
    content = content_tokens(query)
    rows = db.all("SELECT * FROM products")
    if not content:
        pop = sorted(rows, key=lambda p: (p["stock"] == 0, -(p["sold30"] or 0), p["name"]))
        return Result(rows=pop[:limit], content=[], matched_all=False, browse=True)
    scored = []
    cache: dict[str, dict] = {}
    for p in rows:
        f = cache[p["sku"]] = _fields(p)
        raw = None
        total, hit = 0.0, 0
        for t in content:
            tk = keys_of(t)
            s = 0.0
            for name, w in (("name", _W_NAME), ("kw", _W_KEY), ("variant", _W_VARIANT), ("sku", _W_SKU), ("desc", _W_DESC)):
                if tk & f[name]:
                    s += w
            if not s and len(t) >= 5 and t.isascii():          # one-letter typo: "jamdni", "panjabbi"
                raw = raw if raw is not None else _raw(p)
                if any(_dist1(v, r) for v in _variants(t) for r in raw):
                    s = 3.0
            if s:
                hit += 1
                total += s
        if hit:
            scored.append((hit, total, p))
    if not scored:
        return Result(rows=[], content=content, unmatched=content)
    full = [x for x in scored if x[0] == len(content)]
    use = full or scored
    use.sort(key=lambda x: (-x[0], -x[1], x[2]["stock"] == 0, -(x[2]["sold30"] or 0)))
    best = use[0]
    matched_tokens = set()
    # which of the customer's words found nothing at all (to say so honestly)
    for t in content:
        tk = keys_of(t)
        if any(tk & set().union(*cache[p["sku"]].values()) for _, _, p in scored):
            matched_tokens.add(t)
    return Result(rows=[x[2] for x in use[:limit]], content=content, matched_all=bool(full) and best[0] == len(content), unmatched=[t for t in content if t not in matched_tokens])


def best_unique(query: str) -> str | None:
    """The SKU the customer clearly means, or None when several different products tie (or nothing matches)."""
    r = search(query)
    if r.browse or not r.rows or not r.matched_all:
        return None
    names = {p["name"] for p in r.rows}
    if len(names) > 1:
        return None
    # several variants of one product: only unique if the words picked out a single variant
    return r.rows[0]["sku"] if len(r.rows) == 1 else None


def group_by_name(rows) -> list[tuple[str, list]]:
    out: dict[str, list] = {}
    for p in rows:
        out.setdefault(p["name"], []).append(p)
    return list(out.items())


def overview(n: int = 8) -> dict:
    rows = db.all("SELECT name, stock, sold30 FROM products")
    names: list[str] = []
    for p in sorted(rows, key=lambda p: (p["stock"] == 0, -(p["sold30"] or 0))):
        if p["name"] not in names:
            names.append(p["name"])
    return {"count": len(rows), "examples": names[:n]}

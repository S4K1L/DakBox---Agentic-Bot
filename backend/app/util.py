from __future__ import annotations

import re

BN_DIGITS = "০১২৩৪৫৬৭৮৯"


def to_bn_digits(s: object) -> str:
    return re.sub(r"[0-9]", lambda m: BN_DIGITS[int(m.group())], str(s))


def from_bn_digits(s: str) -> str:
    return re.sub(r"[০-৯]", lambda m: str(BN_DIGITS.index(m.group())), s)


def taka(n: float, bn: bool = False) -> str:
    """Taka with lakh grouping: 1,450 and 8,43,160."""
    neg = n < 0
    v = int(round(abs(n)))
    s = str(v)
    last3, rest = s[-3:], s[:-3]
    if rest:
        rest = re.sub(r"\B(?=(\d{2})+(?!\d))", ",", rest) + ","
    out = f"{'-' if neg else ''}৳{rest}{last3}"
    return to_bn_digits(out) if bn else out


BANGLISH = set(
    """ami amar apni apnar apnara ache achhe nai nei kothay kothai koto kotodin korbo korte kore korun parbo parben pabo jonno chai chaichi den din dibo
    dite lagbe hobe hoyeche hoy ta ti ki kemon bhai apu vai dhonnobad dhonnobaad thik accha achha bolen bolun jante janaben pathan pathiye nibo nite
    ekta duita shob sob onek kom beshi dam taka bhalo kharap vege gese gelo ase asche asbe jay jabe ekhane ekhon ajke kal agei pore tahole kintu othoba
    naki eta ota ei oi amake amader tomar apnake""".split()
)


def detect_lang(text: str) -> str:
    """bn = Bangla script, bl = Banglish (Bangla in English letters), en = English."""
    if re.search(r"[ঀ-৿]", text):
        return "bn"
    words = [w for w in re.sub(r"[^a-z\s]", " ", text.lower()).split() if w]
    if not words:
        return "en"
    hits = sum(1 for w in words if w in BANGLISH)
    if hits >= 2 or (hits >= 1 and len(words) <= 3):
        return "bl"
    return "en"


def lang_name(l: str) -> str:
    return "বাংলা" if l == "bn" else "Banglish" if l == "bl" else "English"


def initials(name: str) -> str:
    p = name.strip().split()
    if not p:
        return "?"
    a = p[0][0]
    b = p[-1][0] if len(p) > 1 else (p[0][1] if len(p[0]) > 1 else "")
    return (a + b).upper()


def hue_for(s: str) -> int:
    h = 7
    for ch in s:
        h = (h * 31 + ord(ch)) % 360
    return h


# Example zone rates. Real rates come from each courier's API.
RATES = [
    {"id": "steadfast", "name": "Steadfast", "dhaka": (70, "1 day"), "out": (130, "2 to 3 days")},
    {"id": "pathao", "name": "Pathao", "dhaka": (70, "1 day"), "out": (130, "2 to 4 days")},
    {"id": "redx", "name": "RedX", "dhaka": (60, "1 day"), "out": (110, "2 to 3 days")},
    {"id": "paperfly", "name": "Paperfly", "dhaka": (70, "1 to 2 days"), "out": (120, "3 to 4 days")},
]


def rates_for(zone: str) -> list[dict]:
    key = "dhaka" if zone == "dhaka" else "out"
    return [{"id": r["id"], "name": r["name"], "price": r[key][0], "window": r[key][1]} for r in RATES]


_DHAKA = re.compile(r"dhaka|ঢাকা|uttara|mirpur|dhanmondi|gulshan|banani|mohammadpur|tejgaon|badda|rampura|motijheel", re.I)


def is_dhaka(district: str) -> bool:
    return bool(_DHAKA.search(district))


DISTRICTS = [
    "dhaka", "chattogram", "chittagong", "sylhet", "rajshahi", "khulna", "barishal", "barisal", "rangpur", "mymensingh", "comilla", "cumilla",
    "gazipur", "narayanganj", "bogura", "cox", "jessore", "jashore", "dinajpur", "tangail",
    "ঢাকা", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর", "ময়মনসিংহ", "কুমিল্লা",
]

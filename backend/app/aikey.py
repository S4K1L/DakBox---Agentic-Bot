"""Which AI answers customers, and the API key for it, changeable from the owner panel.

Providers: Claude (Anthropic) and anything that speaks the OpenAI chat format with tool calls: ChatGPT (OpenAI), Gemini (Google's
OpenAI-compatible endpoint), DeepSeek, and a "custom" address for others (Groq, OpenRouter, a local Ollama, ...). One provider is active at a time.
Each provider's key is kept separately, so switching back and forth does not mean typing keys again.

Keys: a key saved in the panel (encrypted in the database, like the Meta tokens) wins over the provider's environment variable
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY). Keys are never returned by any endpoint (only the last four characters), never
logged, and never written to the audit log. A key is checked with the provider (a free "list models" call) before it is saved.

The assistant's safety rules (order limits, stock, payments, refunds) are enforced in code, not by the model, so they hold for every provider.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx

from . import db
from .secrets_store import seal, seal_master, unseal, unseal_master

VERSION = "2023-06-01"                      # Anthropic API version header
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
DEFAULT_ANTHROPIC_SMALL = "claude-haiku-5-5"
NO_KEY = "-"                                # a custom (for example local) server that needs no key

PROVIDERS: dict[str, dict] = {
    "anthropic": {"label": "Claude (Anthropic)", "short": "Claude", "kind": "anthropic", "base": "https://api.anthropic.com", "env": "ANTHROPIC_API_KEY", "env_base": "ANTHROPIC_BASE_URL",
                  "where": "console.anthropic.com, API keys"},
    "openai": {"label": "ChatGPT (OpenAI)", "short": "ChatGPT", "kind": "openai", "base": "https://api.openai.com/v1", "env": "OPENAI_API_KEY", "env_base": "OPENAI_BASE_URL",
               "where": "platform.openai.com, API keys"},
    "gemini": {"label": "Gemini (Google)", "short": "Gemini", "kind": "openai", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "env": "GEMINI_API_KEY",
               "env_base": "GEMINI_BASE_URL", "where": "aistudio.google.com, Get API key"},
    "deepseek": {"label": "DeepSeek", "short": "DeepSeek", "kind": "openai", "base": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY", "env_base": "DEEPSEEK_BASE_URL",
                 "where": "platform.deepseek.com, API keys"},
    "custom": {"label": "Other (OpenAI-compatible)", "short": "Custom AI", "kind": "openai", "base": None, "env": None, "env_base": None,
               "where": "your provider's dashboard (Groq, OpenRouter, a local Ollama, ...)"},
}

_transport: httpx.AsyncBaseTransport | None = None
_ANTHROPIC_KEY = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{16,300}$")
_ANY_KEY = re.compile(r"^[\x21-\x7e]{8,400}$")


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject a stand-in for every provider here."""
    global _transport
    _transport = t


def client(timeout: float = 40.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=False)


class KeyError_(Exception):
    """A problem with the key or provider worth showing to the owner as is."""

    def __init__(self, message: str, kind: str = "key"):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------- configuration
def _cfg() -> dict:
    return db.get_setting("ai_cfg", {}) or {}


def _save_cfg(c: dict) -> None:
    db.set_setting("ai_cfg", c)


def valid_provider(pid: str | None) -> str:
    if pid not in PROVIDERS:
        raise KeyError_("Choose one of the listed AI providers.")
    return pid


def active() -> str:
    p = _cfg().get("provider") or "anthropic"
    return p if p in PROVIDERS else "anthropic"


def _sealed_keys() -> dict:
    d = dict(db.get_setting("ai_keys", {}) or {})
    if "anthropic" not in d:                  # the single key saved by the first version of this panel
        legacy = db.get_setting("ai_key", None)
        if legacy:
            d["anthropic"] = legacy
    return d


def panel_key(pid: str | None = None) -> str | None:
    return unseal(_sealed_keys().get(pid or active()))


def env_key(pid: str) -> str | None:
    name = PROVIDERS[pid]["env"]
    return ((os.environ.get(name) or "").strip() or None) if name else None


def _bid_or_none() -> str | None:
    try:
        from . import registry
        return db.current() or (None if db.strict() else registry.default_id())
    except Exception:  # noqa: BLE001
        return None


def platform_allowed() -> bool:
    """Whether this business's plan lets it use the platform's AI keys."""
    from . import registry
    b = _bid_or_none()
    return bool(b and registry.plan_of(b)["platform_ai"])


def platform_key(pid: str) -> tuple[str | None, str | None]:
    """The platform's own key for a provider (saved by the platform administrator, else the server's environment variable), and where it came from.
    Only for businesses whose plan allows it; never for a custom address."""
    if pid == "custom" or not platform_allowed():
        return None, None
    from . import registry
    sealed = registry.platform_ai()["keys"].get(pid)
    k = unseal_master(sealed) if sealed else None
    if k:
        return k, "platform"
    e = env_key(pid)
    return (e, "environment") if e else (None, None)


def get_key(pid: str | None = None) -> str | None:
    pid = pid or active()
    return panel_key(pid) or platform_key(pid)[0] or None


def source(pid: str | None = None) -> str | None:
    """panel (the business's own key), platform (a key the platform administrator saved), environment (the server's variable) or None."""
    pid = pid or active()
    if panel_key(pid):
        return "panel"
    return platform_key(pid)[1]


def mask(key: str | None) -> str | None:
    if key == NO_KEY:
        return "No key needed"
    return f"…{key[-4:]}" if key and len(key) > 8 else None


def _models() -> dict:
    return _cfg().get("models") or {}


def model(pid: str | None = None) -> str | None:
    pid = pid or active()
    m = (_models().get(pid) or {}).get("model")
    if pid == "anthropic":
        return m or _platform_model(pid, "model") or os.environ.get("DAKBOX_MODEL") or DEFAULT_ANTHROPIC_MODEL
    return m or _platform_model(pid, "model") or None


def _platform_model(pid: str, which: str) -> str | None:
    """When the platform's key is in use, the model the platform administrator chose for that provider is the default."""
    if panel_key(pid) or not platform_key(pid)[0]:
        return None
    from . import registry
    return (registry.platform_ai()["models"].get(pid) or {}).get(which) or None


def small_model(pid: str | None = None) -> str | None:
    pid = pid or active()
    m = (_models().get(pid) or {}).get("small")
    if pid == "anthropic":
        return m or _platform_model(pid, "small") or os.environ.get("DAKBOX_SUMMARY_MODEL") or DEFAULT_ANTHROPIC_SMALL
    return m or _platform_model(pid, "small") or model(pid)


def base_url(pid: str | None = None) -> str | None:
    pid = pid or active()
    p = PROVIDERS[pid]
    if pid == "custom":
        return _cfg().get("custom_base") or None
    return ((os.environ.get(p["env_base"]) if p["env_base"] else None) or p["base"]).rstrip("/")


def quota() -> dict | None:
    """Replies this month against the plan, for keys that belong to the platform. None when the business uses its own key (never limited)."""
    from . import limits
    a = limits.ai()
    return {"used": a["used"], "limit": a["limit"], "exhausted": a["exhausted"]} if a["limited"] else None


def ready(pid: str | None = None) -> bool:
    """Can this provider answer a customer right now: a key, a model, (for a custom server) an address, and monthly allowance left when the key is the platform's."""
    pid = pid or active()
    if not (get_key(pid) and model(pid) and base_url(pid)):
        return False
    if pid == active():
        q = quota()
        if q and q["exhausted"]:
            return False
    return True


def count_reply() -> None:
    """One AI reply was written. Counted for every business (for the platform's usage view); only platform-key replies are limited."""
    from . import registry
    b = _bid_or_none()
    if b:
        registry.usage_add(b, "ai_replies", 1)


def engine_id() -> str:
    pid = active()
    return "claude" if pid == "anthropic" else pid


def engine_label() -> str:
    return PROVIDERS[active()]["short"]


def kind() -> str:
    return PROVIDERS[active()]["kind"]


# ---------------------------------------------------------------- what the panel shows (never a key)
def provider_view(pid: str) -> dict:
    p = PROVIDERS[pid]
    k = get_key(pid)
    return {"id": pid, "label": p["label"], "kind": p["kind"], "hasKey": bool(k), "source": source(pid), "masked": mask(k), "model": model(pid), "smallModel": small_model(pid) if model(pid) else None,
            "baseUrl": base_url(pid) if pid == "custom" else None, "ready": ready(pid), "where": p["where"], "keyOptional": pid == "custom"}


def status() -> dict:
    st = db.get_setting("ai_status", {}) or {}
    pid = active()
    q = quota()
    err, err_at = st.get("error"), st.get("at")
    if q and q["exhausted"]:
        err, err_at = (f"This month's allowance of {q['limit']} AI replies on your plan is used up, so the offline rules answer until next month. "
                       "Add your own AI key below (no limit), or ask the platform administrator for a bigger plan."), None
    return {"provider": pid, "providerLabel": PROVIDERS[pid]["label"], "source": source(pid), "masked": mask(get_key(pid)), "model": model(pid), "smallModel": small_model(pid) if model(pid) else None,
            "baseUrl": base_url(pid) if pid == "custom" else None, "ready": ready(pid), "lastError": err, "lastErrorAt": err_at, "lastOkAt": st.get("ok_at"),
            "quota": q, "platformAllowed": platform_allowed(), "providers": [provider_view(x) for x in PROVIDERS]}


# ---------------------------------------------------------------- writing
def _reset_client() -> None:
    from .agent import agent
    agent._client = None


def normalize_key(pid: str, raw: str | None) -> str:
    key = (raw or "").strip().strip('"').strip("'")
    if pid == "custom" and not key:
        return NO_KEY
    if pid == "anthropic":
        if not _ANTHROPIC_KEY.match(key):
            raise KeyError_("That does not look like an Anthropic API key. Keys start with sk-ant- and are copied from console.anthropic.com, API keys.")
    elif not _ANY_KEY.match(key):
        raise KeyError_("That does not look like an API key. Copy it in full from the provider's dashboard, with no spaces.")
    return key


def normalize(raw: str | None) -> str:        # kept for the Claude-only callers
    return normalize_key("anthropic", raw)


async def validate_base(raw: str | None) -> str:
    """The address of a custom OpenAI-compatible server. Must be https and a public address, so a typo cannot aim this server at an internal one."""
    from .catalog_import import CatalogError, _allow_private, _host_ok
    raw = (raw or "").strip().rstrip("/")
    u = urlparse(raw)
    private_ok = _allow_private()
    if u.scheme not in (("http", "https") if private_ok else ("https",)) or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise KeyError_("Enter the provider's address, starting with https://, for example https://api.groq.com/openai/v1")
    if u.port not in (None, 443) and not private_ok:
        raise KeyError_("Only the normal https port can be used for a custom address.")
    try:
        await _host_ok(u.hostname)
    except CatalogError as e:
        raise KeyError_(str(e)) from None
    return raw


def _apply(c: dict, pid: str, model_: str | None, small: str | None, base: str | None, activate: bool) -> dict:
    m = dict(c.get("models") or {})
    cur = dict(m.get(pid) or {})
    if model_ is not None:
        cur["model"] = model_.strip() or None
    if small is not None:
        cur["small"] = small.strip() or None
    m[pid] = cur
    c["models"] = m
    if base is not None and pid == "custom":
        c["custom_base"] = base
    if activate:
        c["provider"] = pid
    return c


def save(pid: str, key: str, *, model_: str | None = None, small: str | None = None, base: str | None = None, activate: bool = True) -> None:
    keys = _sealed_keys()
    keys[pid] = seal(key)
    db.set_setting("ai_keys", keys)
    if pid == "anthropic":
        db.set_setting("ai_key", None)       # the old single-key slot is now ai_keys.anthropic
    _save_cfg(_apply(_cfg(), pid, model_, small, base, activate))
    db.set_setting("ai_status", {})
    _reset_client()


def configure(pid: str, *, model_: str | None = None, small: str | None = None, base: str | None = None, activate: bool = True) -> None:
    """Switch provider or change models without touching the key."""
    _save_cfg(_apply(_cfg(), pid, model_, small, base, activate))
    db.set_setting("ai_status", {})
    _reset_client()


def clear(pid: str | None = None) -> None:
    pid = pid or active()
    keys = _sealed_keys()
    keys.pop(pid, None)
    db.set_setting("ai_keys", keys)
    if pid == "anthropic":
        db.set_setting("ai_key", None)
    db.set_setting("ai_status", {})
    _reset_client()


# ---------------------------------------------------------------- asking the provider
def auth_headers(pid: str, key: str) -> dict:
    if PROVIDERS[pid]["kind"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": VERSION}
    return {} if key == NO_KEY else {"Authorization": f"Bearer {key}"}


def models_url(pid: str, base: str | None = None) -> str:
    b = (base or base_url(pid) or "").rstrip("/")
    return b + ("/v1/models" if PROVIDERS[pid]["kind"] == "anthropic" else "/models")


async def check(pid: str, key: str, want: str | None, base: str | None = None) -> dict:
    """Ask the provider (a free call) whether the key works and which models it can use. Raises KeyError_ with a plain reason when it does not."""
    name = PROVIDERS[pid]["label"]
    try:
        async with client(15.0) as c:
            r = await c.get(models_url(pid, base), params={"limit": 1000} if pid == "anthropic" else None, headers=auth_headers(pid, key))
    except httpx.TimeoutException:
        raise KeyError_(f"{name} did not answer in time. Try again in a moment.", "network") from None
    except httpx.HTTPError:
        raise KeyError_(f"Could not reach {name} from this server. Check the server's internet connection.", "network") from None
    if r.status_code in (401, 403):
        raise KeyError_(f"{name} rejected this key. Check that it was copied in full and has not been deleted or disabled.")
    if r.status_code == 429:
        raise KeyError_(f"{name} says too many requests right now. Wait a minute and try again.", "network")
    unlisted = r.status_code in (404, 405) and pid == "custom"       # some servers have no model list: the key cannot be checked here
    if r.status_code != 200 and not unlisted:
        raise KeyError_(f"{name} answered with an unexpected error ({r.status_code}). Try again later.", "network")
    ids: list[str] = []
    if r.status_code == 200:
        try:
            ids = [str(m.get("id")).removeprefix("models/") for m in (r.json().get("data") or []) if m.get("id")]
        except (ValueError, AttributeError):
            ids = []
    return {"ok": True, "models": sorted(set(ids))[:400], "modelAvailable": (want in ids) if (ids and want) else None, "unverified": unlisted}


# ---------------------------------------------------------------- what happened on real conversations
def note_error(e: Exception) -> None:
    """Remember why the last assistant reply fell back to the offline engine, so the panel can say so. Never includes the key."""
    code = getattr(e, "status_code", None)
    who = PROVIDERS[active()]["short"]
    why = {400: f"{who} refused the request. Check the model name in the panel.", 401: f"{who} rejected the key (it may have been revoked). Save a working key.",
           402: f"{who} says the account is out of credit. Check its billing page.", 403: f"{who} refused the request for this key.",
           404: f"The model name is not available to this key at {who}.", 429: f"{who} is rate limiting this key, or the account is out of credit. Check its billing page."}.get(code)
    msg = why or (f"{who} had a problem" + (f" (error {code})" if code else "") + ". The offline engine answered instead.")
    db.set_setting("ai_status", {**(db.get_setting("ai_status", {}) or {}), "error": msg, "at": db.now()})


def note_ok() -> None:
    st = db.get_setting("ai_status", {}) or {}
    if st.get("error") or not st.get("ok_at"):
        db.set_setting("ai_status", {"ok_at": db.now()})

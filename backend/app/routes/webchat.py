"""Public web-chat endpoints and the embeddable widget page (/widget)."""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import db, domain, publicbiz
from ..agent.tools import agent_settings

router = APIRouter()
SID = re.compile(r"^[a-z0-9]{16,40}$")
_last: dict[tuple[str, str], float] = {}


def _conv_for(sid: str):
    return db.get(
        "SELECT c.id, c.mode FROM conversations c JOIN customers u ON u.id=c.customer_id WHERE u.external_id=? AND u.channel_kind='web' ORDER BY c.last_message_at DESC LIMIT 1",
        [f"web_{sid}"],
    )


class SendBody(BaseModel):
    sid: str
    text: str = Field(min_length=1, max_length=1000)
    b: str | None = Field(default=None, max_length=60)       # which business's chat this is (its address name); empty = the default business


@router.post("/api/webchat/send")
async def send(b: SendBody):
    bid = publicbiz.enter(b.b)
    if not SID.match(b.sid):
        raise HTTPException(400, "bad request")
    t = time.time()
    if len(_last) > 5000:
        _last.clear()
    if t - _last.get((bid, b.sid), 0) < 0.6:
        raise HTTPException(429, "slow down")
    _last[(bid, b.sid)] = t
    ch = db.get("SELECT id FROM channels WHERE kind='web' ORDER BY created_at LIMIT 1")
    if not ch:
        raise HTTPException(503, "web chat is off")
    guest = 1000 + int(b.sid[:4], 36) % 9000
    await domain.process_inbound(ch["id"], f"web_{b.sid}", f"Guest {guest}", b.text.strip())
    return {"ok": True}


@router.get("/api/webchat/messages")
async def messages(sid: str, after: int = 0, b: str | None = None):
    publicbiz.enter(b)
    if not SID.match(sid):
        raise HTTPException(400, "bad request")
    conv = _conv_for(sid)
    if not conv:
        return {"items": [], "mode": "agent"}
    rows = db.all("SELECT * FROM messages WHERE conversation_id=? AND role != 'event' AND id > ? ORDER BY id", [conv["id"], after])
    items = []
    for m in rows:
        meta = db.jl(m["meta"], None) or {}
        p = db.get("SELECT * FROM products WHERE sku=?", [meta["product"]]) if meta.get("product") else None
        items.append({"id": m["id"], "role": {"customer": "me", "human": "human"}.get(m["role"], "bot"), "text": m["text"],
                      "product": {"name": p["name"], "variant": p["variant"], "price": p["price"], "stock": p["stock"], "art": p["art"]} if p else None})
    return {"items": items, "mode": conv["mode"]}


class HumanBody(BaseModel):
    sid: str
    b: str | None = Field(default=None, max_length=60)


@router.post("/api/webchat/human")
async def human(b: HumanBody):
    publicbiz.enter(b.b)
    if not SID.match(b.sid):
        raise HTTPException(400, "bad request")
    conv = _conv_for(b.sid)
    if not conv:
        return {"ok": False}
    db.run("UPDATE conversations SET handoff_reason='asked for a person' WHERE id=?", [conv["id"]])
    domain.set_mode(conv["id"], "human", "Customer")
    return {"ok": True}


@router.get("/widget", response_class=HTMLResponse)
async def widget(b: str | None = None):
    publicbiz.enter(b)
    name = agent_settings()["storeName"]
    key = (b or "").lower() if re.fullmatch(r"[A-Za-z0-9-]{0,60}", b or "") else ""
    html_name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return WIDGET.replace("__INITIAL__", html_name[:1]).replace("__STORE__", html_name).replace("__B__", key)


WIDGET = r"""<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__STORE__ chat</title>
<style>
:root{--ink:#0c1230;--bg:#f4f6fc;--card:#fff;--line:#e3e7f3;--mut:#6a7391;--p:#2f5bff;--p2:#6a8bff;font-family:"Figtree","Hind Siliguri","Noto Sans Bengali",system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;height:100dvh;display:flex;flex-direction:column;background:var(--bg);color:var(--ink);font-size:15px}
header{padding:14px 16px;background:linear-gradient(135deg,#0c1230,#1b2a74);color:#fff;display:flex;gap:12px;align-items:center}
.logo{width:40px;height:40px;border-radius:13px;background:linear-gradient(135deg,var(--p),var(--p2));display:grid;place-items:center;font-weight:800}
header b{display:block;font-size:15px}header small{opacity:.75;display:flex;gap:6px;align-items:center}header small i{width:7px;height:7px;border-radius:50%;background:#3ddc97}
.sp{flex:1}.lang{display:flex;background:#ffffff1f;border-radius:999px;padding:3px}.lang button{border:0;background:none;color:#fff;border-radius:999px;padding:5px 10px;font:inherit;font-size:12px;cursor:pointer;opacity:.7}.lang button.on{background:#fff;color:var(--ink);opacity:1;font-weight:700}
.bar{padding:8px 14px;background:#fff;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--mut)}
.bar button{border:0;background:none;color:var(--p);font:inherit;font-weight:700;cursor:pointer}
#log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.m{max-width:84%;padding:10px 14px;border-radius:18px;line-height:1.45;overflow-wrap:anywhere;animation:in .25s ease-out}
@keyframes in{from{opacity:0;transform:translateY(6px)}}
.bot{align-self:flex-start;background:var(--card);border:1px solid var(--line);border-bottom-left-radius:6px}
.human{align-self:flex-start;background:#e8f7f0;border:1px solid #bfe6d4;border-bottom-left-radius:6px}
.me{align-self:flex-end;background:linear-gradient(135deg,var(--p),#4a73ff);color:#fff;border-bottom-right-radius:6px}
.note{align-self:center;text-align:center;font-size:12px;color:var(--mut);max-width:90%}
.prod{align-self:flex-start;width:84%;background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden}
.prod .art{height:96px;display:grid;place-items:center;font-size:42px}
.prod .in{padding:10px 14px}.prod b{display:block}.prod span{color:var(--mut);font-size:13px}.prod .pr{float:right;font-weight:800;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chips button{border:1px solid #c6d3ff;background:#fff;color:var(--p);border-radius:999px;padding:8px 14px;font:inherit;font-weight:600;cursor:pointer}.chips button:hover{background:#eef2ff}
.dots{display:inline-flex;gap:4px}.dots i{width:6px;height:6px;border-radius:50%;background:#9aa3c4;animation:b 1.2s infinite}.dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}@keyframes b{50%{opacity:.25}}
form{display:flex;gap:8px;padding:12px;background:#fff;border-top:1px solid var(--line)}
input{flex:1;height:44px;border:1px solid var(--line);border-radius:999px;padding:0 18px;font:inherit;background:var(--bg)}input:focus{outline:2px solid var(--p);border-color:transparent;background:#fff}
form button{width:44px;height:44px;border-radius:50%;border:0;background:linear-gradient(135deg,var(--p),#4a73ff);color:#fff;cursor:pointer;font-size:18px}
</style></head><body>
<header><div class="logo">__INITIAL__</div><div><b>__STORE__</b><small><i></i><span id="st"></span></small></div><div class="sp"></div>
<div class="lang"><button data-l="bn" class="on">বাংলা</button><button data-l="en">English</button></div></header>
<div class="bar"><span id="disc"></span><button id="human"></button></div>
<div id="log"></div>
<form id="f"><input id="in" autocomplete="off"><button aria-label="Send">➤</button></form>
<script>
const T={bn:{st:'সহকারী · কয়েক সেকেন্ডেই উত্তর',disc:'আপনি স্বয়ংক্রিয় সহকারীর সাথে কথা বলছেন।',human:'মানুষের সাথে কথা বলুন',ph:'মেসেজ লিখুন',hi:'আসসালামু আলাইকুম! আমি পণ্য খুঁজে দিতে, অর্ডারের অবস্থা জানাতে আর রিটার্নের নিয়ম বলতে পারি। কী লাগবে?',c:['ওয়াটার বোতল খুঁজুন','আমার অর্ডার ট্র্যাক করুন','রিটার্নের নিয়ম'],call:'একজন মানুষকে ডেকে আনছি। একটু অপেক্ষা করুন।'},
en:{st:'Assistant · replies in seconds',disc:"You're chatting with an automated assistant.",human:'Talk to a person',ph:'Type a message',hi:'Hello! I can help you find products, check an order, or answer questions about returns. What do you need?',c:['Find a water bottle','Track my order','Return policy'],call:'Calling a person now. Please wait a moment.'}};
const B='__B__';let L='bn',sid=localStorage.getItem('dk_sid'+B);if(!sid){sid=Array.from(crypto.getRandomValues(new Uint8Array(12)),b=>b.toString(36).padStart(2,'0')).join('').slice(0,20)+'x1';localStorage.setItem('dk_sid'+B,sid)}
const $=s=>document.querySelector(s),log=$('#log');let after=0,typing=null;
const ICON={bottle:'🧴',tent:'⛺',boot:'🥾',jacket:'🧥'};
function add(cls,html){const d=document.createElement('div');d.className=cls;d.innerHTML=html;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function ui(){const t=T[L];$('#st').textContent=t.st;$('#disc').textContent=t.disc;$('#human').textContent=t.human;$('#in').placeholder=t.ph;document.documentElement.lang=L}
function greet(){const t=T[L];add('note',esc(t.disc));add('m bot',esc(t.hi));const c=add('chips','');t.c.forEach(x=>{const b=document.createElement('button');b.textContent=x;b.onclick=()=>send(x);c.appendChild(b)})}
async function send(text){if(!text.trim())return;add('m me',esc(text));$('#in').value='';showTyping();await fetch('/api/webchat/send',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({sid,text,b:B||null})})}
function showTyping(){hideTyping();typing=add('m bot','<span class="dots"><i></i><i></i><i></i></span>')}
function hideTyping(){typing&&typing.remove();typing=null}
async function poll(){try{const r=await (await fetch('/api/webchat/messages?sid='+sid+'&after='+after+(B?'&b='+encodeURIComponent(B):''))).json();for(const m of r.items){after=Math.max(after,m.id);if(m.role==='me'){continue}hideTyping();add('m '+m.role,esc(m.text));if(m.product){const p=m.product;add('prod','<div class="art" style="background:#eef2ff">'+(ICON[p.art]||'📦')+'</div><div class="in"><span class="pr">৳'+p.price.toLocaleString('en-IN')+'</span><b>'+esc(p.name)+'</b><span>'+esc(p.variant||'')+' · '+(p.stock>0?p.stock+' in stock':'Out of stock')+'</span></div>')}}}catch(e){}}
$('#f').onsubmit=e=>{e.preventDefault();send($('#in').value)};
$('#human').onclick=async()=>{add('m bot',esc(T[L].call));await fetch('/api/webchat/human',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({sid,b:B||null})})};
document.querySelectorAll('.lang button').forEach(b=>b.onclick=()=>{L=b.dataset.l;document.querySelectorAll('.lang button').forEach(x=>x.classList.toggle('on',x===b));ui();if(!after){log.innerHTML='';greet()}});
ui();greet();setInterval(poll,1500);poll();
</script></body></html>"""

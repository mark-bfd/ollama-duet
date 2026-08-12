"""Orbit — a tiny fictional project-tracker SaaS with a Duet assistant.

Run it:   pip install fastapi uvicorn
          uvicorn demo.app:app --port 8700     (from the repo root)
Open:     http://localhost:8700

Everything here is fake in-memory data; the point is the WIRING:
  * every turn injects a live status digest (grounding)
  * `lookup_customer` is cloud_safe=False — customer PII never leaves
    your machine, even when the cloud brain answers
  * `propose_action` returns a button; the model proposes, YOU click
  * the reply badge shows which brain answered
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse

from duet import Duet, Toolbox

# --- the fictional app state ------------------------------------------------
TICKETS = [
    {"id": 101, "title": "Deploy pipeline flaky on Fridays", "state": "open"},
    {"id": 102, "title": "Dark mode toggle resets on reload", "state": "open"},
    {"id": 103, "title": "Export to CSV drops UTF-8 names", "state": "done"},
]
CUSTOMERS = {  # pretend-PII: exactly what should NEVER reach a third party
    "acme": {"name": "Acme Corp", "plan": "scale", "arr": 48_000,
             "contact": "jo@acme.example"},
    "globex": {"name": "Globex", "plan": "starter", "arr": 6_000,
               "contact": "hank@globex.example"},
}
DEPLOY = {"version": "v2.14.1", "state": "green", "last": "today 06:12"}
PROPOSED: list[dict] = []          # buttons the assistant has offered

# --- tools --------------------------------------------------------------------
box = Toolbox()


@box.tool("Live platform status: deploy state and open ticket count.")
def get_status():
    open_n = sum(1 for t in TICKETS if t["state"] == "open")
    return (f"deploy {DEPLOY['version']} is {DEPLOY['state']} "
            f"(last: {DEPLOY['last']}); {open_n} open tickets")


@box.tool("List tickets with id, title, and state.")
def list_tickets():
    return "; ".join(f"#{t['id']} {t['title']} [{t['state']}]"
                     for t in TICKETS)


@box.tool("Look up a customer account by key (name, plan, ARR, contact).",
          {"type": "object",
           "properties": {"key": {"type": "string"}},
           "required": ["key"]},
          cloud_safe=False)   # <-- PII stays local. This is the whole point.
def lookup_customer(key: str):
    c = CUSTOMERS.get(key.lower())
    if not c:
        return f"no customer '{key}'"
    return (f"{c['name']}: plan={c['plan']}, ARR=${c['arr']:,}, "
            f"contact={c['contact']}")


@box.tool("Offer the user a one-click button to a page instead of acting. "
          "Use for anything that changes data: you propose, they click.",
          {"type": "object",
           "properties": {"label": {"type": "string"},
                          "path": {"type": "string"}},
           "required": ["label", "path"]})
def propose_action(label: str, path: str):
    PROPOSED.append({"label": label, "path": path})
    return f"offered the user a button: {label} -> {path}"


duet = Duet(
    toolbox=box,
    system="""You are Orbit's in-app assistant. Warm, brief, a little fun.
Answer from TOOLS, which read live state — never guess numbers.
To change anything, use propose_action to hand the user a button.
Keep replies to a few sentences.""",
)

# --- the web app ---------------------------------------------------------------
app = FastAPI(title="Orbit demo")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Orbit — Duet demo</title><style>
 body{font-family:system-ui;margin:2rem auto;max-width:44rem;padding:0 1rem;
      background:#0e1116;color:#dde3ea}
 h1{font-size:1.3rem} .card{background:#161b22;border:1px solid #2b3138;
      border-radius:10px;padding:1rem;margin:.6rem 0}
 #log{min-height:8rem} .turn{margin:.5rem 0}
 .who{opacity:.55;font-size:.8rem} .cloud{color:#7cb7ff}
 .btn{display:inline-block;margin:.3rem .3rem 0 0;padding:.35rem .7rem;
      border:1px solid #3b82f6;border-radius:8px;color:#7cb7ff;
      text-decoration:none;font-size:.9rem}
 form{display:flex;gap:.5rem} input{flex:1;padding:.5rem;border-radius:8px;
      border:1px solid #2b3138;background:#0e1116;color:#dde3ea}
 button{padding:.5rem 1rem;border-radius:8px;border:0;background:#3b82f6;
      color:white;cursor:pointer}
</style></head><body>
<h1>🛰️ Orbit <span style="opacity:.5">— fictional SaaS, real assistant</span></h1>
<div class="card">Deploy <b>v2.14.1</b> · green · 2 open tickets — ask the
assistant about any of it. Try: <i>“what’s our status?”</i>,
<i>“look up acme”</i> (private tool), <i>“open the tickets page for me”</i>
(proposes a button).</div>
<div class="card" id="log"></div>
<form onsubmit="send(event)"><input id="msg" placeholder="Ask Orbit…"
 autocomplete="off"><button>Send</button></form>
<script>
const hist = [];
async function send(e){
  e.preventDefault();
  const box = document.getElementById('msg'), q = box.value.trim();
  if(!q) return; box.value='';
  add('you', q);
  const r = await fetch('/chat', {method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body: new URLSearchParams({message:q, history:JSON.stringify(hist)})});
  const d = await r.json();
  add('orbit', d.text, d.brain, d.actions);
  hist.push({role:'user', content:q}, {role:'assistant', content:d.text});
}
function add(who, text, brain, actions){
  const el = document.createElement('div'); el.className='turn';
  const badge = brain==='cloud' ? ' <span class="cloud">☁ cloud</span>' : '';
  el.innerHTML = `<div class="who">${who}${badge}</div>${text}` +
    (actions||[]).map(a=>` <a class="btn" href="${a.path}">${a.label} ▶</a>`).join('');
  document.getElementById('log').appendChild(el);
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


@app.post("/chat")
def chat(message: str = Form(...), history: str = Form("[]")):
    PROPOSED.clear()
    try:
        hist = json.loads(history)
    except json.JSONDecodeError:
        hist = []
    turn = duet.chat(hist, message, context=get_status())
    return JSONResponse({"text": turn.text, "brain": turn.brain,
                         "actions": list(PROPOSED)})


@app.get("/tickets", response_class=HTMLResponse)
def tickets():
    rows = "".join(f"<div class='card'>#{t['id']} {t['title']} — "
                   f"{t['state']}</div>" for t in TICKETS)
    return PAGE.replace('<div class="card" id="log"></div>', rows)

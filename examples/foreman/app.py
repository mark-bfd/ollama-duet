"""Foreman — an ops console for your AI automations, with a two-brain
application assistant embedded in the web window. The flagship demo.

Run it:   pip install fastapi uvicorn
          uvicorn examples.foreman.app:app --port 8702    (from the repo root)
Open:     http://localhost:8702

This is the pattern for builders who are tired of paying frontier-API
prices to run automations a good open-weight model handles fine. The
assistant is fed the app's own documentation, watches the automation
fleet, and lives inside the app — ready to answer, walk you through an
operational question, or stage an action for you:

  * "why did the enrich pipeline fail last night?"   -> ⚡ local, free:
        reads the real run log, answers grounded
  * "how do I add a retry policy?"                   -> ⚡ local, free:
        answers FROM YOUR DOCS (search_docs), not model memory
  * "design a backfill plan for the failed runs
     that stays inside the rate limits"              -> ☁ near-frontier:
        planning-shaped, auto-escalates to a big open-weight cloud model,
        still inside the flat $20/month
  * "file a feature request for per-run cost
     tracking"                                       -> the assistant
        STAGES the request and hands you a button; nothing is filed
        until you click
  * "what's our rate on the Meridian contract?"      -> client-book data
        is cloud_safe=False: answered locally, WITHHELD from cloud turns

Swap the fake dicts for your own run store, docs folder, and tracker API
and this is a production shape, not a toy.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse

from duet import Duet, Toolbox

# --- the automation fleet (fictional) -----------------------------------------
AUTOMATIONS = [
    {"name": "lead-enrich", "schedule": "hourly", "status": "green",
     "last": "06:00 ok (214 records)"},
    {"name": "invoice-sync", "schedule": "nightly 02:00", "status": "green",
     "last": "02:00 ok (38 invoices)"},
    {"name": "mail-triage", "schedule": "q30min", "status": "AMBER",
     "last": "05:30 ok, 05:00 retried x2 (imap timeout)"},
    {"name": "report-gen", "schedule": "Mon 07:00", "status": "RED",
     "last": "Mon 07:00 FAILED: template not found (3 runs)"},
]
DOCS = {   # in a real deployment: your actual docs folder, chunked
    "retry policy": "Retries: set `retry: {max: N, backoff: exponential}` "
                    "in the pipeline YAML. Default is 0. Exhausted retries "
                    "mark the run FAILED and alert the on-call channel.",
    "rate limits": "Outbound API calls are capped at 60/min per pipeline. "
                   "Backfills must use `--throttle` or they will starve "
                   "the live lanes.",
    "backfill": "Use `foreman backfill <pipeline> --from <date>` — runs "
                "land in the backfill lane, throttled, never the live lane.",
    "cost tracking": "Per-run cost tracking is NOT yet implemented; "
                     "costs are visible only at the account level.",
}
CLIENTS = {   # cloud_safe=False: names, rates, and terms stay in-house
    "meridian": "Meridian Corp — $4,200/mo retainer, renews Nov 1, "
                "SLA: 4h response",
    "kestrel": "Kestrel Labs — $1,800/mo, month-to-month, no SLA",
}
REQUESTS: list[str] = ["per-run cost tracking (staged by assistant, "
                       "confirmed by operator)"]
PROPOSED: list[dict] = []

# --- tools ----------------------------------------------------------------------
box = Toolbox()


@box.tool("Live status of every automation: schedule, state, last run.")
def get_run_status():
    return " | ".join(f"{a['name']} [{a['status']}] {a['schedule']} — "
                      f"{a['last']}" for a in AUTOMATIONS)


@box.tool("Search the product docs; returns the matching section verbatim.",
          {"type": "object",
           "properties": {"query": {"type": "string"}},
           "required": ["query"]})
def search_docs(query: str):
    q = query.lower()
    hits = [f"[{k}] {v}" for k, v in DOCS.items()
            if any(w in k or w in v.lower() for w in q.split())]
    return " || ".join(hits) if hits else f"no doc section matches '{query}'"


@box.tool("The open feature-request queue.")
def list_feature_requests():
    return "; ".join(REQUESTS) or "queue empty"


@box.tool("Client book: contract terms and rates for a client (private).",
          {"type": "object",
           "properties": {"name": {"type": "string"}},
           "required": ["name"]},
          cloud_safe=False)   # revenue data never rides a cloud turn
def client_book(name: str):
    return CLIENTS.get(name.lower(), f"no client '{name}'")


@box.tool("Stage an action as a one-click button (label + path) instead of "
          "acting. To file a feature request, propose path "
          "/requests?add=TITLE. You stage, the operator clicks.",
          {"type": "object",
           "properties": {"label": {"type": "string"},
                          "path": {"type": "string"}},
           "required": ["label", "path"]})
def propose_action(label: str, path: str):
    PROPOSED.append({"label": label, "path": path})
    return f"staged a button: {label} -> {path}"


duet = Duet(
    toolbox=box,
    system="""You are Foreman's embedded assistant — the operator's second
pair of hands for this automation console. Terse, precise, technical.
Answer from TOOLS: run status, docs, the request queue. Quote docs when
they answer the question. To change anything (file a request, restart a
pipeline), use propose_action and say you STAGED it — nothing happens
until the operator clicks. Never invent client terms or run history.""",
)

# --- escalation: ops questions stay local, engineering-design asks go big -------
_BIG_ASK = re.compile(
    r"\b(design|architect|plan|backfill plan|root.?cause|optimi[sz]e|"
    r"refactor|trade.?offs?|strategy|draft .*(proposal|rfc))\b", re.I)


def smart_escalate(message: str) -> str:
    """Planning/design-shaped asks go straight to the near-frontier brain —
    better first answer, no local retry. Everything else runs local (free),
    with failover behind it. Swap in your own policy; the router only
    reads `prefer`."""
    return "cloud" if _BIG_ASK.search(message) else ""


# --- the web app ------------------------------------------------------------------
app = FastAPI(title="Foreman demo")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Foreman — Duet flagship demo</title><style>
 body{font-family:ui-monospace,Consolas,monospace;margin:2rem auto;
      max-width:52rem;padding:0 1rem;background:#0b0e12;color:#c9d4e0}
 h1{font-size:1.25rem;font-family:system-ui} .sub{opacity:.55}
 .card{background:#11161d;border:1px solid #223041;border-radius:8px;
      padding:.9rem 1rem;margin:.55rem 0;font-size:.9rem}
 .green{color:#5fd08a}.AMBER{color:#e8c268}.RED{color:#ef7b7b}
 #log{min-height:9rem} .turn{margin:.55rem 0}
 .who{opacity:.5;font-size:.78rem}
 .local{color:#5fd08a} .cloud{color:#7cb7ff}
 .btn{display:inline-block;margin:.3rem .3rem 0 0;padding:.3rem .65rem;
      border:1px solid #3b82f6;border-radius:6px;color:#7cb7ff;
      text-decoration:none;font-size:.85rem}
 form{display:flex;gap:.5rem;align-items:center}
 input[type=text]{flex:1;padding:.5rem;border-radius:6px;
      border:1px solid #223041;background:#0b0e12;color:#c9d4e0;font:inherit}
 label{font-size:.8rem;opacity:.7;white-space:nowrap;cursor:pointer}
 button{padding:.5rem .9rem;border-radius:6px;border:0;background:#3b82f6;
      color:#fff;cursor:pointer;font:inherit}
</style></head><body>
<h1>🛠️ Foreman <span class="sub">— AI-automation ops console · assistant embedded</span></h1>
<div class="card" id="fleet">loading fleet…</div>
<div class="card">Try:
 <i>"why did report-gen fail?"</i> (⚡ local, reads the log) ·
 <i>"how do I add a retry policy?"</i> (⚡ local, answers from YOUR docs) ·
 <i>"design a backfill plan for the failed runs that respects rate limits"</i>
 (☁ auto-escalates to near-frontier) ·
 <i>"file a feature request for run-level alerting"</i> (stages a button —
 you click, it files) ·
 <i>"what's our rate on the Meridian contract?"</i> (private: local-only,
 withheld from ☁ turns)</div>
<div class="card" id="log"></div>
<form onsubmit="send(event)">
 <input type="text" id="msg" placeholder="Ask Foreman…" autocomplete="off">
 <label><input type="checkbox" id="big"> ☁ near-frontier</label>
 <button>Run</button>
</form>
<script>
const hist = [];
fetch('/fleet').then(r=>r.text()).then(t=>document.getElementById('fleet').innerHTML=t);
async function send(e){
  e.preventDefault();
  const box = document.getElementById('msg'), q = box.value.trim();
  if(!q) return; box.value='';
  add('operator', q);
  const r = await fetch('/chat', {method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body: new URLSearchParams({message:q, history:JSON.stringify(hist),
      prefer: document.getElementById('big').checked ? 'cloud' : ''})});
  const d = await r.json();
  add('foreman', d.text, d.brain, d.actions);
  hist.push({role:'user', content:q}, {role:'assistant', content:d.text});
}
function add(who, text, brain, actions){
  const el = document.createElement('div'); el.className='turn';
  const badge = !brain ? '' : brain==='cloud'
      ? ' <span class="cloud">☁ near-frontier</span>'
      : ' <span class="local">⚡ local · $0</span>';
  el.innerHTML = `<div class="who">${who}${badge}</div>${text}` +
    (actions||[]).map(a=>` <a class="btn" href="${a.path}">${a.label} ▶</a>`).join('');
  document.getElementById('log').appendChild(el);
  el.scrollIntoView();
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


@app.get("/fleet", response_class=HTMLResponse)
def fleet():
    return " &nbsp; ".join(
        f"<span class='{a['status']}'>●</span> {a['name']} "
        f"<span class='sub'>({a['schedule']})</span>" for a in AUTOMATIONS)


@app.get("/requests", response_class=HTMLResponse)
def requests_page(add: str = ""):
    # the write happens HERE, on the operator's click — never on the model's say-so
    if add and add not in REQUESTS:
        REQUESTS.append(add)
    items = "".join(
        f"<div style='background:#11161d;border:1px solid #223041;"
        f"border-radius:8px;padding:.7rem;margin:.4rem 0'>📋 {r}</div>"
        for r in REQUESTS)
    return (f"<html><body style='font-family:ui-monospace,Consolas,monospace;"
            f"background:#0b0e12;color:#c9d4e0;max-width:52rem;margin:2rem auto'>"
            f"<h2>Feature requests</h2>{items}"
            f"<p><a href='/' style='color:#7cb7ff'>← back to Foreman</a></p>"
            f"</body></html>")


@app.post("/chat")
def chat(message: str = Form(...), history: str = Form("[]"),
         prefer: str = Form("")):
    PROPOSED.clear()
    try:
        hist = json.loads(history)
    except json.JSONDecodeError:
        hist = []
    if prefer != "cloud":
        prefer = smart_escalate(message)
    turn = duet.chat(hist, message, context=get_run_status(), prefer=prefer)
    return JSONResponse({"text": turn.text, "brain": turn.brain,
                         "actions": list(PROPOSED)})

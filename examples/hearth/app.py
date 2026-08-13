"""Hearth — a household hub with a two-brain assistant. The flagship demo.

Run it:   pip install fastapi uvicorn
          uvicorn examples.hearth.app:app --port 8701    (from the repo root)
Open:     http://localhost:8701

Why this demo: everyone has a household. Watch three properties in action:

  * "whose turn is dishes?"        -> answered AT HOME, free, instant
  * "plan next week's dinners
     around the pantry, practice
     schedule, and budget"         -> ESCALATES to the big cloud brain
                                      (auto — see smart_escalate — or via
                                      the toggle), still flat-fee
  * "what's Riley allergic to?"    -> the ANSWER works locally; on a cloud
                                      turn the allergy/budget tools are
                                      withheld — family data never leaves
                                      the house, by code, not by promise

All data below is fictional. Swap the dicts for your own calendar, chores,
pantry, and budget sources and you have a real household copilot.
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

# --- the household (fictional) ----------------------------------------------
WEEK = {
    "Mon": ["Alex: soccer practice 17:30"],
    "Tue": ["Sam: dentist 15:00", "trash night"],
    "Wed": ["Riley: recital rehearsal 18:00"],
    "Thu": [],
    "Fri": ["family movie night"],
    "Sat": ["Alex: soccer game 09:00", "grocery run"],
    "Sun": ["meal prep"],
}
CHORES = {"dishes": "Sam", "trash": "Alex", "laundry": "Riley",
          "vacuum": "Jordan"}
PANTRY = ["rice", "black beans", "pasta", "canned tomatoes", "onions",
          "tortillas", "cheddar", "frozen peas", "chicken thighs (freezer)"]
# The two tools below are the point of the demo: they stay HOME.
PROFILES = {   # cloud_safe=False — health details never ride a cloud turn
    "alex": "Alex, 12 — peanut allergy (EpiPen in kitchen drawer)",
    "sam": "Sam, 15 — vegetarian",
    "riley": "Riley, 9 — lactose intolerant",
    "jordan": "Jordan, adult — no restrictions",
}
BUDGET = {"groceries_week": 165, "spent_so_far": 92,
          "notes": "birthday gift fund: don't touch"}
SHOPPING = ["milk (oat)", "eggs"]

PROPOSED: list[dict] = []

# --- tools --------------------------------------------------------------------
box = Toolbox()


@box.tool("This week's family calendar, by day.")
def get_week():
    return " | ".join(f"{d}: {', '.join(ev) if ev else 'free'}"
                      for d, ev in WEEK.items())


@box.tool("Current chore assignments.")
def whose_turn():
    return "; ".join(f"{chore}: {person}" for chore, person in CHORES.items())


@box.tool("What's in the pantry right now.")
def list_pantry():
    return ", ".join(PANTRY)


@box.tool("A family member's profile: age, dietary needs, allergies.",
          {"type": "object",
           "properties": {"name": {"type": "string"}},
           "required": ["name"]},
          cloud_safe=False)   # health data stays HOME. Non-negotiable.
def family_profile(name: str):
    return PROFILES.get(name.lower(), f"no profile for {name}")


@box.tool("Grocery budget: weekly amount, spent so far, notes.",
          cloud_safe=False)   # money stays HOME too.
def get_budget():
    return (f"${BUDGET['groceries_week']}/week, ${BUDGET['spent_so_far']} "
            f"spent; {BUDGET['notes']}")


@box.tool("The current shopping list.")
def shopping_list():
    return ", ".join(SHOPPING) or "empty"


@box.tool("Offer a one-click button (label + path) instead of acting. Use "
          "for anything that changes data — e.g. to add ITEM to the "
          "shopping list, propose path /shopping?add=ITEM. You propose, "
          "the family clicks.",
          {"type": "object",
           "properties": {"label": {"type": "string"},
                          "path": {"type": "string"}},
           "required": ["label", "path"]})
def propose_action(label: str, path: str):
    PROPOSED.append({"label": label, "path": path})
    return f"offered a button: {label} -> {path}"


duet = Duet(
    toolbox=box,
    system="""You are Hearth, this family's home assistant. Warm and practical.
Answer from TOOLS — they read the real calendar, chores, pantry, and (locally)
profiles and budget. Never guess. To change anything (add to a list, move an
event), use propose_action to offer a button — and say you're OFFERING it;
never claim you already made the change (nothing changes until they click).
A few sentences, tops.""",
)

# --- auto-escalation: everyday asks stay home, planning asks go big -----------
_BIG_ASK = re.compile(
    r"\b(plan|organi[sz]e|draft|meal ?plan|schedule .* (week|month)|"
    r"figure out|optimi[sz]e|budget .* (week|month)|come up with)\b", re.I)


def smart_escalate(message: str) -> str:
    """A deliberately simple heuristic: planning-shaped asks get the big
    brain up front (better first answer, no retry). Everything else stays
    local, with normal failover behind it. Replace with your own policy —
    length, time-of-day, a classifier on the local model — the router
    doesn't care where `prefer` comes from."""
    return "cloud" if _BIG_ASK.search(message) else ""


# --- the web app ----------------------------------------------------------------
app = FastAPI(title="Hearth demo")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Hearth — Duet flagship demo</title><style>
 body{font-family:system-ui;margin:2rem auto;max-width:46rem;padding:0 1rem;
      background:#14100c;color:#ede4d8}
 h1{font-size:1.35rem} .card{background:#1d1712;border:1px solid #3a2f24;
      border-radius:12px;padding:1rem;margin:.6rem 0}
 #log{min-height:9rem} .turn{margin:.55rem 0}
 .who{opacity:.55;font-size:.8rem}
 .home{color:#f0b35f} .cloud{color:#7cb7ff}
 .btn{display:inline-block;margin:.3rem .3rem 0 0;padding:.35rem .7rem;
      border:1px solid #f0b35f;border-radius:8px;color:#f0b35f;
      text-decoration:none;font-size:.9rem}
 form{display:flex;gap:.5rem;align-items:center}
 input[type=text]{flex:1;padding:.55rem;border-radius:8px;
      border:1px solid #3a2f24;background:#14100c;color:#ede4d8}
 label{font-size:.85rem;opacity:.75;white-space:nowrap;cursor:pointer}
 button{padding:.55rem 1rem;border-radius:8px;border:0;background:#f0b35f;
      color:#241a10;cursor:pointer;font-weight:600}
</style></head><body>
<h1>🏡 Hearth <span style="opacity:.5">— the family hub that thinks</span></h1>
<div class="card">Try the three magic asks:<br>
 1. <i>“whose turn is dishes?”</i> — answered <b class="home">🏠 at home</b>, free.<br>
 2. <i>“plan next week’s dinners around the pantry, the practice schedule,
    and the budget”</i> — auto-escalates to the <b class="cloud">☁ big brain</b>.<br>
 3. <i>“what is Riley allergic to?”</i> — works at home; on a ☁ turn the
    allergy &amp; budget tools are <b>withheld</b>. Family data never leaves
    the house.<br>
 4. <i>“add tortillas to the shopping list”</i> — the assistant <b>proposes a
    button</b>; nothing is written until <b>you</b> click it.</div>
<div class="card" id="log"></div>
<form onsubmit="send(event)">
 <input type="text" id="msg" placeholder="Ask Hearth…" autocomplete="off">
 <label><input type="checkbox" id="big"> ☁ big brain</label>
 <button>Ask</button>
</form>
<script>
const hist = [];
async function send(e){
  e.preventDefault();
  const box = document.getElementById('msg'), q = box.value.trim();
  if(!q) return; box.value='';
  add('you', q);
  const r = await fetch('/chat', {method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body: new URLSearchParams({message:q, history:JSON.stringify(hist),
      prefer: document.getElementById('big').checked ? 'cloud' : ''})});
  const d = await r.json();
  add('hearth', d.text, d.brain, d.actions);
  hist.push({role:'user', content:q}, {role:'assistant', content:d.text});
}
function add(who, text, brain, actions){
  const el = document.createElement('div'); el.className='turn';
  const badge = !brain ? '' : brain==='cloud'
      ? ' <span class="cloud">☁ big brain</span>'
      : ' <span class="home">🏠 at home</span>';
  el.innerHTML = `<div class="who">${who}${badge}</div>${text}` +
    (actions||[]).map(a=>` <a class="btn" href="${a.path}">${a.label} ▶</a>`).join('');
  document.getElementById('log').appendChild(el);
  el.scrollIntoView();
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


@app.get("/shopping", response_class=HTMLResponse)
def shopping(add: str = ""):
    # THIS is where the write happens — on the user's click, never the model's
    if add and add not in SHOPPING:
        SHOPPING.append(add)
    items = "".join(
        f"<div style='background:#1d1712;border:1px solid #3a2f24;"
        f"border-radius:12px;padding:.8rem;margin:.5rem 0'>🛒 {i}</div>"
        for i in SHOPPING)
    return (f"<html><body style='font-family:system-ui;background:#14100c;"
            f"color:#ede4d8;max-width:46rem;margin:2rem auto'>"
            f"<h1>Shopping list</h1>{items}"
            f"<p><a href='/' style='color:#f0b35f'>← back to Hearth</a></p>"
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
    turn = duet.chat(hist, message,
                     context=f"{get_week()} || chores: {whose_turn()}",
                     prefer=prefer)
    return JSONResponse({"text": turn.text, "brain": turn.brain,
                         "actions": list(PROPOSED)})

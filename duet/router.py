"""The Duet router — local-first, cloud-backed, one API shape.

Three tiers, one bounded tool loop:

  1. LOCAL   your small model on your own Ollama       free, private, fast
  2. CLOUD   a big `*:cloud` tag through the SAME       flat-fee; fires when
             signed-in local daemon (no key needed)     local is busy/erroring
  3. DIRECT  https://ollama.com + Bearer OLLAMA_API_KEY fires only when the
                                                        daemon itself is down

Because all three speak Ollama's native /api/chat, the failover is a
retarget, not a rewrite: same messages, same tool schema, same loop.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from duet.tools import Toolbox

LOCAL_URL = "http://localhost:11434/api/chat"
DIRECT_URL = "https://ollama.com/api/chat"

CLOUD_NOTE = """
You are running as the CLOUD backup brain (the local model was busy or
down). Private tools are withheld from you — never invent what they would
have returned. If the user needs one, say the local assistant handles that
and offer to retry when it's back."""


class BrainUnreachable(Exception):
    """The endpoint didn't answer — the router's cue to try the next tier."""


@dataclass
class Turn:
    """One assistant reply: the text, and which brain produced it — surface
    `brain` in your UI (a badge, a banner) so users always know whether the
    answer stayed on-machine."""
    text: str
    brain: str = "local"            # "local" | "cloud"
    tool_calls: List[str] = field(default_factory=list)


def _http_transport(url: str, body: dict, key: Optional[str],
                    timeout: int) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise BrainUnreachable(str(e)) from e


class Duet:
    """One assistant, two brains.

        duet = Duet(toolbox=box, system="You are Orbit's assistant...")
        turn = duet.chat(history, "what's our deploy status?")
        # turn.brain -> "local" almost always; "cloud" when local was busy

    Env overrides (handy for A/B without code changes):
        DUET_LOCAL_MODEL, DUET_CLOUD_MODEL, OLLAMA_API_KEY
    """

    def __init__(self, toolbox: Toolbox,
                 system: str = "You are a concise, helpful app assistant.",
                 local_model: str = "qwen3.5:9b",
                 cloud_model: str = "glm-5.2:cloud",
                 local_url: str = LOCAL_URL,
                 direct_url: str = DIRECT_URL,
                 api_key: Optional[str] = None,
                 keep_alive: str = "5m",
                 max_tool_rounds: int = 4,
                 history_window: int = 8,
                 timeout: int = 120,
                 think: Optional[bool] = None,
                 transport: Callable = _http_transport) -> None:
        self.toolbox = toolbox
        self.system = system
        self.local_model = os.environ.get("DUET_LOCAL_MODEL") or local_model
        self.cloud_model = os.environ.get("DUET_CLOUD_MODEL") or cloud_model
        self.local_url = local_url
        self.direct_url = direct_url
        self._api_key = api_key
        self.keep_alive = keep_alive
        self.max_tool_rounds = max_tool_rounds
        self.history_window = history_window
        self.timeout = timeout
        # Reasoning models (qwen3.5 etc.) default to a THINKING pass that can
        # eat the whole response budget on an assistant turn. think=False
        # turns it off for snappy tool-calling; None sends nothing (safe for
        # models that reject the field).
        self.think = think
        self.transport = transport      # injectable: tests swap this out

    # -- key ---------------------------------------------------------------
    def api_key(self) -> Optional[str]:
        """Key for the direct tier only. Constructor wins, env fallback.
        None simply means tier 3 is unconfigured — tiers 1-2 need no key."""
        return self._api_key or os.environ.get("OLLAMA_API_KEY") or None

    # -- transport ---------------------------------------------------------
    def _call(self, model: str, messages: List[dict], tools: Optional[list],
              url: str, key: Optional[str] = None) -> dict:
        body = {"model": model, "messages": messages, "stream": False}
        if self.think is not None:
            body["think"] = self.think
        if url == self.local_url:
            # unload when idle so the GPU frees up for your real workloads;
            # meaningless for the hosted endpoint
            body["keep_alive"] = self.keep_alive
        if tools:
            body["tools"] = tools
        return self.transport(url, body, key, self.timeout)

    # -- the one loop both brains share -------------------------------------
    def _run(self, history: List[dict], user_msg: str, context: str,
             *, model: str, brain: str, url: str,
             key: Optional[str] = None) -> Turn:
        cloud = brain == "cloud"
        system = self.system
        if context:
            system += f"\n\nLive right now: {context}"
        if cloud:
            system += CLOUD_NOTE
        schema = self.toolbox.schema(cloud=cloud)
        messages = [
            {"role": "system", "content": system},
            *history[-self.history_window:],
            {"role": "user", "content": user_msg},
        ]
        used: List[str] = []
        for _ in range(self.max_tool_rounds):
            resp = self._call(model, messages, schema, url, key)
            msg = resp.get("message", {})
            calls = msg.get("tool_calls") or []
            if not calls:
                text = (msg.get("content") or "").strip()
                return Turn(text=text or "I'm not sure — try rephrasing?",
                            brain=brain, tool_calls=used)
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                used.append(name)
                result = self.toolbox.run(name, args, cloud=cloud)
                messages.append({"role": "tool", "content": result})
        # rounds exhausted — ask the model to wrap up from what it has
        resp = self._call(model, messages, None, url, key)
        return Turn(text=(resp.get("message", {}).get("content") or "").strip(),
                    brain=brain, tool_calls=used)

    # -- tiers ---------------------------------------------------------------
    def _run_local(self, history, user_msg, context) -> Turn:
        return self._run(history, user_msg, context,
                         model=self.local_model, brain="local",
                         url=self.local_url)

    def _run_cloud(self, history, user_msg, context) -> Turn:
        try:
            # tier 2: the big model THROUGH your signed-in daemon — keyless
            return self._run(history, user_msg, context,
                             model=self.cloud_model, brain="cloud",
                             url=self.local_url)
        except BrainUnreachable as daemon_err:
            key = self.api_key()
            if not key:
                raise RuntimeError(
                    f"local daemon down ({daemon_err}) and no OLLAMA_API_KEY "
                    f"set for ollama.com direct") from daemon_err
            # tier 3: ollama.com direct takes the bare name, not :cloud
            model = self.cloud_model
            if model.endswith(":cloud"):
                model = model[:-len(":cloud")]
            return self._run(history, user_msg, context,
                             model=model, brain="cloud",
                             url=self.direct_url, key=key)

    # -- the public entry point ----------------------------------------------
    def chat(self, history: List[dict], user_msg: str,
             context: str = "", prefer: str = "") -> Turn:
        """One assistant turn. Local-first; any local failure fails over to
        the cloud backup. Pass prefer="cloud" for an explicit big-brain turn
        (needs no key — it rides the daemon). `context` is your live status
        digest: inject real state every turn and the assistant stays grounded
        instead of guessing."""
        if prefer == "cloud":
            try:
                return self._run_cloud(history, user_msg, context)
            except Exception as e:  # noqa: BLE001
                return Turn(text=f"(Cloud brain unreachable — {e})",
                            brain="cloud")
        try:
            return self._run_local(history, user_msg, context)
        except Exception as local_err:  # noqa: BLE001
            try:
                turn = self._run_cloud(history, user_msg, context)
                turn.text = ("_local brain was busy — answered on the cloud "
                             "backup_\n\n" + turn.text)
                return turn
            except Exception as cloud_err:  # noqa: BLE001
                return Turn(text=f"(Both brains unreachable — local: "
                            f"{local_err}; cloud: {cloud_err})", brain="cloud")

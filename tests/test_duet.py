"""Duet unit tests — no network, no Ollama needed (transport is injected).

Run:  python tests/test_duet.py     (stdlib only)
 or:  pytest tests/                 (same asserts)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from duet import BrainUnreachable, Duet, Toolbox  # noqa: E402


def make_box():
    box = Toolbox()

    @box.tool("Live status.")
    def get_status():
        return "all green, 2 open tickets"

    @box.tool("Look up a customer (private).",
              {"type": "object", "properties": {"key": {"type": "string"}},
               "required": ["key"]}, cloud_safe=False)
    def lookup_customer(key: str):
        return f"SECRET-DATA-{key}"

    return box


def reply(content, tool=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"function": {"name": tool, "arguments": {}}}]
        msg["content"] = ""
    return {"message": msg}


def test_tool_loop_local():
    n = {"i": 0}

    def transport(url, body, key, timeout):
        n["i"] += 1
        return reply("", "get_status") if n["i"] == 1 else \
            reply("All green — two tickets open.")

    d = Duet(make_box(), transport=transport)
    t = d.chat([], "status?")
    assert t.brain == "local" and "green" in t.text and n["i"] == 2
    assert t.tool_calls == ["get_status"]
    print("[ok] local tool loop: call then answer")


def test_schema_withholding():
    box = make_box()
    local = {t["function"]["name"] for t in box.schema()}
    cloud = {t["function"]["name"] for t in box.schema(cloud=True)}
    assert "lookup_customer" in local and "lookup_customer" not in cloud
    print("[ok] private tools absent from the cloud schema")


def test_dispatch_withholding():
    """Even if the cloud model ASKS for the private tool, it gets a refusal."""
    seen = {}

    def transport(url, body, key, timeout):
        if body["model"].endswith(":cloud") and "messages" in body:
            tool_msgs = [m for m in body["messages"] if m["role"] == "tool"]
            if not tool_msgs:
                return reply("", "lookup_customer")
            seen["result"] = tool_msgs[-1]["content"]
            return reply("understood")
        raise BrainUnreachable("local model gone")

    d = Duet(make_box(), transport=transport)
    t = d.chat([], "who is acme?")   # local raises -> cloud tier answers
    assert t.brain == "cloud"
    assert "withheld" in seen["result"] and "SECRET" not in seen["result"]
    print("[ok] cloud dispatch refuses private tools by name")


def test_failover_banner():
    def transport(url, body, key, timeout):
        if body["model"] == "qwen3.5:9b":
            raise BrainUnreachable("busy")
        return reply("cloud says hi")

    t = Duet(make_box(), transport=transport).chat([], "hi")
    assert t.brain == "cloud" and "cloud backup" in t.text
    print("[ok] failover banner marks the cloud answer")


def test_direct_tier_bare_name():
    calls = []

    def transport(url, body, key, timeout):
        calls.append((url, body["model"], key))
        if "localhost" in url:
            raise BrainUnreachable("daemon down")
        return reply("direct here")

    d = Duet(make_box(), api_key="k-123", transport=transport)
    t = d.chat([], "hi")
    url, model, key = calls[-1]
    assert t.brain == "cloud" and "direct here" in t.text
    assert url.startswith("https://ollama.com") and key == "k-123"
    assert not model.endswith(":cloud"), "direct API takes the bare name"
    print("[ok] daemon-dead goes direct with bare model name + key")


def test_no_key_degrades():
    def transport(url, body, key, timeout):
        raise BrainUnreachable("everything down")

    d = Duet(make_box(), api_key=None, transport=transport)
    d.api_key = lambda: None            # ignore any real env key
    t = d.chat([], "hi")
    assert "unreachable" in t.text and "OLLAMA_API_KEY" in t.text
    print("[ok] everything-down + no key = one clear message, no crash")


def test_prefer_cloud_keyless():
    def transport(url, body, key, timeout):
        assert body["model"].endswith(":cloud") and key is None
        return reply("big brain here")

    t = Duet(make_box(), transport=transport).chat([], "hi", prefer="cloud")
    assert t.brain == "cloud" and "big brain" in t.text
    print("[ok] prefer=cloud rides the daemon, no key needed")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items())
               if k.startswith("test_")]:
        fn()
    print("\nALL DUET TESTS PASSED")

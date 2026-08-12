"""Tool registry for a Duet assistant.

Every tool is a plain function plus a JSON-schema description the model
reads. Tools carry the one extra bit the privacy story hangs on:
``cloud_safe``. Cloud-safe tools may be served to the cloud brain;
everything else is local-only and withheld from the cloud TWICE — from its
advertised schema AND from its dispatch, so even a hallucinated call by
name gets a refusal instead of your data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., object]
    cloud_safe: bool


class Toolbox:
    """Register tools with a decorator; serve schema + dispatch per brain.

        box = Toolbox()

        @box.tool("Live service status.")
        def get_status():
            return "all green"

        @box.tool("Look up a customer by name.",
                  {"type": "object",
                   "properties": {"name": {"type": "string"}},
                   "required": ["name"]},
                  cloud_safe=False)          # <- never leaves your machine
        def lookup_customer(name: str):
            return db.find(name)
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def tool(self, description: str, parameters: Optional[dict] = None,
             cloud_safe: bool = True) -> Callable:
        def deco(fn: Callable) -> Callable:
            self._tools[fn.__name__] = Tool(
                name=fn.__name__,
                description=description,
                parameters=parameters or {"type": "object", "properties": {}},
                fn=fn,
                cloud_safe=cloud_safe,
            )
            return fn
        return deco

    def names(self, cloud: bool = False) -> List[str]:
        return [t.name for t in self._tools.values()
                if not cloud or t.cloud_safe]

    def schema(self, cloud: bool = False) -> List[dict]:
        """Ollama-native tool schema; the cloud view omits private tools."""
        return [
            {"type": "function", "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }}
            for t in self._tools.values() if not cloud or t.cloud_safe
        ]

    def run(self, name: str, args: dict, cloud: bool = False) -> str:
        """Execute a tool call. The cloud brain gets refusals, not data,
        for private tools — enforcement lives HERE, not only in schema()."""
        t = self._tools.get(name)
        if t is None:
            return f"no tool named {name}"
        if cloud and not t.cloud_safe:
            return (f"tool {name} is private and withheld from the cloud "
                    f"brain; the local assistant handles it")
        try:
            return str(t.fn(**(args or {})))
        except TypeError as e:
            return f"bad arguments for {name}: {e}"
        except Exception as e:  # tool bugs become text the model can relay
            return f"{name} failed: {e}"

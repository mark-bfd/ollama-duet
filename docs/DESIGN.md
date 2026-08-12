# Design notes

Why the pieces are shaped the way they are, and what to watch when adapting.

## One transport, one loop

`Duet._run()` is the only conversation loop in the system. Local and cloud
brains differ solely in `(model, url, key)`. This is the load-bearing
decision: when your failover path is the SAME code as your happy path, it is
tested on every turn that exercises the happy path — the classic failure of
backup systems (rotting untested until the day they're needed) can't happen.

The transport (`_http_transport`) is a constructor argument. Tests inject a
fake; you could inject retries, logging, or a different HTTP stack the same
way.

## Failure semantics

`BrainUnreachable` is raised ONLY for transport-level failures (connection
refused, timeout, DNS). Everything else — a malformed model reply, a tool
exception — is either absorbed (tool errors become text the model can relay)
or allowed to propagate to `chat()`'s broad catch, which also fails over.
The rule of thumb: **any local failure is a reason to try the bigger brain**,
because the user is waiting.

The cascade terminates in words, not exceptions: everything-down returns a
`Turn` explaining exactly what's unreachable, so your UI never needs a
try/except around `chat()`.

## Why the cloud tier is two tiers

The elegant path — a `*:cloud` model tag through your signed-in local daemon —
shares a failure mode with the thing it backs up: if the daemon process dies,
both die. Hence tier 3, `ollama.com` direct with a Bearer key. Two details:

- The direct API takes the **bare model name** (`glm-5.2`), not the daemon's
  `:cloud` alias. `_run_cloud` strips the suffix.
- Tier 3 is optional. `api_key()` returning None doesn't crash anything; the
  router reports cleanly. Ship without it; add the key when you care about
  daemon-down coverage.

## Privacy: schema AND dispatch

Most tool-withholding implementations stop at the schema: don't advertise the
tool, assume the model won't call it. That assumption is weaker with
open-weight models that may have seen your tool names in context, or simply
hallucinate plausible ones. So `Toolbox.run(name, args, cloud=True)` checks
`cloud_safe` at execution and returns a refusal string. The cloud model
learns the tool exists — but never what it returns. The private data path is
closed by code, not by prompt.

The `CLOUD_NOTE` appended to the cloud system prompt tells the model this
explicitly, which stops it from inventing what the tool "would have said" —
the failure mode that makes withholding look like hallucination.

## Grounding beats memory

Small local models make poor oracles and fine operators. The `context`
parameter exists so every turn opens with real, current state ("deploy green,
2 open tickets") — cheap to compute, and it converts "what's our status?"
from a hallucination risk into a reading-comprehension task. If you keep
durable norms (user preferences, standing rules), keep them in a file you
inject, not in the model's memory; 9B models won't reliably remember, so
don't ask them to.

## Propose, never fire

`propose_action` is a convention, not a mechanism: the tool records a button
(label + path) that your UI renders next to the reply. The assistant cannot
execute writes because no write tool exists — the strongest sandbox is an
absent capability. If you add write tools, keep them `cloud_safe=False` at
minimum, and prefer the button pattern for anything irreversible.

## Cost model, honestly

- Local turns: $0 marginal. Your GPU, your electricity.
- Cloud turns: covered by the flat subscription. The plan throttles
  (session windows + weekly caps) instead of billing overages — the cap is
  enforced by the provider, which is why this repo contains no token-metering
  code. Deliberately. A budget you must enforce in code is a budget that
  leaks; a plan with no overage path cannot.
- For a *backup* brain that fires on a minority of turns, typical usage sits
  far below the caps.

## Adapting checklist

1. Register tools; mark everything touching PII/secrets `cloud_safe=False`.
2. Build a one-line status digest; pass it as `context` on every turn.
3. Render `turn.brain` visibly (badge) and any proposed buttons.
4. Pick models; set `think=False` for reasoning models on assistant duty.
5. Tune `keep_alive` (idle unload vs. cold-start failovers) and `timeout`.
6. Optionally seed `OLLAMA_API_KEY` (env or constructor) for tier 3.
7. Keep your history window short (`history_window=8` default) — the digest
   carries the state; the transcript doesn't need to.

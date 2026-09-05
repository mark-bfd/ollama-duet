# AGENTS.md — ollama-duet
Public/personal repo: Ollama Cloud models (`deepseek-v4-flash:cloud`, `glm-5.2:cloud`) are allowed for coding here via `opencode.json`.
- Local Ollama calls must use `bfd-*` models (num_ctx 16384 baked in); bare base models spill to CPU on the Dell.
- One GPU stream at a time — check `SynologyDrive/claude-shared/BOARD.md` (Intent table) before any local-model run; prefer cloud during the day.
- Never restart the display adapter; never change Ollama env/Modelfiles from an agent session.
- Read the repo README / MARK-READ-THIS.md (if present) before starting. Commit; do not push unless the repo's own docs say so.

# Curio


Windows voice tutor with a desktop companion, screen guidance and configurable speech/model providers.
## Stack and folders
- `curio-py/` — the desktop app (**frontend**). Python 3.12, PySide6/Qt, qasync, httpx, uv. Whisper (faster-whisper) and Kokoro TTS run on the laptop. Tests in `curio-py/tests/` (pytest).
- `server/` — **backend**: bash/Python scripts to run vLLM (Qwen3-VL-30B-A3B-Instruct-FP8) on a shared OSU lab GPU, reached over an SSH tunnel at `http://localhost:8000/v1`.
- `worker/` — **backend**: Cloudflare Worker (TypeScript) that proxies Anthropic/AssemblyAI/ElevenLabs for the cloud backend.
- `docs/` — `RUNNING.md` (how to run), `ARCHITECTURE.md` (how it fits), `PROGRESS.md` (status, decisions).

## Commands
- Install: `cd curio-py && uv sync --extra local`
- Run the app: `cd curio-py && uv run python -m curio` (needs mic, hotkey, and the GPU tunnel; see `docs/RUNNING.md`)
- Test: `cd curio-py && uv run pytest -q`
- Lint: `cd curio-py && uv run ruff check .` (has some existing errors; don't add new ones)
- Server scripts: `bash -n server/<script>.sh`, `DRY_RUN=1 ./serve.sh`. Never start/stop real GPU jobs from here.
- Worker: `cd worker && npm install && npx wrangler deploy --dry-run` (never real-deploy without asking)

## Orchestration
The main session is the orchestrator. It plans and delegates; subagents in `.claude/agents/` do the work.

1. **Plan first.** Before writing code, break the request into tasks and decide which agent owns each one.
2. **Delegate.**
   - `frontend-dev` — anything in `curio-py/`
   - `backend-dev` — anything in `server/` or `worker/`
   - `reviewer` — read-only review of finished changes, P0/P1 only
   - `tester` — runs tests/lint/dry-runs, reports failures with file:line, doesn't fix
3. **Run independent tasks in parallel.** Launch agents in the same message when their tasks don't depend on each other.
4. **Keep frontend and backend in separate folders.** `frontend-dev` only touches `curio-py/`; `backend-dev` only touches `server/` and `worker/`. Never give two agents the same files at once. When a feature crosses the boundary, settle the interface (request/response shape, config keys) in the plan first, then hand each side its part.
  - You can run multiple frontend-dev agents at once, but give each one a different set of files (for example one on curio/ui/, one on curio/clients/). Never two agents on the same file.
5. **Review and test before done.** Every finished feature goes to `reviewer` and `tester` (in parallel). If either reports problems, send the fixes back to the owning dev agent, then re-run review and tests. A feature is only done when the reviewer has no P0/P1 issues and the tester is all green.
6. Don't commit unless the user asks.

### Context rule
The main session should avoid reading large files itself (big modules, logs, lockfiles, long docs) when a subagent can do it. Delegate the reading and ask for a short answer: the relevant lines, a summary, or file:line references.

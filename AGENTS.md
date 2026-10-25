# Repository Guidelines

## Project Structure

- `curio-py/curio/` contains the Windows desktop app, including UI, clients, and configuration.
- `curio-py/tests/` contains pytest tests; `curio-py/curio.spec` defines the PyInstaller build.
- `worker/src/` contains the TypeScript Cloudflare Worker proxy. `server/` contains shell and Python scripts for the lab vLLM service.
- `docs/` holds the running guide, architecture, and project status. Root-level PNG files are companion sprite sheets.

## Build, Test, and Development

Run Python commands from `curio-py/`:

- `uv sync --extra local` installs the app and optional local speech/voice dependencies.
- `uv run python -m curio` launches the desktop app.
- `uv run pytest` runs the test suite; `uv run ruff check .` checks Python style.
- `uv run pyinstaller curio.spec` builds the standalone Windows executable.

For the Worker, use `cd worker; npm install`, then `npm run dev` for local development. `npm run deploy` publishes it; deploy only when the change is intended for the configured Cloudflare account. Server shell scripts can be syntax-checked with `bash -n server/<script>.sh`; `DRY_RUN=1` previews `serve.sh` without starting a model.

## Coding Style

Use Python 3.12 and follow Ruff settings in `curio-py/pyproject.toml`: 100-character lines and the configured `E`, `F`, `W`, `I`, `UP`, `B`, and `SIM` rules. Use four-space indentation, descriptive `snake_case` names, and `test_*.py` test files. Keep Worker code in TypeScript and match the existing formatting and naming patterns in `worker/src/`. Avoid committing machine-specific settings, API keys, or generated build artifacts.

## Testing

Add or update focused tests in `curio-py/tests/` for Python behavior changes, then run `uv run pytest` and `uv run ruff check .` from `curio-py/`. For Worker or server changes, run the relevant local development or dry-run checks and describe any environment-dependent validation in the pull request. No repository-wide coverage threshold is configured.

## Commits and Pull Requests

Keep commits focused and use short, imperative subjects (for example, `Fix hotkey release handling`). The Git history was unavailable in this environment, so verify local conventions when preparing a commit. Pull requests should explain the user-visible change, link related issues, list checks run, and include screenshots or logs when they clarify UI or model-server behavior. Never include credentials or real deployment secrets.

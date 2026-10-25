# WS3: shared map server, client and "where people get stuck" dashboard

You own `curio/map_sync/`. Read `docs/parallel/README.md` and
`curio-py/curio/learning_contract.py` first, especially `summary_to_wire`
and `path_to_wire` / `path_from_wire`: that JSON is the only thing that
crosses the network. It has no ids, timestamps or window titles; keep it that
way.

## 1. Server: `curio/map_sync/server.py`

Standard library only (`http.server.ThreadingHTTPServer` + a JSON file on
disk, written atomically). Run with
`python -m curio.map_sync.server --host 0.0.0.0 --port 8765 --data map.json`
so a second laptop on the same Wi-Fi can reach it.

- `POST /v1/walkthroughs`: one `summary_to_wire` payload. Validate strictly:
  wire version, types, at most 30 steps, instruction ≤ 300 chars, coordinates
  in 0..1, body ≤ 64 KB. Simple per-IP rate limit. Store completed and
  incomplete summaries; incomplete ones only count toward difficulty.
- `GET /v1/paths?app=`: aggregated `path_to_wire` paths. Group completed
  summaries by app + task (normalised with `task_key`; exact match is fine
  here) + element-label sequence. `verified_count` = number of summaries;
  recent ones weigh more, so a corrected path overtakes a stale one after an
  app update. Each step's `difficulty` = share of attempts at that step
  index that were retried, timed out or abandoned.
- `GET /v1/stats?app=`: per app → task → step: attempts, stuck rate, label.
- `GET /`: the dashboard.

## 2. Dashboard: `curio/map_sync/assets/dashboard.html`

A single self-contained page (no CDN) that polls `/v1/stats` every few
seconds: per app and task, a row of step cells coloured by stuck rate,
plus a "most confusing steps" list ("62% of users get stuck at 'pivot
fields' in excel"). It's what the judges see on the projector, so make it
look good. Load it with `importlib.resources`.

## 3. Client: `curio/map_sync/client.py`

`HttpMapSync(base_url: str, *, client: httpx.AsyncClient | None = None)`
implementing `MapSync`:
- `push` posts `summary_to_wire`; `pull` returns `path_from_wire` paths and
  skips malformed ones.
- 3-second timeouts. Every method fails soft (returns `False`/empty and
  logs) when the server is down. The app must work offline.
- `step_difficulty` is synchronous: answer from a cache filled by the last
  `pull`/stats call.

## 4. Demo seeding: `python -m curio.map_sync.seed --url ... --users 40`

Posts realistic fake walkthroughs for three or four tasks (for example excel
"insert a pivot table", windows settings "turn on dark mode", "change
default browser"), with one step that's clearly hard, plus a few summaries
of an "old" path that the newer one overtakes, so the dashboard and
self-healing are visible in the demo.

## Done when

Tests start the server on an ephemeral port in a thread and cover
validation and rejection, aggregation, difficulty, recency weighting and
client fail-soft behaviour. Write `docs/map-sync.md` with the two-laptop
demo steps and firewall notes, and `docs/parallel/handoff-ws3.md` listing
requests for WS1 (PyInstaller data file for the dashboard, a script entry).

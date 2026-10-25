# Map sync: the shared "where people get stuck" map

Walkthrough reports can be shared opt-in with a small map server. It aggregates
model-reported paths and stuck signals, not verified outcomes or distinct people.
Free text is not guaranteed anonymous even though IDs/window titles are omitted.

New seed posts carry synthetic=true. Default paths/stats exclude marked records;
dashboard polls `/v1/stats?include_synthetic=1` with synthetic/unknown counts.
Unmarked old records have unknown origin. Update the server before running the
new seeder; older strict servers reject the extension. No deployment occurred.
Local verifier references are never exported. Returned path evidence is only
model-reported/unknown. Contradictory final attempts cannot reinforce a path.

Code lives in `curio-py/curio/map_sync/`:

| File | What it is |
|---|---|
| `server.py` | Standard-library HTTP server and a JSON file on disk |
| `client.py` | `HttpMapSync`, the app's `MapSync` implementation |
| `seed.py` | Posts realistic fake walkthroughs for the demo |
| `assets/dashboard.html` | Self-contained dashboard served at `/` |

## What crosses the network

Only `summary_to_wire` JSON goes up and only `path_to_wire` JSON comes down
(see `curio/learning_contract.py`): app, app version, task text, and per step
the instruction, element label and 0..1 position, concepts, assistance level
and outcome. No walkthrough ids, timestamps or window titles. The server
rejects any payload with keys outside that schema, so a client bug can't leak
them. The server stores its own receipt time for recency weighting, and that
time never leaves the server.

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/walkthroughs` | One `summary_to_wire` payload. `201` on success, `400` for invalid payloads, `413` over 64 KB, `429` when rate limited (with `Retry-After`) |
| `GET` | `/v1/paths?app=` | `{"v": 1, "paths": [...]}`, each a `path_to_wire` dict plus `score`. Best path first within each task |
| `GET` | `/v1/stats?app=` | `{"apps": [{"app", "tasks": [{"task", "walkthroughs", "completed", "steps": [{"index", "label", "attempts", "stuck", "stuck_rate"}]}]}], "hardest": [...]}` |
| `GET` | `/` | Dashboard, polls `/v1/stats` every 3 s |
| `GET` | `/healthz` | `{"ok": true}` |

Validation: wire version 1; non-empty `app` and `task`; 1 to 30 step events;
step index 1..100; instruction at most 300 characters; coordinates finite and
in 0..1; known assistance and outcome values; at most 10 concepts per step;
no unknown keys.

### How paths and difficulty are computed

- Walkthroughs are grouped by app and `task_key(task)`.
- **Paths** come from completed walkthroughs only, grouped by the sequence of
  element labels. For each step index the path keeps the last attempt, which
  is the one the user got through. `verified_count` is the number of
  walkthroughs that followed the path.
- **Recency**: each walkthrough's weight halves for every 8 newer completed
  walkthroughs of the same task and for every 30 days of age. A path's
  `score` is the sum of its weights, and paths are ordered by it. That's how a
  path that's been corrected after an app update overtakes the stale one,
  even if the stale one has more walkthroughs.
- **Difficulty** of a step = the share of walkthroughs (completed or not) that
  reached that step index and got stuck there, meaning any attempt was
  retried, timed out or abandoned. The dashboard's stuck rate is the same
  number. A step's label is the newest one seen.

## Client

```python
from curio.map_sync.client import HttpMapSync

sync = HttpMapSync("http://192.168.1.20:8765")
await sync.push(summary)          # bool
paths = await sync.pull("excel")  # tuple[TaskPath, ...], source=SHARED, best first per task
await sync.refresh_stats()        # optional: fill the difficulty cache from /v1/stats
sync.step_difficulty("excel", "insert a pivot table", 5)  # float | None, sync, cached
await sync.aclose()
```

Every call has a 3-second timeout and fails soft: if the server is down, slow
or returns junk, it logs and returns `False`, `()` or `None`.
`step_difficulty` never touches the network.

## Two-laptop demo

On **laptop A** (the server; it can also run Curio):

```powershell
cd curio-py
uv run python -m curio.map_sync.server --host 0.0.0.0 --port 8765 --data map.json
ipconfig   # note the Wi-Fi IPv4 address, e.g. 192.168.1.20
```

Seed it so the dashboard has a story to tell (from any machine):

```powershell
uv run python -m curio.map_sync.seed --url http://192.168.1.20:8765 --users 40
# add --delay 0.1 to watch the dashboard fill live
```

Open `http://192.168.1.20:8765/` on the projector. The seed data includes:

- Excel "insert a pivot table": the step where you drag a field into the
  PivotTable Fields pane is clearly the hardest (about 60% get stuck).
- Settings "turn on dark mode": slightly more walkthroughs on the old
  "Choose your default app mode" layout, then newer ones on the "Choose your
  mode" dropdown. `GET /v1/paths?app=settings` ranks the new path first.
- Settings "change default browser" and Chrome "clear browsing data", each
  with one hard step.

On **both laptops**, point Curio's map sync at `http://192.168.1.20:8765`
(the config key is WS1's, see `docs/parallel/handoff-ws3.md`), then:

1. Laptop A: "how do I insert a pivot table?" and finish the walkthrough. The
   path is pushed and the dashboard's walkthrough count goes up.
2. Laptop B, same question: it pulls the shared path and guides straight
   through it.

To start over, stop the server and delete `map.json`.

## Firewall and network notes

- The first time `python.exe` listens on `0.0.0.0`, Windows Defender Firewall
  asks whether to allow it. Tick **Private networks** and allow it. If the
  prompt was dismissed, add a rule from an elevated PowerShell:

  ```powershell
  New-NetFirewallRule -DisplayName "Curio map server" -Direction Inbound `
    -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private
  ```

  Remove it after the demo with
  `Remove-NetFirewallRule -DisplayName "Curio map server"`.
- Windows treats new Wi-Fi networks as **Public** by default, which blocks
  the rule above. Switch the network to Private in Settings > Network &
  internet > Wi-Fi > (network) > Network profile type, or allow
  `-Profile Private,Public` for the demo only.
- Venue and campus Wi-Fi often isolate clients from each other. If laptop B
  can't reach `http://<A's IP>:8765/healthz`, use a phone hotspot or a travel
  router.
- There's no TLS or auth: it's a demo server for a trusted LAN. The rate
  limit (120 POSTs per minute per IP, `--rate 0` to disable) and strict
  validation stop accidents, not attackers.

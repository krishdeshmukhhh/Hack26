# WS3 handoff: map sync

Branch `feat/map-sync`. All files are in WS3's area: `curio/map_sync/`,
`tests/test_map_sync.py`, `docs/map-sync.md`. Full write-up in
[../map-sync.md](../map-sync.md).

## Public API

```python
# curio/map_sync/client.py — implements learning_contract.MapSync
HttpMapSync(base_url: str, *, client: httpx.AsyncClient | None = None)
    async push(summary: WalkthroughSummary) -> bool
    async pull(app: str | None = None) -> tuple[TaskPath, ...]   # best path first per task
    async refresh_stats(app: str | None = None) -> bool         # extra: fills difficulty cache
    step_difficulty(app: str, task: str, step_index: int) -> float | None   # sync, cached
    async aclose() -> None   # closes the httpx client only if HttpMapSync created it

# curio/map_sync/server.py
make_server(host: str, port: int, data: Path, *, rate_per_minute: float = 120.0) -> MapServer
MapServer.url, MapServer.store, serve_forever(), shutdown(), server_close()
validate_summary(raw) -> dict          # raises ValidationError
aggregate_paths(records, app=None, *, now=None) -> list[dict]
aggregate_stats(records, app=None) -> dict
main(argv=None)                        # python -m curio.map_sync.server

# curio/map_sync/seed.py
build(users: int, rng: random.Random) -> list[WalkthroughSummary]
post_all(url: str, summaries, *, delay: float = 0.0) -> int
main(argv=None)                        # python -m curio.map_sync.seed
```

`curio/map_sync/__init__.py` imports nothing, so the server stays
standard-library only. Import `HttpMapSync` from `curio.map_sync.client`.

## Done

- Server: strict validation (wire version, types, ≤ 30 step events,
  instruction ≤ 300 chars, coordinates in 0..1, body ≤ 64 KB, unknown keys
  rejected so ids, timestamps and titles can't be stored), per-IP token-bucket
  rate limit, atomic JSON storage, aggregates cached until the next POST.
- Paths grouped by app + `task_key` + label sequence, ranked by a
  recency-weighted score (half-life of 8 newer walkthroughs and 30 days).
  Per-step difficulty = share of walkthroughs stuck at that index, including
  incomplete ones.
- Dashboard (no CDN, data rendered with `textContent` so labels can't inject
  HTML), served from `importlib.resources`. Screenshot-checked with headless
  Edge against seeded data.
- Client: 3 s timeouts, fails soft on connection errors, timeouts, HTTP
  errors, non-JSON responses and malformed paths.
- Seeder: 4 tasks (Excel pivot table, Settings dark mode old/new, Settings
  default browser, Chrome clear browsing data), deterministic `--seed`,
  respects `429 Retry-After`.
- Tests: `tests/test_map_sync.py`, 38 tests, server on an ephemeral port in a
  thread. Full suite: 445 passed. `ruff check` and `ruff format --check` are
  clean.

## Not verified

- Not tried across two physical laptops or through Windows Firewall. Only
  tested on loopback.
- Not wired into the app (that's WS1's job), so push/pull haven't run against
  a real walkthrough.
- One unexplained failure in about 30 runs of `test_map_sync.py`, early on
  and not reproduced afterwards. Before that I fixed two Windows-only resets
  (a 429 or 413 sent without reading the request body). If an HTTP test
  flakes, look there first.
- The dashboard hasn't been checked on the actual projector resolution.

## Requests for WS1

1. **PyInstaller data file** in `curio.spec` `datas`:
   `("curio/map_sync/assets", "curio/map_sync/assets")`. Only needed if the
   bundled exe should serve the dashboard. The app itself only uses the client.
2. **Script entries** in `pyproject.toml` `[project.scripts]`:
   `curio-map-server = "curio.map_sync.server:main"` and
   `curio-map-seed = "curio.map_sync.seed:main"`.
3. **Config keys** (suggested): `[map_sync] enabled = false` (opt-in, off by
   default), `url = "http://127.0.0.1:8765"`. When disabled, use the null
   `MapSync`.
4. **Wiring**:
   - After a walkthrough ends, `await sync.push(summary)` only when opted in.
     Don't await it on a path that blocks the next question: it can take up
     to 3 s when the server is unreachable.
   - On startup, and after each push, `await task_map.merge(await sync.pull())`.
     `pull()` returns every path, **best first within each task**, and the
     `verified_count` is the raw count. If WS2's `merge` keeps one path per
     task, it should keep the first one per task rather than the highest
     `verified_count`, or the stale dark-mode path wins. (The `score` field is
     on the wire but `path_from_wire` drops it.) Please pass this on to WS2.
   - Pass the same `HttpMapSync` instance as the `DifficultyProvider` for WS4.
     `step_difficulty` matches on `task_key(task)`, so raw question text works.
     Calling `refresh_stats()` alongside `pull()` covers tasks that have no
     completed path yet.
   - Call `await sync.aclose()` at shutdown.
5. **Tray entry** (optional): "Share anonymous walkthroughs" toggle bound to
   `map_sync.enabled`, and "Open stuck map" opening `<url>/`.

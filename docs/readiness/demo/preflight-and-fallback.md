# Demo preflight and fallback

## Ten minutes before judging

1. Use the actual demo laptop/projector, normal non-administrator target window,
   known microphone and speaker. Close private documents/notifications; inspect
   what screenshots will contain. Leave optional memory and sharing off unless
   explicitly demonstrating them with non-sensitive data.
2. From repository root run:
   `curio-py/.venv/Scripts/python.exe scripts/readiness/demo/preflight.py`.
   This checks discoverability/files only; it does not load Qt DLLs, open audio,
   call the model or validate an executable.
3. Follow RUNNING.md for the selected backend, VPN, model server and SSH tunnel.
   Inspect `/v1/models` using your configured authentication without exposing the
   key on the projector or recording. Confirm the exact model name and coordinate
   mode. Do not copy logs containing credentials or ambient keyboard data.
4. Launch Curio; perform one complete ordinary Ctrl+Alt question, hear playback,
   verify a POINT against the actual control, interrupt speech, and ask again.
   Run the chosen task twice from the same documented starting state. Record the
   observed latency and any incorrect action rather than promising a fixed time.
5. If using hands-free, say wake phrase, pause, then question. Test cancel/send,
   noisy room behavior and manual takeover. Fall back to Ctrl+Alt if unreliable.
6. Test Esc from a walkthrough and restore the task's starting state. Any left
   click can advance the ordinary walkthrough; model completion is not proof
   the target task succeeded. Inspect the actual target application result.
7. Ensure any demo skill/map history is labeled **SIMULATED** and uses a separate
   demo store. Do not present seeded records as people or retention evidence.
8. Rehearse three minutes and bring a genuine labeled backup recording, architecture
   diagram and evidence legend. Check their projector readability offline.

## Network/model failure during judging

- After one failed request or roughly 15 seconds without a usable answer, explain:
  “The live model connection is unavailable. I’ll show our architecture and a
  labeled recording of a prior run.” Do not wait through repeated retries.
- Cancel using Ctrl+Alt/Esc as appropriate. If the app is unresponsive, quit from
  the tray and relaunch; report that observation. Do not claim recovery occurred
  until a subsequent real turn succeeds.
- Play the **genuine prior-run recording** with its date/backend and clear
  “recorded, not live” caption. If none exists, use static diagrams and source/test
  evidence; do not simulate a successful live model answer.
- Map-server failure is a separate case: local map/skill paths can continue while
  map sync fails softly. Our six transport tests cover this boundary with mocks,
  not the remote language model, microphone or physical network.
- If asked to demonstrate exact math offline, prepare and rehearse the supported
  deterministic checker separately; do not imply generated explanations or voice
  still work without a model.

## Restore and clean shutdown

After the presentation quit via tray, close the SSH tunnel, and stop the shared
lab model as RUNNING.md directs. Keep synthetic demo stores separate from personal
data. Record live checks/failures with timestamp, backend and build revision; these
are the evidence needed to mark the manual checklist complete.

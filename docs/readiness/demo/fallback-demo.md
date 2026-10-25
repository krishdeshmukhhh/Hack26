# Fallback demo

If model, microphone, audio or network fails, state the observed failure and switch to a technical demonstration. Do not describe fixture output as live assistance.

From the repository root run:

```powershell
curio-py/.venv/Scripts/python.exe scripts/readiness/demo/run_checks.py
```

Show the captured request/path text in check-results.txt. Explain that the manager, SQLite stores and localhost HTTP service are real, while model replies, microphone, screenshots, click events and speech are mocked. Loopback is one host, not two physical laptops. The recovered workflow retains a retry and model-reported completion; no Excel state was verified.

Open seeded-offscreen-tutor.png: actual Qt rendering of typed seeded attempts, with no OCR, live screen, provider or physical audio. Explain why du=x*dx was rejected and du=2*x*dx accepted. Tutoring is transient; this screenshot does not prove restart persistence.

If Python is unavailable, show the committed text results and PNG with those labels. There is no live backup video. Do not claim the assistant works offline: only cached workflow data and deterministic math checks work without a model.

Cleanup: stop Curio normally, stop any separately started map server, restore the demo workbook, remove only this run's UUID temp folder after inspecting it. No firewall rules or personal Curio configuration were changed by these checks.

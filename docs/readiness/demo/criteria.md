# Declared technical comparison criteria

Declared before executing test_demo_journey.py. These are technical checks, not human usability experiments.

1. Same pivot-table question with no capture versus a synthetic screenshot: actual manager request has zero versus one image blocks. No claim about answer quality, latency or user success.
2. Fresh SQLite state versus retrieved workflow: later prompt contains a shared path and the corrected Insert instruction; fresh prompt has neither. Real loopback HTTP and SQLite, mocked model/microphone/screens/clicks/TTS. No physical laptop claim.
3. Simulated model assertions versus supported exact polynomial math: a missing factor 2 is rejected, correction accepted, final answer recorded as guided completion. No general math or mastery claim.
4. Empty versus 12 seeded unassisted model-reported successes: recommendation moves toward less assistance; abandonment adds no attempts. Seeded evidence is not observed human performance.

Lifecycle criteria: restart reopens event/path SQLite; cancellation and stale provider/capture output are rejected by existing focused tests; disabled learning creates no services; offline failures return safely and recover; all owned HTTP clients, stores and server threads close.

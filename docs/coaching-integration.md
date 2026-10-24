# Coaching integration review

Base: `integration snapshot` (`Continuous memory implemented.`). The requested feature refs
are absent. The shared coaching foundation and both feature packages arrived as
untracked files; reviewed source additions and implementation summaries therefore
replace unavailable branch commit ranges. This is integration in the main working
tree, not evidence of two Git merges. Existing tracked memory interfaces are kept.
Staging was attempted after verification but failed creating `.git/index.lock`
with permission denied. There is no integration commit hash to report.

| Reviewed source | Finding | Resolution |
| --- | --- | --- |
| Shared contract/tests | Separate replies, assessments, evidence and lifecycle | Shared records and correctness requirements preserved. |
| Tutorial content fetcher | Public HTML, redirect/DNS validation, pinned IP transport, bounded input | Existing protections retained; no fabricated video content or transcript-download integration. |
| Tutorial coach/widget and five test files | Provider/capture injection; model claims are not independent verification | Dedicated configured client, explicit capture, public interruption and awaitable widget cleanup. |
| Tutoring checker/service/contract/widget/tests | Bounded AST allowlist and exact rational polynomial algebra; no eval | Deterministic assessments kept separate from model explanations; recognition requires review/confirmation. |
| Application/manager/tray | Feature entry points and routing missing | One explicit mode router and shared window; one final-transcript consumer. |

No symbolic dependency is needed: the checker uses standard-library AST parsing
and Fractions, not SymPy or executable input. Configuration and dependency
manifests remain unchanged. Coaching inherits the configured backend/model through
a separate client so its raw deltas cannot leak into the ordinary voice stream.
Final coaching replies use existing TTS but never execute POINT/STEP tags.

Mode changes cancel old requests/audio and end legacy walkthroughs. Tutorial
navigation pauses; Stop/Escape/close return to ordinary mode. Generations reject
stale model output and hints for revised math problems. Shutdown awaits feature
widget tasks, disconnects signals and releases Qt objects on the GUI thread.
An early full run hit a native Qt access violation; explicit shutdown cleanup
was added and subsequent focused and full runs passed. Physical shutdown still
needs a manual smoke test.

Coaching sessions are transient, with no ordinary conversation-buffer updates or
persistent learning. Explicit screen-sharing buttons hide Curio windows/overlay,
use the existing screenshot capture, then restore visibility. Recognition is
untrusted text; a model cannot grant mathematical correctness or independent
screen verification. Attribution validates source references, not semantic truth.

Tests use mocked HTTP/models/screenshots/TTS, real Qt widgets and the real exact
checker. A rendered offscreen tutoring window was visually inspected. Segoe UI
was loaded explicitly in that inspection harness because the offscreen backend
exposed no font families. This is not a physical desktop smoke test. Computer Use
native pipe discovery failed after retries and reset. Actual URLs, video access,
microphone/audio, OCR/model quality, display behavior and packaging are unverified.
See PROGRESS.md for final command results and RUNNING.md for use/checklists.

Supported slice: ordinary public HTML tutorials, or a supplied permitted video
transcript; bounded polynomial substitution integrals. Trig/log/radical/definite
integrals, variable denominators and LaTeX are unsupported. Tutorial screen checks
are model suggestions unless an independent verifier is injected. Practice
verifies one answer without in-app hints, not general mastery.

# URL tutorial coach

Application integration now exists through CoachingRuntime, CoachingWindow and
the tray. See coaching-integration.md and RUNNING.md. The isolated package handoff
below remains useful; the shared shell closes/reopens without disposing feature
widgets until shutdown.

Implemented in `curio-py/curio/tutorial_coach/`. No startup, tray, config,
CompanionManager, shared prompt, dependency or persistence changes. Requires the
existing `curio.coaching_contract` foundation (it appeared concurrently during
implementation and is deliberately not included in this feature's commit).

## Working behavior

Local tutorial documents are also supported through **Choose tutorial file and
preview...**, alongside the URL input. Supported extensions: `.txt`, `.md`,
`.markdown`, `.html`, `.htm` and `.pdf`. Selection authorizes extraction and
sharing the extracted text with the configured model to build the same editable
plan. Files are not copied into persistent storage or added to memory learning.
The absolute local path is excluded from model requests; opaque upload references
retain the filename and source line, HTML block or PDF page.

Limits: 2 MB per file, 60,000 extracted characters, 800 text blocks and 100 PDF
pages. Plain text accepts UTF-8/UTF-16. PDF extraction uses the installed Qt PDF
module off the UI thread. Scanned/image-only, encrypted or malformed PDFs fail
with a clear error; OCR is not bundled. Word documents, images, archives and video
files are unsupported. HTML scripts and linked resources are not executed or
loaded. Documents and their instructions remain untrusted data.

Paste a public HTML URL, preview the extracted ordered plan, edit instructions
and expected results in the table, reorder/remove steps, then Start. Each step
retains the exact extracted supporting text and final source URL, including an
element anchor where available. Model-generated references must resolve to real
source blocks; this validates attribution, not the truth of a model paraphrase.
Review the preview before following it. Edits retain original attribution.

Start/Repeat/Resume present one instruction. Pause and Stop cancel pending work
and interrupt output. Skip navigates without asserting success. “I completed it”
records `user_confirmed`. Explain this explicitly requests explanation; questions
and recovery default to hints. Worked examples are available only through an
explicit `await coach.ask(text, level=AssistanceLevel.WORKED_EXAMPLE)` call.

Check screen authorizes one capture and submission to the injected provider.
Questions, explanation, recovery and step advancement never capture implicitly.
A model compares the current image with the step's expected result, describes
differences and asks for clarification. Even a model claiming a match cannot
verify completion: shared evidence is `MODEL_CLAIM`, with assessment
`needs_clarification` or `unsupported`. “Use screen verification” stays disabled.

An injected independent `VerificationProvider` can return `confirmed` or
`incorrect` with source-backed observed/verifier evidence for the current capture.
Its session/work/step IDs and capture references are checked. Only a confirmed
assessment enables “Use screen verification”, recording `independently_verified`.
This is separate from `user_confirmed` and `skipped`. Neither lifecycle completion
nor exhausting the plan asserts mastery. No independent application-specific
verifier is bundled; mocked tests demonstrate the injection path.

## Exact initialization and Qt wiring

Public constructor:

```python
Coach(provider, model, *, fetcher=None, capture=None, transcripts=None,
      coaching_provider=None, verification_provider=None, extractor=None,
      timeout=60.0, parent=None)
TutorialCoachWidget(coach: Coach, parent: QWidget | None = None)
```

`provider` implements the existing async
`send(messages, system, model, max_tokens=1024) -> str`. Both `LLMClient` and
`OpenAICompatLLMClient` work without conversion in this package. Set `model` from
integration configuration; there is no hardcoded backend or model. Prefer a
dedicated instance of the configured client class so existing manager listeners
on `delta`/`done`/`error` cannot consume unrelated coach requests. Do not connect
those raw streaming signals to voice or pointing; cancelled text is not final.

Within the existing Qt/qasync thread, using integration-owned configured clients:

```python
import asyncio
from curio.screen_capture import capture_all
from curio.tutorial_coach import Coach
from curio.tutorial_coach.widget import TutorialCoachWidget

# llm_for_coach: configured, dedicated LLMClient OR OpenAICompatLLMClient.
# selected_model: integration's configured model string.
# qt_parent: optional existing QWidget.
async def capture_for_coach():
    # Called only after this widget's explicit Check screen action.
    # Hide/exclude any overlays here if your capture requires it.
    return await asyncio.to_thread(capture_all)

coach = Coach(llm_for_coach, selected_model, capture=capture_for_coach)
widget = TutorialCoachWidget(coach, parent=qt_parent)
widget.show()
```

The widget internally connects `coach.changed -> refresh` and
`coach.response(str) -> output.setPlainText`. It schedules async operations on the
existing running event loop, displays errors as plain text, stops/cancels its
tasks on close, and disconnects those listeners. Keep references to both objects.
Widget close is final; construct another widget to reopen after close.

Optional spoken output uses final text only. For example, with a dedicated or
integration-arbitrated TTS client (`speak(str)` async and `stop()` sync):

```python
speech_task = None

def stop_speech():
    global speech_task
    tts_for_coach.stop()
    if speech_task is not None:
        speech_task.cancel()
    speech_task = None

async def speak_final(text):
    try:
        await tts_for_coach.speak(text)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass  # Route a UI-safe audio failure through integration's error surface.

def speak_response(text):
    global speech_task
    stop_speech()
    speech_task = asyncio.create_task(speak_final(text))

coach.interrupted.connect(stop_speech)
coach.response.connect(speak_response)
# On application shutdown, before stopping qasync:
# widget.close()
# await coach.aclose()
# stop_speech()
# coach.response.disconnect(speak_response)
# coach.interrupted.disconnect(stop_speech)
```

Integration must arbitrate push-to-talk, the legacy walkthrough and TTS ownership:
call `coach.pause()` if active before giving those flows control. This feature
does not modify global hotkeys. It strips POINT/STEP control tags and emits no
desktop actions or automatic pointer motion. Screenshot-grounded pointing is a
future integration option, not implemented behavior.

## Shared contracts and adapter injection

`coach.session` is an immutable `CoachingSession`; goals carry each expected
result, and steps carry source references. UI states map as follows:

| UI | Shared lifecycle |
| --- | --- |
| preview | created |
| active | active |
| paused | paused |
| finished | completed (navigation only) |
| stopped | cancelled, or previously completed |

Each preview/edit and restart creates a new session ID. Each accepted async
request gets a fresh `RequestContext`; earlier tokens are cancelled. Pause/Stop,
repeat and navigation invalidate pending tasks and generations. Late results,
including those from a provider suppressing cancellation, cannot publish replies
or advance the session. Concurrent async requests are rejected while busy.

Optional `coaching_provider`, `verification_provider`, and `extractor` implement
the shared `CoachingProvider`, `VerificationProvider`, and `ContentExtractor`
protocols. `PageFetcher.extract(source, *, context)` itself implements the latter;
the default direct fetch path additionally preserves per-block text mapping.
Custom extractors return aggregate text and source references, preserved together
as one attributable block. These injected adapters are trusted application code:
they must enforce URL policy, permission, timeouts and cancellation before/after
awaiting I/O. A reference is never fetch authority. The built-in model boundary
always treats URLs, content, edits, questions and images as untrusted data.

An independent verifier receives `SubmittedWork` with a new work ID and opaque
`screen:...` source URIs for this capture. During `assess` only, it may resolve
these using `coach.read_artifact(uri)` to obtain the existing ScreenshotImage-like
object. Example setup: construct the coach, then assign a verifier constructed
with `artifact_reader=coach.read_artifact` to `coach.verification_provider`.
Artifacts are removed in `finally`, on cancellation and on stop. Evidence retains
only summaries and opaque references. A verifier must actually check image/work
criteria and freshness; relabeling a model assertion as `VERIFIER_RESULT` violates
the shared contract even if a dataclass constructor accepts it.

`subscribe_events(callback)` and `subscribe_notifications(callback)` return
idempotent unsubscribe functions. Events are shared `CoachingEvent` records for
session changes, proposed steps, replies and assessments; proposed steps never
establish correctness. Notifications use `tutorial.timeout` or
`tutorial.request_failed` with UI-safe messages. All calls/events occur on the
Qt/qasync thread; marshal external-thread calls to that thread in integration.
Listeners are isolated from each other's exceptions. Consumers check session ID,
request ID and token, allowing matching terminal session events after cancellation.
`await coach.aclose()` cancels and awaits outstanding service work and clears
event subscribers. The service never creates a global QApplication.

## Fetch safety and limits

HTTP(S) public destinations only, standard ports, no credentials, local names or
private/reserved IPs. All DNS answers are checked before every redirect/request.
Connections pin a validated IP while retaining the original Host/SNI/certificate
validation, preventing a second DNS lookup. Environment proxies, cookies, browser
credentials and subresource fetching are absent. HTTPS downgrade redirects fail.
No source scripts, downloads, tools or desktop actions are executed. Authorization
errors and payment responses are reported without bypass attempts.

Defaults: 15 seconds total fetch, 4 redirects, 2 MB response, 60,000 extracted
characters, 800 content blocks, 40 proposed steps, 60 seconds per coach operation,
8 screens and 12 MB aggregate JPEG input. The default stdlib HTTP transport runs
off the UI thread with socket timeouts and a watchdog. Cancellation stops result
delivery immediately; a blocking resolver/socket worker may wind down up to its
bounded timeout. No automatic retry. No conversation, page, screenshot, or audio
archive is created. Only current plan, completion labels and assessment summaries
remain in process memory. Provider-side retention remains the provider's policy.

## Unsupported and extension cases

- JavaScript-only pages, authenticated pages, paywall bypass, remote PDF/document URLs,
  nonstandard ports, compressed responses despite requesting identity encoding,
  very large tutorials, and multi-page crawling are unsupported.
- Known YouTube/Vimeo URLs, video-tag pages and recognized video embeds require
  actual transcripts. There is no bundled transcript retrieval integration.
  `transcripts.transcript(url)` may supply a permitted transcript; otherwise paste
  one in the widget. For other video services select the Video URL checkbox.
  There is no title/description-based video inference, video download or ASR.
- HTML extraction is intentionally heuristic, preferring article/main content,
  excluding navigation, scripts, forms and explicitly hidden elements. It does
  not render CSS, infer all visibility rules, or establish tutorial correctness.
- Screen comparisons are model suggestions. Independent verification needs an
  application-specific injected verifier. No live desktop, physical voice,
  external URL or GPU model smoke test was performed.

Future possibilities include rendered-page extraction, permitted transcript
adapters, application-specific screen verifiers and screenshot-grounded pointing.
They are extension points, not bundled working behavior.

## Validation

From `curio-py`, run the owned mocked/offscreen tests and scoped lint:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_tutorial_coach*.py -q
.venv/Scripts/python.exe -m ruff check curio/tutorial_coach tests/test_tutorial_coach*.py
```

PowerShell native argument glob expansion differs by host; list the five test
filenames explicitly if your runner does not expand the wildcard. Tests cover
extraction/provenance, unsafe destinations/redirects/DNS, pinned transport,
inaccessible/unsupported pages, missing/pasted/injected transcripts, timeouts,
malicious text boundaries, ordered plan editing, lifecycle and cancellation,
screen mismatch/uncertainty, model claims versus independent evidence, ephemeral
artifacts, shared provider/event wiring and actual Qt widget controls.

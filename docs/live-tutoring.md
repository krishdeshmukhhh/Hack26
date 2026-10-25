# Live tutoring integration

Application wiring now exists through CoachingRuntime, CoachingWindow and the
tray's Live integral tutor entry. See coaching-integration.md and RUNNING.md.
The isolated package interfaces and supported mathematics below remain the same;
host recognition/question callbacks use the existing configured provider.

This isolated introductory slice verifies indefinite polynomial substitution
integrals with exact rational arithmetic. No model supplies correctness verdicts.
The shared contract appeared during implementation and was reviewed. The
`curio.live_tutoring.contract.TutoringProvider` adapter implements its async
coaching/verification signatures and synchronous event subscriptions. Instantiate
one per session, then call `open(session, integrand, context=context)`. Use its
active `session` snapshot in subsequent calls, fresh request and work IDs, and
explicit assistance levels. Assessments carry exact-verifier evidence attributed
to the submitted work revision. Coaching replies never establish success.
`cancel()` emits a terminal session event. The provider itself creates no tasks;
capture tasks belong to the widget/host. The adapter supports active/cancelled
sessions; CoachingRuntime and CoachingWindow own application shutdown orchestration.

Instantiate `curio.live_tutoring.TutoringService`, then import
`TutoringWidget` from `curio.live_tutoring.widget` and embed it in a host window.
The application already embeds it through CoachingWindow, connects voice routing
through CoachingRuntime/CompanionManager, and exposes the tray entry. Configured
provider callbacks supply questions/recognition; no separate tutor config is needed.

Enter an **integrand**, rather than integral notation, for example
`2*x*(x^2+1)^2`. Submit one equation at a time:

1. `u=x^2+1`
2. `du=2*x*dx`
3. `I=u^2` (I denotes the integrand in u, with du implicit)
4. `F=u^3/3+C`
5. `F=(x^2+1)^3/3+C`

The workspace retains the problem, all attempts, feedback, questions and help.
Every assessment uses the shared `AssessmentStatus`: `confirmed`, `incorrect`,
`needs_clarification`, or `unsupported`. The widget displays these labels
explicitly. Missing context or incomplete equations require clarification;
supported mathematical mismatches are incorrect; unavailable mathematics is
unsupported. Completion and independent demonstration are separate metadata,
never additional assessment statuses.
After a verified final answer, it offers a related problem without a solution.
The **Start related unassisted problem** button (service: `start_practice()`)
starts that problem while keeping the previous transcript visible. Practice
records intermediate work without coaching, disables hints and voice advice,
and verifies only the final `F=...+C` by differentiation. Starting a normal
problem restores assistance. Practice completion offers another related problem;
neither the offer nor starting it is evidence of mastery.

Guided completion and independent demonstration are separate outcomes. Final
feedback exposes `completion_kind` (`guided_completion` or
`independent_demonstration`), and the service retains immutable `completions`
records with the problem, submitted answer and attempt history. The workspace's
progress label reports the distinction across the service's in-memory problems.
Only a verified final answer in unassisted practice establishes independent
demonstration on that specific problem. Guided steps, worked examples, opening
practice and the derivative recall check cannot establish it. Practice retries
remain in the record. This is evidence of performance without in-app coaching,
not a claim about outside assistance or broader mastery. Shared assessments keep
their existing statuses; their rationale conveys the completion distinction.
The first supported error blocks that transition. A corrected attempt can advance;
changing u clears downstream accepted work. Help advances from a hint through an
explanation to a worked next equation. A derivative transfer check asks the student
to independently reproduce the chain-rule factor. This checks a specific skill,
not general conceptual mastery. Sessions remain in memory only.

## Injection boundaries

`TutoringService(checker=..., capture=..., recognize=...)` accepts a synchronous
checker `(expression, variable) -> {integer_power: Fraction}` and two asynchronous
callbacks: `capture() -> images`, `recognize(images) -> str`. Capture output is
opaque, so the host can adapt the existing `capture_all` screenshot records and
its chosen vision provider. Recognition must return one equation; it is untrusted
text and never assessed until `confirm_equation(edited_text)` is explicitly called.
The widget exposes an editable confirmation field. Cancellation, restart and close
invalidate pending captures; generation checks discard late callback results.
Use qasync for the widget's capture operation. Callback adapters own timeouts,
provider credentials, capture visibility, and any resource cleanup.

`TutoringWidget(..., voice_callback=callback)` invokes the synchronous callback
as `(transcript, service) -> display_text`. Connect the host transcription client's
`final_transcript` signal to `widget.submit_voice_question`. Questions are not
automatically parsed as steps. The host may schedule its existing voice/provider
pipeline from this callback and own its cancellation and TTS. Model advice is not
a symbolic verdict. No pointing commands are generated: there is no verified
screen coordinate for typed equations. Existing POINT mapping remains host-owned.

## Supported mathematics and limits

Expressions use explicit `*`, integer constants, rational division by nonzero
constants, parentheses, unary signs and nonnegative integer powers (`^` or `**`).
Input powers are bounded to 12, total polynomial degree to 32, expression length
to 256 and AST size to 100 nodes. Parsing uses an AST allowlist with no evaluation.
Polynomial identities use exact coefficients, not numeric samples. Changes of
variables are checked by composition and multiplication by u'(x); antiderivatives
are checked by differentiation. Equivalent expanded/factored answers and numeric
additive offsets are accepted. The final answer must use x and retain a free
additive constant `C`; it may appear first, last, scaled or negated (for example
`C+x^2`, `x^2-C+7`, or `(2*x^2+C)/2`). A specific numeric constant or cancelling
`C-C` does not represent the full family. Variable-dependent `C` terms and
nonlinear expressions in C are explicitly unsupported.

All supported integrands, substitutions and antiderivatives are polynomials
defined for every real x (and every real u). The workspace displays this domain.
The checker does not cancel variable denominators or erase holes in a domain:
even `(x^2-1)/(x-1)` is unsupported. Logarithmic, radical and rational domain
conditions and interval-dependent constants require a future checker adapter;
no verdict about such domains is inferred from an LLM or point samples.

Trigonometry, logarithms, variable denominators, radicals, definite integrals,
implicit multiplication, LaTeX and multi-equation submissions are unsupported and
receive no correctness claim. A chosen substitution can be recorded even when it
does not admit a polynomial rewrite; worked help then says so. OCR accuracy, live
audio, physical screen capture and provider behavior require host integration tests.

Run `python -m pytest tests/test_live_tutoring.py` from `curio-py` for exact-math,
error recovery, hint progression, confirmation, stale-capture and offscreen Qt tests.

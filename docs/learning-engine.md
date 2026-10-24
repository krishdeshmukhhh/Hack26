# Learning engine

`curio.learning.RuleBasedLearningEngine` implements `LearningEngine` from
`curio.memory_contract`. It is independent of Qt, storage, and model providers.
All results are pending proposals; callers own approval, persistence and events.

Inject an async `snapshot_provider` returning current records (including pending
ones) to deduplicate against storage. Without it, callers must use
`resolve_contradictions` against their current snapshot before persisting.
`process_explicit_feedback` handles durable preferences and `Remember ...` commands.
Temporary instructions and ambiguous feedback produce no durable proposal.
`update_preferences` and `resolve_contradictions` return replacement proposals
with advisory superseded IDs. Approval and retirement must use the normal contract
workflow. Fact contradiction detection is deliberately limited to direct negation.

`propose_forgetting` returns IDs for deletion approval, never deletes records.
“Forget that preference” requires `ExplicitFeedback.memory_id`; an exact content
match or “forget everything” can also select records. A plain learning call returns
no new memories for forgetting commands.

Automatic learning requires enabled settings and policy `propose`. Three distinct
`source_id` values supporting the same preference are required by default; retries
do not add evidence. Missing IDs produce no inferred proposals. Assistant text is
never evidence. Signals are bounded session state, not persisted user history;
call `reset_signals` when disabling learning, forgetting, or changing profiles.
The optional injected inference callback runs only after repeated evidence and can
refine that same preference. No inference or network client is configured by default.

`LearningPolicy` controls confidence threshold (default .8), repetition threshold,
tracked signals and proposal count. Explicit feedback scores .98, repeated signals
.85. Thresholds filter proposals; confidence never grants approval.

`adaptive_values` uses approved, unexpired preferences only. Priority is constructor
`explicit_preferences` > explicit feedback/user entries > automatic entries; ties
use latest update time then ID. Supported values are `response.verbosity`:
`short`/`long`, and `interaction.frequency`: `low`/`high`. `AdaptiveBounds` configures
each normalized output range within [0, 1]; unknown values use the midpoint.
Consumers decide whether adaptation is enabled and how these normalized values map
to actual behavior. This engine does not change application settings.

`rank_relevance` provides deterministic lexical ranking of approved, live records;
ties use source priority, confidence and ID. The retrieval branch still owns prompt
formatting, injection and token-budget enforcement.

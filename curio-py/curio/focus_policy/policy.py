"""Adaptive check-in policy: when to step in during a focus session, and how.

Implements focus_contract.FocusPolicy. Rules and evidence are in
docs/focus-learning-research.md (sections C, D, E, F); the design is in
docs/focus-policy.md. Nothing here ever blocks an app or site, strict mode
included: strict only shortens the spacing between check-ins.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta, tzinfo

from curio.focus_contract import (
    BreakStyle,
    FocusPlan,
    FocusSignal,
    IfThenPlan,
    Intervention,
    InterventionKind,
    InterventionResponse,
    ModelCall,
    ResumeNote,
    SignalKind,
)

from . import wording
from .wording import CHOICES, METACOGNITIVE_TEMPLATES, NEW_STYLE_NOTICE, PLAN_ONLY_TEMPLATES

Clock = Callable[[], datetime]

# Spoken drift interventions: these count against the hourly limit and back off
# when ignored. Ambient cues are silent and don't count.
SPOKEN_NUDGES = frozenset({InterventionKind.CHECK_IN, InterventionKind.PLAN_REMINDER})

RATIONALE: dict[InterventionKind, str] = {
    InterventionKind.AMBIENT_CUE: "C",
    InterventionKind.CHECK_IN: "C",
    InterventionKind.PLAN_REMINDER: "A",
    InterventionKind.RESUME: "D",
    InterventionKind.BREAK_START: "E",
    InterventionKind.BREAK_END: "E",
    InterventionKind.METACOGNITIVE: "F",
    InterventionKind.REFLECTION: "F",
}

EXPIRES_AFTER: dict[InterventionKind, timedelta] = {
    InterventionKind.AMBIENT_CUE: timedelta(seconds=20),
    InterventionKind.CHECK_IN: timedelta(seconds=30),
    InterventionKind.PLAN_REMINDER: timedelta(seconds=30),
    InterventionKind.RESUME: timedelta(seconds=20),
    InterventionKind.BREAK_START: timedelta(seconds=45),
    InterventionKind.BREAK_END: timedelta(seconds=45),
    InterventionKind.METACOGNITIVE: timedelta(seconds=60),
    InterventionKind.REFLECTION: timedelta(seconds=120),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class QuietHours:
    """A daily window with no spoken interventions; may wrap past midnight."""

    start: time
    end: time
    tz: tzinfo | None = None  # None: the machine's local time zone

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.tz).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


@dataclass(frozen=True, kw_only=True)
class PolicySettings:
    max_spoken_per_hour: int = 3
    rung_spacing: timedelta = timedelta(seconds=60)  # between ladder rungs
    strict_spacing_factor: float = 0.5  # strict mode: shorter spacing, never blocking
    breakpoint_cap: timedelta = timedelta(minutes=2)  # longest wait for a breakpoint
    snooze: timedelta = timedelta(minutes=10)
    quiet_hours: tuple[QuietHours, ...] = ()
    max_backoff: float = 8.0  # cap on false-alarm and ignored multipliers
    self_paced_stretch: timedelta = timedelta(minutes=50)  # unbroken work before suggesting
    break_decline_cooldown: timedelta = timedelta(minutes=15)  # after "keep going"
    rephrase_timeout_seconds: float = 4.0


@dataclass
class _Episode:
    """One drift: from DRIFT_STARTED until RETURNED (or a break)."""

    app: str
    title: str
    started_at: datetime
    eligible_at: datetime  # earliest time for the next rung
    rung: int = 0  # rungs delivered so far
    stopped: bool = False  # learner dismissed or said "not a distraction"
    false_alarm: bool = False


class AdaptiveFocusPolicy:
    """Decides on interventions from FocusSignals; never blocks anything.

    F4 calls ``start_session`` once, ``decide`` for every signal,
    ``record_response`` when the learner answers (or the intervention expires,
    as IGNORED), and ``reflection_prompt`` after the session ends. ``rephrase``
    optionally rewords an intervention through the injected model.
    """

    def __init__(
        self,
        *,
        clock: Clock = _utc_now,
        settings: PolicySettings | None = None,
        interaction_frequency: float | Callable[[], float] = 0.5,
        model: ModelCall | None = None,
        seen_variants: Iterable[str] = (),
    ) -> None:
        self._clock = clock
        self._settings = settings or PolicySettings()
        self._interaction_frequency = interaction_frequency
        self._model = model
        self._messages = wording.MessageBook(seen_variants)
        # Learner-level state, kept across sessions.
        self._spoken_times: deque[datetime] = deque()
        self._false_alarms: dict[str, int] = {}
        self._consecutive_ignored = 0
        self._snoozed_until: datetime | None = None
        self._intervention_apps: dict[str, str] = {}
        # Session-level state.
        self._plan_id: str | None = None
        self._reset_session(None)

    # --- FocusPolicy -------------------------------------------------------------

    def decide(self, signal: FocusSignal, plan: FocusPlan) -> Intervention | None:
        if plan.id != self._plan_id:
            self._reset_session(plan)
        now = self._clock()
        self._update_episode_app(signal)
        match signal.kind:
            case SignalKind.DRIFT_STARTED:
                return self._on_drift_started(signal, plan, now)
            case SignalKind.DRIFT_CONTINUING:
                return self._escalate(plan, now, at_breakpoint=False)
            case SignalKind.BREAKPOINT:
                if self._episode is not None:
                    return self._escalate(plan, now, at_breakpoint=True)
                return self._maybe_halfway(plan, now) or self._maybe_self_paced_break(plan, now)
            case SignalKind.RETURNED:
                return self._on_returned(plan, now)
            case SignalKind.BREAK_DUE:
                return self._suggest_break(plan, now)
            case SignalKind.BREAK_OVER:
                return self._end_break(plan, now)
            case SignalKind.SESSION_ENDING:
                return self._on_session_ending(plan, now)
        return None

    def record_response(self, intervention: Intervention, response: InterventionResponse) -> None:
        now = self._clock()
        app = self._intervention_apps.get(intervention.id)
        episode = self._episode
        if response is InterventionResponse.SNOOZED:
            self._snoozed_until = now + self._settings.snooze
        if response is InterventionResponse.FALSE_ALARM and app is not None:
            self._false_alarms[app] = self._false_alarms.get(app, 0) + 1
            if episode is not None and episode.app == app:
                episode.stopped = True
                episode.false_alarm = True
        if intervention.kind in SPOKEN_NUDGES:
            if response is InterventionResponse.IGNORED:
                self._consecutive_ignored += 1
            else:
                self._consecutive_ignored = 0
            if response is InterventionResponse.DISMISSED and episode is not None:
                episode.stopped = True
        if intervention.kind is InterventionKind.BREAK_START:
            if response is InterventionResponse.ACCEPTED:
                self.begin_break()
            elif response is InterventionResponse.DISMISSED:
                self._break_declined_at = now

    def resume_note(self) -> ResumeNote | None:
        return self._note

    def set_resume_note(self, note: ResumeNote) -> None:
        """Store a note (for example one the learner spoke); only the newest is kept."""
        self._note = note

    # --- Session lifecycle and context --------------------------------------------

    def start_session(self, plan: FocusPlan) -> Intervention:
        """Reset for a new plan and return the planning prompt (section F)."""
        self._reset_session(plan)
        self._session_start = self._clock()
        return self._metacognitive(plan, "start", self._session_start)

    def reflection_prompt(self, plan: FocusPlan) -> Intervention:
        """End-of-session reflection ("what got in the way today?")."""
        now = self._clock()
        self._episode = None
        self._on_break = False
        return self._emit(self._intervention(InterventionKind.REFLECTION, plan, now))

    def set_context(
        self, *, where: str, next_action: str = "", source: str = "walkthrough"
    ) -> None:
        """Latest "where you are / what's next", used for the next automatic resume note."""
        self._context = ResumeNote(
            where=where, next_action=next_action, source=source, at=self._clock()
        )

    def begin_break(self) -> None:
        """The learner started a break (accepted a suggestion or chose one themselves)."""
        if self._plan is not None:
            self._capture_resume_note(self._plan, self._clock())
        self._on_break = True
        self._episode = None

    def set_interaction_frequency(self, value: float | Callable[[], float]) -> None:
        self._interaction_frequency = value

    async def rephrase(self, intervention: Intervention) -> Intervention:
        """Reword through the model when one is set; the template is the fallback."""
        if self._model is None or not intervention.message:
            return intervention
        notice = NEW_STYLE_NOTICE if intervention.message.startswith(NEW_STYLE_NOTICE) else ""
        body = intervention.message.removeprefix(notice)
        text = await wording.rephrase(
            self._model, body, timeout_seconds=self._settings.rephrase_timeout_seconds
        )
        if text == body:
            return intervention
        return replace(intervention, message=notice + text)

    @property
    def drifting(self) -> bool:
        return self._episode is not None

    @property
    def on_break(self) -> bool:
        return self._on_break

    @property
    def seen_variants(self) -> frozenset[str]:
        return self._messages.seen_variants

    # --- Drift ladder ----------------------------------------------------------------

    def _on_drift_started(
        self, signal: FocusSignal, plan: FocusPlan, now: datetime
    ) -> Intervention | None:
        if self._on_break or self._episode is not None:
            return None
        sample = signal.sample
        app = sample.app if sample is not None else ""
        # Apps with false alarms wait longer before even the ambient cue.
        delay = self._base_spacing(plan) * (self._app_backoff(app) - 1)
        self._episode = _Episode(
            app=app,
            title=sample.window_title if sample is not None else "",
            started_at=now,
            eligible_at=now + delay,
        )
        self._capture_resume_note(plan, now)
        return self._escalate(plan, now, at_breakpoint=False)

    def _escalate(
        self, plan: FocusPlan, now: datetime, *, at_breakpoint: bool
    ) -> Intervention | None:
        episode = self._episode
        if episode is None or episode.stopped or self._on_break:
            return None
        ladder = self._ladder(plan, episode)
        if episode.rung >= len(ladder) or now < episode.eligible_at or self._snoozed(now):
            return None
        kind = ladder[episode.rung]
        if kind is not InterventionKind.AMBIENT_CUE:
            # Vulnerable and receptive: wait for a breakpoint, up to the cap.
            if not at_breakpoint and now < episode.eligible_at + self._settings.breakpoint_cap:
                return None
            if self._quiet(now) or self._spoken_last_hour(now) >= self._hourly_limit():
                return None
        intervention = self._intervention(
            kind, plan, now, if_then=self._matching_plan(plan, episode)
        )
        episode.rung += 1
        episode.eligible_at = now + self._spacing(plan, episode.app)
        return self._emit(intervention, app=episode.app)

    def _ladder(self, plan: FocusPlan, episode: _Episode) -> tuple[InterventionKind, ...]:
        ladder = (InterventionKind.AMBIENT_CUE, InterventionKind.CHECK_IN)
        if self._matching_plan(plan, episode) is not None:
            ladder += (InterventionKind.PLAN_REMINDER,)
        return ladder

    @staticmethod
    def _matching_plan(plan: FocusPlan, episode: _Episode) -> IfThenPlan | None:
        title = episode.title.casefold()
        for if_then in plan.if_then:
            for cue in if_then.cue_apps:
                key = cue.casefold()
                if key and (key == episode.app.casefold() or key in title):
                    return if_then
        return None

    def _update_episode_app(self, signal: FocusSignal) -> None:
        if self._episode is not None and signal.sample is not None:
            self._episode.app = signal.sample.app
            self._episode.title = signal.sample.window_title

    def _on_returned(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        episode, self._episode = self._episode, None
        note = self._note
        if episode is None or episode.false_alarm or self._on_break or note is None:
            return None
        if note is self._last_read_note or self._quiet(now):
            return None
        self._last_read_note = note
        return self._emit(self._intervention(InterventionKind.RESUME, plan, now), app=episode.app)

    # --- Resume notes ------------------------------------------------------------

    def _capture_resume_note(self, plan: FocusPlan, now: datetime) -> None:
        """Newest of: the learner's own note, the latest context, else the plan goal."""
        context, existing = self._context, self._note
        if context is not None and (existing is None or context.at > existing.at):
            self._note = replace(context, at=now)
        elif existing is None:
            self._note = ResumeNote(where=plan.goal, next_action="", source="plan", at=now)

    # --- Breaks ------------------------------------------------------------------

    def _suggest_break(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        if plan.break_style is BreakStyle.NONE or self._on_break:
            return None
        if self._snoozed(now) or self._quiet(now):
            return None
        declined = self._break_declined_at
        if declined is not None and now - declined < self._settings.break_decline_cooldown:
            return None
        if plan.break_style is BreakStyle.SELF_PACED:
            since = self._last_break_end or self._session_start or plan.started_at
            if now - since < self._settings.self_paced_stretch:
                return None
        return self._emit(self._intervention(InterventionKind.BREAK_START, plan, now))

    def _maybe_self_paced_break(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        if plan.break_style is not BreakStyle.SELF_PACED:
            return None  # fixed breaks come from BREAK_DUE
        return self._suggest_break(plan, now)

    def _end_break(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        if not self._on_break:
            return None
        self._on_break = False
        self._last_break_end = now
        if self._quiet(now):
            return None
        if self._note is None:
            self._capture_resume_note(plan, now)
        self._last_read_note = self._note
        return self._emit(self._intervention(InterventionKind.BREAK_END, plan, now))

    # --- Metacognitive prompts ---------------------------------------------------

    def _maybe_halfway(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        if self._halfway_done or self._on_break or self._episode is not None:
            return None
        start = self._session_start or plan.started_at
        elapsed = now - start
        if not plan.duration / 2 <= elapsed < plan.duration:
            return None
        if self._snoozed(now) or self._quiet(now):
            return None
        self._halfway_done = True
        return self._metacognitive(plan, "halfway", now)

    def _on_session_ending(self, plan: FocusPlan, now: datetime) -> Intervention | None:
        if self._ending_done or self._on_break or self._episode is not None:
            return None
        if self._quiet(now):
            return None
        self._ending_done = True
        return self._metacognitive(plan, "ending", now)

    def _metacognitive(self, plan: FocusPlan, phase: str, now: datetime) -> Intervention:
        message = self._messages.render(
            InterventionKind.METACOGNITIVE,
            {"goal": plan.goal},
            variants=METACOGNITIVE_TEMPLATES[phase],
            family=phase,
        )
        return self._emit(self._make(InterventionKind.METACOGNITIVE, message, now))

    # --- Building interventions ------------------------------------------------------

    def _intervention(
        self,
        kind: InterventionKind,
        plan: FocusPlan,
        now: datetime,
        *,
        if_then: IfThenPlan | None = None,
    ) -> Intervention:
        if kind is InterventionKind.AMBIENT_CUE:
            return self._make(kind, "", now)  # pet animation only, nothing spoken
        fields = {"goal": plan.goal}
        variants: tuple[str, ...] | None = None
        family = ""
        if kind is InterventionKind.PLAN_REMINDER and if_then is not None:
            fields |= {"cue": if_then.cue, "response": if_then.response}
        if kind in (InterventionKind.RESUME, InterventionKind.BREAK_END):
            note = self._note or ResumeNote(where=plan.goal, next_action="", source="plan")
            fields |= {"where": note.where, "next": note.next_action}
            if not note.next_action:
                variants, family = PLAN_ONLY_TEMPLATES[kind], "plan"
        message = self._messages.render(kind, fields, variants=variants, family=family)
        return self._make(kind, message, now)

    @staticmethod
    def _make(kind: InterventionKind, message: str, now: datetime) -> Intervention:
        return Intervention(
            kind=kind,
            message=message,
            choices=CHOICES[kind],
            rationale=RATIONALE[kind],
            expires_after=EXPIRES_AFTER[kind],
            at=now,
        )

    def _emit(self, intervention: Intervention, *, app: str | None = None) -> Intervention:
        if app is not None:
            self._intervention_apps[intervention.id] = app
        if intervention.kind in SPOKEN_NUDGES:
            self._spoken_times.append(intervention.at)
        return intervention

    # --- Limits and pacing -------------------------------------------------------------

    def _frequency(self) -> float:
        value = self._interaction_frequency
        raw = value() if callable(value) else value
        return min(1.0, max(0.0, float(raw)))

    def _frequency_factor(self) -> float:
        """0.5 (frequency 0) to 1.5 (frequency 1); 1.0 at the default 0.5."""
        return 0.5 + self._frequency()

    def _hourly_limit(self) -> int:
        return max(1, round(self._settings.max_spoken_per_hour * self._frequency_factor()))

    def _spoken_last_hour(self, now: datetime) -> int:
        while self._spoken_times and now - self._spoken_times[0] >= timedelta(hours=1):
            self._spoken_times.popleft()
        return len(self._spoken_times)

    def _base_spacing(self, plan: FocusPlan) -> timedelta:
        spacing = self._settings.rung_spacing / self._frequency_factor()
        if plan.strict:
            spacing *= self._settings.strict_spacing_factor
        return spacing

    def _spacing(self, plan: FocusPlan, app: str) -> timedelta:
        ignored = min(self._settings.max_backoff, 2.0**self._consecutive_ignored)
        return self._base_spacing(plan) * self._app_backoff(app) * ignored

    def _app_backoff(self, app: str) -> float:
        return min(self._settings.max_backoff, 2.0 ** self._false_alarms.get(app, 0))

    def _snoozed(self, now: datetime) -> bool:
        return self._snoozed_until is not None and now < self._snoozed_until

    def _quiet(self, now: datetime) -> bool:
        return any(window.contains(now) for window in self._settings.quiet_hours)

    def _reset_session(self, plan: FocusPlan | None) -> None:
        self._plan = plan
        self._plan_id = plan.id if plan is not None else None
        self._session_start: datetime | None = None
        self._episode: _Episode | None = None
        self._on_break = False
        self._last_break_end: datetime | None = None
        self._break_declined_at: datetime | None = None
        self._halfway_done = False
        self._ending_done = False
        self._context: ResumeNote | None = None
        self._note: ResumeNote | None = None
        self._last_read_note: ResumeNote | None = None

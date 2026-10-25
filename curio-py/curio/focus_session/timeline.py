"""Live on-goal / drifting / break timeline for self-monitoring (section F).

Plain data, no Qt. Time between two observations belongs to the state that
was current at the start of the gap. Drift is only what the drift tracker
called sustained drift; a quick lookup stays on goal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class TimelineState(StrEnum):
    ON_GOAL = "on_goal"
    DRIFTING = "drifting"
    BREAK = "break"


@dataclass
class Segment:
    state: TimelineState
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


class SessionTimeline:
    def __init__(self, started_at: datetime) -> None:
        self.started_at = started_at
        self.segments: list[Segment] = [Segment(TimelineState.ON_GOAL, started_at, started_at)]

    @property
    def state(self) -> TimelineState:
        return self.segments[-1].state

    @property
    def now(self) -> datetime:
        return self.segments[-1].end

    def observe(self, at: datetime) -> None:
        """Extend the current state up to ``at``; earlier times are ignored."""
        if at > self.segments[-1].end:
            self.segments[-1].end = at

    def set_state(self, state: TimelineState, at: datetime) -> None:
        self.observe(at)
        last = self.segments[-1]
        if state == last.state:
            return
        if last.seconds == 0:
            last.state = state
            self.segments = _merged(self.segments)
        else:
            self.segments.append(Segment(state, last.end, last.end))

    def relabel(self, since: datetime, frm: TimelineState, to: TimelineState) -> None:
        """Turn ``frm`` time after ``since`` into ``to`` (drift found in hindsight)."""
        since = max(since, self.started_at)
        result: list[Segment] = []
        for seg in self.segments:
            if seg.state != frm or seg.end <= since:
                result.append(seg)
                continue
            if seg.start < since:
                result.append(Segment(seg.state, seg.start, since))
                result.append(Segment(to, since, seg.end))
            else:
                result.append(Segment(to, seg.start, seg.end))
        self.segments = _merged(result)

    def drift_started(self, at: datetime, drift_seconds: float) -> None:
        self.observe(at)
        self.relabel(at - timedelta(seconds=max(0.0, drift_seconds)), TimelineState.ON_GOAL,
                     TimelineState.DRIFTING)
        self.set_state(TimelineState.DRIFTING, at)

    def unmark_latest_drift(self) -> bool:
        """The learner said it wasn't a distraction: the last drift run counts as on goal."""
        for index in range(len(self.segments) - 1, -1, -1):
            if self.segments[index].state == TimelineState.DRIFTING:
                self.segments[index].state = TimelineState.ON_GOAL
                self.segments = _merged(self.segments)
                return True
        return False

    def totals(self) -> dict[TimelineState, float]:
        totals = dict.fromkeys(TimelineState, 0.0)
        for seg in self.segments:
            totals[seg.state] += seg.seconds
        return totals

    @property
    def total_seconds(self) -> float:
        return max(0.0, (self.now - self.started_at).total_seconds())


def _merged(segments: list[Segment]) -> list[Segment]:
    """Join neighbours in the same state; a zero-length tail keeps the current state."""
    merged: list[Segment] = []
    for seg in segments:
        if merged and merged[-1].state == seg.state:
            merged[-1].end = max(merged[-1].end, seg.end)
        elif merged and merged[-1].seconds == 0:
            merged[-1] = Segment(seg.state, merged[-1].start, seg.end)
        else:
            merged.append(Segment(seg.state, seg.start, seg.end))
    return merged

"""Activity sensing, on/off-goal classification and drift tracking (focus mode).

Implements the sensing half of ``curio.focus_contract``: an ActivitySource
that samples the foreground app, title and idle time; a TrackClassifier that
judges each sample against the FocusPlan (user corrections, rules, then an
optional model); and a DriftTracker that turns judgments into FocusSignals.
Evidence for each rule is in docs/focus-learning-research.md, sections B and C.
Nothing here records keystroke content: input is only ever counted.
"""

from curio.focus_sensing.activity import (
    FakeActivitySource,
    RawActivity,
    WindowsActivitySource,
    scripted_samples,
)
from curio.focus_sensing.classifier import RuleFirstClassifier
from curio.focus_sensing.corrections import SQLiteCorrectionStore, title_pattern
from curio.focus_sensing.cycle import BreakPhase, break_phase
from curio.focus_sensing.drift import DriftThresholds, DriftTotals, ThresholdDriftTracker

__all__ = [
    "BreakPhase",
    "DriftThresholds",
    "DriftTotals",
    "FakeActivitySource",
    "RawActivity",
    "RuleFirstClassifier",
    "SQLiteCorrectionStore",
    "ThresholdDriftTracker",
    "WindowsActivitySource",
    "break_phase",
    "scripted_samples",
    "title_pattern",
]

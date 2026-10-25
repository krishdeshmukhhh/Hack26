"""Skills window: the "skill map" of what Curio thinks this user knows.

Construct on the Qt/qasync thread with a SkillModel. Concepts are grouped by
the apps they were practiced in, each with a mastery bar; selecting one shows
the evidence behind it ("why?"), and every skill can be reset. Call
``refresh()`` after a walkthrough is observed; if the model has
``subscribe(callback)`` (``SqliteSkillModel`` does) the window does this itself
while shown. Optional model extras (``evidence``, ``reset_concept``,
``export_data``, ``graph``) light up the matching controls.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curio.design_system import DS
from curio.learning_contract import AssistanceLevel, SkillModel, SkillState, StepOutcome
from curio.skills.model import DEFAULT_PARAMS, assistance_for

MASTERY_ROLE = Qt.ItemDataRole.UserRole + 1
CONCEPT_ROLE = Qt.ItemDataRole.UserRole + 2

_BAND_COLORS = {
    AssistanceLevel.NONE: DS.Colors.accent_green,
    AssistanceLevel.HINTED: DS.Colors.accent_blue,
    AssistanceLevel.POINTED: DS.Colors.accent_amber,
    AssistanceLevel.DID_IT: DS.Colors.error_red,
}
_BAND_TEXT = {
    AssistanceLevel.NONE: "Estimated familiar — less guidance suggested",
    AssistanceLevel.HINTED: "Getting there — Curio gives a hint",
    AssistanceLevel.POINTED: "Learning — Curio points at each step",
    AssistanceLevel.DID_IT: "More support suggested — ask for step-by-step guidance",
}
_ASSISTANCE_TEXT = {
    AssistanceLevel.NONE: "on your own",
    AssistanceLevel.HINTED: "with a hint",
    AssistanceLevel.POINTED: "with pointing",
    AssistanceLevel.DID_IT: "done by Curio",
}
_OUTCOME_TEXT = {
    StepOutcome.SUCCEEDED: "Model reported progress",
    StepOutcome.RETRIED: "Had to retry",
    StepOutcome.TIMED_OUT: "Timed out",
    StepOutcome.ABANDONED: "Stopped",
}
_UNPRACTICED = "Not yet practiced"


def _relative(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "Never"
    days = (now - value).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    return value.astimezone().strftime("%b %d, %Y")


def _dot(color: str, size: int = 10) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return QIcon(pixmap)


def _title(text: str) -> str:
    return text[:1].upper() + text[1:]


class MasteryBarDelegate(QStyledItemDelegate):
    """Rounded mastery bar coloured by the advice band, with a percentage."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        mastery = index.data(MASTERY_ROLE)
        if mastery is None:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(DS.Colors.info_bg))
        rect = QRectF(option.rect).adjusted(DS.Spacing.sm, 0, -DS.Spacing.sm, 0)
        label_width = 40.0
        track = QRectF(rect.left(), rect.center().y() - 4, rect.width() - label_width, 8)
        path = QPainterPath()
        path.addRoundedRect(track, 4, 4)
        painter.fillPath(path, QColor(DS.Colors.border))
        fill = QRectF(track)
        fill.setWidth(max(track.height(), track.width() * float(mastery)))
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill, 4, 4)
        painter.fillPath(fill_path, QColor(_BAND_COLORS[assistance_for(float(mastery))]))
        painter.setPen(QColor(DS.Colors.text_primary))
        text_rect = QRectF(track.right(), rect.top(), label_width, rect.height())
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{float(mastery):.0%}",
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(max(size.width(), 160), max(size.height(), 28))


class SkillsWidget(QWidget):
    """Async view over a SkillModel. No model calls run until refresh/show.

    ``refreshed`` emits after each successful load; ``operation_finished``
    carries (operation, success). Closing cancels work and detaches from the
    model.
    """

    refreshed = Signal()
    operation_finished = Signal(str, bool)

    def __init__(
        self,
        model: SkillModel,
        parent: QWidget | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._graph = getattr(model, "graph", None)
        self._params = getattr(model, "params", DEFAULT_PARAMS)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tasks: set[asyncio.Task] = set()
        self._busy = False
        self._refresh_pending = False
        self._unsubscribe: Callable[[], None] | None = None
        self._states: dict[str, SkillState] = {}
        self._selected: str | None = None
        self.setWindowTitle("Curio — Skill map")
        self.setMinimumSize(640, 440)
        self.resize(960, 620)
        self.setFont(QFont("Segoe UI", 10))
        c = DS.Colors
        self.setStyleSheet(
            f"QWidget {{ background: {c.panel_bg}; color: {c.text_primary};"
            f" font-family: 'Segoe UI'; }}"
            f"QTreeWidget, QListWidget {{ background: {c.surface}; border: 1px solid {c.border};"
            f" border-radius: {DS.CornerRadius.small}px; padding: {DS.Spacing.xs}px; }}"
            f"QTreeWidget::item, QListWidget::item {{ padding: {DS.Spacing.xs}px; }}"
            f"QTreeWidget::item:selected, QListWidget::item:selected"
            f" {{ background: {c.info_bg}; color: {c.text_white}; }}"
            f"QHeaderView::section {{ background: {c.surface}; color: {c.text_secondary};"
            f" border: none; padding: {DS.Spacing.xs}px {DS.Spacing.sm}px; }}"
            f"QPushButton {{ background: {c.surface}; border: 1px solid {c.border};"
            f" border-radius: {DS.CornerRadius.small}px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ border-color: {c.accent_blue}; }}"
            f"QPushButton#danger:hover {{ border-color: {c.error_red}; color: {c.error_red}; }}"
            f"QWidget:disabled {{ color: {c.text_secondary}; }}"
            f"QFrame#card {{ background: {c.surface}; border: 1px solid {c.border};"
            f" border-radius: {DS.CornerRadius.medium}px; }}"
            f"QFrame#card QLabel {{ background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DS.Spacing.xl, DS.Spacing.lg, DS.Spacing.xl, DS.Spacing.lg)
        layout.setSpacing(DS.Spacing.md)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Skill map")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        titles.addWidget(title)
        subtitle = QLabel(
            "Estimates from model-reported walkthrough progress, not a knowledge test. "
            "Unmarked history has unknown origin. You can reset any estimate."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {c.text_secondary};")
        titles.addWidget(subtitle)
        self.synthetic_banner = QLabel("SIMULATED data present — estimates include demo history.")
        self.synthetic_banner.setWordWrap(True)
        self.synthetic_banner.hide()
        titles.addWidget(self.synthetic_banner)
        header.addLayout(titles, 1)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setStyleSheet(f"color: {c.text_secondary}; font-size: {DS.Fonts.size_md}px;")
        header.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setAccessibleName("Skills by app")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Concept", "Estimated mastery", "Attempts", "Last practiced"])
        self.tree.setItemDelegateForColumn(1, MasteryBarDelegate(self.tree))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(DS.Spacing.lg)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumWidth(420)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header_view = self.tree.header()
        header_view.setStretchLastSection(False)
        header_view.setMinimumSectionSize(48)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.resizeSection(1, 170)
        for col in (2, 3):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._select)
        splitter.addWidget(self.tree)

        detail = QFrame()
        detail.setObjectName("card")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(DS.Spacing.lg, DS.Spacing.lg, DS.Spacing.lg, DS.Spacing.lg)
        detail_layout.setSpacing(DS.Spacing.sm)
        self.concept_title = QLabel("Select a skill")
        self.concept_title.setTextFormat(Qt.TextFormat.PlainText)
        self.concept_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        detail_layout.addWidget(self.concept_title)
        self.concept_meta = QLabel("Pick a concept to see the evidence behind it.")
        self.concept_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.concept_meta.setWordWrap(True)
        self.concept_meta.setStyleSheet(f"color: {c.text_secondary};")
        detail_layout.addWidget(self.concept_meta)
        self.mastery_label = QLabel()
        self.mastery_label.setTextFormat(Qt.TextFormat.PlainText)
        self.mastery_label.setStyleSheet("font-size: 30px; font-weight: 600;")
        detail_layout.addWidget(self.mastery_label)
        self.band_label = QLabel()
        self.band_label.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.band_label)
        self.related_label = QLabel()
        self.related_label.setTextFormat(Qt.TextFormat.PlainText)
        self.related_label.setWordWrap(True)
        self.related_label.setStyleSheet(f"color: {c.text_secondary};")
        detail_layout.addWidget(self.related_label)
        why = QLabel("Why?")
        why.setStyleSheet(f"font-weight: 600; margin-top: {DS.Spacing.sm}px;")
        detail_layout.addWidget(why)
        self.evidence_list = QListWidget()
        self.evidence_list.setAccessibleName("Evidence for the selected skill")
        self.evidence_list.setWordWrap(True)
        self.evidence_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.evidence_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.evidence_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.evidence_list.setSpacing(2)
        detail_layout.addWidget(self.evidence_list, 1)
        self.reset_concept_button = QPushButton("Reset this skill…")
        self.reset_concept_button.setObjectName("danger")
        self.reset_concept_button.clicked.connect(self.reset_selected)
        self.reset_concept_button.setVisible(hasattr(model, "reset_concept"))
        detail_layout.addWidget(self.reset_concept_button, 0, Qt.AlignmentFlag.AlignLeft)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 400])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Export JSON…")
        self.export_button.clicked.connect(self._choose_export)
        self.reset_all_button = QPushButton("Reset all skills…")
        self.reset_all_button.setObjectName("danger")
        self.reset_all_button.clicked.connect(self.reset_all)
        self.status = QLabel("Ready.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Skill operation status")
        self.status.setStyleSheet(f"color: {c.text_secondary};")
        actions.addWidget(self.status, 1)
        for button in (self.refresh_button, self.export_button, self.reset_all_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self._show_detail(None)
        self._update_actions()

    # --- plumbing -------------------------------------------------------------

    def _message(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        color = DS.Colors.error_red if error else DS.Colors.text_secondary
        self.status.setStyleSheet(f"color: {color};")

    def _update_actions(self) -> None:
        for control in (self.refresh_button, self.export_button, self.reset_all_button):
            control.setEnabled(not self._busy)
        self.reset_concept_button.setEnabled(not self._busy and self._selected is not None)

    def _start(self, name: str, work: Callable[[], Awaitable[str]]) -> None:
        if self._busy:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._message("Skill operations require the application's qasync event loop.", True)
            self.operation_finished.emit(name, False)
            return
        self._busy = True
        self._update_actions()
        self._message(f"{name}…")

        async def run() -> None:
            try:
                message = await work()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._message(f"{name} failed. Try again.", True)
                self.operation_finished.emit(name, False)
            else:
                self._message(message)
                self.operation_finished.emit(name, True)
            finally:
                self._busy = False
                self._update_actions()
                if self._refresh_pending:
                    self._refresh_pending = False
                    self.refresh()

        task = loop.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _name(self, concept: str, app: str) -> str:
        return self._graph.name_in(concept, app) if self._graph else concept

    # --- loading ----------------------------------------------------------------

    async def _fetch(self) -> None:
        states = await self._model.snapshot()
        provenance = getattr(self._model, "has_synthetic_data", None)
        self.synthetic_banner.setVisible(bool(await provenance()) if provenance else False)
        self._states = {s.concept: s for s in states}
        now = self._clock()
        selected = self._selected
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, list[SkillState]] = {}
        for state in states:
            for app in state.apps or (_UNPRACTICED,):
                groups.setdefault(app, []).append(state)
        reselect: QTreeWidgetItem | None = None
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        for app in sorted(groups, key=lambda a: (a == _UNPRACTICED, a)):
            members = sorted(groups[app], key=lambda s: (-s.mastery, s.concept))
            group = QTreeWidgetItem([_title(app), "", "", ""])
            group.setFont(0, bold)
            group.setForeground(0, QBrush(QColor(DS.Colors.text_white)))
            group.setToolTip(0, f"{len(members)} skill{'s' * (len(members) != 1)}")
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            for state in members:
                item = QTreeWidgetItem([
                    _title(self._name(state.concept, app)), "", str(state.attempts),
                    _relative(state.last_practiced, now),
                ])
                item.setData(0, CONCEPT_ROLE, state.concept)
                item.setData(1, MASTERY_ROLE, state.mastery)
                item.setToolTip(1, f"{state.mastery:.0%} · {_BAND_TEXT[self._band(state)]}")
                group.addChild(item)
                if state.concept == selected and reselect is None:
                    reselect = item
            group.setExpanded(True)
        self.tree.blockSignals(False)
        apps = {a for s in states for a in s.apps}
        self.summary.setText(
            f"{len(states)} skill{'s' * (len(states) != 1)} · "
            f"{len(apps)} app{'s' * (len(apps) != 1)}"
        )
        if reselect is not None:
            self.tree.setCurrentItem(reselect)
        else:
            self._selected = None
            self._show_detail(None)
        if not states:
            self.concept_meta.setText(
                "No skills yet. Finish a walkthrough and Curio will start a map here."
            )

    def _band(self, state: SkillState) -> AssistanceLevel:
        return assistance_for(state.mastery, self._params)

    @Slot()
    def refresh(self) -> None:
        """Reload from the model; coalesces calls made while busy."""
        if self._busy:
            self._refresh_pending = True
            return

        async def work() -> str:
            await self._fetch()
            self.refreshed.emit()
            return f"Showing {len(self._states)} skills."

        self._start("Load skills", work)

    # --- detail -------------------------------------------------------------------

    def _select(self) -> None:
        item = self.tree.currentItem()
        concept = item.data(0, CONCEPT_ROLE) if item is not None else None
        self._selected = concept
        self._show_detail(self._states.get(concept) if concept else None)
        self._update_actions()
        if concept and hasattr(self._model, "evidence"):
            self._load_evidence(concept)

    def _show_detail(self, state: SkillState | None) -> None:
        self.evidence_list.clear()
        if state is None:
            self.concept_title.setText("Select a skill")
            self.concept_meta.setText("Pick a concept to see the evidence behind it.")
            self.mastery_label.clear()
            self.band_label.clear()
            self.related_label.clear()
            return
        apps = state.apps
        names = {self._name(state.concept, a) for a in apps} - {state.concept}
        self.concept_title.setText(
            _title(state.concept) + (f"  ({', '.join(sorted(names))})" if names else "")
        )
        last = _relative(state.last_practiced, self._clock()).lower()
        self.concept_meta.setText(
            f"Practiced in {', '.join(apps) or 'no apps yet'} · {state.attempts} attempt"
            f"{'s' * (state.attempts != 1)} · last {last}"
        )
        band = self._band(state)
        self.mastery_label.setText(f"{state.mastery:.0%}")
        self.mastery_label.setStyleSheet(
            f"font-size: 30px; font-weight: 600; color: {_BAND_COLORS[band]};"
        )
        self.band_label.setText(_BAND_TEXT[band])
        related = self._graph.related(state.concept) if self._graph else {}
        if related:
            top = sorted(related.items(), key=lambda kv: -kv[1])[:4]
            self.related_label.setText(
                "Helps with: " + ", ".join(f"{k} ({w:.0%})" for k, w in top)
            )
        else:
            self.related_label.clear()
        if not hasattr(self._model, "evidence"):
            self.evidence_list.addItem("This model doesn't keep per-step evidence.")

    def _load_evidence(self, concept: str) -> None:
        async def load() -> None:
            try:
                rows = await self._model.evidence(concept)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._message("Couldn't load the evidence for this skill.", True)
                return
            if self._selected != concept:
                return
            self.evidence_list.clear()
            if not rows:
                self.evidence_list.addItem("No evidence recorded.")
            for e in rows:
                delta = e.mastery_after - e.mastery_before
                when = e.recorded_at.astimezone().strftime("%b %d")
                hard = (
                    "" if e.difficulty is None
                    else f" · {e.difficulty:.0%} recorded stuck-event rate"
                )
                item = QListWidgetItem(
                    f"{delta:+.0%}  {_OUTCOME_TEXT[e.outcome]} {_ASSISTANCE_TEXT[e.assistance]}"
                    f" · {when}\n“{e.instruction}” — {e.task} ({e.app}, step {e.step_index})"
                    f"\nCounted at {e.weight:.0%} strength{hard}"
                )
                item.setIcon(_dot(DS.Colors.accent_green if delta >= 0 else DS.Colors.error_red))
                self.evidence_list.addItem(item)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(load())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- actions ----------------------------------------------------------------

    def _confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(
                self, title, message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def reset_selected(self) -> None:
        concept = self._selected
        if concept is None or self._busy or not hasattr(self._model, "reset_concept"):
            return
        if not self._confirm(
            "Reset this skill?",
            f"Forget everything Curio learned about “{concept}”, including its evidence?",
        ):
            return

        async def work() -> str:
            await self._model.reset_concept(concept)
            await self._fetch()
            return f"Reset “{concept}”."

        self._start("Reset skill", work)

    def reset_all(self) -> None:
        if self._busy or not self._confirm(
            "Reset all skills?",
            "Forget every skill and all the evidence behind them? This cannot be undone.",
        ):
            return

        async def work() -> str:
            await self._model.reset()
            await self._fetch()
            return "All skills reset."

        self._start("Reset skills", work)

    def _choose_export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export skills", "curio-skills.json", "JSON (*.json)"
        )
        if filename:
            self.export_to(Path(filename))

    def export_to(self, path: Path) -> None:
        async def work() -> str:
            export = getattr(self._model, "export_data", None)
            if export is not None:
                data: dict[str, Any] = await export()
            else:
                data = {
                    "format": "curio-skills",
                    "skills": [
                        {
                            "concept": s.concept, "mastery": s.mastery, "attempts": s.attempts,
                            "last_practiced": s.last_practiced.isoformat()
                            if s.last_practiced else None,
                            "apps": list(s.apps),
                        }
                        for s in await self._model.snapshot()
                    ],
                }
            text = json.dumps(data, indent=2, ensure_ascii=False)
            await asyncio.to_thread(path.write_text, text, encoding="utf-8")
            return f"Exported {len(data.get('skills', ()))} skills to {path.name}."

        self._start("Export skills", work)

    # --- lifecycle ----------------------------------------------------------------

    def _on_model_changed(self) -> None:
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        subscribe = getattr(self._model, "subscribe", None)
        if subscribe is not None and self._unsubscribe is None:
            self._unsubscribe = subscribe(self._on_model_changed)
        self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._refresh_pending = False
        for task in tuple(self._tasks):
            task.cancel()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        super().closeEvent(event)

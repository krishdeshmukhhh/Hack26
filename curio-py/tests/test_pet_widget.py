import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_pet_widget_selection_and_capture(app):
    from curio.pet_config import PetSettings
    from curio.ui.pet_widget import PetCompanionWidget

    widget = PetCompanionWidget(settings=PetSettings())
    assert widget.catalog is not None
    widget.select_pet("cat")
    assert widget.settings.species == "cat"
    widget.show()
    widget.hide_for_capture()
    assert not widget.isVisible()
    widget.restore_after_capture()
    assert widget.isVisible()
    widget.hide()
    assert not widget._frame_timer.isActive()


def test_pet_widget_interaction_and_fallback(app, monkeypatch):
    from curio.pet_config import PetSettings
    from curio.state import VoiceState
    from curio.ui.pet_widget import PetCompanionWidget

    widget = PetCompanionWidget(settings=PetSettings())
    widget.set_state(VoiceState.LISTENING)
    widget._track_cursor(force=True)
    assert widget.controller.action == "attentive"
    widget.set_speaking(True)
    widget.set_state(VoiceState.IDLE)
    assert not widget._speaking
    widget.select_pet("ferret")
    widget.show()
    assert not widget.grab().isNull()
    widget.hide()
    import curio.ui.pet_widget as module

    monkeypatch.setattr(
        module, "SpriteCatalog", lambda species: (_ for _ in ()).throw(ValueError("bad asset"))
    )
    broken = PetCompanionWidget(settings=PetSettings())
    assert broken.catalog is None
    assert not broken.grab().isNull()


def test_switch_pet_preserves_streaming_and_pointing(app):
    from curio.pet_config import PetSettings
    from curio.state import VoiceState
    from curio.ui.pet_widget import PetCompanionWidget

    widget = PetCompanionWidget(settings=PetSettings())
    widget.set_state(VoiceState.RESPONDING)
    widget.text_started("hello")
    widget.controller.point_to((100, 100))
    widget.select_pet("cat")
    assert widget.controller.streaming
    assert widget.controller.point_active
    assert widget.controller.settings.species == "cat"


def _frames(widget, seconds, step=0.1):
    """Advance the pet as if ``seconds`` passed, without waiting."""
    import time

    for _ in range(round(seconds / step)):
        widget._last_tick = time.monotonic() - step
        widget._advance_motion()


def test_pet_point_shows_pill_then_both_leave(app):
    from curio.pet_config import PetSettings
    from curio.state import VoiceState
    from curio.ui.pet_widget import PetCompanionWidget

    widget = PetCompanionWidget(settings=PetSettings())
    widget.show()
    widget.set_state(VoiceState.RESPONDING)
    widget.fly_to(400, 300)
    assert widget.controller.point_active
    assert widget.bubble.active
    _frames(widget, 4.0)
    # The visit ends on its own (independent of speech) and the pill fades with it.
    assert not widget.controller.point_active
    assert not widget._pill_visit
    widget.hide()


def test_pet_walkthrough_step_holds_until_released(app):
    from curio.pet_config import PetSettings
    from curio.state import VoiceState
    from curio.ui.pet_widget import PetCompanionWidget

    widget = PetCompanionWidget(settings=PetSettings())
    widget.show()
    widget.set_state(VoiceState.RESPONDING)
    widget.fly_to(400, 300, hold=True, step=(1, 3))
    widget.set_state(VoiceState.GUIDING)
    _frames(widget, 6.0)
    assert widget.controller.point_active
    assert widget.bubble.active
    widget.set_state(VoiceState.IDLE)  # walkthrough ended → release
    _frames(widget, 4.0)
    assert not widget.controller.point_active
    widget.hide()


def test_widget_lingers_then_walks_to_latest_cursor(app, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPoint

    import curio.ui.pet_widget as module
    from curio.pet_config import PetSettings

    clock = [100.0]
    cursor = [QPoint(200, 200)]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "QCursor", SimpleNamespace(pos=lambda: cursor[0]))
    widget = module.PetCompanionWidget(settings=PetSettings(jump_frequency=0, playful_idle=False))
    widget._track_cursor(force=True)
    start = widget.pos()
    cursor[0] = QPoint(430, 200)
    clock[0] += 0.1
    widget._track_cursor()
    assert widget.pos() == start
    assert widget.controller.action == "idle"
    for _ in range(10):
        clock[0] += 0.1
        widget._track_cursor()
    assert widget.x() > start.x()
    assert widget.x() < cursor[0].x()
    assert widget.controller.action in {"walk", "run"}
    assert not widget.grab().isNull()


def test_widget_settles_and_sleeps_without_cursor_input(app, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QPoint

    import curio.ui.pet_widget as module
    from curio.pet_config import PetSettings

    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "QCursor", SimpleNamespace(pos=lambda: QPoint(200, 200)))
    widget = module.PetCompanionWidget(
        settings=PetSettings(sleep_after_seconds=10, playful_idle=False, jump_frequency=0)
    )
    widget._track_cursor(force=True)
    for _ in range(130):
        clock[0] += 0.1
        widget._track_cursor()
    assert widget.controller.action == "sleep"
    assert widget.player.action == "sleep"
    assert not widget.grab().isNull()

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
    assert not widget._cursor_timer.isActive()


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

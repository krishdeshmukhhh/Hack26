from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtTest import QTest

from curio.ui import focus_overlay, target_ring


@pytest.fixture
def ring(qt_application, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(target_ring.time, "monotonic", lambda: now[0])
    widget = target_ring.TargetRingOverlay()
    yield widget, now
    widget.close()


def test_lifecycle_clear_and_close(ring):
    widget, now = ring
    assert not widget.isVisible()
    widget.pulse_at(100, 120)
    assert widget.isVisible() and widget._timer.isActive()
    now[0] += 1.51
    widget._on_frame()
    assert not widget.isVisible() and not widget._timer.isActive()
    widget.pulse_at(100, 120)
    widget.clear()
    widget.restore_after_capture()
    assert not widget.isVisible() and not widget._timer.isActive()
    widget.pulse_at(100, 120)
    widget.close()
    assert not widget._timer.isActive()


def test_replacement(ring):
    widget, now = ring
    widget.pulse_at(100, 120)
    now[0] += 1
    widget.pulse_at(200, 220)
    assert widget._center == QPointF(200, 220) - widget.geometry().topLeft()
    now[0] += 0.6
    widget._on_frame()
    assert widget.isVisible()


def test_capture_visibility_and_expiration(ring):
    widget, now = ring
    widget.hide_for_capture()
    widget.restore_after_capture()
    assert not widget.isVisible()
    widget.pulse_at(100, 100)
    widget.hide_for_capture()
    widget.hide_for_capture()
    assert not widget.isVisible()
    widget.restore_after_capture()
    assert widget.isVisible()
    widget.hide_for_capture()
    now[0] += 2
    widget.restore_after_capture()
    assert not widget.isVisible() and not widget._timer.isActive()


def test_replacement_and_clear_during_capture(ring):
    widget, _ = ring
    widget.pulse_at(100, 100)
    widget.hide_for_capture()
    widget.pulse_at(200, 200)
    assert not widget.isVisible()
    widget.restore_after_capture()
    assert widget.isVisible()
    widget.hide_for_capture()
    widget.clear()
    widget.restore_after_capture()
    assert not widget.isVisible()


def test_previously_hidden_stays_hidden(ring):
    widget, _ = ring
    widget.pulse_at(100, 100)
    widget.hide()
    widget.hide_for_capture()
    widget.restore_after_capture()
    assert not widget.isVisible()


@pytest.mark.parametrize(
    ("physical", "expected"),
    [((-2400, 300), (-2480, 150)), ((300, 450), (200, 300)), ((-3000, -600), (-3000, -600))],
)
def test_mixed_dpi_negative_origins(monkeypatch, physical, expected):
    screens = [
        SimpleNamespace(geometry=lambda: QRect(-2560, 0, 1280, 720), devicePixelRatio=lambda: 2),
        SimpleNamespace(geometry=lambda: QRect(0, 0, 1280, 720), devicePixelRatio=lambda: 1.5),
        SimpleNamespace(
            geometry=lambda: QRect(-3000, -600, 800, 400), devicePixelRatio=lambda: 1.5
        ),
    ]
    for index, screen in enumerate(screens):
        screen.name = lambda index=index: f"screen{index}"
    monkeypatch.setattr(focus_overlay.QGuiApplication, "screens", lambda: screens)
    monkeypatch.setattr(focus_overlay, "_windows_bounds", lambda: {
        screen.name(): (screen.geometry().x(), screen.geometry().y(),
                        round(screen.geometry().width() * screen.devicePixelRatio()),
                        round(screen.geometry().height() * screen.devicePixelRatio()))
        for screen in screens
    })
    _, point = target_ring._logical_target(*physical)
    assert point == QPointF(*expected)


def test_paint_and_input_flags(ring):
    widget, now = ring
    widget.pulse_at(100, 100)
    now[0] += 0.4
    widget._on_frame()
    image = widget.grab().toImage()
    assert not image.isNull()
    assert any(image.pixelColor(x, 100).alpha() for x in range(101, 145))
    assert widget.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_timer_expires_while_capture_hidden(ring):
    widget, now = ring
    widget.pulse_at(100, 100)
    widget.hide_for_capture()
    now[0] += 2
    QTest.qWait(50)
    assert not widget._timer.isActive()
    widget.restore_after_capture()
    assert not widget.isVisible()


def test_pulses_expand_fade_and_keep_center(ring):
    widget, now = ring
    widget.pulse_at(100, 100)
    now[0] += 0.1
    early = widget.grab().toImage()
    now[0] += 0.1
    later = widget.grab().toImage()

    def ring_pixels(image):
        return [
            (x, image.pixelColor(x, 100).alpha())
            for x in range(101, 145)
            if image.pixelColor(x, 100).alpha()
        ]

    first, second = ring_pixels(early), ring_pixels(later)
    assert min(x for x, _ in second) > min(x for x, _ in first)
    assert max(alpha for _, alpha in second) < max(alpha for _, alpha in first)
    assert early.pixelColor(100, 100).alpha() == 0
    assert later.pixelColor(100, 100).alpha() == 0
    for x, _ in second:
        assert (
            abs(later.pixelColor(x, 100).alpha() - later.pixelColor(200 - x - 1, 100).alpha()) <= 2
        )

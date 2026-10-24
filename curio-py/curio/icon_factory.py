"""Programmatic QIcon generator for Curio tray states.

Draws a solid circle with a centered "C" glyph using Pillow, then wraps the
resulting PNG bytes in a QIcon. Rendered at 64x64 for HiDPI smoothness; Qt
downsamples to the system tray size (typically 32x32) cleanly.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QIcon, QPixmap

from curio.design_system import DS
from curio.state import VoiceState

_RENDER_SIZE = 64

STATE_COLORS: dict[str, str] = {
    VoiceState.IDLE.value: DS.Colors.accent_blue,
    VoiceState.LISTENING.value: DS.Colors.accent_green,
    VoiceState.PROCESSING.value: DS.Colors.accent_blue,
    VoiceState.RESPONDING.value: DS.Colors.accent_amber,
    VoiceState.GUIDING.value: DS.Colors.accent_green,
    "error": DS.Colors.error_red,
}


def _render_icon(fill_color: str) -> QIcon:
    """Draw a filled circle with a centered 'C' and return it as a QIcon."""
    image = Image.new("RGBA", (_RENDER_SIZE, _RENDER_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Solid circle filling (nearly) the full canvas with a small margin.
    margin = 2
    draw.ellipse(
        (margin, margin, _RENDER_SIZE - margin, _RENDER_SIZE - margin),
        fill=fill_color,
    )

    # Center a "C" glyph using the default bitmap font.
    font = ImageFont.load_default()
    text = "C"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (_RENDER_SIZE - text_w) / 2 - bbox[0]
    text_y = (_RENDER_SIZE - text_h) / 2 - bbox[1]
    draw.text((text_x, text_y), text, fill="white", font=font)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return QIcon(pixmap)


def icon_for_state(state: VoiceState) -> QIcon:
    """Return a QIcon for the given voice state."""
    color = STATE_COLORS.get(state.value, STATE_COLORS[VoiceState.IDLE.value])
    return _render_icon(color)


def icon_for_error() -> QIcon:
    """Return the red error QIcon."""
    return _render_icon(STATE_COLORS["error"])

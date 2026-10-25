"""Separate real Windows capability/offscreen-render smoke; never a live demo claim."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sounddevice
from curio.live_tutoring.widget import TutoringWidget
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTextToSpeech import QTextToSpeech
from PySide6.QtWidgets import QApplication, QLabel

root = Path(__file__).resolve().parents[3]
app = QApplication([])
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
font_id = QFontDatabase.addApplicationFont(str(font_path))
if font_id < 0:
    raise RuntimeError("Cannot load the preview font; do not publish an unreadable capture")
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
widget = TutoringWidget()
banner = QLabel("SEEDED COMPONENT EXHIBIT — real Qt / exact checker; no live model or audio")
banner.setWordWrap(True)
widget.layout().insertWidget(0, banner)
widget.problem.setText("2*x*(x^2+1)^2")
widget.start_button.click()
for equation in ("u=x^2+1", "du=x*dx", "du=2*x*dx"):
    widget.step.setText(equation)
    widget.submit_button.click()
widget.resize(850, 700)
widget.show()
app.processEvents()
image = root / "docs/readiness/demo/seeded-offscreen-tutor.png"
assert widget.grab().save(str(image))
engine = QTextToSpeech()
report = {
    "qt": "real offscreen widget rendered with seeded typed attempts",
    "capture": image.name,
    "preview_font": app.font().family(),
    "tts_engines": QTextToSpeech.availableEngines(),
    "tts_voice_count": len(engine.availableVoices()),
    "audio_device_count": len(sounddevice.query_devices()),
    "limits": "No acoustic recognition, playback, physical screen or live provider verified",
}
print(json.dumps(report, indent=2))
(root / "docs/readiness/demo/windows-smoke.json").write_text(
    json.dumps(report, indent=2)
)
engine.stop()
widget.close()
app.processEvents()

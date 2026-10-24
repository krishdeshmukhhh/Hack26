"""Keep one QApplication alive across async service and widget test modules.

Qt does not support repeatedly destroying/recreating QApplication. A session
reference also prevents QCoreApplication-only fixtures from taking ownership
before a later test needs QWidget support.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    application = QApplication.instance() or QApplication([])
    yield application

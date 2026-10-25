from curio.ui.tray_icon import TrayIcon


def test_tray_share_toggle() -> None:
    tray = TrayIcon()
    toggles = []
    tray.share_walkthroughs_toggled.connect(toggles.append)
    labels = [a.text() for a in tray.contextMenu().actions()]
    assert "Skills…" in labels and "Share walkthroughs anonymously" in labels

    tray.set_share_walkthroughs(True)  # syncing from config is silent
    assert tray._share_action.isChecked() and toggles == []
    tray._share_action.trigger()  # the user unchecks it
    assert toggles == [False]
    tray.set_learning_available(True, map_server=True)
    assert tray._stuck_map_action.isVisible()
    tray.set_learning_available(False, map_server=True)
    assert not tray._share_action.isEnabled() and not tray._stuck_map_action.isVisible()

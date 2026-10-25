import asyncio

from curio.learning_contract import SkillState
from curio.learning_events import NullSkillModel
from curio.learning_events.skills_window import SkillsWindow, describe_skill
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
    tray.set_learning_available(False)
    assert not tray._share_action.isEnabled()


def test_skills_window_lists_snapshot() -> None:
    class Model(NullSkillModel):
        async def snapshot(self):
            return (
                SkillState(concept="layers", mastery=0.4, attempts=1),
                SkillState(concept="pivot tables", mastery=0.82, attempts=5, apps=("excel",)),
            )

    window = SkillsWindow(Model())
    asyncio.run(window.refresh())
    items = [window._list.item(i).text() for i in range(window._list.count())]
    assert items == ["pivot tables (excel): 82% after 5 tries", "layers: 40% after 1 try"]

    empty = SkillsWindow(NullSkillModel())
    asyncio.run(empty.refresh())
    assert "No skills yet" in empty._status.text()
    assert describe_skill(SkillState(concept="x", mastery=0, attempts=0)) == "x: 0% after 0 tries"

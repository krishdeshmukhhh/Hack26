import asyncio

from curio.tutorial_coach.widget import TutorialCoachWidget

from .test_tutorial_coach import run
from .test_tutorial_coach_session import prepared


def test_injected_widget_edits_controls_and_unsubscribes():
    async def scenario():
        coach, model = await prepared()
        widget = TutorialCoachWidget(coach)
        assert widget.table.rowCount() == 2
        widget.table.item(0, 0).setText("Open the File menu")
        assert coach.plan.steps[0].instruction == "Open the File menu"
        widget.buttons["Start"].click()
        assert coach.state == "active"
        assert widget.output.toPlainText() == "Open the File menu"
        assert not widget.buttons["Check screen (share now)"].isEnabled()
        widget.buttons["Pause"].click()
        assert coach.state == "paused"
        widget.buttons["Resume"].click()
        model.result = "The menu contains export options."
        widget.buttons["Explain this"].click()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert widget.output.toPlainText() == model.result
        widget.buttons["I completed it"].click()
        assert coach.index == 1
        widget.close()
        assert coach.state == "stopped"
        previous = widget.output.toPlainText()
        coach.response.emit("Should no longer update closed widget")
        assert widget.output.toPlainText() == previous

    run(scenario())

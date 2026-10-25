import asyncio
import json

import pytest

from curio.tutorial_coach import Coach, CoachError, PageFetcher, extract_html


def run(coro):
    return asyncio.run(coro)


class Model:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def send(self, messages, system, model, max_tokens=1024):
        self.calls.append((messages, system, model))
        return self.result


HTML = (
    '<nav>Ignore me</nav><article><h1>Export</h1><p id="open">Open File menu.</p>'
    "<ol><li>Choose Export. The export dialog appears.</li></ol>"
    "<script>steal()</script></article>"
)


def test_extract_provenance():
    source = extract_html(HTML, "https://example.com/guide")
    assert [b.text for b in source.blocks] == [
        "Export",
        "Open File menu.",
        "Choose Export. The export dialog appears.",
    ]
    assert source.blocks[1].url == "https://example.com/guide#open"
    assert "steal" not in str(source)


def test_plan_and_session():
    async def scenario():
        model = Model(
            json.dumps(
                {
                    "steps": [
                        {
                            "instruction": "Open File menu.",
                            "expected": "File menu is visible.",
                            "sources": [2],
                        }
                    ]
                }
            )
        )
        coach = Coach(model, "local-model")
        plan = await coach.prepare_source(extract_html(HTML, "https://example.com/guide"))
        assert plan.steps[0].sources[0].text == "Open File menu."
        coach.edit_step(0, "Open the File menu", "Menu visible")
        coach.start()
        assert coach.repeat() == "Open the File menu"
        coach.pause()
        with pytest.raises(CoachError):
            coach.skip()
        coach.resume()
        coach.confirm()
        assert coach.state == "finished"
        assert coach.completions[0] == "user_confirmed"
        coach.stop()
        assert coach.state == "stopped"

    run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/a",
        "http://127.0.0.1",
        "https://user:pass@example.com",
        "http://[::1]",
        "http://169.254.169.254",
        "http://10.0.0.1",
        "https://example.com:444/a",
    ],
)
def test_unsafe_urls(url):
    with pytest.raises(CoachError):
        run(PageFetcher().fetch(url))

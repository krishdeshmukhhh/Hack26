"""The demo history shows transfer from photoshop layers to figma frames."""

import asyncio
from datetime import UTC, datetime

from curio.learning_contract import AssistanceLevel
from curio.skills.demo import fill, main

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def test_demo_history_shows_transfer(tmp_path):
    async def scenario():
        model = await fill(tmp_path / "demo.sqlite3", now=NOW)
        states = {s.concept: s for s in await model.snapshot()}
        assert states["layers"].mastery > 0.8
        assert "figma" not in {a for s in states.values() for a in s.apps}
        assert await model.recommend_assistance("figma", ["frames"]) == AssistanceLevel.HINTED
        assert await model.recommend_assistance("excel", ["pivot tables"]) == (
            AssistanceLevel.POINTED
        )
        assert "in figma the same idea is frames" in await model.prompt_context(
            "figma", ["frames"]
        )
        # refilling is idempotent: the demo uses fixed step ids
        again = await fill(tmp_path / "demo.sqlite3", now=NOW)
        assert {s.concept: s.attempts for s in await again.snapshot()} == {
            k: s.attempts for k, s in states.items()
        }

    asyncio.run(scenario())


def test_demo_cli(tmp_path, capsys):
    assert main(["--path", str(tmp_path / "cli.sqlite3"), "--reset"]) == 0
    out = capsys.readouterr().out
    assert "layers" in out and "figma / frames: hinted" in out

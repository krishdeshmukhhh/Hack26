import json
from pathlib import Path

from curio.clients.transcription_client import (
    TranscriptEvent,
    parse_assemblyai_message,
)

FIXTURE = Path(__file__).parent / "fixtures" / "assemblyai_v3_messages.json"


def test_parses_begin_message_as_none() -> None:
    messages = json.loads(FIXTURE.read_text())
    begin = next(m for m in messages if m["type"] == "Begin")
    event = parse_assemblyai_message(begin)
    assert event is None  # Begin messages are not user-facing events


def test_parses_interim_turn_as_interim_event() -> None:
    messages = json.loads(FIXTURE.read_text())
    interim = next(
        m for m in messages if m["type"] == "Turn" and not m.get("end_of_turn")
    )
    event = parse_assemblyai_message(interim)
    assert isinstance(event, TranscriptEvent)
    assert event.is_final is False
    assert event.text == interim["transcript"]


def test_parses_final_turn_as_final_event() -> None:
    messages = json.loads(FIXTURE.read_text())
    final = next(
        m for m in messages if m["type"] == "Turn" and m.get("end_of_turn")
    )
    event = parse_assemblyai_message(final)
    assert isinstance(event, TranscriptEvent)
    assert event.is_final is True
    assert event.text == final["transcript"]


def test_ignores_unknown_message_type() -> None:
    event = parse_assemblyai_message({"type": "SomeFutureMessage", "foo": "bar"})
    assert event is None


def test_ignores_termination_message() -> None:
    event = parse_assemblyai_message({"type": "Termination"})
    assert event is None


def test_parses_lowercase_turn_type() -> None:
    event = parse_assemblyai_message(
        {"type": "turn", "transcript": "hi", "end_of_turn": True}
    )
    assert event == TranscriptEvent(text="hi", is_final=True)

"""Tests for the Kokoro TTS client's text chunking and fallback, plus TTS config."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from curio.clients import kokoro_tts_client
from curio.clients.kokoro_tts_client import KokoroTTSClient, split_sentences
from curio.config import Config, ConfigError


def test_split_sentences_keeps_boundaries() -> None:
    text = (
        "you'll want to open the color page. it's that paintbrush icon at the bottom! "
        "click it and you get the color wheels."
    )
    assert split_sentences(text) == [
        "you'll want to open the color page.",
        "it's that paintbrush icon at the bottom!",
        "click it and you get the color wheels.",
    ]


def test_split_sentences_merges_short_fragments() -> None:
    assert split_sentences("yes. that one. the big red save button on the right.") == [
        "yes. that one. the big red save button on the right."
    ]
    assert split_sentences("open the export menu now. ok.") == ["open the export menu now. ok."]


def test_split_sentences_empty() -> None:
    assert split_sentences("   ") == []


class _FakeFallback:
    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            error = Signal(str)

        self._sig = _Sig()
        self.error = self._sig.error
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        pass


def test_falls_back_when_model_cannot_load(tmp_path: Path, monkeypatch) -> None:
    def no_download(url: str, dest: Path) -> None:
        raise RuntimeError("offline")

    monkeypatch.setattr(kokoro_tts_client, "_download", no_download)
    fallback = _FakeFallback()
    client = KokoroTTSClient(fallback=fallback, model_dir=tmp_path)
    asyncio.run(client.speak("hello there, this is a test."))
    asyncio.run(client.speak("and again."))
    assert fallback.spoken == ["hello there, this is a test.", "and again."]


def test_tts_engine_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('backend = "local"\n')
    local = Config.from_path(path).local
    assert local is not None
    assert (local.tts_engine, local.whisper_model) == ("kokoro", "base.en")

    path.write_text('backend = "local"\n[local]\ntts_engine = "system"\n')
    assert Config.from_path(path).local.tts_engine == "system"

    path.write_text('backend = "local"\n[local]\ntts_engine = "festival"\n')
    with pytest.raises(ConfigError, match="tts_engine"):
        Config.from_path(path)

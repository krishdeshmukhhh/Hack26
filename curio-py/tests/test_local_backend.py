"""Tests for the local backend: config, OpenAI conversion, coords, Whisper buffering."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from curio.clients.openai_llm_client import parse_openai_sse_lines, to_openai_messages
from curio.clients.whisper_transcription_client import (
    WhisperTranscriptionClient,
    pcm16_to_float32,
)
from curio.config import Config, ConfigError
from curio.point_mapper import map_point_to_screen
from curio.point_parser import PointTag
from curio.prompts import build_system_prompt
from curio.screen_capture import ScreenshotImage


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


# ---- config ---------------------------------------------------------------


def test_local_backend_needs_no_worker_url(tmp_path: Path) -> None:
    cfg = Config.from_path(_write(tmp_path, 'backend = "local"\n'))
    assert cfg.backend == "local"
    assert cfg.local is not None
    assert cfg.local.llm_base_url == "http://localhost:8000/v1"
    assert cfg.default_model == "Qwen/Qwen3-VL-32B-Instruct"
    assert cfg.point_coords == "norm1000"


def test_local_backend_custom_values(tmp_path: Path) -> None:
    cfg = Config.from_path(
        _write(
            tmp_path,
            'backend = "local"\n'
            "[local]\n"
            'llm_model = "Qwen/Qwen2.5-VL-72B-Instruct"\n'
            'point_coords = "pixel"\n'
            'llm_api_key = "secret"\n',
        )
    )
    assert cfg.default_model == "Qwen/Qwen2.5-VL-72B-Instruct"
    assert cfg.point_coords == "pixel"
    assert cfg.local is not None and cfg.local.llm_api_key == "secret"


def test_cloud_backend_defaults_to_pixel_coords(tmp_path: Path) -> None:
    cfg = Config.from_path(_write(tmp_path, 'worker_url = "https://w.example.dev"\n'))
    assert cfg.backend == "cloud"
    assert cfg.local is None
    assert cfg.point_coords == "pixel"


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ('backend = "banana"\n', "backend"),
        ('backend = "local"\n[local]\npoint_coords = "inches"\n', "point_coords"),
        ('backend = "local"\n[local]\nwhisper_device = "tpu"\n', "whisper_device"),
        ('backend = "local"\n[local]\nllm_base_url = ""\n', "llm_base_url"),
    ],
)
def test_local_backend_rejects_bad_values(tmp_path: Path, toml: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        Config.from_path(_write(tmp_path, toml))


# ---- OpenAI-compatible client ---------------------------------------------


def test_to_openai_messages_converts_images_and_system() -> None:
    messages = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "screen label"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
                },
                {"type": "text", "text": "where is save?"},
            ],
        },
    ]
    out = to_openai_messages(messages, "be helpful")
    assert out[0] == {"role": "system", "content": "be helpful"}
    assert out[1] == {"role": "user", "content": "earlier question"}
    assert out[3]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,QUJD"},
    }
    assert out[3]["content"][2] == {"type": "text", "text": "where is save?"}


def test_parse_openai_sse_lines() -> None:
    raw = (
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
        b": keep-alive\n\n"
        b"data: not json\n\n"
        b'data: {"choices":[{"delta":{"content":"there"}}]}\n\n'
        b'data: {"choices":[],"usage":{"total_tokens":5}}\n\n'
        b"data: [DONE]\n\n"
    )
    assert list(parse_openai_sse_lines(raw)) == ["hello ", "there"]


# ---- coordinates ----------------------------------------------------------


def _shot(left: int = 0, top: int = 0) -> ScreenshotImage:
    return ScreenshotImage(
        jpeg_bytes=b"",
        label="test",
        is_cursor_screen=True,
        display_width_px=1920,
        display_height_px=1080,
        image_width_px=1280,
        image_height_px=720,
        scale=1280 / 1920,
        monitor_left=left,
        monitor_top=top,
    )


def test_norm1000_maps_to_display_pixels() -> None:
    tag = PointTag(500, 500, "center")
    assert map_point_to_screen(tag, [_shot()], "norm1000") == (960, 540)


def test_norm1000_respects_monitor_offset_and_clamps() -> None:
    tag = PointTag(1200, 0, "edge")
    assert map_point_to_screen(tag, [_shot(left=-1920, top=100)], "norm1000") == (0, 100)


def test_prompt_matches_coordinate_mode() -> None:
    assert "0 to 1000" in build_system_prompt(point_coords="norm1000")
    assert "pixel dimensions" in build_system_prompt(point_coords="pixel")
    assert "{" not in build_system_prompt(point_coords="norm1000")


# ---- Whisper buffering ----------------------------------------------------


def test_pcm16_to_float32() -> None:
    pcm = np.array([0, 16384, -32768], dtype="<i2").tobytes()
    assert pcm16_to_float32(pcm).tolist() == [0.0, 0.5, -1.0]


async def _chunks(*chunks: bytes):
    for chunk in chunks:
        yield chunk


def _run_session(client: WhisperTranscriptionClient, *chunks: bytes) -> None:
    async def go() -> None:
        stream = asyncio.ensure_future(client.start_stream(_chunks(*chunks)))
        await asyncio.sleep(0)
        await client.stop_stream()
        await stream

    asyncio.run(go())


def test_whisper_short_press_emits_empty_final() -> None:
    client = WhisperTranscriptionClient("base.en")
    finals: list[str] = []
    client.final_transcript.connect(finals.append)
    _run_session(client, b"\x00\x00" * 100)  # ~6 ms of audio
    assert finals == [""]


def test_whisper_transcribes_buffered_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WhisperTranscriptionClient("base.en")
    seen: list[int] = []

    def fake_transcribe(pcm: bytes) -> str:
        seen.append(len(pcm))
        return "where is the save button"

    monkeypatch.setattr(client, "_transcribe", fake_transcribe)
    finals: list[str] = []
    client.final_transcript.connect(finals.append)
    half_second = b"\x00\x00" * 8000
    _run_session(client, half_second, half_second)
    assert seen == [32000]
    assert finals == ["where is the save button"]


def test_whisper_drops_stale_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WhisperTranscriptionClient("base.en")

    def fake_transcribe(_pcm: bytes) -> str:
        client._session += 1  # a new press started while we were transcribing
        return "old question"

    monkeypatch.setattr(client, "_transcribe", fake_transcribe)
    finals: list[str] = []
    client.final_transcript.connect(finals.append)
    _run_session(client, b"\x00\x00" * 16000)
    assert finals == []

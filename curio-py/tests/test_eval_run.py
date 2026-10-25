"""End-to-end runner test against a tiny fake OpenAI-compatible streaming server."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from curio.eval import run as eval_run
from curio.eval.case import load_cases

CASES = Path(__file__).resolve().parent.parent / "eval_cases"
REPLY = "first minimize this window. [POINT:930,20:minimize button] [STEP:1/4] [CONCEPTS:windows]"
SEEN: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers["content-length"])
        SEEN.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for i in range(0, len(REPLY), 20):
            chunk = {"choices": [{"delta": {"content": REPLY[i : i + 20]}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SEEN.clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def _settings(url: str) -> eval_run.ModelSettings:
    return eval_run.ModelSettings(
        base_url=url, model="fake", api_key="", temperature=0.2, point_coords="norm1000"
    )


def test_run_all_against_fake_server(server):
    cases = load_cases(CASES)
    assert {c.name for c in cases} >= {"example-bg-maximized", "example-bg-clear"}
    result = asyncio.run(
        eval_run.run_all(_settings(server), cases, repeat=2, label="t")
    )

    assert len(SEEN) == len(cases) * 2
    assert SEEN[0]["stream"] is True and SEEN[0]["model"] == "fake"
    assert SEEN[0]["messages"][0]["role"] == "system"

    maxed = result["cases"]["example-bg-maximized"]["summary"]
    assert maxed["pass_rate"] == 1.0 and maxed["point_rate"] == 1.0
    assert maxed["median_ttft_s"] is not None
    assert maxed["median_total_s"] >= maxed["median_ttft_s"]
    clear = result["cases"]["example-bg-clear"]["summary"]
    assert clear["pass_rate"] == 0.0  # reply says minimize, which that case forbids

    text = eval_run.format_results(result)
    assert "example-bg-maximized" in text and "OVERALL" in text
    comparison = eval_run.format_comparison(result, result)
    assert "+0pp" in comparison


def test_unreachable_raises():
    settings = _settings("http://127.0.0.1:9/v1")
    cases = load_cases(CASES)[:1]
    with pytest.raises(eval_run.EndpointUnreachable, match="cannot reach"):
        asyncio.run(eval_run.run_all(settings, cases, repeat=1, label="x"))

"""Real map client with simulated transport failures; no live model or network."""

import asyncio

import httpx
import pytest
from curio.learning_contract import WalkthroughSummary
from curio.map_sync.client import HttpMapSync


@pytest.mark.parametrize("failure", ["connect", "timeout", "status", "json"])
def test_map_failure_then_recovery_on_same_client(failure):
    async def run():
        healthy = False

        def respond(request):
            if not healthy:
                if failure == "connect":
                    raise httpx.ConnectError("simulated offline", request=request)
                if failure == "timeout":
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                if failure == "status":
                    return httpx.Response(503)
                return httpx.Response(200, text="not JSON")
            if request.url.path == "/v1/stats":
                return httpx.Response(200, json={"apps": [{
                    "app": "excel", "tasks": [{"task": "pivot", "steps": [
                        {"index": 1, "stuck_rate": 0.25},
                    ]}],
                }]})
            return httpx.Response(200, json={"paths": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            sync = HttpMapSync("https://simulated.invalid", client=http)
            assert await sync.pull() == ()
            assert await sync.refresh_stats() is False
            assert sync.step_difficulty("excel", "pivot", 1) is None
            healthy = True
            assert await sync.refresh_stats() is True
            assert sync.step_difficulty("excel", "pivot", 1) == 0.25
            healthy = False
            assert await sync.refresh_stats() is False
            # A failed refresh preserves the last usable cache.
            assert sync.step_difficulty("excel", "pivot", 1) == 0.25

    asyncio.run(run())


def test_push_failure_then_success_on_same_client():
    async def run():
        healthy = False

        def respond(request):
            if not healthy:
                raise httpx.ConnectError("simulated offline", request=request)
            return httpx.Response(201)

        summary = WalkthroughSummary(
            walkthrough_id="simulated", app="excel", task="pivot", steps=(), completed=False,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            sync = HttpMapSync("https://simulated.invalid", client=http)
            assert await sync.push(summary) is False
            healthy = True
            assert await sync.push(summary) is True

    asyncio.run(run())


def test_cancelling_inflight_refresh_propagates_and_client_can_recover():
    async def run():
        entered = asyncio.Event()
        healthy = False

        async def respond(request):
            if not healthy:
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(200, json={"apps": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            sync = HttpMapSync("https://simulated.invalid", client=http)
            pending = asyncio.create_task(sync.refresh_stats())
            await asyncio.wait_for(entered.wait(), timeout=1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            healthy = True
            assert await sync.refresh_stats() is True

    asyncio.run(run())

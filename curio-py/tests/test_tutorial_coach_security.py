import asyncio
from unittest.mock import patch

import pytest

from curio.tutorial_coach import CoachError, PageFetcher, PageResponse, extract_html
from curio.tutorial_coach.content import _request, resolve_public

from .test_tutorial_coach import HTML, run


async def public_resolver(host, port):
    return ["93.184.216.34"]


def fetcher(responses, **kwargs):
    calls = []

    async def transport(url, ip, timeout, limit):
        calls.append((url, ip))
        return responses.pop(0)

    return PageFetcher(resolver=public_resolver, transport=transport, **kwargs), calls


def page(body=HTML, **headers):
    return PageResponse(200, {"content-type": "text/html", **headers}, body.encode())


def test_redirect_provenance_and_pin():
    service, calls = fetcher([PageResponse(302, {"location": "/new"}, b""), page()])
    source = run(service.fetch("https://example.com/old"))
    assert source.url == "https://example.com/new"
    assert source.blocks[1].url == "https://example.com/new#open"
    assert calls == [
        ("https://example.com/old", "93.184.216.34"),
        ("https://example.com/new", "93.184.216.34"),
    ]


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1",
        "https://10.0.0.1",
        "http://example.com",
        "https://user:pass@example.com",
        "https://[::ffff:127.0.0.1]",
    ],
)
def test_redirect_rejected_before_request(target):
    service, calls = fetcher([PageResponse(302, {"location": target}, b"")])
    with pytest.raises(CoachError):
        run(service.fetch("https://example.com"))
    assert len(calls) == 1


def test_redirect_private_dns_and_mixed_answers():
    async def resolver(host, port):
        return ["93.184.216.34"] if host == "example.com" else ["93.184.216.34", "10.1.1.1"]

    service, calls = fetcher([PageResponse(302, {"location": "https://other.example"}, b"")])
    service.resolver = resolver
    with pytest.raises(CoachError, match="non-public"):
        run(service.fetch("https://example.com"))
    assert len(calls) == 1


def test_default_resolver_rejects_private_dns():
    async def scenario():
        loop = asyncio.get_running_loop()

        async def lookup(*args, **kwargs):
            return [(None, None, None, None, ("192.168.0.1", 443))]

        with patch.object(loop, "getaddrinfo", lookup), pytest.raises(CoachError, match="private"):
            await resolve_public("public.example", 443)

    run(scenario())


@pytest.mark.parametrize(
    "response, message",
    [
        (PageResponse(403, {}, b""), "permission"),
        (PageResponse(404, {}, b""), "404"),
        (PageResponse(200, {"content-type": "application/pdf"}, b"data"), "HTML"),
        (PageResponse(302, {}, b""), "destination"),
        (page("x" * 101), "size"),
        (page("<script>hidden</script>"), "meaningful"),
    ],
)
def test_fetch_errors(response, message):
    service, _ = fetcher([response], max_bytes=100)
    with pytest.raises(CoachError, match=message):
        run(service.fetch("https://example.com"))


def test_redirect_limit():
    service, calls = fetcher([PageResponse(302, {"location": "/loop"}, b"")] * 5)
    with pytest.raises(CoachError, match="redirects"):
        run(service.fetch("https://example.com"))
    assert len(calls) == 5


def test_fetch_timeout_and_cancellation():
    async def scenario():
        entered = asyncio.Event()

        async def transport(*args):
            entered.set()
            await asyncio.Event().wait()

        service = PageFetcher(resolver=public_resolver, transport=transport, timeout=0.01)
        with pytest.raises(CoachError, match="timed out"):
            await service.fetch("https://example.com")
        service.timeout = 10
        task = asyncio.create_task(service.fetch("https://example.com"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())


def test_default_transport_uses_original_host_and_pinned_ip():
    class Response:
        status = 200

        def getheaders(self):
            return [("content-type", "text/html")]

        def read1(self, count):
            return b""

    class Connection:
        sock = None

        def __init__(self, host, port, timeout):
            assert host == "example.com"
            assert port == 443

        def request(self, method, path, headers):
            assert method == "GET"
            assert path == "/a?b=1"
            assert "Cookie" not in headers
            self._create_connection(("example.com", 443), 10)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    with (
        patch("http.client.HTTPSConnection", Connection),
        patch("socket.create_connection") as connect,
    ):
        _request("https://example.com/a?b=1", "93.184.216.34", 10, 100)
        connect.assert_called_once_with(("93.184.216.34", 443), 10, None)


def test_redirect_to_video_is_not_extracted_from_title():
    service, calls = fetcher(
        [
            PageResponse(302, {"location": "https://youtube.com/watch?v=1"}, b""),
        ]
    )
    with pytest.raises(CoachError, match="transcript"):
        run(service.fetch("https://example.com"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "markup",
    [
        '<video src="movie.mp4"></video>',
        '<iframe src="https://www.youtube.com/embed/1"></iframe>',
        '<meta property="og:type" content="video.other">',
    ],
)
def test_video_html_requires_transcript(markup):
    service, _ = fetcher(
        [page("<h1>A long descriptive video title about exporting files</h1>" + markup)]
    )
    with pytest.raises(CoachError, match="transcript"):
        run(service.fetch("https://example.com"))


def test_malformed_attributes_and_excessive_nesting():
    source = extract_html(
        '<meta property="og:type" content><iframe src></iframe>' + HTML, "https://example.com"
    )
    assert source.blocks[1].text == "Open File menu."
    with pytest.raises(CoachError, match="complex"):
        extract_html("<div>" * 129 + HTML, "https://example.com")

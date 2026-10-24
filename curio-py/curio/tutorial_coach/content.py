"""Bounded public-page retrieval. No browser, proxy, cookies or subresource loads."""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import socket
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from curio.coaching_contract import ExtractedContent, RequestContext, SourceReference


class CoachError(ValueError):
    """An actionable source, plan or session error."""


@dataclass(frozen=True)
class Block:
    id: int
    text: str
    url: str
    references: tuple[SourceReference, ...] = ()


@dataclass(frozen=True)
class Source:
    url: str
    blocks: tuple[Block, ...]
    kind: str = "html"


def public_url(url: str) -> str:
    """Syntactic validation; DNS is additionally checked immediately before fetch."""
    try:
        if len(url) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError
        p = urlsplit(url)
        if (
            p.scheme not in ("https", "http")
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or "\\" in url
            or p.port not in (None, 80 if p.scheme == "http" else 443)
        ):
            raise ValueError
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if (
            host == "localhost"
            or "." not in host
            and ":" not in host
            or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
        return urldefrag(url)[0]
    except (ValueError, UnicodeError) as exc:
        raise CoachError("Use a public HTTP(S) URL without credentials or unusual ports.") from exc


async def resolve_public(host: str, port: int) -> list[str]:
    results = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(item[4][0] for item in results))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise CoachError("URL resolves to a private, local or reserved network address.")
    return addresses


@dataclass(frozen=True)
class PageResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _request(url: str, address: str, timeout: float, limit: int) -> PageResponse:
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == "https" else 80)
    cls = http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection
    connection = cls(p.hostname, port, timeout=timeout)
    # Keep the original hostname for Host, SNI and certificate verification, while
    # connecting ONLY to the validated IP (no second DNS lookup / rebinding).
    connection._create_connection = lambda _addr, timeout, source_address=None: (
        socket.create_connection((address, port), timeout, source_address)
    )
    deadline = time.monotonic() + timeout
    wire_socket = None

    def abort():
        # A slow peer must not keep a cancelled worker alive by dripping headers.
        sock = wire_socket or connection.sock
        if sock is not None:
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    watchdog = threading.Timer(timeout, abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        path = urlunsplit(("", "", p.path or "/", p.query, ""))
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/html, application/xhtml+xml",
                "Accept-Encoding": "identity",
                "User-Agent": "Curio-TutorialCoach/1.0",
            },
        )
        wire_socket = connection.sock
        response = connection.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise CoachError("Compressed responses are unsupported; paste a transcript instead.")
        try:
            declared_size = int(headers.get("content-length", "0"))
        except ValueError as exc:
            raise CoachError("Page returned an invalid content length.") from exc
        if declared_size < 0 or declared_size > limit:
            raise CoachError("Tutorial page exceeds the size limit.")
        chunks = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            # read1 returns available data rather than waiting to fill a large buffer.
            if wire_socket is not None:
                wire_socket.settimeout(remaining)
            chunk = response.read1(min(65536, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise CoachError("Tutorial page exceeds the size limit.")
            chunks.append(chunk)
        return PageResponse(response.status, headers, b"".join(chunks))
    finally:
        watchdog.cancel()
        connection.close()


async def request_page(url, address, timeout, limit):
    return await asyncio.to_thread(_request, url, address, timeout, limit)


class PageFetcher:
    """Resolver and transport injection is for trusted application code/tests only."""

    def __init__(
        self,
        *,
        resolver=resolve_public,
        transport=request_page,
        timeout=15.0,
        max_bytes=2_000_000,
        max_redirects=4,
    ):
        self.resolver = resolver
        self.transport = transport
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    async def extract(
        self, source: SourceReference, *, context: RequestContext
    ) -> ExtractedContent:
        context.cancellation.raise_if_cancelled()
        result = await self.fetch(source.uri)
        context.cancellation.raise_if_cancelled()
        return ExtractedContent(
            text="\n".join(block.text for block in result.blocks),
            sources=tuple(
                SourceReference(
                    id=f"{source.id}-{block.id}",
                    uri=block.url,
                    locator=f"block {block.id}",
                    title=block.text[:100],
                )
                for block in result.blocks
            ),
        )

    async def fetch(self, url: str) -> Source:
        try:
            async with asyncio.timeout(self.timeout):
                for _ in range(self.max_redirects + 1):
                    url = public_url(url)
                    p = urlsplit(url)
                    if any(
                        p.hostname == host or p.hostname.endswith("." + host)
                        for host in ("youtube.com", "youtu.be", "vimeo.com")
                    ):
                        raise CoachError(
                            "Video page requires an actual transcript; paste it instead."
                        )
                    addresses = await self.resolver(
                        p.hostname, p.port or (443 if p.scheme == "https" else 80)
                    )
                    # Also validate injected resolver results; default resolver checks all.
                    if not addresses or any(
                        not ipaddress.ip_address(ip).is_global for ip in addresses
                    ):
                        raise CoachError("URL resolves to a non-public address.")
                    response = await self.transport(url, addresses[0], self.timeout, self.max_bytes)
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise CoachError("Redirect has no destination.")
                        target = public_url(urljoin(url, location))
                        if p.scheme == "https" and urlsplit(target).scheme != "https":
                            raise CoachError("Refusing an HTTPS to HTTP redirect.")
                        url = target
                        continue
                    if response.status in (401, 403, 402):
                        raise CoachError(
                            "Page requires permission, login or payment; no bypass attempted."
                        )
                    if response.status != 200:
                        raise CoachError(f"Tutorial page returned HTTP {response.status}.")
                    if len(response.body) > self.max_bytes:
                        raise CoachError("Tutorial page exceeds the size limit.")
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type.split(";")[0].strip() not in (
                        "text/html",
                        "application/xhtml+xml",
                    ):
                        raise CoachError(
                            "Only ordinary HTML pages are supported. Paste a transcript."
                        )
                    encoding = "utf-8"
                    for part in content_type.split(";")[1:]:
                        if part.strip().startswith("charset="):
                            encoding = part.strip()[8:].strip("\"'")
                    try:
                        html = response.body.decode(encoding, errors="replace")
                    except LookupError as exc:
                        raise CoachError(
                            "Page declares an unsupported character encoding."
                        ) from exc
                    return await asyncio.to_thread(extract_html, html, url)
                raise CoachError("Too many redirects.")
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise CoachError(
                "Tutorial fetch timed out or could not reach the public page."
            ) from exc


class _Extractor(HTMLParser):
    ignored = {
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "noscript",
        "template",
        "iframe",
        "svg",
        "button",
    }
    blocks = {"h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote", "dt", "dd"}
    void = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.anchor = ""
        self.region = False
        self.entries = []
        self.has_video = False
        self.nodes = 0

    def flush(self):
        text = " ".join("".join(self.parts).split())
        if text:
            self.entries.append((text, self.anchor, self.region))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if len(self.stack) >= 128 or self.nodes > 30_000:
            raise CoachError("Tutorial HTML is too complex to extract safely.")
        attributes = dict(attrs)
        if tag == "video" or (
            tag == "meta"
            and attributes.get("property") == "og:type"
            and (attributes.get("content") or "").startswith("video")
        ):
            self.has_video = True
        if tag == "iframe" and any(
            host in (attributes.get("src") or "").lower()
            for host in ("youtube.com", "youtube-nocookie.com", "vimeo.com")
        ):
            self.has_video = True
        hidden = (
            tag in self.ignored
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or any(item[1] for item in self.stack)
        )
        if tag in self.blocks and not hidden:
            self.flush()
            self.anchor = attributes.get("id", "")
            self.region = any(item[0] in ("main", "article") for item in self.stack)
        if tag == "br":
            self.parts.append(" ")
        if tag not in self.void:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        if tag in self.blocks and not any(item[1] for item in self.stack):
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(item[1] for item in self.stack):
            self.parts.append(data)


def extract_html(html: str, url: str) -> Source:
    parser = _Extractor()
    parser.feed(html)
    parser.flush()
    if parser.has_video:
        raise CoachError(
            "Page contains video. Paste its actual transcript; video inference is disabled."
        )
    entries = parser.entries
    if any(region for _, _, region in entries):
        entries = [entry for entry in entries if entry[2]]
    blocks = tuple(
        Block(i + 1, text, url + ("#" + anchor if anchor else ""))
        for i, (text, anchor, _) in enumerate(entries)
    )
    if not blocks or sum(len(b.text) for b in blocks) < 30:
        raise CoachError("No meaningful tutorial text found. Page may require JavaScript or login.")
    if sum(len(b.text) for b in blocks) > 60_000 or len(blocks) > 800:
        raise CoachError("Extracted tutorial is too long. Paste a shorter transcript or section.")
    return Source(url, blocks)

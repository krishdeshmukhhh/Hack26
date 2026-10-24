"""AssemblyAI v3 streaming transcription: parser + websocket client.

This module contains two layers:

1. A pure parser — ``TranscriptEvent`` + ``parse_assemblyai_message`` — that
   decodes AssemblyAI Universal-Streaming v3 JSON messages into user-facing
   transcript events. Zero Qt / async / network dependencies; unit-tested in
   isolation.
2. ``TranscriptionClient`` — a ``QObject`` that owns the websocket lifecycle:
   fetches a short-lived token from the Cloudflare Worker, opens the v3
   websocket, runs concurrent send / recv loops, and emits ``interim_transcript``
   / ``final_transcript`` / ``error`` Qt signals. ``start_stream`` and
   ``stop_stream`` are ``async def`` coroutines designed to be kicked off from
   Qt signal handlers via ``asyncio.ensure_future`` once the app has wired
   Qt's event loop to asyncio with ``qasync`` (runtime dependency; not imported
   here).

See the Swift reference implementation at
``leanring-buddy/AssemblyAIStreamingTranscriptionProvider.swift`` for the exact
URL format, query-parameter names, termination frame protocol, and the
one-shot reconnect strategy this client mirrors.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
import websockets
from PySide6.QtCore import QByteArray, QObject, Signal

logger = logging.getLogger(__name__)

# AssemblyAI Universal-Streaming v3 endpoint + query params. These match the
# Swift reference (AssemblyAIStreamingTranscriptionProvider.swift lines 111,
# 448-465) exactly — sample_rate, encoding, and token are the literal keys the
# AssemblyAI server expects.
_ASSEMBLYAI_WS_BASE = "wss://streaming.assemblyai.com/v3/ws"
_SAMPLE_RATE_HZ = 16000
_ENCODING = "pcm_s16le"

# Graceful drain contract: after sending the Terminate frame we wait up to this
# many seconds for the server's final Turn message before cancelling the recv
# loop. The Swift client uses a similarly short bounded wait.
_DRAIN_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class TranscriptEvent:
    """A user-facing transcript update emitted by the parser.

    ``is_final`` is True when AssemblyAI has closed the turn (either via
    ``end_of_turn`` or ``turn_is_formatted``), signalling the final text for
    that utterance. Interim events stream in as the user keeps speaking.
    """

    text: str
    is_final: bool


def parse_assemblyai_message(msg: dict) -> TranscriptEvent | None:
    """Parse a single AssemblyAI v3 websocket message.

    Returns a ``TranscriptEvent`` for user-facing transcript updates, or
    ``None`` for lifecycle/control messages (``Begin``, ``Termination``,
    errors, unknown future types).

    The Swift reference lowercases the type before matching; we mirror that
    behaviour so any casing variants AssemblyAI sends still parse correctly.
    """
    message_type = msg.get("type")
    if not isinstance(message_type, str):
        return None

    if message_type.lower() != "turn":
        return None

    transcript = msg.get("transcript")
    if not isinstance(transcript, str):
        return None

    is_final = bool(msg.get("end_of_turn")) or bool(msg.get("turn_is_formatted"))
    return TranscriptEvent(text=transcript, is_final=is_final)


def _redact_token(msg: str, token: str | None) -> str:
    """Scrub a token substring from a stringified exception / log message.

    ``websockets.connect`` formats the full URL (including our query-string
    token) into its exception messages, which then flow through ``logger``
    calls and the ``error`` Qt signal. This helper keeps the token out of
    log files, crash reports, and any UI surface that receives the signal.
    """
    if not token:
        return msg
    return msg.replace(token, "<redacted>")


class TranscriptionClient(QObject):
    """Qt-facing AssemblyAI v3 streaming websocket client.

    Signals
    -------
    interim_transcript(str)
        Emitted for every non-final ``Turn`` message (i.e. while the user is
        still speaking).
    final_transcript(str)
        Emitted for every final ``Turn`` message (``end_of_turn=True`` or
        ``turn_is_formatted=True``). Also emitted with an empty string from
        ``stop_stream`` if the stream ended before any final was seen — the
        ``CompanionManager`` uses this sentinel to abort the turn silently
        (see PRD Task 4.8).
    error(str)
        Emitted once when the token fetch, websocket handshake, or either
        loop raises an exception that could not be recovered by the single
        reconnect attempt.

    Lifecycle
    ---------
    ``start_stream(pcm_chunk_iterator)`` and ``stop_stream()`` are ``async def``
    coroutines. The caller is responsible for running the Qt app under a
    ``qasync`` event loop and dispatching these coroutines with
    ``asyncio.ensure_future(...)`` from the relevant Qt signal handlers. This
    module does not import qasync; that wiring lives in the application entry
    point.
    """

    interim_transcript = Signal(str)
    final_transcript = Signal(str)
    error = Signal(str)

    def __init__(self, worker_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Strip any trailing slash so f"{worker_url}/transcribe-token" never
        # produces a double slash — the Cloudflare Worker route matcher is
        # picky about that.
        self._worker_url = worker_url.rstrip("/")
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._send_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._last_final_text: str | None = None
        self._drain_event: asyncio.Event | None = None
        self._stopping: bool = False
        # Whether a websocket session ever actually opened during the most
        # recent ``start_stream`` invocation. Used to gate the empty-final
        # sentinel in ``stop_stream`` so an out-of-order stop before start
        # cannot spuriously emit ``final_transcript("")``.
        self._session_started: bool = False
        # Token for the currently-connecting / connected session. Held only
        # long enough to redact it from any exception text before logging.
        self._current_token: str | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    async def start_stream(self, pcm_chunk_iterator: AsyncIterator[QByteArray]) -> None:
        """Open the websocket and run the send/recv loops until completion.

        One auto-reconnect attempt on a mid-stream websocket drop — after that
        any failure emits ``error(...)`` and returns. The ``pcm_chunk_iterator``
        is an async iterator yielding ``QByteArray`` chunks; the caller signals
        completion by making the iterator raise ``StopAsyncIteration`` (or by
        calling ``stop_stream()``).
        """
        self._last_final_text = None
        self._stopping = False
        self._session_started = False

        try:
            await self._run_session(pcm_chunk_iterator, reconnect_allowed=True)
        except Exception as exc:  # noqa: BLE001 — funnel to the error signal
            redacted = _redact_token(str(exc), self._current_token)
            # Use logger.error with the redacted string rather than
            # logger.exception (which dumps the raw traceback including the
            # unredacted URL). The traceback still gets logged at debug level
            # for local diagnostics if the operator opts in.
            logger.error("TranscriptionClient.start_stream failed: %s", redacted)
            logger.debug("start_stream traceback", exc_info=True)
            self.error.emit(redacted)
        finally:
            self._current_token = None

    async def stop_stream(self) -> None:
        """Graceful drain: Terminate frame, bounded wait for final, close.

        Implements the six-point contract from the plan:
          1. Signal the send loop to stop feeding new PCM (the external
             iterator is expected to have already terminated by the time
             the caller invokes us, but we guard anyway with ``_stopping``).
          2. Send ``{"type":"Terminate"}`` as a TEXT JSON message.
          3. Wait up to 2 seconds for the recv loop to observe a final Turn.
          4. Cancel the recv loop if the timeout wins; log a warning.
          5. Close the websocket.
          6. Emit ``final_transcript("")`` if no final was ever observed —
             the empty-transcript sentinel from PRD Task 4.8.
        """
        # Idempotency guard: a second call after a completed stop is a no-op.
        # ``_stopping`` is True and the ws has already been nulled.
        if self._stopping and self._ws is None:
            return

        # Snapshot whether a session actually ran before we start tearing
        # state down. This gates the empty-final sentinel at the bottom so a
        # stray ``stop_stream`` call before ``start_stream`` cannot emit a
        # spurious ``final_transcript("")`` and trip CompanionManager's
        # silent-abort path.
        session_ran = self._session_started

        self._stopping = True

        ws = self._ws
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "Terminate"}))
            except Exception:  # noqa: BLE001 — best-effort terminate
                logger.warning("failed to send Terminate frame", exc_info=True)

        # Bounded wait for the final Turn message. The recv loop sets
        # _drain_event when it observes a final, or when it exits.
        drain_event = self._drain_event
        if drain_event is not None:
            try:
                await asyncio.wait_for(drain_event.wait(), timeout=_DRAIN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "drain timeout after %.1fs — cancelling recv loop",
                    _DRAIN_TIMEOUT_SECONDS,
                )

        # Cancel any still-running tasks. If recv already finished these are
        # no-ops. We cancel send too since the external iterator may still be
        # alive.
        for task in (self._recv_task, self._send_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 — already closing/closed
                logger.debug("websocket close raised", exc_info=True)

        self._ws = None
        self._send_task = None
        self._recv_task = None
        self._drain_event = None

        # Empty-transcript sentinel for the CompanionManager silent-abort rule.
        # Only fires if a session actually opened this cycle AND no final was
        # ever observed — stop-before-start is a caller bug, not a silent
        # abort.
        if session_ran and self._last_final_text is None:
            self.final_transcript.emit("")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _run_session(
        self,
        pcm_chunk_iterator: AsyncIterator[QByteArray],
        *,
        reconnect_allowed: bool,
    ) -> None:
        """Fetch token, connect ws, run send+recv loops, handle one reconnect."""
        token = await self._fetch_token()
        self._current_token = token
        ws_url = (
            f"{_ASSEMBLYAI_WS_BASE}"
            f"?token={token}"
            f"&sample_rate={_SAMPLE_RATE_HZ}"
            f"&encoding={_ENCODING}"
        )

        try:
            ws = await websockets.connect(ws_url)
        except Exception as exc:  # noqa: BLE001
            redacted = _redact_token(str(exc), token)
            if reconnect_allowed and not self._stopping:
                logger.warning("initial ws connect failed, retrying once: %s", redacted)
                await self._run_session(pcm_chunk_iterator, reconnect_allowed=False)
                return
            # Re-raise as a RuntimeError carrying the redacted message so the
            # outer ``start_stream`` handler never sees the raw token in str(exc).
            raise RuntimeError(f"websocket connect failed: {redacted}") from exc

        self._ws = ws
        self._drain_event = asyncio.Event()
        self._session_started = True

        self._send_task = asyncio.create_task(self._send_loop(ws, pcm_chunk_iterator))
        self._recv_task = asyncio.create_task(self._recv_loop(ws))

        # No try/except around asyncio.wait: a bare ``except CancelledError: raise``
        # is a no-op, and we have no cleanup to do here — task teardown lives
        # below once we know which branch (reconnect vs propagate) we're in.
        done, pending = await asyncio.wait(
            {self._send_task, self._recv_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )

        # Surface any exception from the completed task(s). If the recv loop
        # died on a connection drop mid-stream and we still have the reconnect
        # budget, retry once. Otherwise cancel the sibling, close the ws, and
        # re-raise so ``start_stream`` can funnel it to the error signal.
        for task in done:
            exc = task.exception()
            if exc is None:
                continue

            # Normal close during graceful stop: the Terminate frame we sent
            # in ``stop_stream`` causes the server to close the ws, which
            # surfaces here as ConnectionClosed on either loop. Don't treat
            # that as an error.
            if self._stopping and isinstance(exc, websockets.ConnectionClosed):
                continue

            if (
                reconnect_allowed
                and not self._stopping
                and isinstance(exc, websockets.ConnectionClosed)
            ):
                logger.warning(
                    "ws dropped mid-stream, reconnecting once: %s",
                    _redact_token(str(exc), token),
                )
                # Cancel the remaining task before retrying.
                await self._drain_pending(pending)
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ws = None
                await self._run_session(pcm_chunk_iterator, reconnect_allowed=False)
                return

            # Non-reconnect error path: cancel orphaned sibling(s) BEFORE
            # re-raising so they don't leak as dangling tasks with
            # "Task exception was never retrieved" warnings.
            await self._drain_pending(pending)
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
            raise exc

    @staticmethod
    async def _drain_pending(pending: set[asyncio.Task]) -> None:
        """Cancel and await every task in ``pending``, swallowing exceptions.

        Used from both the reconnect branch and the non-reconnect error branch
        of ``_run_session`` to keep task cleanup identical on both paths.
        """
        for p in pending:
            if p.done():
                continue
            p.cancel()
            try:
                await p
            except BaseException:  # noqa: BLE001 — teardown must not raise
                pass

    async def _fetch_token(self) -> str:
        """POST to the Cloudflare Worker's ``/transcribe-token`` route."""
        url = f"{self._worker_url}/transcribe-token"
        async with httpx.AsyncClient() as client:
            response = await client.post(url)
            response.raise_for_status()
            payload = response.json()
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("transcribe-token response missing 'token' field")
        return token

    async def _send_loop(
        self,
        ws: websockets.WebSocketClientProtocol,
        pcm_chunk_iterator: AsyncIterator[QByteArray],
    ) -> None:
        """Consume PCM chunks from the iterator and ship them as binary frames.

        The iterator yields ``QByteArray`` because MicCapture emits that type
        (PySide6 can't marshal Python ``bytes`` through a queued signal). We
        convert to ``bytes`` here before the websocket send, which expects a
        bytes-like object.
        """
        try:
            async for chunk in pcm_chunk_iterator:
                if self._stopping:
                    break
                # QByteArray -> bytes. ``bytes(qba)`` copies the buffer via
                # the buffer protocol, which is what we want since the wire
                # send may outlive the caller's ref.
                payload = bytes(chunk)
                await ws.send(payload)
        except websockets.ConnectionClosed:
            # During ``stop_stream``, the ws is closed out from under us and
            # the next ``ws.send`` raises ConnectionClosed. That's a normal
            # graceful-stop race, not an error — swallow it. Mid-stream drops
            # while NOT stopping re-raise so ``_run_session`` can trigger its
            # one-shot reconnect.
            if self._stopping:
                return
            raise

    async def _recv_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Receive JSON text frames, parse them, and emit Qt signals."""
        try:
            async for raw in ws:
                # The v3 protocol is JSON-over-text; ignore any stray binary.
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("non-JSON message from AssemblyAI: %r", raw[:200])
                    continue
                if not isinstance(msg, dict):
                    continue

                event = parse_assemblyai_message(msg)
                if event is None:
                    continue

                if event.is_final:
                    # Dedupe by text equality. Swift's reference dedupes by
                    # turnOrder (handleTurnMessage + storeTurnTranscript
                    # around lines 273-330) so each user utterance yields at
                    # most one committed final. We don't track turn order
                    # here, but equality on the text payload covers the two
                    # cases we care about: (1) the ``turn_is_formatted``
                    # follow-up message which carries the same text as a
                    # prior ``end_of_turn``, and (2) a mid-stream reconnect
                    # where the server replays a final we already emitted.
                    if event.text == self._last_final_text:
                        if self._drain_event is not None:
                            self._drain_event.set()
                        continue
                    self._last_final_text = event.text
                    self.final_transcript.emit(event.text)
                    # Unblock any pending drain wait in stop_stream.
                    if self._drain_event is not None:
                        self._drain_event.set()
                else:
                    self.interim_transcript.emit(event.text)
        finally:
            # Make sure stop_stream's bounded wait unblocks even if the server
            # closed without sending a final Turn.
            if self._drain_event is not None:
                self._drain_event.set()

"""Read explicitly selected local documents as bounded, attributed tutorial data."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from curio.coaching_contract import SourceReference

from .content import Block, CoachError, Source, extract_html

FILE_FILTER = "Tutorial documents (*.txt *.md *.markdown *.html *.htm *.pdf)"
MAX_FILE_BYTES = 2_000_000
MAX_TEXT = 60_000
MAX_BLOCKS = 800


def _reference(uri: str, number: int, locator: str, title: str) -> tuple[SourceReference, ...]:
    return (SourceReference(id=f"upload-{number}", uri=uri, locator=locator, title=title),)


def _pdf_blocks(data: bytes, uri: str, title: str) -> tuple[Block, ...]:
    try:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtPdf import QPdfDocument
    except ImportError as exc:
        raise CoachError(
            "PDF support requires the Qt PDF module; use a text export instead."
        ) from exc
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument(None)
    try:
        document.load(buffer)
        if document.error() != QPdfDocument.Error.None_:
            raise CoachError(
                "PDF is invalid, encrypted or unsupported. Use an unprotected text export."
            )
        count = document.pageCount()
        if not 1 <= count <= 100:
            raise CoachError("Select a PDF with between 1 and 100 pages.")
        blocks, total = [], 0
        for page in range(count):
            text = document.getAllText(page).text().strip()
            total += len(text)
            if total > MAX_TEXT:
                raise CoachError(
                    "Document exceeds 60,000 extracted characters; select a smaller excerpt."
                )
            if text:
                number = len(blocks) + 1
                location = f"{uri}#page={page + 1}"
                blocks.append(
                    Block(
                        number,
                        text,
                        location,
                        _reference(location, number, f"page {page + 1}", title),
                    )
                )
        if not blocks:
            raise CoachError(
                "PDF has no extractable text. Scanned PDFs require OCR; use a text export."
            )
        return tuple(blocks)
    finally:
        document.close()
        buffer.close()


def read_tutorial_file(path: Path | str) -> Source:
    """No scripts, external resources, file copying or automatic URL fetching."""
    path = Path(path)
    if str(path).startswith(("\\\\", "//")):
        raise CoachError("Choose a local file rather than a network share or device path.")
    extension = path.suffix.lower()
    if extension not in {".txt", ".md", ".markdown", ".html", ".htm", ".pdf"}:
        raise CoachError("Supported tutorial files: TXT, Markdown, HTML and text-based PDF.")
    try:
        resolved = path.resolve(strict=True)
        if str(resolved).startswith(("\\\\", "//")) or ":" in resolved.name:
            raise CoachError("Choose a regular local file, not a network share or device path.")
        with resolved.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise CoachError("Choose a regular local file.")
            data = handle.read(MAX_FILE_BYTES + 1)
    except (OSError, RuntimeError) as exc:
        raise CoachError(
            "Could not read the selected file. Choose a readable local document."
        ) from exc
    if len(data) > MAX_FILE_BYTES:
        raise CoachError("Document exceeds 2 MB; select a smaller file or excerpt.")
    # Opaque provenance keeps the absolute local path out of provider requests.
    uri = f"upload:{uuid4().hex}/{quote(path.name)}"
    if extension == ".pdf":
        blocks = _pdf_blocks(data, uri, path.name)
    else:
        try:
            encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = data.decode(encoding)
        except UnicodeError as exc:
            raise CoachError(
                "File is not readable UTF-8/UTF-16 text. Export it as plain text."
            ) from exc
        if any(ord(c) < 32 and c not in "\n\r\t\f" for c in text):
            raise CoachError("File contains binary/control data rather than tutorial text.")
        if extension in {".html", ".htm"}:
            source = extract_html(text, uri)
            blocks = tuple(
                replace(
                    block,
                    references=_reference(block.url, block.id, f"HTML block {block.id}", path.name),
                )
                for block in source.blocks
            )
        else:
            if len(text) > MAX_TEXT:
                raise CoachError("Document exceeds 60,000 characters; select a smaller excerpt.")
            entries = []
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                if len(entries) >= MAX_BLOCKS:
                    raise CoachError("Document exceeds 800 text blocks; select a smaller excerpt.")
                index = len(entries) + 1
                location = f"{uri}#line={number}"
                entries.append(
                    Block(
                        index,
                        line.strip(),
                        location,
                        _reference(location, index, f"line {number}", path.name),
                    )
                )
            blocks = tuple(entries)
    if (
        not blocks
        or len(blocks) > MAX_BLOCKS
        or sum(len(block.text) for block in blocks) > MAX_TEXT
    ):
        raise CoachError("Document is empty or exceeds 800 blocks / 60,000 extracted characters.")
    return Source(uri, blocks, "upload")

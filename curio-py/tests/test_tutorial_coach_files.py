"""User-selected local tutorials reuse attributed coaching, without URL fetching."""

import asyncio
import json

import pytest

from curio.tutorial_coach import Coach, CoachError
from curio.tutorial_coach.files import read_tutorial_file
from tests.test_tutorial_coach import Model


@pytest.mark.parametrize("extension", [".txt", ".md", ".html"])
def test_selected_file_keeps_provenance_and_no_absolute_path(tmp_path, extension):
    path = tmp_path / ("lesson" + extension)
    text = "Open the File menu.\nChoose Export and review the output settings."
    path.write_text(
        "<article><p>" + text + "</p></article>" if extension == ".html" else text, encoding="utf-8"
    )
    source = read_tutorial_file(path)
    assert source.kind == "upload"
    assert "lesson" in source.url
    assert str(tmp_path) not in source.url
    assert "Open the File menu" in source.blocks[0].text
    assert source.blocks[0].references


def test_file_plan_uses_existing_review_and_controls(tmp_path):
    path = tmp_path / "lesson.txt"
    path.write_text("Open the File menu.\nChoose Export and review the output settings.")

    async def scenario():
        model = Model(
            json.dumps(
                {"steps": [{"instruction": "Open File", "expected": "Menu", "sources": [1]}]}
            )
        )
        coach = Coach(model, "configured-model")
        await coach.prepare_file(path)
        assert coach.state == "preview"
        assert coach.plan.steps[0].sources[0].references[0].locator == "line 1"
        assert str(tmp_path) not in str(model.calls)
        coach.start()
        assert coach.repeat() == "Open File"
        coach.stop()
        await coach.aclose()

    asyncio.run(scenario())


def test_bad_uploads_are_rejected_before_provider(tmp_path):
    for name, data in [
        ("program.exe", b"not a tutorial"),
        ("empty.txt", b""),
        ("binary.txt", b"\x00\xff\x01"),
        ("large.txt", b"x" * 2_000_001),
        ("broken.pdf", b"not a PDF"),
    ]:
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(CoachError):
            read_tutorial_file(path)
    with pytest.raises(CoachError):
        read_tutorial_file(tmp_path)


def pdf_fixture(text):
    # Minimal real one-page PDF with a standard text font; no external tools.
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + item + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def test_real_pdf_extraction_has_page_references(qt_application, tmp_path):
    path = tmp_path / "lesson.pdf"
    path.write_bytes(pdf_fixture("Open the File menu and choose Export."))

    async def scenario():
        source = await asyncio.to_thread(read_tutorial_file, path)
        assert "choose Export" in source.blocks[0].text
        assert source.blocks[0].references[0].locator == "page 1"
        assert "#page=1" in source.blocks[0].url
        assert str(tmp_path) not in source.url

    asyncio.run(scenario())


def test_pdf_without_text_has_no_invented_plan(qt_application, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(pdf_fixture(""))
    model = Model("Should not run")

    async def scenario():
        coach = Coach(model, "configured-model")
        with pytest.raises(CoachError, match="no extractable text"):
            await coach.prepare_file(path)
        assert not model.calls
        assert coach.plan is None
        await coach.aclose()

    asyncio.run(scenario())


def test_upload_button_previews_and_retains_user_control(tmp_path, monkeypatch):
    from curio.tutorial_coach.widget import TutorialCoachWidget

    path = tmp_path / "lesson.md"
    path.write_text("Open the File menu and review available export options.")
    monkeypatch.setattr(
        "curio.tutorial_coach.widget.QFileDialog.getOpenFileName", lambda *args: (str(path), "")
    )

    async def scenario():
        model = Model(
            json.dumps(
                {"steps": [{"instruction": "Open File", "expected": "Menu", "sources": [1]}]}
            )
        )
        coach = Coach(model, "configured-model")
        widget = TutorialCoachWidget(coach)
        widget.upload.click()
        await asyncio.gather(*tuple(widget._tasks))
        assert coach.state == "preview"
        assert widget.table.rowCount() == 1
        assert "lesson.md" in widget.table.item(0, 2).text()
        widget.buttons["Start"].click()
        assert coach.state == "active"
        assert not widget.upload.isEnabled()
        await widget.aclose()
        await coach.aclose()

    asyncio.run(scenario())

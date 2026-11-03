from io import BytesIO
import shutil
import tempfile

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services import document_ingestion


def _docx_bytes(include_content=True):
    from docx import Document

    document = Document()
    if include_content:
        document.add_paragraph("Approved product price is $240.")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Plan"
        table.cell(0, 1).text = "Annual"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _digital_pdf_bytes(page_count=1):
    writer = PdfWriter()
    for _ in range(page_count):
        page = writer.add_blank_page(width=612, height=792)
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (Digital PDF price $240) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _scanned_pdf_bytes(page_count=1):
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (40, 100),
        "SCANNED BRAND REPORT 4827",
        fill="black",
        font=ImageFont.load_default(size=64),
    )
    image_data = BytesIO()
    image.save(image_data, format="PNG")

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(700, 210))
    for _ in range(page_count):
        pdf.drawImage(ImageReader(BytesIO(image_data.getvalue())), 0, 0, 700, 210)
        pdf.showPage()
    pdf.save()
    image.close()
    return output.getvalue()


def test_docx_extraction_includes_paragraphs_and_tables():
    extracted = document_ingestion.extract_source_text(
        "approved-facts.docx",
        _docx_bytes(),
        document_ingestion.DOCX_MEDIA_TYPE,
    )

    assert "Approved product price is $240." in extracted
    assert "Plan\tAnnual" in extracted


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("empty.docx", b"", "empty"),
        ("malformed.docx", b"not a zip file", "could not be parsed"),
        ("legacy.doc", _docx_bytes(), "Only UTF-8"),
    ],
)
def test_docx_rejects_empty_malformed_and_unsupported_files(
    filename, content, message
):
    with pytest.raises(ValueError, match=message):
        document_ingestion.extract_source_text(filename, content)


def test_docx_rejects_mime_mismatch():
    with pytest.raises(ValueError, match="extension does not match"):
        document_ingestion.extract_source_text(
            "facts.docx", _docx_bytes(), "application/pdf"
        )


def test_empty_docx_is_rejected():
    with pytest.raises(ValueError, match="No readable text"):
        document_ingestion.extract_source_text("empty.docx", _docx_bytes(False))


def test_searchable_pdf_extraction_preserves_digital_text(monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", False)

    extracted = document_ingestion.extract_source_text(
        "facts.pdf", _digital_pdf_bytes(), "application/pdf"
    )

    assert extracted == "Digital PDF price $240"


def test_scanned_pdf_requires_ocr_configuration_when_disabled(monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", False)

    with pytest.raises(ValueError, match="Enable OCR_ENABLED"):
        document_ingestion.extract_source_text(
            "scan.pdf", _scanned_pdf_bytes(), "application/pdf"
        )


def test_scanned_pdf_handles_unavailable_ocr_dependencies(monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", True)
    monkeypatch.setattr(
        document_ingestion,
        "_render_ocr_pages",
        lambda *_args: (_ for _ in ()).throw(
            document_ingestion.OcrDependenciesUnavailable(
                "PDF OCR dependencies are unavailable."
            )
        ),
    )

    with pytest.raises(ValueError, match="OCR dependencies are unavailable"):
        document_ingestion.extract_source_text("scan.pdf", _scanned_pdf_bytes())


def test_scanned_pdf_handles_missing_tesseract_executable(monkeypatch, tmp_path):
    pytesseract = pytest.importorskip("pytesseract")
    pytest.importorskip("pypdfium2")
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", True)
    monkeypatch.setattr(
        pytesseract.pytesseract,
        "tesseract_cmd",
        str(tmp_path / "missing-tesseract"),
    )

    with pytest.raises(ValueError, match="Tesseract executable"):
        document_ingestion.extract_source_text("scan.pdf", _scanned_pdf_bytes())


def test_pdf_ocr_honors_scanned_page_limit(monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", True)
    monkeypatch.setattr(document_ingestion, "MAX_OCR_PAGES", 1)
    monkeypatch.setattr(
        document_ingestion,
        "_render_ocr_pages",
        lambda _data, indices: {indices[0]: "Recognized first page"},
    )

    with pytest.raises(ValueError, match="MAX_OCR_PAGES"):
        document_ingestion.extract_source_text(
            "scan.pdf", _scanned_pdf_bytes(page_count=2)
        )


def test_pdf_page_and_source_size_limits(monkeypatch):
    monkeypatch.setattr(document_ingestion, "MAX_PDF_PAGES", 1)
    with pytest.raises(ValueError, match="allowed 1 pages"):
        document_ingestion.extract_source_text(
            "too-many-pages.pdf", _digital_pdf_bytes(page_count=2)
        )

    monkeypatch.setattr(document_ingestion, "MAX_SOURCE_UPLOAD_SIZE", 4)
    with pytest.raises(ValueError, match="file size limit"):
        document_ingestion.extract_source_text("large.txt", b"12345")


def test_review_upload_extracts_and_stores_docx(client):
    docx = _docx_bytes()
    response = client.post(
        "/api/analyze",
        data={"content_type": "Document"},
        files={
            "file": (
                "draft.docx",
                docx,
                document_ingestion.DOCX_MEDIA_TYPE,
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "Approved product price is $240." in result["content"]
    assert result["document_analysis"]["format"] == "docx"
    assert result["visual_attachment_url"]

    attachment = client.get(result["visual_attachment_url"])
    assert attachment.status_code == 200
    assert attachment.headers["content-type"] == document_ingestion.DOCX_MEDIA_TYPE
    assert "attachment" in attachment.headers["content-disposition"]
    assert attachment.content == docx

    source = client.post(
        "/api/sources/upload",
        files={
            "file": (
                "approved-facts.docx",
                docx,
                document_ingestion.DOCX_MEDIA_TYPE,
            )
        },
    )
    assert source.status_code == 201
    assert "Approved product price is $240." in source.json()["content"]


def test_scanned_pdf_review_uses_ocr_without_manual_text(client, monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", True)
    monkeypatch.setattr(
        document_ingestion,
        "_render_ocr_pages",
        lambda _data, indices: {indices[0]: "Scanned offer price is $240"},
    )

    response = client.post(
        "/api/analyze",
        files={
            "file": (
                "scanned-offer.pdf",
                _scanned_pdf_bytes(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["content"] == "Scanned offer price is $240"
    assert result["image_analysis"]["pages"][0]["ocr_used"] is True


def test_pdf_review_without_readable_text_returns_configuration_error(client, monkeypatch):
    monkeypatch.setattr(document_ingestion, "OCR_ENABLED", False)

    response = client.post(
        "/api/analyze",
        files={
            "file": (
                "scanned-offer.pdf",
                _scanned_pdf_bytes(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert "No readable text was extracted" in response.json()["detail"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_scanned_pdf_ocr_uses_local_tools_and_cleans_temporary_files(
    monkeypatch, tmp_path
):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("pytesseract")
    monkeypatch.setattr(document_ingestion, "MAX_OCR_PAGES", 2)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    pages = document_ingestion.extract_pdf_pages(
        _scanned_pdf_bytes(), ocr_enabled=True
    )

    assert pages[0]["ocr_used"] is True
    assert "4827" in pages[0]["text"]
    assert list(tmp_path.iterdir()) == []


def test_pdf_ocr_renderer_closes_page_resources(monkeypatch):
    import sys
    from types import SimpleNamespace

    closed = []

    class FakeImage:
        def close(self):
            closed.append("image")

    class FakeBitmap:
        def to_pil(self):
            return FakeImage()

        def close(self):
            closed.append("bitmap")

    class FakePage:
        def get_size(self):
            return 612, 792

        def render(self, scale):
            assert 0 < scale <= 2
            return FakeBitmap()

        def close(self):
            closed.append("page")

    class FakeDocument:
        def __init__(self, _file_bytes):
            pass

        def __getitem__(self, _index):
            return FakePage()

        def close(self):
            closed.append("document")

    fake_pdfium = SimpleNamespace(PdfDocument=FakeDocument)
    fake_tesseract = SimpleNamespace(image_to_string=lambda _image: "local OCR")
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)

    assert document_ingestion._render_ocr_pages(b"%PDF-test", [0]) == {
        0: "local OCR"
    }
    assert closed == ["image", "bitmap", "page", "document"]

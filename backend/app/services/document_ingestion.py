from io import BytesIO
import math
from pathlib import PurePath
from typing import Optional
import zipfile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import (
    MAX_OCR_PAGES,
    MAX_SOURCE_LENGTH,
    MAX_SOURCE_UPLOAD_SIZE,
    OCR_ENABLED,
)

MAX_PDF_PAGES = 100
MAX_DOCX_ARCHIVE_ENTRIES = 2048
MAX_DOCX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 200
MAX_OCR_PAGE_PIXELS = 12_000_000
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
_ALLOWED_MEDIA_TYPES = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {DOCX_MEDIA_TYPE, "application/octet-stream"},
}


class OcrDependenciesUnavailable(RuntimeError):
    pass


class OcrPageProcessingError(RuntimeError):
    pass


def _validate_media_type(extension: str, media_type: Optional[str]) -> None:
    if (
        media_type
        and media_type.lower().split(";", 1)[0].strip()
        not in _ALLOWED_MEDIA_TYPES[extension]
    ):
        raise ValueError("The file extension does not match the declared content type.")


def _check_file_size(file_bytes: bytes, limit: int) -> None:
    if len(file_bytes) > limit:
        raise ValueError("The uploaded source file exceeds the configured file size limit.")


def _extract_docx_text(file_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ARCHIVE_ENTRIES:
                raise ValueError("The DOCX document contains too many internal files.")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise ValueError("Encrypted DOCX documents are not supported.")
            uncompressed_size = sum(entry.file_size for entry in entries)
            if uncompressed_size > MAX_DOCX_UNCOMPRESSED_SIZE:
                raise ValueError("The DOCX document exceeds the expanded file size limit.")
            if any(
                entry.file_size > 0
                and entry.file_size / max(entry.compress_size, 1)
                > MAX_DOCX_COMPRESSION_RATIO
                for entry in entries
            ):
                raise ValueError("The DOCX document has an unsafe compression ratio.")
            if (
                "[Content_Types].xml" not in archive.namelist()
                or "word/document.xml" not in archive.namelist()
            ):
                raise ValueError("The uploaded file is not a valid DOCX document.")
    except ValueError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("The uploaded DOCX document could not be parsed.") from exc

    try:
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from lxml.etree import XMLSyntaxError
    except ImportError as exc:
        raise ValueError(
            "DOCX extraction is unavailable because python-docx is not installed."
        ) from exc

    try:
        document = Document(BytesIO(file_bytes))
        parts = []
        for block in document.iter_inner_content():
            if hasattr(block, "rows"):
                parts.extend(
                    "\t".join(cell.text.strip() for cell in row.cells)
                    for row in block.rows
                )
            else:
                parts.append(block.text)
        extracted = "\n".join(part for part in parts if part.strip()).strip()
    except (
        KeyError,
        OSError,
        PackageNotFoundError,
        ValueError,
        XMLSyntaxError,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError("The uploaded DOCX document could not be parsed.") from exc
    if not extracted:
        raise ValueError("No readable text was extracted from the DOCX document.")
    return extracted


def _render_ocr_pages(file_bytes: bytes, page_indices: list[int]) -> dict[int, str]:
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except (ImportError, OSError) as exc:
        raise OcrDependenciesUnavailable(
            "PDF OCR dependencies are unavailable; install pypdfium2 and pytesseract."
        ) from exc

    pdf_document = None
    extracted = {}
    try:
        try:
            pdf_document = pdfium.PdfDocument(file_bytes)
        except pdfium.PdfiumError as exc:
            raise OcrPageProcessingError(
                "The PDF could not be opened by the OCR renderer."
            ) from exc
        for page_index in page_indices:
            page = None
            bitmap = None
            image = None
            try:
                page = pdf_document[page_index]
                width, height = page.get_size()
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    raise ValueError("The PDF page has invalid dimensions.")
                scale = min(
                    2.0,
                    10_000 / max(width, height),
                    math.sqrt(MAX_OCR_PAGE_PIXELS / (width * height)),
                )
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                try:
                    extracted[page_index] = pytesseract.image_to_string(image).strip()
                except pytesseract.TesseractNotFoundError as exc:
                    raise OcrDependenciesUnavailable(
                        "The Tesseract executable is unavailable; install it and ensure it is on PATH."
                    ) from exc
                except pytesseract.TesseractError as exc:
                    raise OcrPageProcessingError(
                        "Tesseract could not process the rendered PDF page."
                    ) from exc
            except pdfium.PdfiumError as exc:
                raise OcrPageProcessingError(
                    "The PDF page could not be rendered for OCR."
                ) from exc
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
    finally:
        if pdf_document is not None:
            pdf_document.close()
    return extracted


def extract_pdf_pages(
    file_bytes: bytes, ocr_enabled: Optional[bool] = None
) -> list[dict]:
    if not file_bytes.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")
    try:
        reader = PdfReader(BytesIO(file_bytes), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF documents are not supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(
                "PDF contains more than the allowed {} pages.".format(MAX_PDF_PAGES)
            )
        pages = []
        for page in reader.pages:
            extraction_failed = False
            try:
                text = (page.extract_text() or "").strip()
            except (KeyError, ValueError, OSError, PdfReadError):
                text = ""
                extraction_failed = True
            pages.append(
                {
                    "text": text,
                    "text_layer_detected": bool(text),
                    "text_extraction_failed": extraction_failed,
                    "ocr_used": False,
                    "limitations": [],
                }
            )
    except ValueError:
        raise
    except (PdfReadError, OSError, KeyError) as exc:
        raise ValueError("The uploaded PDF could not be parsed.") from exc

    use_ocr = OCR_ENABLED if ocr_enabled is None else ocr_enabled
    scanned_indices = [
        index for index, page in enumerate(pages) if not page["text_layer_detected"]
    ]
    if not scanned_indices:
        return pages
    if not use_ocr:
        for index in scanned_indices:
            pages[index]["limitations"].append(
                "No text layer was detected; PDF OCR is disabled."
            )
        return pages

    ocr_indices = scanned_indices[:MAX_OCR_PAGES]
    if len(scanned_indices) > MAX_OCR_PAGES:
        for index in scanned_indices[MAX_OCR_PAGES:]:
            pages[index]["limitations"].append(
                "This scanned page was not OCR-processed because MAX_OCR_PAGES was reached."
            )
    try:
        recognized = _render_ocr_pages(file_bytes, ocr_indices)
    except OcrDependenciesUnavailable as exc:
        message = str(exc)
        for index in ocr_indices:
            pages[index]["limitations"].append(message)
        return pages
    except OcrPageProcessingError as exc:
        for index in ocr_indices:
            pages[index]["limitations"].append(str(exc))
        return pages
    except (OSError, ValueError) as exc:
        for index in ocr_indices:
            pages[index]["limitations"].append(
                "PDF OCR could not process this page ({}).".format(type(exc).__name__)
            )
        return pages

    for index in ocr_indices:
        text = recognized.get(index, "")
        pages[index]["text"] = text
        pages[index]["ocr_used"] = bool(text)
        if not text:
            pages[index]["limitations"].append(
                "OCR did not recognize readable text on this page."
            )
    return pages


def _pdf_ocr_error(pages: list[dict]) -> str:
    missing_pages = [
        str(index + 1) for index, page in enumerate(pages) if not page["text"]
    ]
    if not missing_pages:
        return "No readable text was extracted from the PDF."
    limitations = [
        limitation
        for page in pages
        for limitation in page["limitations"]
    ]
    if any(
        "dependencies are unavailable" in item
        or "Tesseract executable is unavailable" in item
        for item in limitations
    ):
        return (
            "The PDF has scanned pages but OCR dependencies are unavailable. "
            "Install pypdfium2, pytesseract, and the Tesseract executable."
        )
    if not OCR_ENABLED:
        return (
            "The PDF has no readable text on page(s) {}. Enable OCR_ENABLED and "
            "install the Tesseract executable to process scanned pages.".format(
                ", ".join(missing_pages)
            )
        )
    if any("MAX_OCR_PAGES was reached" in item for item in limitations):
        return (
            "The PDF contains more scanned pages than the configured MAX_OCR_PAGES "
            "limit; increase that setting before importing the complete document."
        )
    if any("could not process" in item for item in limitations):
        return (
            "OCR could not process PDF page(s) {}. Check that the Tesseract "
            "executable is installed and available.".format(", ".join(missing_pages))
        )
    return "No readable text was extracted from PDF page(s) {}.".format(
        ", ".join(missing_pages)
    )


def extract_docx_text(
    filename: str,
    file_bytes: bytes,
    media_type: Optional[str] = None,
    max_file_size: Optional[int] = None,
) -> str:
    extension = PurePath(filename).suffix.lower()
    if extension != ".docx":
        raise ValueError("Only DOCX documents are supported by this extractor.")
    _validate_media_type(extension, media_type)
    if not file_bytes:
        raise ValueError("The uploaded DOCX document is empty.")
    _check_file_size(
        file_bytes,
        MAX_SOURCE_UPLOAD_SIZE if max_file_size is None else max_file_size,
    )
    return _extract_docx_text(file_bytes)


def extract_source_text(
    filename: str,
    file_bytes: bytes,
    media_type: Optional[str] = None,
) -> str:
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_SOURCE_EXTENSIONS:
        raise ValueError(
            "Only UTF-8 TXT, Markdown, PDF, or DOCX sources are supported."
        )
    _validate_media_type(extension, media_type)
    if not file_bytes:
        raise ValueError("The uploaded source file is empty.")
    _check_file_size(file_bytes, MAX_SOURCE_UPLOAD_SIZE)
    if extension in {".txt", ".md"}:
        try:
            extracted = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text source must be UTF-8 encoded.") from exc
    elif extension == ".docx":
        extracted = _extract_docx_text(file_bytes)
    else:
        pages = extract_pdf_pages(file_bytes)
        missing_pages = [page for page in pages if not page["text"]]
        if missing_pages:
            raise ValueError(_pdf_ocr_error(pages))
        extracted = "\n".join(page["text"] for page in pages)
    extracted = extracted.strip()
    if not extracted:
        raise ValueError("No readable text was extracted from the source file.")
    if len(extracted.encode("utf-8")) > MAX_SOURCE_LENGTH:
        raise ValueError("Extracted source text exceeds the configured maximum length.")
    return extracted

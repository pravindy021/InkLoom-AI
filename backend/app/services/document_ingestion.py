from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import MAX_SOURCE_LENGTH

MAX_PDF_PAGES = 100
SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".md", ".pdf"}


def extract_source_text(filename: str, file_bytes: bytes) -> str:
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_SOURCE_EXTENSIONS:
        raise ValueError("Only UTF-8 TXT, Markdown, or PDF sources are supported.")
    if extension in {".txt", ".md"}:
        try:
            extracted = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text source must be UTF-8 encoded.") from exc
    else:
        try:
            reader = PdfReader(BytesIO(file_bytes), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF sources are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError("PDF contains more than the allowed 100 pages.")
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as exc:
            raise ValueError("The uploaded PDF could not be parsed.") from exc
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("The uploaded PDF could not be parsed.") from exc
    extracted = extracted.strip()
    if not extracted:
        raise ValueError("No readable text was extracted from the source file.")
    if len(extracted.encode("utf-8")) > MAX_SOURCE_LENGTH:
        raise ValueError("Extracted source text exceeds the configured maximum length.")
    return extracted

from io import BytesIO

from docx import Document
from PIL import Image
import pytest
from sqlalchemy.orm import Session as SqlAlchemySession
from starlette.datastructures import UploadFile
from starlette.formparsers import FormData

from app.services.document_ingestion import DOCX_MEDIA_TYPE


def _docx_bytes():
    document = Document()
    document.add_paragraph("Multipart cleanup check.")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _png_bytes():
    image = Image.new("RGB", (4, 4), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _track_form_cleanup(monkeypatch):
    closed_uploads = []
    original_close = FormData.close

    async def close_and_track(form):
        uploads = [
            value
            for _, value in form.multi_items()
            if isinstance(value, UploadFile)
        ]
        await original_close(form)
        closed_uploads.extend(upload.file.closed for upload in uploads)

    monkeypatch.setattr(FormData, "close", close_and_track)
    return closed_uploads


def test_analysis_upload_closes_form_after_success(client, monkeypatch):
    closed_uploads = _track_form_cleanup(monkeypatch)

    response = client.post(
        "/api/analyze",
        data={"content_type": "Document"},
        files={"file": ("draft.docx", _docx_bytes(), DOCX_MEDIA_TYPE)},
    )

    assert response.status_code == 200
    assert closed_uploads == [True]


def test_analysis_upload_closes_form_after_extraction_error(client, monkeypatch):
    closed_uploads = _track_form_cleanup(monkeypatch)

    response = client.post(
        "/api/analyze",
        data={"content_type": "Document"},
        files={"file": ("malformed.docx", b"not a DOCX", DOCX_MEDIA_TYPE)},
    )

    assert response.status_code == 422
    assert closed_uploads == [True]


def test_analysis_upload_closes_form_when_database_commit_fails(
    client, monkeypatch
):
    closed_uploads = _track_form_cleanup(monkeypatch)

    def fail_commit(_session):
        raise RuntimeError("simulated database commit failure")

    monkeypatch.setattr(SqlAlchemySession, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database commit failure"):
        client.post(
            "/api/analyze",
            data={"content_type": "Document"},
            files={"file": ("draft.docx", _docx_bytes(), DOCX_MEDIA_TYPE)},
        )

    assert closed_uploads == [True]


def test_fastapi_file_form_upload_closes_spool_on_error(client, monkeypatch):
    closed_uploads = _track_form_cleanup(monkeypatch)

    response = client.post(
        "/api/sources/upload",
        files={"file": ("unsupported.bin", b"unsupported", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert closed_uploads == [True]


def test_fastapi_file_form_upload_closes_spool_after_success(client, monkeypatch):
    closed_uploads = _track_form_cleanup(monkeypatch)

    response = client.post(
        "/api/visual-assets",
        data={"asset_type": "logo"},
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 201
    assert closed_uploads == [True]

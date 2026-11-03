from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth_service import hash_password


def _frame_bytes():
    buffer = BytesIO()
    Image.new("RGB", (48, 32), color="#675cba").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_video_analysis_stores_timestamped_frames_and_report_content(
    client, test_engine, monkeypatch
):
    from app.routes import analysis
    from pypdf import PdfReader

    frame_bytes = _frame_bytes()

    async def process_video(_upload, allow_transcription):
        assert allow_transcription is False
        return (
            b"private-video",
            {
                "duration_seconds": 18.5,
                "frame_interval_seconds": 15,
                "metadata": {
                    "width": 1920,
                    "height": 1080,
                    "video_codec": "h264",
                },
                "frames": [
                    {
                        "frame_index": 0,
                        "timestamp_seconds": 0,
                        "file_data": frame_bytes,
                        "media_type": "image/jpeg",
                    }
                ],
                "transcript": {
                    "text": "The product is guaranteed to work.",
                    "segments": [
                        {
                            "start": 2.5,
                            "end": 4.0,
                            "text": "The product is guaranteed to work.",
                        }
                    ],
                    "configured": False,
                },
                "warnings": [],
            },
        )

    monkeypatch.setattr(analysis, "process_video_upload", process_video)
    monkeypatch.setattr(
        analysis,
        "analyze_visual_file",
        lambda *_args, **_kwargs: (
            {
                "format": "JPEG",
                "width": 48,
                "height": 32,
                "extracted_text": "The product is guaranteed to work.",
                "limitations": [],
            },
            [],
        ),
    )
    response = client.post(
        "/api/analyze",
        data={
            "title": "Product launch video",
            "content": "",
            "content_type": "Video",
            "allow_external_transcription": "false",
        },
        files={"file": ("launch.mp4", b"upload", "video/mp4")},
    )
    assert response.status_code == 200
    review_id = response.json()["id"]
    finding = next(
        item
        for item in response.json()["findings"]
        if item.get("matched_text") and "guaranteed" in item["matched_text"].lower()
    )
    assert finding["visual_data"]["timestamp_seconds"] == 2.5

    review = client.get(f"/api/reviews/{review_id}")
    assert review.status_code == 200
    attachment = review.json()["visual_attachment"]
    assert attachment["analysis"]["video"]["duration_seconds"] == 18.5
    assert attachment["analysis"]["video"]["metadata"]["width"] == 1920
    assert attachment["analysis"]["video"]["transcript"]["segments"][0]["text"]
    assert attachment["analysis"]["video"]["frames"][0]["url"].endswith(
        "/video-frames/0"
    )
    frame = client.get(attachment["analysis"]["video"]["frames"][0]["url"])
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"

    report = client.get(f"/api/reviews/{review_id}/report.pdf")
    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(report.content)).pages
    )
    assert "Timestamped transcript" in text
    assert "The product is guaranteed to work." in text

    client.post("/api/auth/logout")
    assert client.get(attachment["analysis"]["video"]["frames"][0]["url"]).status_code == 401
    monkeypatch.setattr("app.services.auth_service.PASSWORD_ITERATIONS", 100_000)
    with Session(test_engine) as db:
        db.add(
            User(
                email="video-outsider@example.test",
                display_name="Video Outsider",
                password_hash=hash_password("strong-test-password"),
                role="contributor",
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "email": "video-outsider@example.test",
            "password": "strong-test-password",
        },
    )
    assert login.status_code == 200
    assert client.get(
        attachment["analysis"]["video"]["frames"][0]["url"]
    ).status_code == 404
    assert client.get(f"/api/reviews/{review_id}/report.pdf").status_code == 404


def test_video_upload_rejects_mime_mismatch_before_processing(client):
    response = client.post(
        "/api/analyze",
        data={"title": "Invalid video", "content": "", "content_type": "Video"},
        files={"file": ("clip.mp4", b"video", "video/quicktime")},
    )
    assert response.status_code == 422
    assert "MIME type" in response.json()["detail"]

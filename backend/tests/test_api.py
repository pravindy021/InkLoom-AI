from io import BytesIO
import shutil

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
from sqlalchemy.orm import Session

from app.models.review_comment import ReviewActivity, ReviewAuditEvent


def test_health_docs_and_seeded_guidelines(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert client.get("/docs").status_code == 200

    guidelines = client.get("/api/guidelines")
    assert guidelines.status_code == 200
    assert any(item["is_seed"] for item in guidelines.json())


def test_create_guideline_and_analyze_compatible_content(client):
    created = client.post(
        "/api/guidelines",
        json={
            "name": "Preferred product language",
            "category": "terminology",
            "description": "Use approved product wording.",
            "severity": "medium",
            "prohibited_terms": ["world class"],
            "preferred_terms": ["excellent"],
            "approved_sources": [],
        },
    )
    assert created.status_code == 201
    guideline_id = created.json()["id"]

    response = client.post(
        "/api/analyze",
        json={
            "content": "Our world class product guarantees 100% success for every customer. Click here.",
            "content_type": "text",
            "title": "Launch message",
            "guideline_ids": [guideline_id],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == body["review_id"]
    assert body["overall_status"] == "needs_review"
    assert body["summary"]["total_issues"] >= 3
    categories = {finding["category"] for finding in body["findings"]}
    assert {"terminology", "unsupported_claim", "accessibility"} <= categories
    assert any("excellent" in (finding["suggestion"] or "") for finding in body["findings"])
    assert body["findings"][0]["review_status"] == "pending"

    detail = client.get("/api/reviews/{}".format(body["id"]))
    assert detail.status_code == 200
    assert detail.json()["content_type"] == "text"
    assert detail.json()["issue_count"] == body["total_issues"]


def test_invalid_content_and_unknown_guideline_are_reported(client):
    blank = client.post("/api/analyze", json={"content": "  "})
    assert blank.status_code == 422

    unknown = client.post(
        "/api/analyze",
        json={"content": "A valid draft", "guideline_ids": [999999]},
    )
    assert unknown.status_code == 422


def test_review_workflow_comments_revisions_and_pagination(client, test_engine):
    analysis = client.post(
        "/api/analyze",
        json={"content": "A simple product description.", "title": "Product copy"},
    )
    review_id = analysis.json()["id"]

    changed = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "in_review", "reviewer": "Reviewer One"},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "in_review"
    assert changed.json()["reviewer"] == "Reviewer One"
    with Session(test_engine) as db:
        event = db.query(ReviewAuditEvent).filter_by(review_id=review_id).one()
        assert event.previous_status == "pending"
        assert event.new_status == "in_review"
        assert event.reviewer == "Reviewer One"

    invalid_status = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "published"},
    )
    assert invalid_status.status_code == 422

    comment = client.post(
        "/api/reviews/{}/comments".format(review_id),
        json={"comment": "Please verify the source.", "author": "Reviewer One"},
    )
    assert comment.status_code == 201
    assert comment.json()["comment"] == "Please verify the source."

    revision = client.post(
        "/api/reviews/{}/revisions".format(review_id),
        json={"content": "Revised product description.", "title": "Revision 1"},
    )
    assert revision.status_code == 201
    assert revision.json()["content"] == "Revised product description."

    detail = client.get("/api/reviews/{}".format(review_id)).json()
    assert len(detail["comments"]) == 1
    assert len(detail["revisions"]) == 1

    listing = client.get("/api/reviews?offset=0&limit=1")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert len(listing.json()["items"]) == 1


def test_image_upload_is_validated_and_explains_visual_limits(client):
    buffer = BytesIO()
    Image.new("RGB", (12, 10), color="white").save(buffer, format="PNG")
    response = client.post(
        "/api/analyze",
        data={"content": "Campaign image description", "content_type": "Campaign"},
        files={"file": ("asset.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["image_analysis"]["format"] == "png"
    assert any(
        "Logo geometry" in limitation
        for limitation in body["image_analysis"]["limitations"]
    )
    assert any(item["title"] == "Image alternative text not provided" for item in body["findings"])

    invalid = client.post(
        "/api/analyze",
        data={"content": "A valid draft"},
        files={"file": ("asset.png", b"not an image", "image/png")},
    )
    assert invalid.status_code == 422


def test_image_upload_size_limit_is_enforced(client, monkeypatch):
    from app.routes import analysis

    monkeypatch.setattr(analysis, "MAX_UPLOAD_SIZE", 3)
    response = client.post(
        "/api/analyze",
        data={"content": "A valid draft"},
        files={"file": ("asset.png", b"four", "image/png")},
    )
    assert response.status_code == 413


def test_configured_palette_comparison_creates_advisory_finding(client, monkeypatch):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 0)
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={"file": ("asset.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["image_analysis"]["palette_comparison"]["potential_mismatch"]
    assert any(item["category"] == "visual_brand" for item in response.json()["findings"])


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract runtime is optional")
def test_optional_tesseract_ocr_extracts_image_copy():
    from app.services.image_analyzer import inspect_image

    image = Image.new("RGB", (900, 140), "white")
    ImageDraw.Draw(image).text(
        (25, 40),
        "guarantees 100% success",
        font=ImageFont.load_default(size=48),
        fill="black",
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    result = inspect_image(buffer.getvalue(), ocr_enabled=True)
    assert result["ocr_available"]
    assert "guarantees 100% success" in result["extracted_text"].lower()


def test_analytics_are_based_on_persisted_review_data(client):
    client.post(
        "/api/analyze",
        json={"content": "Our product guarantees results.", "title": "Claim review"},
    )
    summary = client.get("/api/analytics/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_reviews"] == 1
    assert body["total_issues"] >= 1
    assert body["pending_approvals"] == 1
    assert body["issues_by_severity"]["high"] >= 1
    assert any(row["status"] == "pending" for row in body["status_distribution"])

    blind_spots = client.get("/api/analytics/guideline-blind-spots")
    assert blind_spots.status_code == 200
    assert blind_spots.json()[0]["guideline"] == "Substantiated promotional claims"
    assert "does not prove guideline ambiguity" in blind_spots.json()[0]["heuristic"]


def test_guideline_delete_and_missing_resources(client):
    response = client.post(
        "/api/guidelines",
        json={
            "name": "Temporary rule",
            "category": "tone",
            "description": "A test guideline.",
        },
    )
    guideline_id = response.json()["id"]
    assert client.delete("/api/guidelines/{}".format(guideline_id)).status_code == 204
    assert client.delete("/api/guidelines/{}".format(guideline_id)).status_code == 404
    assert client.get("/api/reviews/12345").status_code == 404


def test_approved_sources_retrieval_and_expiry_metadata(client):
    guideline = next(
        item for item in client.get("/api/guidelines").json()
        if item["category"] == "factual_claim"
    )
    source = client.post(
        "/api/sources",
        json={
            "name": "Product metrics, Q4",
            "content": "The annual subscription price is $240. This source confirms current pricing.",
            "guideline_id": guideline["id"],
            "source_date": "2026-10-01",
            "expiry_date": "2027-01-01",
        },
    )
    assert source.status_code == 201
    source_id = source.json()["id"]

    response = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source_id],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["factual_verification"] == "candidate_evidence_requires_human_review"
    assert body["retrieved_evidence"][0]["name"] == "Product metrics, Q4"
    assert body["retrieved_evidence"][0]["verification"] == "candidate_evidence_requires_human_review"
    factual = next(item for item in body["findings"] if item["category"] == "factual_claim")
    assert "current approved source excerpt matched" in factual["explanation"]

    unknown = client.post(
        "/api/analyze",
        json={"content": "Price is $240", "source_ids": [99999]},
    )
    assert unknown.status_code == 422
    assert client.delete("/api/sources/{}".format(source_id)).status_code == 204
    unsafe_url = client.post(
        "/api/sources",
        json={
            "name": "Unsafe link",
            "content": "Trusted copy",
            "url": "javascript:alert(1)",
        },
    )
    assert unsafe_url.status_code == 422


def test_text_source_file_upload_and_unsupported_format(client):
    upload = client.post(
        "/api/sources/upload",
        data={"name": "Uploaded source", "source_date": "2026-10-01"},
        files={"file": ("facts.txt", b"Approved product price is $240.", "text/plain")},
    )
    assert upload.status_code == 201
    assert upload.json()["content"] == "Approved product price is $240."

    unsupported = client.post(
        "/api/sources/upload",
        files={"file": ("facts.docx", b"not supported", "application/octet-stream")},
    )
    assert unsupported.status_code == 422


def test_pdf_source_upload_extracts_searchable_text(client):
    writer = PdfWriter()
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
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (annual subscription price is $240) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf_bytes = BytesIO()
    writer.write(pdf_bytes)

    response = client.post(
        "/api/sources/upload",
        files={"file": ("price-sheet.pdf", pdf_bytes.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201
    assert "annual subscription price is $240" in response.json()["content"]


def test_expired_source_is_never_presented_as_current_evidence(client):
    source = client.post(
        "/api/sources",
        json={
            "name": "Expired product price",
            "content": "The annual subscription price is $240.",
            "source_date": "2024-01-01",
            "expiry_date": "2024-12-31",
        },
    )
    assert source.status_code == 201
    result = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source.json()["id"]],
        },
    ).json()
    assert result["retrieved_evidence"][0]["freshness"] == "expired"
    assert "Only expired approved source material matched" in next(
        item["explanation"]
        for item in result["findings"]
        if item["category"] == "factual_claim"
    )


def test_review_activity_records_analysis_comment_and_revision(client):
    review_id = client.post(
        "/api/analyze", json={"content": "A simple draft."}
    ).json()["id"]
    client.post(
        "/api/reviews/{}/comments".format(review_id),
        json={"comment": "Review this sentence."},
    )
    client.post(
        "/api/reviews/{}/revisions".format(review_id),
        json={"content": "A revised draft."},
    )
    activity = client.get("/api/reviews/{}/activity".format(review_id))
    assert activity.status_code == 200
    actions = {entry["action"] for entry in activity.json()}
    assert {"analysis_completed", "comment_added", "revision_added"} <= actions


def test_review_websocket_receives_persisted_comments(client):
    review_id = client.post(
        "/api/analyze", json={"content": "A websocket test draft."}
    ).json()["id"]
    with client.websocket_connect(
        "/api/reviews/{}/collaboration".format(review_id)
    ) as websocket:
        assert websocket.receive_json()["type"] == "presence"
        response = client.post(
            "/api/reviews/{}/comments".format(review_id),
            json={"comment": "Live team note", "author": "Reviewer"},
        )
        assert response.status_code == 201
        event = websocket.receive_json()
        assert event["type"] == "comment_created"
        assert event["payload"]["comment"] == "Live team note"
        websocket.send_json(
            {"type": "draft_changed", "content": "Collaboratively edited text."}
        )
        draft = websocket.receive_json()
        assert draft["type"] == "draft_changed"
        revision = client.post(
            "/api/reviews/{}/revisions".format(review_id),
            json={"content": "Persisted collaborative text"},
        )
        assert revision.status_code == 201
        assert websocket.receive_json()["type"] == "revision_created"
    assert client.get("/api/reviews/{}".format(review_id)).json()["content"] == "Persisted collaborative text"


def test_llm_provider_errors_are_explicit_and_do_not_save_reviews(client, monkeypatch):
    from app.routes import analysis
    from app.services.llm_analyzer import LLMProviderError

    async def fail_provider(*_args, **_kwargs):
        raise LLMProviderError("Configured LLM provider request failed (ConnectError).")

    monkeypatch.setattr(analysis, "llm_enabled", lambda: True)
    monkeypatch.setattr(analysis, "analyze_with_llm", fail_provider)
    response = client.post("/api/analyze", json={"content": "A draft."})
    assert response.status_code == 502
    assert "provider request failed" in response.json()["detail"]
    assert client.get("/api/reviews").json()["total"] == 0


def test_configured_llm_findings_are_merged_and_labeled(client, monkeypatch):
    from app.routes import analysis

    async def provide_finding(content, guidelines, evidence):
        return [{
            "category": "tone_of_voice",
            "severity": "low",
            "title": "Review the tone",
            "explanation": "The phrasing may not match the guidelines.",
            "matched_text": content,
            "suggestion": "Use the approved voice.",
            "guideline": None,
            "confidence": 0.7,
            "source": "Configured LLM advisory",
            "guideline_id": None,
        }]

    monkeypatch.setattr(analysis, "llm_enabled", lambda: True)
    monkeypatch.setattr(analysis, "analyze_with_llm", provide_finding)
    response = client.post("/api/analyze", json={"content": "A neutral draft."})
    assert response.status_code == 200
    assert response.json()["analysis_engine"] == "rules+configured_llm"
    assert any(finding["category"] == "tone_of_voice" for finding in response.json()["findings"])

import csv
from io import BytesIO, StringIO

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.content_review import ReviewRevision
from app.models.review_comment import (
    ReviewActivity,
    ReviewApprovalDecision,
    ReviewComment,
)
from app.models.user import User
from app.services.auth_service import hash_password
from app.services.report_exports import _spreadsheet_safe


def _create_user(test_engine, monkeypatch, email, role, name):
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    with Session(test_engine) as db:
        user = User(
            email=email,
            display_name=name,
            password_hash=hash_password("strong-test-password"),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "strong-test-password"},
    )
    assert response.status_code == 200


def _pdf_text(response):
    reader = PdfReader(BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_review_pdf_uses_review_data_and_hides_internal_comments_from_contributor(
    client, test_engine, monkeypatch
):
    contributor_id = _create_user(
        test_engine,
        monkeypatch,
        "report-owner@example.test",
        "contributor",
        "Report Owner",
    )
    reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "report-reviewer@example.test",
        "reviewer",
        "Report Reviewer",
    )
    _login(client, "report-owner@example.test")
    response = client.post(
        "/api/analyze",
        json={
            "title": "Quarterly launch",
            "content": "This product is guaranteed to work.",
            "content_type": "Campaign",
        },
    )
    assert response.status_code == 200
    review_id = response.json()["id"]

    with Session(test_engine) as db:
        db.add_all(
            [
                ReviewComment(
                    review_id=review_id,
                    author="Contributor",
                    comment="Public reviewer note.",
                    is_internal=False,
                ),
                ReviewComment(
                    review_id=review_id,
                    author="Reviewer",
                    comment="Restricted reviewer deliberation.",
                    is_internal=True,
                ),
                ReviewRevision(
                    review_id=review_id,
                    title="Revision one",
                    content="Updated campaign copy.",
                    author_id=reviewer_id,
                ),
                ReviewApprovalDecision(
                    review_id=review_id,
                    reviewer_id=reviewer_id,
                    version_id=0,
                    decision="approved",
                    reason="Evidence reviewed.",
                ),
                ReviewActivity(
                    review_id=review_id,
                    action="revision_created",
                    actor="Report Reviewer",
                    details={"revision": "one"},
                ),
            ]
        )
        db.commit()

    report = client.get(f"/api/reviews/{review_id}/report.pdf")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert "private, no-store" in report.headers["cache-control"]
    text = _pdf_text(report)
    assert "Quarterly launch" in text
    assert "Risk score" in text
    assert "Public reviewer note." in text
    assert "Revision one" in text
    assert "approved" in text
    assert "revision_created" in text
    assert "Restricted reviewer deliberation." not in text

    outsider_id = _create_user(
        test_engine, monkeypatch, "other@example.test", "contributor", "Other"
    )
    assert outsider_id != contributor_id
    _login(client, "other@example.test")
    assert client.get(f"/api/reviews/{review_id}/report.pdf").status_code == 404


def test_analytics_csv_and_pdf_respect_date_filters_and_have_download_headers(client):
    review_id = client.post(
        "/api/analyze",
        json={
            "title": "Exportable review",
            "content": "This product is guaranteed to work.",
        },
    ).json()["id"]
    submitted_at = client.get(f"/api/reviews/{review_id}").json()["submitted_at"]
    today = submitted_at[:10]
    csv_response = client.get(
        "/api/analytics/export.csv",
        params={"start_date": today, "end_date": today},
    )
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "attachment;" in csv_response.headers["content-disposition"]
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8-sig"))))
    values = {(row[0], row[1]): row[2] for row in rows[1:]}
    assert values[("reviews", "total_reviews")] == "1"
    assert values[("findings", "total_issues")] == str(
        client.get(f"/api/reviews/{review_id}").json()["issue_count"]
    )
    assert ("severity", "critical") in values
    assert ("risk_distribution", "critical") in values

    pdf_response = client.get(
        "/api/analytics/report.pdf",
        params={"start_date": today, "end_date": today},
    )
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    pdf_text = _pdf_text(pdf_response)
    assert "Workspace analytics report" in pdf_text
    assert "Exportable review" not in pdf_text
    assert "All time" not in pdf_text

    invalid = client.get(
        "/api/analytics/export.csv",
        params={"start_date": "2026-02-02", "end_date": "2026-02-01"},
    )
    assert invalid.status_code == 422


def test_analytics_csv_escapes_spreadsheet_formula_prefixes():
    assert _spreadsheet_safe("=1+1") == "'=1+1"
    assert _spreadsheet_safe("  @SUM(A1:A2)") == "'  @SUM(A1:A2)"
    assert _spreadsheet_safe("-5") == "'-5"
    assert _spreadsheet_safe(5) == 5

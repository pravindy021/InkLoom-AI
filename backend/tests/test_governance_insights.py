from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.brand_guideline import BrandGuideline
from app.models.content_review import ContentReview, ReviewFinding
from app.models.user import User
from app.services.governance_insights import build_governance_insights
from app.services.auth_service import hash_password


def _finding(
    finding_id,
    review_id,
    guideline_id=None,
    category="terminology",
    title="Repeated issue",
    matched_text="phrase",
    created_at=None,
    status="pending",
):
    return (
        finding_id,
        review_id,
        guideline_id,
        category,
        "medium",
        title,
        status,
        matched_text,
        created_at,
    )


def test_aggregation_deduplicates_exact_rows_and_counts_issue_categories():
    january = datetime(2026, 1, 15, tzinfo=timezone.utc)
    insights = build_governance_insights(
        [
            _finding(1, 10, category="tone", created_at=january),
            _finding(2, 10, category="tone", created_at=january),
            _finding(3, 11, category="tone", created_at=january),
            _finding(4, 12, category="visual_brand", created_at=january),
        ],
        {},
        review_rows=[(10, january), (11, january), (12, january)],
    )

    assert insights["issue_counts"]["unique_findings"] == 3
    assert insights["issue_counts"]["duplicate_finding_records_ignored"] == 1
    assert insights["recurring_categories"] == [
        {"category": "tone", "finding_count": 2, "review_count": 2}
    ]
    assert insights["trends_by_month"] == [
        {"month": "2026-01", "review_count": 3, "unique_findings": 3}
    ]


def test_guideline_clarity_recommendation_requires_multiple_reviews():
    date_value = datetime(2026, 2, 1, tzinfo=timezone.utc)
    insights = build_governance_insights(
        [
            _finding(1, 10, guideline_id=4, category="factual_claim", created_at=date_value),
            _finding(2, 11, guideline_id=4, category="factual_claim", created_at=date_value),
            _finding(3, 12, guideline_id=5, category="visual_brand", created_at=date_value),
        ],
        {4: "Substantiated claims", 5: "Visual palette"},
    )

    assert insights["guideline_recurrence"] == [
        {
            "guideline_id": 4,
            "guideline": "Substantiated claims",
            "finding_count": 2,
            "review_count": 2,
        }
    ]
    assert len(insights["recommendations"]) == 2
    assert insights["recommendations"][0]["type"] == "clarify_guideline"
    assert insights["recommendations"][0]["evidence"]["review_count"] == 2


def test_empty_data_and_missing_timestamps_are_reported_without_inference():
    insights = build_governance_insights(
        [_finding(1, 3, created_at=None, status="legacy")],
        {},
        review_rows=[(3, None)],
    )

    assert insights["recurring_categories"] == []
    assert insights["guideline_recurrence"] == []
    assert insights["trends_by_month"] == []
    assert insights["issue_counts"]["status_unknown"] == 1
    assert insights["data_quality"]["missing_review_timestamps"] == 1
    assert insights["recommendations"] == []
    empty = build_governance_insights([], {})
    assert empty["issue_counts"]["unique_findings"] == 0
    assert empty["trends_by_month"] == []


def test_finding_statuses_separate_explicit_resolution_from_pending_and_unknown():
    insights = build_governance_insights(
        [
            _finding(1, 1, status="resolved"),
            _finding(2, 2, status="pending", title="Another finding"),
            _finding(3, 3, status="legacy", title="Legacy finding"),
        ],
        {},
    )

    assert insights["issue_counts"]["resolved"] == 1
    assert insights["issue_counts"]["unresolved"] == 1
    assert insights["issue_counts"]["status_unknown"] == 1


def test_governance_insights_api_uses_date_window_and_aggregates_persisted_rows(
    client, test_engine
):
    old_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
    current_date = datetime(2026, 2, 15, tzinfo=timezone.utc)
    with Session(test_engine) as db:
        guideline = BrandGuideline(
            name="Clear claims",
            category="claims",
            description="Support claims.",
            examples=[],
            prohibited_terms=[],
            preferred_terms=[],
            approved_sources=[],
            status="approved",
            is_active=True,
        )
        db.add(guideline)
        db.flush()
        for title, created_at in (
            ("First", old_date),
            ("Second", current_date),
        ):
            review = ContentReview(
                title=title,
                content="Private reviewed content",
                content_type="text",
                status="pending",
                guideline_ids=[guideline.id],
                created_at=created_at,
                analysis_timestamp=created_at,
            )
            db.add(review)
            db.flush()
            db.add(
                ReviewFinding(
                    review_id=review.id,
                    guideline_id=guideline.id,
                    category="factual_claim",
                    severity="medium",
                    title="Verify factual statement",
                    explanation="Explanation",
                    matched_text="sensitive quoted text",
                    suggestion="Check evidence",
                    source=guideline.name,
                    confidence=0.5,
                    review_status="pending",
                )
            )
        db.commit()

    response = client.get(
        "/api/analytics/governance-insights",
        params={"start_date": "2026-01-01", "end_date": "2026-02-28"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["date_range"] == {
        "start_date": "2026-01-01",
        "end_date": "2026-02-28",
    }
    assert body["guideline_recurrence"][0]["review_count"] == 2
    assert [row["month"] for row in body["trends_by_month"]] == [
        "2026-01",
        "2026-02",
    ]
    assert "sensitive quoted text" not in response.text
    blind_spots = client.get("/api/analytics/guideline-blind-spots")
    assert blind_spots.status_code == 200
    assert blind_spots.json()[0]["review_count"] == 2
    assert "does not prove guideline ambiguity" in blind_spots.json()[0]["heuristic"]


def test_governance_insights_requires_authentication_and_allows_analytics_role(
    client, test_engine
):
    client.cookies.clear()
    assert client.get("/api/analytics/governance-insights").status_code == 401

    with Session(test_engine) as db:
        db.add(
            User(
                email="insights-contributor@example.test",
                display_name="Insights Contributor",
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
            "email": "insights-contributor@example.test",
            "password": "strong-test-password",
        },
    )
    assert login.status_code == 200
    assert client.get("/api/analytics/governance-insights").status_code == 200

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import migrate_review_workflow
from app.models.review_comment import ReviewActivity
from app.models.user import User
from app.models.visual_asset import ReviewVisualAttachment
from app.services import auth_service


def _create_user(test_engine, monkeypatch, email, role, name):
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    with Session(test_engine) as db:
        user = User(
            email=email,
            display_name=name,
            password_hash=auth_service.hash_password("strong-test-password"),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        return user.id


def _login(client, email):
    password = (
        "test-admin-password-123"
        if email == "admin@example.test"
        else "strong-test-password"
    )
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200


def test_archive_is_admin_only_and_requires_authentication(
    client, test_engine, monkeypatch
):
    review_id = client.post(
        "/api/analyze",
        json={"content": "A review that needs a permission check."},
    ).json()["id"]
    _create_user(
        test_engine,
        monkeypatch,
        "archive-reviewer@example.test",
        "reviewer",
        "Archive Reviewer",
    )
    _create_user(
        test_engine,
        monkeypatch,
        "archive-contributor@example.test",
        "contributor",
        "Archive Contributor",
    )

    client.cookies.clear()
    assert client.delete(f"/api/reviews/{review_id}").status_code == 401

    _login(client, "archive-reviewer@example.test")
    assert client.delete(f"/api/reviews/{review_id}").status_code == 403

    client.cookies.clear()
    _login(client, "archive-contributor@example.test")
    assert client.delete(f"/api/reviews/{review_id}").status_code == 403

    with Session(test_engine) as db:
        assert db.get(User, 1) is not None
        assert db.query(ReviewActivity).filter_by(
            review_id=review_id,
            action="review_archived",
        ).count() == 0


def test_admin_archives_review_and_preserves_audit_and_attachments(
    client, test_engine
):
    review = client.post(
        "/api/analyze",
        json={"content": "A review with retained attachment and history."},
    ).json()
    review_id = review["id"]
    with Session(test_engine) as db:
        db.add(
            ReviewVisualAttachment(
                review_id=review_id,
                filename="review-{}.png".format(review_id),
                media_type="image/png",
                file_data=b"retained-image",
                analysis_metadata={},
            )
        )
        db.commit()

    response = client.delete(f"/api/reviews/{review_id}")
    assert response.status_code == 200
    result = response.json()
    assert result["id"] == review_id
    assert result["archived_at"]
    assert result["archived_by_id"]

    with Session(test_engine) as db:
        from app.models.content_review import ContentReview, ReviewAnalysisRun

        saved = db.get(ContentReview, review_id)
        assert saved.archived_at is not None
        assert saved.archived_by_id == result["archived_by_id"]
        assert db.query(ReviewAnalysisRun).filter_by(review_id=review_id).count() == 1
        attachment = db.query(ReviewVisualAttachment).filter_by(
            review_id=review_id
        ).one()
        assert attachment.file_data == b"retained-image"
        event = db.query(ReviewActivity).filter_by(
            review_id=review_id,
            action="review_archived",
        ).one()
        assert event.actor == "Workspace Admin"
        assert event.created_at is not None
        assert event.details["action"] == "archived"
        assert event.details["archived_at"] == result["archived_at"]

    listing = client.get("/api/reviews")
    assert listing.status_code == 200
    assert review_id not in {item["id"] for item in listing.json()["items"]}
    assert listing.json()["total"] == 0

    assert client.get(f"/api/reviews/{review_id}").status_code == 200
    report = client.get(f"/api/reviews/{review_id}/report.pdf")
    assert report.status_code == 200
    assert report.headers["content-type"] == "application/pdf"
    assert client.delete(f"/api/reviews/{review_id}").status_code == 409


def test_review_archive_migration_is_additive_and_idempotent():
    legacy_engine = create_engine("sqlite://")
    try:
        with legacy_engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    """
                    CREATE TABLE content_reviews (
                        id INTEGER PRIMARY KEY,
                        title VARCHAR(240) NOT NULL,
                        content TEXT NOT NULL,
                        content_type VARCHAR(80) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        reviewer VARCHAR(160),
                        guideline_ids JSON NOT NULL,
                        analysis_timestamp DATETIME NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO content_reviews
                        (id, title, content, content_type, status, reviewer,
                         guideline_ids, analysis_timestamp, created_at, updated_at)
                    VALUES
                        (37, 'Existing review', 'Keep this data', 'Email',
                         'pending', NULL, '[]', '2026-11-03 10:00:00',
                         '2026-11-03 10:00:00', '2026-11-03 10:00:00')
                    """
                )
            )

        migrate_review_workflow(legacy_engine)
        migrate_review_workflow(legacy_engine)

        columns = {
            column["name"]: column
            for column in inspect(legacy_engine).get_columns("content_reviews")
        }
        assert "archived_at" in columns
        assert "archived_by_id" in columns
        with legacy_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id, title, content, status, archived_at, archived_by_id "
                    "FROM content_reviews WHERE id = 37"
                )
            ).one()
        assert tuple(row) == (
            37,
            "Existing review",
            "Keep this data",
            "pending",
            None,
            None,
        )
    finally:
        legacy_engine.dispose()

from io import BytesIO
import os
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
    assert health.json()["evidence_retrieval_mode"] in {
        "embedding_cosine",
        "bm25_lexical",
    }
    assert client.get("/docs").status_code == 200

    guidelines = client.get("/api/guidelines")
    assert guidelines.status_code == 200
    assert any(item["is_seed"] for item in guidelines.json())


def test_authentication_uses_http_only_cookie_and_protects_workspace(client):
    client.cookies.clear()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/guidelines").status_code == 401

    login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/api/guidelines").status_code == 200

    assert client.post(
        "/api/auth/logout",
    ).status_code == 204
    assert client.get("/api/guidelines").status_code == 401


def test_password_recovery_requires_configured_smtp(client, monkeypatch):
    from app.routes import auth

    monkeypatch.setattr(auth, "SMTP_ENABLED", False)
    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_password_recovery_response_is_generic_and_stores_only_token_hash(
    client, test_engine, monkeypatch
):
    import hashlib

    from sqlalchemy.orm import Session

    from app.models.user import PasswordResetToken, RecoveryAttempt
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda email, url: sent.append((email, url)),
    )

    known = client.post(
        "/api/auth/password/forgot",
        json={"email": " ADMIN@example.test "},
    )
    unknown = client.post(
        "/api/auth/password/forgot",
        json={"email": "missing@example.test"},
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert sent[0][0] == "admin@example.test"
    assert sent[0][1].startswith("http://localhost:5173/reset-password#token=")
    assert sent[1] == ("missing@example.test", None)

    raw_token = sent[0][1].split("token=", 1)[1]
    with Session(test_engine) as db:
        record = db.query(PasswordResetToken).one()
        assert record.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert record.token_hash != raw_token
        assert record.used_at is None
        attempts = db.query(RecoveryAttempt).all()
        assert len(attempts) == 2
        email_fingerprints = {row.email_fingerprint for row in attempts}
        assert hashlib.sha256(
            b"inkloom-recovery-email:admin@example.test"
        ).hexdigest() in email_fingerprints
        assert hashlib.sha256(
            b"inkloom-recovery-email:missing@example.test"
        ).hexdigest() in email_fingerprints
        assert all(
            row.ip_fingerprint
            == hashlib.sha256(b"inkloom-recovery-ip:testclient").hexdigest()
            for row in attempts
        )


def test_password_reset_is_single_use_and_revokes_existing_sessions(
    client, test_engine, monkeypatch
):
    from urllib.parse import unquote

    from sqlalchemy.orm import Session

    from app.models.user import AuthSession, PasswordResetToken, User
    from app.routes import auth
    from app.services.auth_service import verify_password

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda _email, url: sent.append(url),
    )
    recovery = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert recovery.status_code == 202
    token = unquote(sent[0].split("token=", 1)[1])
    result = client.post(
        "/api/auth/password/reset",
        json={"token": token, "new_password": "a-new-strong-password-456"},
    )
    assert result.status_code == 200
    assert "set-cookie" in result.headers
    assert client.get("/api/auth/me").status_code == 401
    invalid = client.post(
        "/api/auth/password/reset",
        json={"token": "x" * 40, "new_password": "another-strong-password-789"},
    )
    assert invalid.status_code == 400
    assert client.post(
        "/api/auth/password/reset",
        json={"token": token, "new_password": "another-strong-password-789"},
    ).status_code == 400

    with Session(test_engine) as db:
        user = db.query(User).one()
        assert verify_password("a-new-strong-password-456", user.password_hash)
        assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0
        record = db.query(PasswordResetToken).one()
        assert record.used_at is not None

    login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "a-new-strong-password-456",
        },
    )
    assert login.status_code == 200


def test_password_reset_rejects_expired_tokens(client, test_engine, monkeypatch):
    from datetime import timedelta
    from datetime import datetime, timezone

    from sqlalchemy.orm import Session

    from app.models.user import PasswordResetToken, User
    from app.routes import auth
    from app.services.auth_service import verify_password

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(auth, "send_recovery_email", lambda _email, url: sent.append(url))
    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 202
    token = sent[0].split("token=", 1)[1]
    with Session(test_engine) as db:
        record = db.query(PasswordResetToken).one()
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    expired = client.post(
        "/api/auth/password/reset",
        json={"token": token, "new_password": "a-new-strong-password-456"},
    )
    assert expired.status_code == 400
    with Session(test_engine) as db:
        user = db.query(User).one()
        assert verify_password("test-admin-password-123", user.password_hash)
        assert db.query(PasswordResetToken).one().used_at is None


def test_password_recovery_email_failure_does_not_leave_reset_token(
    client, test_engine, monkeypatch
):
    from sqlalchemy.orm import Session

    from app.models.user import PasswordResetToken
    from app.routes import auth
    from app.services.password_recovery import RecoveryEmailError

    def fail_sending(_email, _url):
        raise RecoveryEmailError("delivery failed")

    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(auth, "send_recovery_email", fail_sending)
    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 503
    assert "delivery failed" not in response.text
    with Session(test_engine) as db:
        assert db.query(PasswordResetToken).count() == 0


def test_password_recovery_is_rate_limited(client, monkeypatch):
    from app.routes import auth
    from app.services import password_recovery

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda email, url: sent.append((email, url)),
    )
    monkeypatch.setattr(password_recovery, "RECOVERY_EMAIL_LIMIT", 2)

    for _ in range(2):
        response = client.post(
            "/api/auth/password/forgot",
            json={"email": "unknown@example.test"},
        )
        assert response.status_code == 202

    blocked = client.post(
        "/api/auth/password/forgot",
        json={"email": "unknown@example.test"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert len(sent) == 2


def test_login_rejects_incorrect_password_without_creating_session(client):
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "incorrect-password",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect."
    assert "set-cookie" not in response.headers


def test_login_throttles_repeated_failures_with_retry_after(
    client, test_engine, monkeypatch
):
    from app.services import auth_service
    from app.models.user import LoginAttempt
    from sqlalchemy.orm import Session

    monkeypatch.setattr(auth_service, "LOGIN_PAIR_LIMIT", 3)
    client.cookies.clear()
    payload = {"email": "admin@example.test", "password": "wrong-password"}
    for _ in range(3):
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 401

    blocked = client.post("/api/auth/login", json=payload)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many sign-in attempts. Try again later."
    assert int(blocked.headers["retry-after"]) > 0
    assert "set-cookie" not in blocked.headers

    with Session(test_engine) as db:
        # Stored identifiers are fingerprints; the submitted email and password
        # are never retained in the rate-limit records.
        attempt = db.query(LoginAttempt).first()
        assert attempt is not None
        assert attempt.email_fingerprint != "admin@example.test"
        assert len(attempt.ip_fingerprint) == 64
        assert not hasattr(attempt, "password")


def test_successful_login_clears_email_failure_history(
    client, test_engine, monkeypatch
):
    from app.services import auth_service
    from app.models.user import LoginAttempt
    from sqlalchemy.orm import Session

    monkeypatch.setattr(auth_service, "LOGIN_PAIR_LIMIT", 3)
    client.cookies.clear()
    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={"email": "admin@example.test", "password": "wrong-password"},
        ).status_code == 401

    success = client.post(
        "/api/auth/login",
        json={
            "email": " admin@example.test ",
            "password": "test-admin-password-123",
        },
    )
    assert success.status_code == 200

    with Session(test_engine) as db:
        assert db.query(LoginAttempt).count() == 0

    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "wrong-password"},
    ).status_code == 401


def test_login_failure_window_expires(client, monkeypatch):
    from datetime import timedelta

    from app.services import auth_service

    start = auth_service._utc_now()
    current = [start]
    monkeypatch.setattr(auth_service, "_utc_now", lambda: current[0])
    monkeypatch.setattr(auth_service, "LOGIN_RATE_WINDOW", timedelta(seconds=60))
    monkeypatch.setattr(auth_service, "LOGIN_PAIR_LIMIT", 1)
    client.cookies.clear()
    payload = {"email": "admin@example.test", "password": "wrong-password"}

    assert client.post("/api/auth/login", json=payload).status_code == 401
    assert client.post("/api/auth/login", json=payload).status_code == 429

    current[0] = start + timedelta(seconds=61)
    assert client.post("/api/auth/login", json=payload).status_code == 401


def test_login_email_and_ip_limits_apply_across_pairs(test_engine, monkeypatch):
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.user import LoginAttempt
    from app.services import auth_service

    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(auth_service, "LOGIN_RATE_WINDOW", timedelta(minutes=15))
    monkeypatch.setattr(auth_service, "LOGIN_EMAIL_LIMIT", 2)
    monkeypatch.setattr(auth_service, "LOGIN_IP_LIMIT", 3)
    now = auth_service._utc_now()
    with Session(test_engine) as db:
        auth_service.record_login_failure(db, "person@example.test", "192.0.2.1", now)
        auth_service.record_login_failure(db, "person@example.test", "192.0.2.2", now)
        assert auth_service.login_retry_after(
            db, "person@example.test", "192.0.2.3", now
        ) > 0

    with Session(test_engine) as db:
        db.query(LoginAttempt).delete()
        db.commit()
        auth_service.record_login_failure(db, "first@example.test", "192.0.2.9", now)
        auth_service.record_login_failure(db, "second@example.test", "192.0.2.9", now)
        auth_service.record_login_failure(db, "third@example.test", "192.0.2.9", now)
        assert auth_service.login_retry_after(
            db, "another@example.test", "192.0.2.9", now
        ) > 0


def test_bootstrap_missing_configuration_does_not_create_admin(
    test_engine, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_PASSWORD", "")
    app = create_app(test_engine)
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"email": "admin@example.test", "password": "not-configured"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Email or password is incorrect."
    from sqlalchemy.orm import Session

    with Session(test_engine) as db:
        assert db.query(User).count() == 0


def test_bootstrap_creates_initial_admin_when_database_is_empty(
    test_engine, monkeypatch
):
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_EMAIL", "first-admin@example.test")
    monkeypatch.setattr(
        auth_service, "BOOTSTRAP_ADMIN_PASSWORD", "first-admin-password-123"
    )
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    Base.metadata.create_all(bind=test_engine)
    with Session(test_engine) as db:
        auth_service.bootstrap_admin(db)
        admin = db.query(User).one()
        assert admin.email == "first-admin@example.test"
        assert admin.role == "admin"
        assert auth_service.verify_password(
            "first-admin-password-123", admin.password_hash
        )


def test_bootstrap_does_not_reset_an_existing_admin_account(
    test_engine, monkeypatch
):
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setattr(
        auth_service, "BOOTSTRAP_ADMIN_PASSWORD", "new-bootstrap-password-123"
    )
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    Base.metadata.create_all(bind=test_engine)
    with Session(test_engine) as db:
        existing_hash = auth_service.hash_password("existing-admin-password-123")
        db.add(
            User(
                email="admin@example.test",
                display_name="Existing Admin",
                password_hash=existing_hash,
                role="admin",
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()
        auth_service.bootstrap_admin(db)
        admin = db.query(User).one()
        assert admin.password_hash == existing_hash
        assert auth_service.verify_password(
            "existing-admin-password-123", admin.password_hash
        )
        assert not auth_service.verify_password(
            "new-bootstrap-password-123", admin.password_hash
        )


def test_environment_loader_uses_explicit_file_without_overriding_shell(
    tmp_path, monkeypatch
):
    from app.config import load_environment

    env_file = tmp_path / ".env"
    env_file.write_text(
        "INKLOOM_TEST_FROM_FILE=file-value\n"
        "INKLOOM_TEST_FROM_SHELL=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("INKLOOM_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("INKLOOM_TEST_FROM_SHELL", "shell-value")

    assert load_environment(env_file)
    assert os.environ["INKLOOM_TEST_FROM_FILE"] == "file-value"
    assert os.environ["INKLOOM_TEST_FROM_SHELL"] == "shell-value"


def test_invited_contributor_sets_password_and_cannot_create_guidelines(client, monkeypatch):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )
    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "editor@example.test",
            "display_name": "Content Editor",
            "role": "contributor",
        },
    )
    assert invitation.status_code == 201
    body = invitation.json()
    assert body["user"]["must_change_password"]
    assert not body["user"]["is_active"]
    invite_token = sent[0].split("token=", 1)[1]
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-editor-password",
        },
    )
    assert accepted.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={
            "email": "editor@example.test",
            "password": "a-strong-editor-password",
        },
    )
    assert login.status_code == 200
    assert not login.json()["user"]["must_change_password"]
    assert client.get("/api/guidelines").status_code == 200
    assert client.post(
        "/api/guidelines",
        json={
            "name": "Unauthorized rule",
            "category": "tone",
            "description": "Should not be created by contributor.",
        },
    ).status_code == 403


def test_reviewer_can_decide_but_cannot_manage_users(client, monkeypatch):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )
    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "reviewer@example.test",
            "display_name": "Brand Reviewer",
            "role": "reviewer",
        },
    ).json()
    invite_token = sent[0].split("token=", 1)[1]
    review_id = client.post(
        "/api/analyze", json={"content": "A product draft."}
    ).json()["id"]
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-reviewer-password",
        },
    )
    assert accepted.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={
            "email": "reviewer@example.test",
            "password": "a-strong-reviewer-password",
        },
    )
    assert login.status_code == 200
    updated = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "approved", "reviewer": "Spoofed Name"},
    )
    assert updated.status_code == 200
    assert updated.json()["reviewer"] == "Brand Reviewer"
    assert client.get("/api/auth/users").status_code == 403


def test_admin_cannot_remove_the_last_active_admin(client):
    admin = client.get("/api/auth/me").json()
    response = client.patch(
        "/api/auth/users/{}".format(admin["id"]),
        json={"role": "reviewer", "is_active": False},
    )
    assert response.status_code == 422


def test_session_mutations_reject_untrusted_origins(client):
    response = client.post(
        "/api/analyze",
        headers={"origin": "https://untrusted.example"},
        json={"content": "An attempted cross-origin submission."},
    )
    assert response.status_code == 403
    assert client.get("/api/reviews").json()["total"] == 0


def test_deactivating_an_account_revokes_its_active_session(client, monkeypatch):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )
    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "disabled@example.test",
            "display_name": "Disabled Member",
            "role": "contributor",
        },
    ).json()
    invite_token = sent[0].split("token=", 1)[1]
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-member-password",
        },
    )
    assert accepted.status_code == 200
    invited_login = client.post(
        "/api/auth/login",
        json={
            "email": "disabled@example.test",
            "password": "a-strong-member-password",
        },
    )
    assert invited_login.status_code == 200
    revoked_cookie = client.cookies.get("inkloom_session")
    client.post("/api/auth/logout")

    admin_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert admin_login.status_code == 200
    member = invitation["user"]
    deactivated = client.patch(
        "/api/auth/users/{}".format(member["id"]),
        json={"role": "contributor", "is_active": False},
    )
    assert deactivated.status_code == 200
    client.cookies.clear()
    assert client.get(
        "/api/auth/me",
        headers={"cookie": "inkloom_session={}".format(revoked_cookie)},
    ).status_code == 401


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
    assert changed.json()["reviewer"] == "Workspace Admin"
    with Session(test_engine) as db:
        event = db.query(ReviewAuditEvent).filter_by(review_id=review_id).one()
        assert event.previous_status == "pending"
        assert event.new_status == "in_review"
        assert event.reviewer == "Workspace Admin"

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
    assert comment.json()["author"] == "Workspace Admin"

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
    assert body["image_analysis"]["layout_metrics"]["orientation"] == "landscape"
    assert "edge_density_percent" in body["image_analysis"]["layout_metrics"]
    assert any(
        "logo safe-zone compliance" in limitation
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


def test_visual_asset_reference_similarity_is_advisory(client, monkeypatch, tmp_path):
    from app.services import image_analyzer

    reference_path = tmp_path / "approved-logo.png"
    reference = Image.new("RGB", (64, 64), "black")
    draw = ImageDraw.Draw(reference)
    draw.rectangle((32, 0, 63, 63), fill="white")
    reference.save(reference_path, format="PNG")
    monkeypatch.setattr(image_analyzer, "BRAND_ASSET_REFERENCES", [str(reference_path)])
    monkeypatch.setattr(image_analyzer, "BRAND_ASSET_SIMILARITY_THRESHOLD", 95)

    different = Image.new("RGB", (64, 64), "black")
    draw = ImageDraw.Draw(different)
    draw.rectangle((0, 32, 63, 63), fill="white")
    buffer = BytesIO()
    different.save(buffer, format="PNG")
    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={"file": ("campaign.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    analysis = response.json()["image_analysis"]
    assert analysis["brand_asset_similarity"]["configured"]
    assert analysis["brand_asset_similarity"]["potential_mismatch"]
    assert any(
        finding["title"] == "Image differs from configured brand asset references"
        for finding in response.json()["findings"]
    )


def test_unreadable_configured_asset_reference_is_reported(client, monkeypatch, tmp_path):
    from app.services import image_analyzer

    monkeypatch.setattr(
        image_analyzer,
        "BRAND_ASSET_REFERENCES",
        [str(tmp_path / "missing-reference.png")],
    )
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={"file": ("campaign.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 503
    assert "configured brand asset reference" in response.json()["detail"]


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
    assert body["factual_verification"] == "claim_level_verification_advisory"
    assert body["retrieved_evidence"][0]["name"] == "Product metrics, Q4"
    assert body["retrieved_evidence"][0]["verification"] == "candidate_evidence_requires_human_review"
    factual = next(item for item in body["findings"] if item["category"] == "factual_claim")
    assert "current approved source excerpt matched" in factual["explanation"]
    assert factual["verification_status"] == "verified"
    assert factual["claim"] == "The annual subscription price is $240."
    assert factual["citations"][0]["name"] == "Product metrics, Q4"
    assert factual["confidence"] == factual["verification_confidence"]
    persisted = client.get("/api/reviews/{}".format(body["review_id"])).json()
    persisted_factual = next(
        item for item in persisted["findings"] if item["category"] == "factual_claim"
    )
    assert persisted_factual["verification_status"] == "verified"

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


def test_factual_claim_can_be_contradicted_by_approved_source(client):
    source = client.post(
        "/api/sources",
        json={
            "name": "Current subscription price",
            "content": "The annual subscription price is $240.",
        },
    )
    assert source.status_code == 201
    response = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $300.",
            "source_ids": [source.json()["id"]],
        },
    )
    assert response.status_code == 200
    finding = next(
        item for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )
    assert finding["verification_status"] == "contradicted"
    assert finding["citations"][0]["excerpt"]
    assert "conflicting value" in finding["verification_explanation"]


def test_factual_claim_without_evidence_remains_unverified(client):
    response = client.post(
        "/api/analyze",
        json={"content": "Our annual subscription price is $300."},
    )
    assert response.status_code == 200
    finding = next(
        item for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )
    assert finding["verification_status"] == "unverified"
    assert finding["citations"] == []
    assert finding["confidence"] < 0.5
    assert "not proof" in finding["verification_explanation"]


def test_external_search_failure_keeps_claim_unverified(client, monkeypatch):
    from app.routes import analysis
    from app.services.factual_verifier import ExternalSearchError

    async def unavailable(_claim):
        raise ExternalSearchError("provider error with no sensitive request data")

    monkeypatch.setattr(analysis, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(analysis, "FACT_CHECK_PROVIDER", "brave")
    monkeypatch.setattr(analysis, "TRUSTED_SOURCE_DOMAINS", ("example.com",))
    monkeypatch.setattr(analysis, "search_trusted_sources", unavailable)
    response = client.post(
        "/api/analyze",
        json={
            "content": "Our annual subscription price is $300.",
            "allow_external_verification": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["external_verification"]["status"] == "provider_error"
    assert response.json()["external_verification"]["claims_failed"] == 1
    finding = next(
        item for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )
    assert finding["verification_status"] == "unverified"


def test_external_search_requires_explicit_opt_in(client, monkeypatch):
    from app.routes import analysis

    calls = []

    async def should_not_run(claim):
        calls.append(claim)
        raise AssertionError("external lookup ran without consent")

    monkeypatch.setattr(analysis, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(analysis, "search_trusted_sources", should_not_run)
    response = client.post(
        "/api/analyze",
        json={"content": "Our annual subscription price is $300."},
    )
    assert response.status_code == 200
    assert response.json()["external_verification"]["status"] == "not_requested"
    assert calls == []


def test_external_search_discards_results_outside_trusted_domains(monkeypatch):
    from app.services import factual_verifier

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "web": {
                    "results": [
                        {
                            "title": "Trusted result",
                            "url": "https://news.example.com/facts",
                            "description": "The annual subscription price is $240.",
                        },
                        {
                            "title": "Lookalike result",
                            "url": "https://example.com.attacker.test/facts",
                            "description": "Untrusted text.",
                        },
                        {
                            "title": "Insecure result",
                            "url": "http://example.com/facts",
                            "description": "Insecure transport.",
                        },
                    ]
                }
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers, params):
            assert headers["X-Subscription-Token"] == "test-key"
            assert params["q"] == "The annual subscription price is $240."
            return FakeResponse()

    monkeypatch.setattr(factual_verifier, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(factual_verifier, "FACT_CHECK_API_KEY", "test-key")
    monkeypatch.setattr(factual_verifier, "TRUSTED_SOURCE_DOMAINS", ("example.com",))
    monkeypatch.setattr(factual_verifier.httpx, "AsyncClient", FakeClient)

    import asyncio

    results = asyncio.run(
        factual_verifier.search_trusted_sources(
            "The annual subscription price is $240."
        )
    )
    assert [item["name"] for item in results] == ["Trusted result"]
    assert results[0]["url"] == "https://news.example.com/facts"


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


def test_semantic_retrieval_finds_non_lexical_match_and_caches_source_vectors(
    client, monkeypatch
):
    from app.services import source_retrieval

    source_ids = []
    for name, content in [
        ("Booking guidance", "Reservations can be arranged with a booking team."),
        ("Astronomy note", "The distant galaxy contains many stars and planets."),
    ]:
        response = client.post(
            "/api/sources", json={"name": name, "content": content}
        )
        assert response.status_code == 201
        source_ids.append(response.json()["id"])

    monkeypatch.setattr(source_retrieval, "EMBEDDING_MODEL", "test-embedding")
    provider_inputs = []

    async def fake_embed(texts):
        provider_inputs.append(list(texts))
        vectors = []
        for text in texts:
            if text.startswith("Studies show"):
                vectors.append([1.0, 0.0])
            elif "booking team" in text:
                vectors.append([0.98, 0.2])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    monkeypatch.setattr(source_retrieval, "_embed_texts", fake_embed)
    payload = {
        "content": "Studies show our service is popular.",
        "source_ids": source_ids,
    }
    first = client.post("/api/analyze", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["evidence_retrieval_method"] == "embedding_cosine"
    assert first_body["retrieved_evidence"][0]["name"] == "Booking guidance"
    assert first_body["retrieved_evidence"][0]["verification"] == (
        "candidate_evidence_requires_human_review"
    )
    assert len(provider_inputs[0]) == 3

    second = client.post("/api/analyze", json=payload)
    assert second.status_code == 200
    assert second.json()["evidence_retrieval_method"] == "embedding_cosine"
    assert len(provider_inputs[1]) == 1


def test_semantic_embedding_provider_failure_is_explicit(client, monkeypatch):
    from app.routes import analysis
    from app.services import source_retrieval

    monkeypatch.setattr(source_retrieval, "EMBEDDING_MODEL", "test-embedding")

    async def fail_provider(*_args, **_kwargs):
        raise source_retrieval.EmbeddingProviderError(
            "Configured embedding provider request failed (ConnectError)."
        )

    monkeypatch.setattr(analysis, "retrieve_evidence", fail_provider)
    response = client.post(
        "/api/analyze", json={"content": "Studies show our service is popular."}
    )
    assert response.status_code == 502
    assert "embedding provider request failed" in response.json()["detail"]
    assert client.get("/api/reviews").json()["total"] == 0


def test_embedding_provider_uses_openai_compatible_endpoint_and_orders_vectors(
    monkeypatch,
):
    import asyncio
    import json
    import httpx

    from app.services import source_retrieval

    monkeypatch.setattr(source_retrieval, "LLM_API_BASE_URL", "https://provider.test/v1")
    monkeypatch.setattr(source_retrieval, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(source_retrieval, "EMBEDDING_MODEL", "test-embedding")

    async def handle_request(request):
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content)["model"] == "test-embedding"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    transport = httpx.MockTransport(handle_request)
    async_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = transport
        return async_client(*args, **kwargs)

    monkeypatch.setattr(source_retrieval.httpx, "AsyncClient", mocked_client)
    vectors = asyncio.run(source_retrieval._embed_texts(["query", "source chunk"]))
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


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
    assert any(
        entry["action"] == "analysis_completed"
        and entry["actor"] == "Workspace Admin"
        for entry in activity.json()
    )


def test_review_websocket_receives_persisted_comments(client):
    review_id = client.post(
        "/api/analyze", json={"content": "A websocket test draft."}
    ).json()["id"]
    with client.websocket_connect(
        "/api/reviews/{}/collaboration".format(review_id),
        headers={"origin": "http://localhost:5173"},
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

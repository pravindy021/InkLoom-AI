import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models.visual_brand import VisualBrandConfiguration, VisualBrandVersion
from app.models.user import User
from app.services.auth_service import hash_password


def _add_user(test_engine, email, role):
    with Session(test_engine) as db:
        db.add(
            User(
                email=email,
                display_name=role.title(),
                password_hash=hash_password("strong-test-password"),
                role=role,
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "strong-test-password"},
    )
    assert response.status_code == 200


def _palette(**overrides):
    result = {
        "primary": ["#123456"],
        "secondary": ["#456789"],
        "accent": ["#F0A020"],
    }
    result.update(overrides)
    return result


def test_admin_can_get_and_update_visual_brand_palette(client, test_engine):
    initial = client.get("/api/guidelines/visual-brand")
    assert initial.status_code == 200
    assert initial.json() == {
        "primary": [],
        "secondary": [],
        "accent": [],
        "version_number": 0,
        "updated_by": None,
        "created_at": None,
        "updated_at": None,
    }

    updated = client.put(
        "/api/guidelines/visual-brand",
        json=_palette(primary=["#abcdef"]),
    )
    assert updated.status_code == 200
    assert updated.json()["primary"] == ["#ABCDEF"]
    assert updated.json()["version_number"] == 1
    assert updated.json()["updated_by"] == "Workspace Admin"
    assert updated.json()["updated_at"] is not None

    with Session(test_engine) as db:
        configuration = db.get(VisualBrandConfiguration, 1)
        assert configuration is not None
        assert configuration.primary == ["#ABCDEF"]
        assert configuration.updated_by.display_name == "Workspace Admin"
        assert db.query(VisualBrandVersion).count() == 1


def test_reviewer_can_read_but_cannot_update_visual_brand_palette(
    client, test_engine
):
    _add_user(test_engine, "palette-reviewer@example.test", "reviewer")
    _login(client, "palette-reviewer@example.test")

    assert client.get("/api/guidelines/visual-brand").status_code == 200
    assert client.put(
        "/api/guidelines/visual-brand",
        json=_palette(),
    ).status_code == 403
    assert client.get("/api/guidelines/visual-brand/versions").status_code == 403


def test_contributor_can_read_palette_under_guideline_read_policy_but_not_update(
    client, test_engine
):
    _add_user(test_engine, "palette-contributor@example.test", "contributor")
    _login(client, "palette-contributor@example.test")

    assert client.get("/api/guidelines").status_code == 200
    assert client.get("/api/guidelines/visual-brand").status_code == 200
    assert client.put(
        "/api/guidelines/visual-brand",
        json=_palette(),
    ).status_code == 403
    assert client.get("/api/guidelines/visual-brand/versions").status_code == 403


def test_visual_brand_endpoints_require_authentication(client):
    client.cookies.clear()

    assert client.get("/api/guidelines/visual-brand").status_code == 401
    assert client.put(
        "/api/guidelines/visual-brand",
        json=_palette(),
    ).status_code == 401
    assert client.get("/api/guidelines/visual-brand/versions").status_code == 401


def test_visual_brand_rejects_invalid_hex_and_client_metadata(client):
    invalid_hex = client.put(
        "/api/guidelines/visual-brand",
        json=_palette(primary=["#12GG56"]),
    )
    assert invalid_hex.status_code == 422

    supplied_metadata = client.put(
        "/api/guidelines/visual-brand",
        json={**_palette(), "updated_by": "Attacker", "version_number": 99},
    )
    assert supplied_metadata.status_code == 422


def test_empty_palette_can_be_saved_and_creates_first_version(client, test_engine):
    saved = client.put(
        "/api/guidelines/visual-brand",
        json={"primary": [], "secondary": [], "accent": []},
    )

    assert saved.status_code == 200
    assert saved.json()["version_number"] == 1
    assert saved.json()["primary"] == []
    with Session(test_engine) as db:
        assert db.get(VisualBrandConfiguration, 1) is not None
        assert db.query(VisualBrandVersion).count() == 1


def test_updates_create_ordered_snapshots_and_noop_does_not_add_version(
    client, test_engine
):
    first_palette = _palette()
    first = client.put(
        "/api/guidelines/visual-brand",
        json=first_palette,
    )
    assert first.status_code == 200
    assert first.json()["version_number"] == 1

    no_op = client.put(
        "/api/guidelines/visual-brand",
        json=first_palette,
    )
    assert no_op.status_code == 200
    assert no_op.json()["version_number"] == 1

    second_palette = _palette(accent=["#AABBCC"])
    second = client.put(
        "/api/guidelines/visual-brand",
        json=second_palette,
    )
    assert second.status_code == 200
    assert second.json()["version_number"] == 2

    versions = client.get("/api/guidelines/visual-brand/versions")
    assert versions.status_code == 200
    assert [item["version_number"] for item in versions.json()] == [2, 1]
    assert versions.json()[0]["snapshot"] == second_palette
    assert versions.json()[0]["editor"] == "Workspace Admin"
    assert versions.json()[0]["editor_id"] is not None
    assert versions.json()[0]["created_at"] is not None
    assert versions.json()[1]["snapshot"] == first_palette
    assert client.get(
        "/api/guidelines/visual-brand/versions?limit=1"
    ).json()[0]["version_number"] == 2
    assert client.get(
        "/api/guidelines/visual-brand/versions?limit=501"
    ).status_code == 422

    with Session(test_engine) as db:
        assert db.query(VisualBrandVersion).count() == 2
        assert db.get(VisualBrandConfiguration, 1).accent == ["#AABBCC"]


def test_version_write_failure_rolls_back_configuration_and_history(
    client, test_engine
):
    def fail_version_flush(session, _flush_context, instances):
        if any(isinstance(item, VisualBrandVersion) for item in session.new):
            raise RuntimeError("simulated version history failure")

    event.listen(Session, "before_flush", fail_version_flush)
    try:
        with pytest.raises(RuntimeError, match="simulated version history failure"):
            client.put(
                "/api/guidelines/visual-brand",
                json=_palette(),
            )
    finally:
        event.remove(Session, "before_flush", fail_version_flush)

    with Session(test_engine) as db:
        assert db.get(VisualBrandConfiguration, 1) is None
        assert db.query(VisualBrandVersion).count() == 0


def test_visual_brand_configuration_persists_across_database_sessions(
    client, test_engine
):
    payload = _palette(primary=["#ABCDEF"])
    assert client.put(
        "/api/guidelines/visual-brand",
        json=payload,
    ).status_code == 200

    with Session(test_engine) as first_session:
        first = first_session.get(VisualBrandConfiguration, 1)
        assert first.primary == ["#ABCDEF"]
    with Session(test_engine) as second_session:
        second = second_session.get(VisualBrandConfiguration, 1)
        assert second.primary == ["#ABCDEF"]
        assert second.version_number == 1


def test_concurrent_palette_updates_serialize_on_independent_sqlite_connections(
    tmp_path, monkeypatch
):
    from app.main import create_app
    from app.services import auth_service

    database_path = tmp_path / "palette-concurrency.sqlite3"
    engine = create_engine(
        "sqlite:///{}".format(database_path),
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    active_connections = set()
    max_active_connections = 0
    connection_lock = Lock()

    def track_checkout(dbapi_connection, _connection_record, _connection_proxy):
        nonlocal max_active_connections
        with connection_lock:
            active_connections.add(id(dbapi_connection))
            max_active_connections = max(
                max_active_connections, len(active_connections)
            )

    def track_checkin(dbapi_connection, _connection_record):
        with connection_lock:
            active_connections.discard(id(dbapi_connection))

    event.listen(engine, "checkout", track_checkout)
    event.listen(engine, "checkin", track_checkin)
    monkeypatch.setattr(
        auth_service, "BOOTSTRAP_ADMIN_EMAIL", "admin@example.test"
    )
    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_PASSWORD",
        "test-admin-password-123",
    )
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)

    palettes = [
        {
            "primary": ["#{:06X}".format(index)],
            "secondary": ["#{:06X}".format(index + 100)],
            "accent": ["#{:06X}".format(index + 200)],
        }
        for index in range(1, 7)
    ]
    request_barrier = Barrier(len(palettes))

    try:
        with TestClient(create_app(engine)) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "admin@example.test",
                    "password": "test-admin-password-123",
                },
            )
            assert login.status_code == 200

            def submit_palette(palette):
                request_barrier.wait(timeout=10)
                return client.put(
                    "/api/guidelines/visual-brand",
                    json=palette,
                )

            with ThreadPoolExecutor(max_workers=len(palettes)) as executor:
                responses = list(executor.map(submit_palette, palettes))

            assert [response.status_code for response in responses] == [
                200
            ] * len(palettes)

        assert max_active_connections >= 2
        with Session(engine) as db:
            versions = (
                db.query(VisualBrandVersion)
                .order_by(VisualBrandVersion.version_number.asc())
                .all()
            )
            configuration = db.get(VisualBrandConfiguration, 1)

            assert len(versions) == len(palettes)
            assert [item.version_number for item in versions] == list(
                range(1, len(palettes) + 1)
            )
            snapshots = [item.snapshot for item in versions]
            assert all(palette in snapshots for palette in palettes)
            assert configuration.version_number == len(palettes)
            assert {
                "primary": configuration.primary,
                "secondary": configuration.secondary,
                "accent": configuration.accent,
            } == versions[-1].snapshot
    finally:
        engine.dispose()

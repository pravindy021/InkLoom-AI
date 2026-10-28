import io
import sqlite3
import sys

import pytest

import run_local


class TerminalInput(io.StringIO):
    def isatty(self):
        return True


def test_local_launcher_reads_password_hidden_and_validates_credentials(monkeypatch):
    monkeypatch.setattr(sys, "stdin", TerminalInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "  ADMIN@example.test ")
    values = iter(["a-local-password-123", "a-local-password-123"])
    monkeypatch.setattr(run_local.getpass, "getpass", lambda _prompt: next(values))

    assert run_local.read_admin_credentials() == (
        "admin@example.test",
        "a-local-password-123",
    )


def test_local_launcher_rejects_non_matching_password_confirmation(monkeypatch):
    monkeypatch.setattr(sys, "stdin", TerminalInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "admin@example.test")
    values = iter(["a-local-password-123", "different-password-123"])
    monkeypatch.setattr(run_local.getpass, "getpass", lambda _prompt: next(values))

    with pytest.raises(ValueError, match="Passwords do not match"):
        run_local.read_admin_credentials()


def test_local_launcher_preserves_existing_database_and_requires_matching_admin(
    tmp_path, monkeypatch
):
    from app.services.auth_service import hash_password

    database = tmp_path / "local.db"
    monkeypatch.setattr(run_local, "LOCAL_DATABASE", database)
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE users (email TEXT, password_hash TEXT, role TEXT, is_active INTEGER)"
    )
    connection.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?)",
        (
            "admin@example.test",
            hash_password("a-local-password-123"),
            "admin",
            1,
        ),
    )
    connection.commit()
    connection.close()

    assert run_local.existing_database_matches_admin(
        "admin@example.test", "a-local-password-123"
    )
    assert not run_local.existing_database_matches_admin(
        "admin@example.test", "a-different-password-123"
    )
    assert not run_local.existing_database_matches_admin(
        "other@example.test", "a-local-password-123"
    )

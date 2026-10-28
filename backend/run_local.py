import getpass
import os
import re
import sys
from pathlib import Path
from typing import Tuple

BACKEND_DIR = Path(__file__).resolve().parent
LOCAL_DATABASE = BACKEND_DIR / "inkloom-local-dev.db"


def read_admin_credentials() -> Tuple[str, str]:
    if not sys.stdin.isatty():
        raise RuntimeError("Run this launcher directly in a terminal.")

    email = input("New local Admin email: ").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid Admin email address.")

    password = getpass.getpass("New local Admin password (hidden): ")
    confirmation = getpass.getpass("Confirm Admin password (hidden): ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain between 12 and 128 characters.")
    return email, password


def existing_database_matches_admin(email: str, password: str) -> bool:
    if not LOCAL_DATABASE.exists() or LOCAL_DATABASE.stat().st_size == 0:
        return True

    import sqlite3

    connection = sqlite3.connect(
        "file:{}?mode=ro".format(LOCAL_DATABASE.as_posix()),
        uri=True,
    )
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "users" not in tables:
            return True
        users = connection.execute(
            "SELECT email, password_hash, role, is_active FROM users"
        ).fetchall()
    finally:
        connection.close()

    if not users:
        return True

    from app.services.auth_service import verify_password

    return any(
        row_email == email
        and role == "admin"
        and is_active
        and verify_password(password, password_hash)
        for row_email, password_hash, role, is_active in users
    )


def main() -> None:
    os.chdir(BACKEND_DIR)
    try:
        email, password = read_admin_credentials()
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    os.environ["DATABASE_URL"] = "sqlite:///./{}".format(LOCAL_DATABASE.name)
    os.environ["BOOTSTRAP_ADMIN_EMAIL"] = email
    os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = password
    os.environ["AUTH_COOKIE_SECURE"] = "false"

    if not existing_database_matches_admin(email, password):
        raise SystemExit(
            "The isolated local database already has accounts with different "
            "credentials. No data was changed; use its existing Admin login."
        )

    import uvicorn

    print("Starting local InkLoom API at http://localhost:8000")
    print("Local database: {}".format(LOCAL_DATABASE.name))
    print("Admin credentials are held only in this process environment.")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()

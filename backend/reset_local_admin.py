import getpass
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User, AuthSession
from app.services.auth_service import hash_password

db: Session = SessionLocal()

try:
    users = db.query(User).filter(User.role == "admin").all()

    if len(users) != 1:
        raise SystemExit(
            f"Expected exactly 1 admin account; found {len(users)}. No changes made."
        )

    admin = users[0]
    print(f"Admin account: {admin.email}")
    confirm = input("Reset this account's password? Type YES: ")

    if confirm != "YES":
        raise SystemExit("Cancelled. No changes made.")

    password = getpass.getpass("Enter a new strong password: ")
    confirm_password = getpass.getpass("Re-enter the new password: ")

    if password != confirm_password:
        raise SystemExit("Passwords do not match. No changes made.")

    if len(password) < 12:
        raise SystemExit("Use at least 12 characters. No changes made.")

    admin.password_hash = hash_password(password)
    admin.must_change_password = False

    db.query(AuthSession).filter(
        AuthSession.user_id == admin.id
    ).delete(synchronize_session=False)

    db.commit()
    print("Admin password updated successfully. Existing sessions revoked.")

except SystemExit:
    db.rollback()
    raise
except Exception:
    db.rollback()
    raise
finally:
    db.close()

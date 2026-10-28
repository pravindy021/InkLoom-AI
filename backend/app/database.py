from sqlalchemy import DateTime, Integer, String, Text, create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def migrate_source_approval(target_engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table("source_documents"):
        return

    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    source_table = target_engine.dialect.identifier_preparer.quote("source_documents")
    additions = {
        "approval_status": (String(24), "NOT NULL DEFAULT 'pending'"),
        "reviewed_by_id": (
            Integer(),
            "REFERENCES users(id) ON DELETE SET NULL",
        ),
        "reviewed_at": (DateTime(timezone=True), ""),
        "review_note": (Text(), ""),
    }
    with target_engine.begin() as connection:
        for name, (column_type, constraints) in additions.items():
            if name in columns:
                continue
            quoted_name = target_engine.dialect.identifier_preparer.quote(name)
            definition = "{} {}".format(
                column_type.compile(dialect=target_engine.dialect), constraints
            ).strip()
            connection.exec_driver_sql(
                "ALTER TABLE {} ADD COLUMN {} {}".format(
                    source_table, quoted_name, definition
                )
            )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

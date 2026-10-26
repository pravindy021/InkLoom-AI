from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import API_VERSION, CORS_ORIGINS
from app.database import Base, engine, get_db
from app.models import BrandGuideline
from app.routes import analytics, analysis, guidelines, health, reviews, sources

SEED_GUIDELINES = [
    {
        "name": "Substantiated promotional claims",
        "category": "claims",
        "description": "Absolute and performance-related promotional claims should be supported by current evidence.",
        "severity": "high",
    },
    {
        "name": "Approved terminology",
        "category": "terminology",
        "description": "Use configured preferred terminology and avoid configured prohibited terms.",
        "severity": "medium",
    },
    {
        "name": "Current factual evidence",
        "category": "factual_claim",
        "description": "Check factual statements against current approved sources; never imply verification without evidence.",
        "severity": "medium",
    },
]


def _enable_sqlite_foreign_keys(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def set_sqlite_pragma(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(database_engine: Engine = engine) -> FastAPI:
    _enable_sqlite_foreign_keys(database_engine)
    local_sessions = sessionmaker(
        bind=database_engine, autoflush=False, autocommit=False
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(bind=database_engine)
        db = local_sessions()
        try:
            if db.query(BrandGuideline).count() == 0:
                for item in SEED_GUIDELINES:
                    db.add(BrandGuideline(**item, is_seed=True))
                db.commit()
        finally:
            db.close()
        yield

    app = FastAPI(
        title="InkLoom AI API",
        description=(
            "Brand-governance review API. Rule-based findings are advisory heuristics, "
            "not legal advice, factual verification, or a full accessibility audit."
        ),
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Reviewer"],
    )

    def get_app_db():
        db: Session = local_sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_app_db
    app.include_router(health.router)
    app.include_router(guidelines.router)
    app.include_router(analysis.router)
    app.include_router(reviews.router)
    app.include_router(sources.router)
    app.include_router(analytics.router)
    return app


app = create_app()

"""Database engine and portable health helpers for the ChatBI API."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .config import ROOT


def normalize_database_url(url: str) -> str:
    """Select the pinned psycopg 3 dialect for conventional PostgreSQL URLs."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def database_url() -> str:
    configured = os.getenv("CHATBI_DATABASE_URL")
    if configured:
        return normalize_database_url(configured)
    database_path = ROOT / "data" / "local" / "chatbi.sqlite"
    return f"sqlite:///{database_path.as_posix()}"


def make_engine(url: str | None = None) -> Engine:
    resolved_url = normalize_database_url(url) if url else database_url()
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
    engine = create_engine(resolved_url, connect_args=connect_args, pool_pre_ping=True)
    if resolved_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = make_engine()
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


def check_database() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = set(inspect(connection).get_table_names())
            required_tables = {
                "alembic_version",
                "dataset_manifests",
                "orders",
                "saas_subscriptions",
                "saas_plans",
                "turn_feedback",
            }
            if not required_tables.issubset(tables):
                return False
            migration_revisions = (
                connection.execute(text("SELECT version_num FROM alembic_version"))
                .scalars()
                .all()
            )
            if not migration_revisions:
                return False
            dataset_ids = (
                connection.execute(text("SELECT dataset_id FROM dataset_manifests")).scalars().all()
            )
            if not {
                "ecommerce_mock_v1",
                "ecommerce_empty_day_fixture_v1",
                "saas_subscription_mock_v1",
            }.issubset(dataset_ids):
                return False
        return True
    except SQLAlchemyError:
        return False

"""Explicitly seed the generated Mock snapshots into a new PostgreSQL database."""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.chatbi.database import make_engine  # noqa: E402
from backend.chatbi.models import Base, DatasetManifest  # noqa: E402
from backend.chatbi.seed import DATASET_IDS, prepare_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load only generated Mock datasets into a new PostgreSQL database."
    )
    parser.add_argument(
        "--confirm-empty-mock-target",
        action="store_true",
        help="Confirm the target is an empty, dedicated Mock database.",
    )
    args = parser.parse_args()
    if not args.confirm_empty_mock_target:
        parser.error("Pass --confirm-empty-mock-target after verifying this is a new Mock database.")

    url = os.getenv("CHATBI_CLOUD_SEED_DATABASE_URL", "").strip()
    if not url:
        parser.error("Set CHATBI_CLOUD_SEED_DATABASE_URL in the current shell; it is never printed.")
    if make_url(url).get_backend_name() != "postgresql":
        parser.error("Cloud Mock seeding only accepts a PostgreSQL database URL.")

    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            required = set(Base.metadata.tables) | {"alembic_version"}
            missing = sorted(required - tables)
            if missing:
                parser.error(
                    "Database schema is incomplete; run Alembic migrations first. Missing: "
                    + ", ".join(missing)
                )
            populated = [
                table_name
                for table_name, table in Base.metadata.tables.items()
                if connection.scalar(select(func.count()).select_from(table))
            ]
            if populated:
                parser.error(
                    "Refusing to seed a non-empty target. Tables with rows: "
                    + ", ".join(sorted(populated))
                )

        with Session(engine) as session, session.begin():
            for dataset_id in DATASET_IDS:
                prepare_dataset(session, dataset_id)
            loaded = set(session.scalars(select(DatasetManifest.dataset_id)).all())
            if not set(DATASET_IDS).issubset(loaded):
                raise RuntimeError("Mock manifest verification failed after import.")
    finally:
        engine.dispose()

    print("Loaded and verified the three generated Mock datasets in the empty PostgreSQL target.")


if __name__ == "__main__":
    main()

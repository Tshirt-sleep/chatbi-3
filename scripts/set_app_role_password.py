"""Set the dedicated Supabase application role password without echoing secrets."""

from __future__ import annotations

from getpass import getpass

import psycopg
from psycopg import sql

APP_ROLE = "chatbi_app"


def normalize_owner_url(url: str) -> str:
    """Accept both Supabase's raw URI and SQLAlchemy's psycopg URI form."""
    prefix = "postgresql+psycopg://"
    if url.startswith(prefix):
        return "postgresql://" + url[len(prefix) :]
    return url


def safe_error_hint(error: psycopg.Error) -> str:
    """Return a generic diagnostic without printing a connection string."""
    message = str(error).lower()
    if "password authentication failed" in message:
        return (
            "The database rejected authentication; recheck the owner username/password."
        )
    if (
        "could not translate host name" in message
        or "name or service not known" in message
    ):
        return "The pooler hostname could not be resolved; recheck the copied host."
    if "timeout" in message or "timed out" in message:
        return "The connection timed out; check the project status, pooler endpoint, and network."
    if "ssl" in message or "tls" in message:
        return "The TLS connection failed; retain Supabase's sslmode=require option."
    return (
        "Check the raw Supabase Session Pooler URL, role, project status, and network."
    )


def main() -> int:
    owner_url = getpass("Supabase owner Session Pooler URL (hidden): ").strip()
    if not owner_url:
        print("No connection URL provided.")
        return 2
    owner_url = normalize_owner_url(owner_url)

    password = getpass("New chatbi_app password (hidden): ")
    confirmation = getpass("Repeat new chatbi_app password (hidden): ")
    if not password or password != confirmation:
        print("Password is empty or the two entries do not match.")
        return 2

    connection: psycopg.Connection | None = None
    stage = "connect"
    try:
        connection = psycopg.connect(owner_url)
        stage = "set_password"
        connection.execute(
            sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                sql.Identifier(APP_ROLE), sql.Literal(password)
            )
        )
        stage = "commit"
        connection.commit()
    except psycopg.Error as error:
        sqlstate = error.sqlstate or "unknown"
        print(
            f"Password update failed during {stage} "
            f"({type(error).__name__}, SQLSTATE {sqlstate}). {safe_error_hint(error)}"
        )
        if stage == "commit":
            print(
                "The commit result may be uncertain. Before retrying, test whether the new "
                "chatbi_app credential can connect."
            )
        return 1
    finally:
        if connection is not None:
            connection.close()

    print("chatbi_app password updated. No secret was displayed or written to a file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

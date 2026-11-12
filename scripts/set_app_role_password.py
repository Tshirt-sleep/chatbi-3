"""Set the dedicated Supabase application role password without echoing secrets."""

from __future__ import annotations

from getpass import getpass

import psycopg
from psycopg import sql

APP_ROLE = "chatbi_app"


def main() -> int:
    owner_url = getpass("Supabase owner Session Pooler URL (hidden): ").strip()
    if not owner_url:
        print("No connection URL provided.")
        return 2

    password = getpass("New chatbi_app password (hidden): ")
    confirmation = getpass("Repeat new chatbi_app password (hidden): ")
    if not password or password != confirmation:
        print("Password is empty or the two entries do not match.")
        return 2

    try:
        with psycopg.connect(owner_url) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                    sql.Identifier(APP_ROLE), sql.Literal(password)
                )
            )
    except psycopg.Error as error:
        sqlstate = error.sqlstate or "unknown"
        print(f"Password update failed (SQLSTATE {sqlstate}). Check the project and owner URL.")
        return 1

    print("chatbi_app password updated. No secret was displayed or written to a file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

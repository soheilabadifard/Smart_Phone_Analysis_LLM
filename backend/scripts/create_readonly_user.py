"""
Create a read-only MariaDB user for the LLM Ask path.

The Ask endpoint executes LLM-generated SQL. Even with a SELECT-only parser
guard, defense-in-depth means the connection itself should be incapable of
mutating the database.

Reads admin credentials from .env (DB_USER / DB_PASSWORD / DB_HOST / DB_PORT /
DB_NAME) and creates DB_RO_USER with DB_RO_PASSWORD, granting SELECT only.

Run once after the database is populated, or any time the read-only password
needs to be rotated. Idempotent: safe to re-run.
"""

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database_eng import create_schema


def main() -> None:
    load_dotenv()

    admin_user = os.environ["DB_USER"]
    admin_pass = os.environ["DB_PASSWORD"]
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))
    db_name = os.environ["DB_NAME"]

    ro_user = os.getenv("DB_RO_USER", "gsm_readonly")
    ro_pass = os.environ["DB_RO_PASSWORD"]

    engine = create_schema(admin_user, admin_pass, host=host, port=port)

    with engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE USER IF NOT EXISTS :user@'localhost' "
                f"IDENTIFIED BY :pwd"
            ).bindparams(user=ro_user, pwd=ro_pass)
        )
        conn.execute(
            text(f"ALTER USER :user@'localhost' IDENTIFIED BY :pwd").bindparams(
                user=ro_user, pwd=ro_pass
            )
        )
        conn.execute(text(f"REVOKE ALL PRIVILEGES ON *.* FROM '{ro_user}'@'localhost'"))
        conn.execute(text(f"GRANT SELECT ON `{db_name}`.* TO '{ro_user}'@'localhost'"))
        conn.execute(text("FLUSH PRIVILEGES"))
        conn.commit()

    print(f"Read-only user '{ro_user}'@'localhost' is set up with SELECT on `{db_name}`.")


if __name__ == "__main__":
    main()

"""Defense-in-depth SQL guard for LLM-generated queries.

The DB connection is already SELECT-only (gsm_readonly user), but parsing the
SQL before sending it lets us reject obvious problems with a clear error
message instead of a MariaDB privilege error.
"""

import sqlglot
from sqlglot import exp


class UnsafeSQLError(ValueError):
    pass


# Look up disallowed classes by name with getattr so the guard tolerates
# sqlglot API churn (e.g. AlterTable was renamed to Alter in 26.x).
_DISALLOWED_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Create",
    "Alter", "AlterTable",
    "Truncate", "TruncateTable",
    "Merge", "Replace",
)
_DISALLOWED: tuple[type, ...] = tuple(
    getattr(exp, name) for name in _DISALLOWED_NAMES if hasattr(exp, name)
)


def ensure_select_only(sql: str) -> str:
    """Parse `sql`, confirm a single SELECT statement, return canonical form.

    Raises UnsafeSQLError on anything we don't want to execute.
    """
    statements = [s for s in sqlglot.parse(sql, dialect="mysql") if s is not None]
    if len(statements) == 0:
        raise UnsafeSQLError("Empty SQL.")
    if len(statements) > 1:
        raise UnsafeSQLError("Only one statement is allowed; got multiple.")

    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, exp.Union, exp.With)):
        raise UnsafeSQLError(f"Only SELECT statements are allowed; got {type(stmt).__name__}.")

    for node in stmt.walk():
        n = node[0] if isinstance(node, tuple) else node
        if _DISALLOWED and isinstance(n, _DISALLOWED):
            raise UnsafeSQLError(f"Disallowed clause: {type(n).__name__}.")

    return stmt.sql(dialect="mysql")

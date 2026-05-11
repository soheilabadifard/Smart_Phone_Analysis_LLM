"""Thin wrapper around the local MLX server (OpenAI-compatible)."""

import os
import re

from openai import OpenAI

from app.llm.few_shot import EXAMPLES
from app.llm.schema_snapshot import SCHEMA_DESCRIPTION

SYSTEM_PROMPT = f"""\
You convert plain-English questions about a smartphone database into a single
MariaDB SELECT query.

{SCHEMA_DESCRIPTION}

RULES:
- Output exactly ONE SQL statement, a SELECT (or WITH ... SELECT).
- Wrap the SQL in a ```sql fenced code block. No prose around it.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, MERGE, or REPLACE.
- Always LIMIT results to at most 100 rows unless the user explicitly asks for more.
- Prefer readable column aliases (AS brand, AS avg_price_eur, ...).
- Filter NULLs out of aggregates and ORDER BY columns where they would skew results.
- If the question is ambiguous, pick the most reasonable interpretation and proceed.
- If you receive an error message about a previous attempt, study it carefully,
  identify the exact column or join that caused the failure, and emit a fully
  corrected query — do not repeat the same mistake.

The examples that follow show the expected join idioms and output format.
"""


def initial_messages(question: str) -> list[dict]:
    """System prompt + few-shot turns + the user's question."""
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_q, assistant_sql in EXAMPLES:
        msgs.append({"role": "user", "content": user_q})
        msgs.append({"role": "assistant", "content": assistant_sql})
    msgs.append({"role": "user", "content": question})
    return msgs


def _client() -> OpenAI:
    return OpenAI(
        base_url=os.getenv("MLX_BASE_URL", "http://localhost:8080/v1"),
        api_key=os.getenv("MLX_API_KEY", "not-needed"),
    )


_SQL_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
# Stricter pattern that requires the explicit `sql` language tag. Used by the
# review loop to decide whether the assistant emitted a refinement — a bare
# ``` block with prose inside should NOT be treated as SQL.
_SQL_FENCE_TAGGED = re.compile(r"```sql\s+(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(response_text: str) -> str:
    """Pull the SQL out of the assistant response.

    Lenient on purpose: tries ```sql first, then bare ```, then falls back to
    the whole text. The guard rejects whatever we hand it if it isn't a real
    SELECT, so leniency here just gives the model more shots at being parsed.
    """
    m = _SQL_FENCE_TAGGED.search(response_text) or _SQL_FENCE.search(response_text)
    if m:
        return m.group(1).strip().rstrip(";").strip()
    return response_text.strip().rstrip(";").strip()


def has_fenced_sql(response_text: str) -> bool:
    """True if the assistant response contains a ```sql … ``` block.

    Used by the review loop to distinguish approval (no fence or a bare
    ``` block with prose) from a refinement (explicitly ```sql tagged).
    Stricter than `extract_sql` on purpose.
    """
    return _SQL_FENCE_TAGGED.search(response_text) is not None


def format_result_preview(columns: list[str], rows: list[dict],
                          max_rows: int = 10) -> str:
    """Render a Markdown table preview of an executed query result.

    Sent back to the LLM in the review turn so it can judge whether the
    table actually answers the question. Truncated to `max_rows` to keep
    the prompt size bounded.
    """
    if not columns:
        return "(no columns returned)"
    if not rows:
        return f"(0 rows returned for columns: {', '.join(columns)})"

    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join(["---"] * len(columns)) + "|"
    body_rows = rows[:max_rows]
    body = "\n".join(
        "| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in columns) + " |"
        for r in body_rows
    )
    extra = ""
    if len(rows) > max_rows:
        extra = f"\n\n…{len(rows) - max_rows} more row(s) not shown."
    return f"{header}\n{sep}\n{body}{extra}\n\n(returned {len(rows)} row(s))"


def review_user_message(question: str, sql: str, preview: str) -> str:
    """User turn that asks the model to judge its own result."""
    return (
        "You ran this SQL:\n"
        "```sql\n"
        f"{sql}\n"
        "```\n\n"
        "It produced this result:\n\n"
        f"{preview}\n\n"
        f"Question: \"{question}\"\n\n"
        "Does this result correctly answer the question?\n"
        "- If YES, reply with the single word `OK` and nothing else.\n"
        "- If NO, emit a corrected SQL in a ```sql fenced block, with no other prose.\n"
        "- An empty result set is a valid answer when the data genuinely doesn't "
        "match the filters; only refine if you can identify a specific column, "
        "join, or filter that needs to change."
    )


_EXPLAIN_SYSTEM_PROMPT = (
    "You explain the result of a SQL query to a non-technical reader. "
    "Be concise (2-4 short sentences), specific, and plain. Refer to actual "
    "values from the table where useful. Do NOT emit SQL, code blocks, or "
    "markdown headings. If the result has 0 rows, say so plainly and "
    "interpret that as 'no devices match these filters'."
)


def explanation_messages(question: str, sql: str, preview: str) -> list[dict]:
    """Self-contained chat conversation for the explanation turn.

    Independent from the NL→SQL conversation so the model isn't tempted to
    re-emit SQL. Also keeps the context short (just system + one user turn).
    """
    user_content = (
        f"Question: \"{question}\"\n\n"
        "SQL:\n"
        "```sql\n"
        f"{sql}\n"
        "```\n\n"
        "Result:\n\n"
        f"{preview}\n\n"
        "Explain this result in 2-4 short sentences for the user."
    )
    return [
        {"role": "system", "content": _EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def strip_code_fences(text: str) -> str:
    """Remove any ```...``` blocks from `text` — defensive cleanup for the
    explanation turn, in case the model slips in code despite instructions."""
    return _SQL_FENCE.sub("", text).strip()


def chat(messages: list[dict]) -> str:
    """Single round-trip to the MLX server. Returns the assistant text."""
    resp = _client().chat.completions.create(
        model=os.getenv("MLX_MODEL", "mlx-community/Qwen2.5-Coder-32B-Instruct-bf16"),
        messages=messages,
        temperature=0.1,
        max_tokens=800,
    )
    return resp.choices[0].message.content or ""


def chat_stream(messages: list[dict]):
    """Token-streaming variant of `chat()`. Yields the assistant's delta
    content as it arrives so the streaming Ask route can emit token events.

    Returns a generator; callers should `''.join(...)` the yielded tokens
    when they need the full text. The OpenAI SDK's `stream=True` mode wraps
    the SSE stream and yields chunks whose `.choices[0].delta.content` is
    either a token string or None on the terminating chunk.
    """
    stream = _client().chat.completions.create(
        model=os.getenv("MLX_MODEL", "mlx-community/Qwen2.5-Coder-32B-Instruct-bf16"),
        messages=messages,
        temperature=0.1,
        max_tokens=800,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None)
        if token:
            yield token

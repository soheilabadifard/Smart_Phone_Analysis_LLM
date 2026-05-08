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
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, or MERGE.
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


def extract_sql(response_text: str) -> str:
    m = _SQL_FENCE.search(response_text)
    if m:
        return m.group(1).strip().rstrip(";").strip()
    return response_text.strip().rstrip(";").strip()


def chat(messages: list[dict]) -> str:
    """Single round-trip to the MLX server. Returns the assistant text."""
    resp = _client().chat.completions.create(
        model=os.getenv("MLX_MODEL", "mlx-community/Qwen2.5-Coder-32B-Instruct-bf16"),
        messages=messages,
        temperature=0.1,
        max_tokens=800,
    )
    return resp.choices[0].message.content or ""

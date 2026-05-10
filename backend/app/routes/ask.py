"""NL → SQL endpoint with self-correction.

The pipeline retries on guard rejections and DB errors, feeding the error
back to the model. Each attempt is reported so the UI can show the loop.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm.pipeline import answer_question

router = APIRouter()


class AskRequest(BaseModel):
    question: str


class AttemptOut(BaseModel):
    sql: str
    error: str | None = None
    succeeded: bool = False
    kind: str = "execution"          # 'execution' | 'review'
    judgment: str | None = None      # LLM's review-turn text


class AskResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    attempts: list[AttemptOut]
    raw_llm_response: str


def _to_out(a) -> AttemptOut:
    return AttemptOut(
        sql=a.sql, error=a.error, succeeded=a.succeeded,
        kind=getattr(a, "kind", "execution"),
        judgment=getattr(a, "judgment", None),
    )


@router.post("", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    result = answer_question(req.question)

    if not result.attempts or not result.attempts[-1].succeeded:
        last_err = result.attempts[-1].error if result.attempts else "no attempts"
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"LLM failed to produce a runnable query after {len(result.attempts)} attempts.",
                "last_error": last_err,
                "attempts": [_to_out(a).model_dump() for a in result.attempts],
            },
        )

    return AskResponse(
        question=result.question,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        attempts=[_to_out(a) for a in result.attempts],
        raw_llm_response=result.raw_llm_response,
    )

# Backend (FastAPI)

Local API for the smartphone platform. Talks to the existing MariaDB and to a
local MLX LLM server.

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Add to `.env` (at repo root) on top of the existing DB vars:

```
DB_RO_USER=gsm_readonly
DB_RO_PASSWORD=<choose one>
MLX_BASE_URL=http://localhost:8080/v1
MLX_MODEL=mlx-community/Qwen2.5-Coder-32B-Instruct-bf16
```

Then create the read-only user (one-time):

```bash
python scripts/create_readonly_user.py
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

OpenAPI docs at <http://localhost:8000/docs>.

## Tests

The pytest suite lives at the repo root (`tests/`) and covers both the
backend and the data pipeline. Run from the repo root:

```bash
pytest                     # all tests
pytest tests/test_sql_guard.py -v
pytest -m "not integration"  # skip integration markers
```

The suite uses an in-memory SQLite engine and monkeypatches the LLM call,
so no MariaDB and no `mlx_lm.server` are needed to run it.

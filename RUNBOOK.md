# Runbook — Local Smartphone Platform

Three processes for the full demo. Open three terminals.

## 0. One-time setup

Add to `.env` at the repo root:

```
DB_RO_USER=gsm_readonly
DB_RO_PASSWORD=<choose one>
MLX_BASE_URL=http://localhost:8080/v1
MLX_MODEL=mlx-community/Qwen2.5-Coder-32B-Instruct-bf16
MLX_MAX_RETRIES=5         # NL→SQL self-correction cap (default 5)
```

Create the read-only DB user (idempotent, run again whenever you rotate the password):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/create_readonly_user.py
```

Install frontend dependencies:

```bash
cd ../frontend
npm install
```

Install MLX runtime:

```bash
pip install mlx-lm
```

## 1. Start the local LLM (terminal A)

```bash
mlx_lm.server --model mlx-community/Qwen2.5-Coder-32B-Instruct-bf16 --port 8080
```

First run will download ~64 GB of weights from Hugging Face into `~/.cache/huggingface`.

## 2. Start the backend (terminal B)

```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

OpenAPI debug page: <http://localhost:8000/docs>

## 3. Start the frontend (terminal C)

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173>.

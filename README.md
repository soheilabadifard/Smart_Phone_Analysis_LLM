# Smartphone Database Platform

End-to-end relational application built around a **MariaDB 10.11 star
schema** populated with public smartphone specifications scraped from
GSMArena. Built for **CIS 761 (DBMS)**. The platform spans the full
pipeline from web scraping through schema population to three end-user
surfaces — a recommendation interface, a market-analytics dashboard
partitioned by device class, and a natural-language SQL (NL→SQL)
interface driven by a locally hosted large language model.

| | |
|---|---|
| **Database** | MariaDB 10.11, star schema (`Device` fact + 7 dim tables), ~12,000 device-configuration rows across 22 brands and 15 release years |
| **Backend** | FastAPI, 35 REST endpoints (Recommend / Analytics / Ask) |
| **Frontend** | React + Vite + Plotly, 5 tabs (Recommend, Phone / Watch / Tablet Analytics, Ask) |
| **NL→SQL** | Local MLX server (Qwen2.5-Coder-32B-Instruct-bf16) with `sqlglot` SELECT-only guard, bounded self-correction, result review, conversation memory, and token-level NDJSON streaming |
| **Tests** | 455 backend (`pytest`) + 36 frontend (`vitest`) — both run in CI on every push |

The original course proposal and ER diagram are in
[`Project_Proposal.pdf`](Project_Proposal.pdf). The full final report
lives at [`Deliverables/FinalReport/main.tex`](Deliverables/FinalReport/main.tex).

## Use cases

1. **Phone Recommendation.** Users specify preferences such as budget,
   brand, OS, RAM, storage, battery, display size, camera features, and
   5G support. The Recommend tab maps these to a typed Pydantic schema
   and a parameterised SQL query.

2. **Smartphone Market Analytics.** R-style summaries, distributions,
   nine hypothesis tests, and three nested OLS regression models with
   Breusch-Pagan / Jarque-Bera / VIF / Cook's distance diagnostics. The
   Analytics view ships in three flavours (phones / watches / tablets)
   so cross-form-factor mixing doesn't skew the aggregates. Two
   confidence-interval charts (mean price by brand for a selectable
   year, mean battery capacity by brand) honour interactive year + α
   selectors.

3. **Natural-Language Query Interface.** Users ask plain-English
   questions ("which 5 brands have the highest average phone price?").
   The Ask tab guards every LLM-emitted query with `sqlglot` (parses,
   rejects anything that isn't a single `SELECT` / `UNION` / `WITH`),
   executes through a `gsm_readonly` DB user, asks the model to review
   its own result, and finally produces a 2-4 sentence plain-English
   explanation. Results stream back as NDJSON so the SQL and rows render
   before the review and explanation turns finish. Optional
   conversation memory (`session_id`) lets users follow up with
   "now show that for Samsung".

## Quick start

The platform runs as **three local processes** (LLM server, FastAPI
backend, Vite frontend). Full setup + startup order is in
[`RUNBOOK.md`](RUNBOOK.md). Short version:

```bash
# 0. Populate the database (one-off, ~hours for the full crawl)
pip install sqlalchemy pandas beautifulsoup4 python-dotenv numpy pymysql
python pipeline.py                    # all 6 steps end-to-end
python pipeline.py --skip-crawl       # reuse existing flattened_data.csv

# 1. Local LLM server (terminal A)
mlx_lm.server --model mlx-community/Qwen2.5-Coder-32B-Instruct-bf16 --port 8080

# 2. Backend (terminal B)
cd backend && uvicorn app.main:app --reload --port 8000

# 3. Frontend (terminal C)
cd frontend && npm run dev
```

Open <http://localhost:5173>.

## Data pipeline

`pipeline.py` orchestrates six steps under `etl/`. Each step verifies
its expected output before the next runs, so a silent failure halts the
chain rather than corrupting downstream artefacts.

| Step | Script | Output |
|---|---|---|
| 1 | `etl/crawl.py` | `phone_info.json`, `phone_models.json`, `brand_links.json` |
| 2 | `etl/JsonToDataframe.py` | `flattened_data.csv` |
| 3 | `etl/extracrawling.py` | `pricing.json` (per-config prices for multi-tier devices) |
| 4 | `etl/pricing_json_to_csv.py` | `pricing.csv` |
| 5 | `etl/Data_cleaning.py` | `processed_data.csv` (typed, normalised, FX-converted) |
| 6 | `etl/newDatabase.py` | populated MariaDB schema |

CLI:

```bash
python pipeline.py --list             # show step inventory
python pipeline.py --skip-crawl       # reuse existing crawl artefacts
python pipeline.py --steps clean,load # run a subset
```

The crawler is resilient: per-URL retry + skip on failure, Cloudflare
block detection, two-layer resume (`passed_link.csv` + `phone_models.json`
checkpoints), realistic header set with cookie persistence and per-session
UA rotation. Rebuild the resume state from existing artefacts with
`python etl/rebuild_passed_links.py`.

## Repository layout

```
.
├── etl/                      Data pipeline (crawl → clean → load)
├── backend/                  FastAPI: recommend, analytics, ask routes
│   └── app/
│       ├── routes/           recommend.py, analytics.py, ask.py, session_store.py
│       └── llm/              client.py, schema_snapshot.py, few_shot.py,
│                             sql_guard.py, pipeline.py
├── frontend/                 React + Vite + Plotly — 5 tabs
│   └── src/views/            RecommendView, AnalyticsView, AskView
├── evaluation/               25-question NL→SQL benchmark
├── tests/                    452 backend pytest cases (SQLite + mocked LLM)
├── frontend/tests/           34 vitest cases (jsdom + mocked Plotly)
├── Deliverables/             table.sql, records.sql, queries.sql, viols.sql,
│                             screenshots, FinalReport/main.tex
├── pipeline.py               One-command ETL orchestrator
├── generate_table_sql.py     Emits Deliverables/table.sql from the ORM
├── generate_records_sql.py   Emits Deliverables/records.sql from populated DB
├── database_eng.py           Shared SQLAlchemy engine factory
├── RUNBOOK.md                Three-terminal startup guide
├── CLAUDE.md                 Architecture + design notes for contributors
└── Project_Proposal.pdf      Original course proposal + ER diagram
```

## Tests

```bash
# Backend (from repo root)
pip install -r backend/requirements.txt
pytest -v                              # 455 cases
pytest tests/test_sql_guard.py         # one file
pytest -k oscillation                  # by name

# Frontend (from frontend/)
npm install
npm test                               # 36 cases
npm run test:watch
```

Backend tests use an in-memory SQLite engine and a stubbed LLM client —
no MariaDB or `mlx_lm.server` required. Frontend tests run in jsdom
with `react-plotly.js` and `fetch` mocked. CI runs both suites against
a Python 3.11 / 3.12 matrix on every push to `main`
(`.github/workflows/ci.yml`).

## NL→SQL benchmark

A 25-question hand-curated benchmark for the Ask path lives under
`evaluation/`. Each question carries a reference SQL; the runner
compares the LLM-emitted query's result set to the reference's on three
axes (`guard_passed`, `executed`, `result_correct`). The runner is
local-only because it hits a real MLX server, but the comparison logic
itself is exercised by 14 CI tests.

```bash
python -m evaluation.run_benchmark
python -m evaluation.run_benchmark --filter Q1,Q5,Q9 --quiet
python -m evaluation.run_benchmark --json eval_results.json
```

## Documentation

- [`RUNBOOK.md`](RUNBOOK.md) — three-terminal startup guide.
- [`CLAUDE.md`](CLAUDE.md) — architecture notes, pipeline invariants, design decisions, env vars.
- [`Deliverables/FinalReport/main.tex`](Deliverables/FinalReport/main.tex) — full course final report (LaTeX, compile with `latexmk -pdf -shell-escape`).
- [`Deliverables/Queries_report/main.tex`](Deliverables/Queries_report/main.tex) — companion report embedding every query alongside its result.
- [`Project_Proposal.pdf`](Project_Proposal.pdf) — original course proposal + ER diagram.

## Contributors

- [Soheil Abadifard](https://github.com/abadifard)
- [Sanaz Gheibuni](https://github.com/sanaazz)

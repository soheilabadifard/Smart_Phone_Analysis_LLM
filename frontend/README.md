# Frontend (Vite + React)

Three views: **Recommend** (typed filter form), **Analytics** (Plotly charts),
**Ask** (NL → SQL via local MLX model).

## Setup

```bash
cd frontend
npm install
```

## Run

```bash
npm run dev
```

Opens on <http://localhost:5173>. Vite proxies `/api/*` to the FastAPI backend
on `http://localhost:8000`, so start the backend first.

## Tests

```bash
npm test           # one-shot run
npm run test:watch # watch mode
```

Vitest runs in jsdom; `react-plotly.js` is stubbed in `tests/setup.jsx` so
charts render as `<div data-testid="mock-plot">` placeholders. `fetch` is
mocked per-test.

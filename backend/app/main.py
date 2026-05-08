from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import analytics, ask, recommend

app = FastAPI(title="Smartphone Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(ask.router, prefix="/api/ask", tags=["ask"])


@app.get("/api/health")
def health():
    return {"ok": True}

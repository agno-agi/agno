"""StrategyIQ API — Grok routing, tier gating, RAG agents."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from billing.stripe import router as billing_router
from config import settings, validate_jwt_secret
from constants import SEC_DISCLAIMER
from routers.ai import router as ai_router
from routers.auth import router as auth_router
from routers.market import router as market_router
from routers.portfolio import router as port_router
from routers.screener import router as screener_router

app = FastAPI(title="StrategyIQ", version="1.0.0")

# Browsers reject Access-Control-Allow-Origin: * when credentials are enabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(screener_router)
app.include_router(port_router)
app.include_router(ai_router)
app.include_router(billing_router)
app.include_router(market_router)


@app.on_event("startup")
def _validate_startup_settings() -> None:
    validate_jwt_secret(settings.jwt_secret)


@app.get("/health")
def health():
    return {"status": "ok", "disclaimer": SEC_DISCLAIMER}


@app.get("/")
def root():
    return {
        "name": "StrategyIQ",
        "version": "1.0.0",
        "tiers": {
            "beginner": {"price": 0, "queries_per_day": 3},
            "pro": {"price": 29, "realtime": True, "signals": True},
            "elite": {"price": 79, "custom_agents": True, "port_analytics": True},
        },
        "disclaimer": SEC_DISCLAIMER,
    }

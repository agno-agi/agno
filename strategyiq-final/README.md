# StrategyIQ Final

Commercial Bloomberg Terminal replica for retail investors.

**Financial information only, not financial advice.**

## Structure

```
strategyiq-final/
├── backend/           FastAPI + RAG + Celery workers
├── frontend/          Next.js 14 desktop terminal + mobile PWA
├── infra/             Docker, ECS deploy, Terraform (VPC+RDS+Redis+ECS+ALB)
├── api/               Vercel Python function wrapper
├── vercel.json
└── .cursorrules
```

## Quick Start

```bash
cp backend/.env.example backend/.env
cd infra && docker-compose up
```

- Frontend: http://localhost:3000
- API: http://localhost:8000/docs

## Tiers

| Tier | Price | Features |
|------|-------|----------|
| Beginner | Free | 3 queries/day, delayed |
| Pro | $29/mo | Real-time, signals, Grok |
| Elite | $79/mo | Custom agents, PORT VaR/Sharpe |

## Auth

| Endpoint | Description |
|----------|-------------|
| `POST /auth/register` | Create Beginner account, returns JWT |
| `POST /auth/login` | Login, returns JWT + tier |
| `GET /auth/me` | Current user profile |

Frontend: `/login` page + `AuthBar` in dashboard header.

## Key Modules

| Module | Path | Description |
|--------|------|-------------|
| EQS | `backend/routers/screener.py` + `frontend/components/EqSGo.tsx` | 50 filters, presets, 15min Redis cache |
| Market | `backend/routers/market.py` + `integrations/polygon.py` | History/quote via Polygon (FMP fallback) |
| PORT | `backend/routers/portfolio.py` | Holdings table + Celery VaR |
| RAG | `backend/rag/ingest.py` | 500 stocks SEC filings → Pinecone |
| Crypto | `backend/workers/ingest_crypto.py` | 500 crypto → Pinecone |
| AI | `backend/rag/agent.py` | Tier-aware Claude/GPT/Grok |
| Chat | `frontend/app/api/chat/route.ts` | Proxy to `/ai/agent` with JWT |

## Migrations

```bash
cd backend && alembic upgrade head
```

## Deploy

```bash
# Local
cd infra && docker-compose up

# AWS ECS
./infra/deploy-aws.sh staging

# Vercel
vercel deploy

# Terraform
cd infra/terraform && terraform init && terraform apply
```

## CI/CD

GitHub Actions workflow at `.github/workflows/deploy.yml`:

| Job | Trigger | Action |
|-----|---------|--------|
| `test` | PR + push to main | flake8, pytest, frontend build |
| `deploy-frontend` | push to main | Vercel production deploy |
| `deploy-backend` | push to main | ECR push + ECS rolling deploy + Alembic migrate |
| `notify` | after deploy | Slack/Discord hook (optional) |

Required secrets: `VERCEL_TOKEN`, `ORG_ID`, `PROJECT_ID`, `AWS_ROLE_TO_ASSUME`, `SUBNET_IDS`, `SG_ID`

## Edge API (Vercel)

| Route | Runtime | Description |
|-------|---------|-------------|
| `/api/chat` | Edge | JWT verify + Upstash 3/day limit (beginner) → FastAPI `/ai/agent` |
| `/api/billing/checkout` | Edge | Proxy to Stripe checkout |
| `middleware.ts` | Edge | Protects `/dashboard`, `/api/chat`, `/api/billing` |

Required Vercel env: `JWT_SECRET` (min 16 chars, must match backend), `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `NEXT_PUBLIC_API_URL`, `FASTAPI_URL` (server-side FastAPI base URL), `CORS_ORIGINS` (backend, comma-separated)

Root `vercel.json` keeps Next Edge `/api/chat` and `/api/billing/*` on the frontend; FastAPI is routed at `/auth`, `/ai`, `/eqs`, `/port`, `/market`, `/billing`, `/health`.

## Zip Distribution

```bash
zip -r strategyiq-final.zip strategyiq-final -x "*.pyc" "*__pycache__*" "*.git*"
```

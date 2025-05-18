from fastapi import FastAPI
from agno.app.slack.async_router import router as slack_router

app = FastAPI()

app.include_router(slack_router, prefix="/api")

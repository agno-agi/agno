"""
Barebones FastAPI Server for Performance Comparison

This creates the simplest possible FastAPI server wrapping an Agno agent.
Used as a baseline to measure AgentOS overhead.

Usage:
    python cookbook/09_evals/performance/framework_comparison/servers/fastapi_server.py

Server runs at http://localhost:7779
"""

import os

os.environ["AGNO_TELEMETRY"] = "false"

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Form
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.log import set_log_level_to_error

set_log_level_to_error()

agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        system_message="You are a helpful assistant. Be concise.",
        telemetry=False,
        add_history_to_context=False,
        enable_session_summaries=False,
    )
    yield


app = FastAPI(lifespan=lifespan)


class RunResponse(BaseModel):
    content: str
    run_id: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/agent/run")
async def run_agent(message: str = Form(...)):
    response = await agent.arun(message)
    return RunResponse(content=response.content, run_id=response.run_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7779, log_level="error")

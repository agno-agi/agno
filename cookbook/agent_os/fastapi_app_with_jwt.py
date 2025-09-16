"""
Clean AgentOS middleware example using the tuple pattern.

This shows the cleanest DX for AgentOS middleware configuration.
"""

import jwt
from datetime import datetime, timedelta

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import get_current_user_id, JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools

from fastapi import FastAPI, HTTPException, Request, Form

# JWT Secret (use environment variable in production)
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

JWT_MIDDLEWARE = (JWTMiddleware, {
    "secret_key": JWT_SECRET,
    "algorithm": "HS256",
    "token_prefix": "Bearer",
    "user_id_claim": "user_id",
    "auto_error": False,
})

# Create agent
research_agent = Agent(
    id="research-agent",
    name="Research Agent", 
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)

# Create custom FastAPI app
app = FastAPI(
    title="JWT Protected AgentOS",
    version="1.0.0",
)

# Custom routes that use JWT
@app.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Login endpoint that returns JWT token"""
    if username == "demo" and password == "password":
        payload = {
            "user_id": "user_123",
            "username": username,
            "exp": datetime.utcnow() + timedelta(hours=24),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return {"access_token": token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/user/profile")
async def get_user_profile(request: Request):
    """Protected route that shows user information from JWT"""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    return {
        "user_id": user_id,
        "message": f"Hello, user {user_id}!",
        "authenticated": True
    }

@app.post("/agents/research/chat")
async def chat(request: Request):
    """Protected route that shows user information from JWT"""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")
    result = await research_agent.arun(
        input="What is the capital of France?",
        user_id=user_id,
        stream=False,
    )
    return {
        "user_id": user_id,
        "message": result.content,
        "run_id": result.run_id,
        "authenticated": True
    }

# Clean AgentOS setup with tuple middleware pattern! ✨
agent_os = AgentOS(
    description="JWT Protected AgentOS with clean tuple middleware",
    agents=[research_agent],
    fastapi_app=app,
    middleware=[
        JWT_MIDDLEWARE,
    ],
)

# Get the final app
app = agent_os.get_app()

if __name__ == "__main__":
    """
    Run the JWT protected AgentOS using clean tuple middleware pattern.
    
    Test endpoints:
    1. POST /auth/login - Login to get JWT token
    2. GET /user/profile - Protected route (requires JWT)  
    3. Standard AgentOS routes (with JWT support)
    
    Middleware pattern: (MiddlewareClass, params_dict)
    """
    agent_os.serve(app="fastapi_app_with_jwt:app", port=7777, reload=True)
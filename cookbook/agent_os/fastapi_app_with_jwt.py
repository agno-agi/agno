"""
Example AgentOS app with custom JWT middleware for user authentication.

This example shows how to:
1. Set up JWT middleware to extract user_id from tokens
2. Access user_id in custom routes
3. Pass user_id to agent runs
"""

import jwt
from datetime import datetime, timedelta

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, get_current_user_id
from agno.tools.duckduckgo import DuckDuckGoTools

from fastapi import FastAPI, HTTPException, Request, Form

# JWT Secret (use environment variable in production)
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

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
    # In real app, validate credentials against database
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
async def chat_with_agent(
    request: Request,
    message: str = Form(...),
):
    """Custom route that passes user_id to agent"""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    # Run agent with user context
    result = await research_agent.arun(
        input=message,
        user_id=user_id,  # This gets passed to the agent
        stream=False,
    )
    
    return {
        "response": result.content,
        "user_id": user_id,
        "run_id": result.run_id,
    }

# Setup JWT middleware 
app.add_middleware(
    JWTMiddleware,
    secret_key=JWT_SECRET,
    algorithm="HS256",
    token_prefix="Bearer",
    user_id_claim="user_id",
    auto_error=False,
)

# Setup AgentOS with custom middleware
agent_os = AgentOS(
    description="JWT Protected AgentOS example",
    agents=[research_agent],
    fastapi_app=app,
)

# Get the final app
app = agent_os.get_app()

if __name__ == "__main__":
    """
    Run the JWT protected AgentOS.
    
    Test endpoints:
    1. POST /auth/login - Login to get JWT token
    2. GET /user/profile - Protected route (requires JWT)
    3. POST /agents/research/chat - Chat with agent (requires JWT)
    """
    agent_os.serve(app="fastapi_app_with_jwt:app", port=7777, reload=True)
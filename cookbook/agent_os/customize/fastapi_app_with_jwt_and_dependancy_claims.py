"""
This example demonstrates how to use our JWT middleware with dependency claims extraction.

# Note: This example won't work with the AgentOS UI, because of the token validation mechanism in the JWT middleware.
"""

from datetime import datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI, Form, HTTPException, Request

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
    title="JWT Dependencies Claims Example",
    version="1.0.0",
)

# Add JWT middleware with dependencies claims extraction
app.add_middleware(
    JWTMiddleware,
    secret_key=JWT_SECRET,
    excluded_route_paths=["/auth/login", "/docs", "/openapi.json"],
    validate_token=True,
    dependencies_claims=["name", "email", "roles", "department", "permissions"]  # Claims to extract
)

# Mock user database
USERS = {
    "admin": {
        "password": "admin123",
        "user_id": "admin_001",
        "name": "Admin User",
        "email": "admin@example.com",
        "roles": ["admin", "user"],
        "department": "IT",
        "permissions": ["read", "write", "delete"]
    },
    "user": {
        "password": "user123", 
        "user_id": "user_001",
        "name": "Regular User",
        "email": "user@example.com",
        "roles": ["user"],
        "department": "Sales",
        "permissions": ["read"]
    },
    "manager": {
        "password": "manager123",
        "user_id": "manager_001", 
        "name": "Manager User",
        "email": "manager@example.com",
        "roles": ["manager", "user"],
        "department": "Marketing",
        "permissions": ["read", "write"]
    }
}

@app.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Login endpoint that returns JWT token with rich claims"""
    if username in USERS and USERS[username]["password"] == password:
        user_data = USERS[username]
        payload = {
            "sub": user_data["user_id"],
            "username": username,
            "name": user_data["name"],
            "email": user_data["email"],
            "roles": user_data["roles"],
            "department": user_data["department"],
            "permissions": user_data["permissions"],
            "exp": datetime.utcnow() + timedelta(hours=24),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return {"access_token": token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/profile")
async def get_user_profile(request: Request):
    """Get user profile using extracted dependencies - Direct access to request.state"""
    if not getattr(request.state, "user_id", None):
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    dependencies = request.state.dependencies
    
    return {
        "user_id": request.state.user_id,
        "name": dependencies.get("name"),
        "email": dependencies.get("email"), 
        "roles": dependencies.get("roles"),
        "department": dependencies.get("department"),
        "permissions": dependencies.get("permissions"),
        "all_dependencies": dependencies
    }


@app.get("/admin-only")
async def admin_only_route(request: Request):
    """Route that requires admin role - Direct access"""
    user_roles = request.state.dependencies.get("roles", [])
    if "admin" not in user_roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    return {
        "message": "Welcome to the admin area!",
        "user": request.state.dependencies.get("name"),
        "roles": user_roles
    }


@app.get("/manager-or-admin")
async def manager_or_admin_route(request: Request):
    """Route that requires manager or admin role - Direct access"""
    user_roles = request.state.dependencies.get("roles", [])
    if not any(role in user_roles for role in ["admin", "manager"]):
        raise HTTPException(status_code=403, detail="Manager or Admin role required")
    
    return {
        "message": "Welcome to the management area!",
        "user": request.state.dependencies.get("name"),
        "email": request.state.dependencies.get("email"),
        "roles": user_roles,
        "department": request.state.dependencies.get("department")
    }


@app.get("/permissions-check")
async def permissions_check(request: Request):
    """Check user permissions - Direct access"""
    permissions = request.state.dependencies.get("permissions", [])
    
    return {
        "user": request.state.dependencies.get("name"),
        "permissions": permissions,
        "can_write": "write" in permissions,
        "can_delete": "delete" in permissions,
        "can_read": "read" in permissions
    }


# AgentOS setup
agent_os = AgentOS(
    description="JWT Dependencies Claims Example",
    agents=[research_agent],
    fastapi_app=app,
)

# Get the final app
app = agent_os.get_app()

if __name__ == "__main__":
    """
    Run your AgentOS with JWT middleware that extracts dependency claims.
    
    Test the functionality:
    
    1. Login as admin:
       curl -X POST "http://localhost:7777/auth/login" -d "username=admin&password=admin123"
    
    2. Login as user:
       curl -X POST "http://localhost:7777/auth/login" -d "username=user&password=user123"
    
    3. Login as manager:
       curl -X POST "http://localhost:7777/auth/login" -d "username=manager&password=manager123"
    
    4. Test protected routes with token:
       curl -H "Authorization: Bearer <token>" http://localhost:7777/profile
       curl -H "Authorization: Bearer <token>" http://localhost:7777/admin-only
       curl -H "Authorization: Bearer <token>" http://localhost:7777/manager-or-admin
       curl -H "Authorization: Bearer <token>" http://localhost:7777/permissions-check
    """
    agent_os.serve(app="test:app", port=7777, reload=True)
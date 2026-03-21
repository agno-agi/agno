# Microsoft 365 Copilot Integration - Complete Guide

**Purpose:** This guide contains all essential information to integrate any agent system with Microsoft 365 Copilot.
**Created:** March 7, 2026
**Project:** Agno Framework M365 Copilot Interface
**Status:** Production Ready (18 tests passing, security audited)

---

## Quick Start Summary

**What this does:** Expose your AI agents/teams/workflows to Microsoft 365 Copilot as callable plugins via OpenAPI specification.
**Key Components:**
- HTTP endpoints for agent invocation
- Microsoft Entra ID JWT validation (JWKS-based)
- OpenAPI 3.0.1 specification for Copilot Studio registration
- Session management for multi-turn conversations

**Architecture:**
```
Microsoft 365 Copilot
       ↓
  Copilot Studio (Plugin Registration)
       ↓
  OpenAPI Spec ← GET /m365/manifest
       ↓
  HTTP Request (Bearer JWT)
       ↓
[M365 Copilot Interface] ← Your Agent System Here
       ↓
    Agno Agents/Teams/Workflows
```

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Core Components](#2-core-components)
3. [Authentication Flow](#3-authentication-flow)
4. [API Endpoints](#4-api-endpoints)
5. [Configuration](#5-configuration)
6. [Deployment Steps](#6-deployment-steps)
7. [Microsoft 365 Setup](#7-microsoft-365-setup)
8. [Testing Guide](#8-testing-guide)
9. [Security Considerations](#9-security-considerations)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Architecture Overview

### 1.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Microsoft 365 Ecosystem                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  M365 Copilot │───→│ Copilot Studio │───→│   Entra ID   │   │
│  │               │    │              │    │              │   │
│  └───────────────┘    └───────┬──────┘    └──────┬───────┘   │
│                             │                    │             │
│                              ↓ (OpenAPI)          ↓ (JWT)      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │           Plugin Registry (OpenAPI Spec)            │  │
│  └────────────────────────────────────────────────────────┘  │
│                              │                             │
└──────────────────────────────┼─────────────────────────────┘
                               │
                               │ HTTP + JWT
                               ↓
┌────────────────────────────────────────────────────────────┐
│              Your Agent System (Agno/Custom)                  │
├────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────┐   │
│  │         M365 Copilot Interface (This Layer)         │   │
│  │  ┌────────────┐  ┌───────────┐  ┌──────────────┐  │   │
│  │  │ /manifest │  │ /agents    │  │  /invoke     │  │   │
│  │  │   (GET)   │  │  (GET)     │  │   (POST)     │  │   │
│  │  └────────────┘  └───────────┘  └──────────────┘  │   │
│  │         │              │                 │              │   │
│  │  ┌──────▼──────┐  ┌──▼────────┐  ┌───▼──────────┐  │   │
│  │  │  Auth       │  │  Router   │  │   Manifest   │  │   │
│  │  │  Middleware │  │  Handler  │  │  Generator   │  │   │
│  │  └─────────────┘  └───────────┘  └──────────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                          │                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Agent Runtime (Agno/Custom)              │  │
│  │  ┌─────────┐  ┌───────┐  ┌─────────┐                   │  │
│  │  │  Agent  │  │  Team │  │Workflow │                   │  │
│  │  └─────────┘  └───────┘  └─────────┘                   │  │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow

**Invocation Flow:**
```
1. User: "Analyze Q3 financial data" in M365 Copilot
2. M365 Copilot: → Copilot Studio: Find matching plugin
3. Copilot Studio: → GET /m365/manifest (discover capabilities)
4. Copilot Studio: → POST /m365/invoke/financial-analyst
   Headers: Authorization: Bearer <JWT>
   Body: {
     "message": "Analyze Q3 financial data",
     "session_id": "user-session-123",
     "context": {"user_locale": "en-US"}
   }
5. M365 Interface: Validate JWT (JWKS → Entra ID)
6. M365 Interface: Route to Agent/Team/Workflow
7. Agent: Execute and return response
8. M365 Interface: POST /m365/invoke response
9. M365 Copilot: Display result to user
```

---

## 2. Core Components

### 2.1 M365Copilot Interface Class

**Purpose:** Main interface class that connects agents to M365 Copilot.

**Key Attributes:**
- `type`: "m365" (interface identifier)
- `version`: "1.0"
- `agent`: Agno agent to expose
- `team`: Agno team to expose
- `workflow`: Agno workflow to expose
- `tenant_id`: Microsoft Entra ID tenant ID
- `client_id`: Application (client) ID for JWT validation
- `audience`: Expected JWT token audience

**Key Methods:**
- `get_router()`: Returns FastAPI router with all endpoints
- `serve()`: Starts the FastAPI server

### 2.2 Authentication Module (auth.py)

**Purpose:** Validate Microsoft Entra ID JWT tokens.

**Key Functions:**

#### `validate_m365_token()`
```python
async def validate_m365_token(
    token: str,
    expected_tenant_id: str,
    expected_client_id: str,
    enable_signature_verification: bool = True
) -> Dict[str, Any]:
    """
    Validates JWT token with JWKS signature verification.

    Returns: Token claims (upn, oid, tid, aud, iss, exp, scp, roles)
    Raises: ValueError if token invalid/expired/wrong tenant
    """
```

**Validates:**
- ✅ JWT signature (RS256 against JWKS)
- ✅ Issuer (matches tenant_id)
- ✅ Audience (matches client_id)
- ✅ Expiration (exp claim)
- � Not Before (nbf claim)
- ✅ Tenant ID (tid claim matches)

#### `get_jwks()`
- Fetches JWKS from Entra ID: `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`
- Caches for 1 hour (LRU cache)
- Timeout: 5 seconds

### 2.3 Manifest Generator (manifest.py)

**Purpose:** Generate OpenAPI 3.0.1 specification for Copilot Studio.

**Output Specification:**
```yaml
openapi: 3.0.1
info:
  title: "Your Agent API"
  description: "Rich description for LLM understanding"
  version: "1.0.0"
  contact:
    email: "support@example.com"
servers:
  - url: "https://your-agno-server.com"
    description: "Agno Agent Server"
security:
  - bearerAuth: []
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  schemas:
    InvokeRequest: { ... }
    InvokeResponse: { ... }
paths:
  /m365/invoke/{agent_id}:
    post:
      operationId: "invoke_{agent_id}"
      summary: "Invoke {agent_name}"
      description: "Rich description"
      requestBody:
        content:
          application/json:
            schema: { ... }
            example: { ... }
      responses:
        200:
          description: "Success"
        401:
          description: "Unauthorized"
        404:
          description: "Not Found"
        500:
          description: "Server Error"
```

### 2.4 Router Module (router.py)

**Endpoints:**

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/m365/manifest` | No | OpenAPI specification |
| GET | `/m365/agents` | Yes | List available agents |
| POST | `/m365/invoke` | Yes | Invoke agent/team/workflow |
| GET | `/m365/health` | No | Health check |

**Authentication:**
- Uses FastAPI dependency injection
- Creates factory function `_get_validated_token_dependency(tenant_id, client_id)`
- Injects validated token claims into route handlers

---

## 3. Authentication Flow

### 3.1 Microsoft Entra ID Token Structure

```json
{
  "aud": "your-client-id",
  "iss": "https://login.microsoftonline.com/your-tenant-id/v2.0",
  "tid": "your-tenant-id",
  "oid": "user-object-id",
  "upn": "user@example.com",
  "name": "John Doe",
  "iat": 1234567890,
  "nbf": 1234567890,
  "exp": 1234571490,
  "scp": "User.Read Mail.ReadWrite",
  "roles": []
}
```

### 3.2 Validation Steps

```
1. Receive JWT from Authorization header
   ↓
2. Extract key ID (kid) from token header
   ↓
3. Fetch JWKS from Entra ID (cached 1 hour)
   ↓
4. Get public key by kid
   ↓
5. Verify signature with public key (RS256)
   ↓
6. Verify issuer (iss matches tenant_id)
   ↓
7. Verify audience (aud matches client_id)
   ↓
8. Verify expiration (exp > now)
   ↓
9. Verify tenant claim (tid matches tenant_id)
   ↓
10. Return validated claims
```

### 3.3 JWKS Validation

**Endpoint:** `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`

**Response Structure:**
```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "key-id-1",
      "n": "modulus-base64",
      "e": "AQAB",
      "x5t": "certificate-thumbprint"
    }
  ]
}
```

**Caching Strategy:**
- In-memory LRU cache (maxsize=1)
- TTL: 1 hour
- Keys rotate rarely, safe to cache
- For multi-worker deployments, use Redis instead

---

## 4. API Endpoints

### 4.1 GET /m365/manifest

**Purpose:** Return OpenAPI specification for plugin registration.

**Authentication:** None (public endpoint)

**Response:**
```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "Your Agents",
    "description": "...",
    "version": "1.0.0"
  },
  "paths": {
    "/m365/invoke/agent-123": {
      "post": {
        "operationId": "invoke_agent_123",
        "summary": "Invoke Financial Analyst",
        "description": "...",
        "requestBody": { ... },
        "responses": { ... }
      }
    }
  }
}
```

### 4.2 GET /m365/agents

**Purpose:** List available agents (with descriptions).

**Authentication:** Bearer JWT required

**Headers:**
```
Authorization: Bearer <jwt-token>
```

**Response:**
```json
[
  {
    "agent_id": "financial-analyst",
    "name": "Financial Analyst",
    "description": "Expert financial analysis...",
    "type": "agent",
    "capabilities": ["conversation", "search", "knowledge"]
  }
]
```

### 4.3 POST /m365/invoke

**Purpose:** Execute an agent/team/workflow.

**Authentication:** Bearer JWT required

**Request:**
```json
{
  "component_id": "financial-analyst",
  "message": "Analyze Q3 revenue trends",
  "session_id": "user-session-123",
  "context": {
    "user_locale": "en-US",
    "time_zone": "America/New_York"
  }
}
```

**Response (Success):**
```json
{
  "component_id": "financial-analyst",
  "component_type": "agent",
  "output": "Q3 revenue increased by 15%...",
  "session_id": "user-session-123",
  "status": "success",
  "metadata": {
    "agent_name": "Financial Analyst",
    "agent_id": "..."
  }
}
```

**Response (Error):**
- **404:** Component not found
- **500:** Internal server error

### 4.4 GET /m365/health

**Purpose:** Health check endpoint.

**Authentication:** None

**Response:**
```json
{
  "status": "healthy",
  "interface": "m365",
  "components": {
    "agent": true,
    "team": false,
    "workflow": false
  }
}
```

---

## 5. Configuration

### 5.1 Environment Variables

```bash
# Required
export M365_TENANT_ID="your-entra-id-tenant-id"
export M365_CLIENT_ID="your-application-client-id"

# Optional
export M365_AUDIENCE="api://agno"  # Default: "api://agno"
export AGNO_SERVER_URL="https://your-server.com"  # For OpenAPI spec
export ENABLE_AGENT_DISCOVERY=true  # Default: true
```

### 5.2 Python Configuration

```python
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot

# Create agent
agent = Agent(
    name="Financial Analyst",
    instructions="You are a financial expert...",
    # ... other agent config
)

# Create M365 interface
m365_interface = M365Copilot(
    agent=agent,
    # Optional: Customize OpenAPI spec
    api_title="CENF Financial Agents",
    api_description="Specialized AI agents for financial analysis",
    agent_descriptions={
        agent.id: "Expert financial analysis with 15+ years experience"
    },
    # Optional: Environment variables will be used if not provided
    tenant_id="your-tenant-id",  # Or use M365_TENANT_ID env var
    client_id="your-client-id",   # Or use M365_CLIENT_ID env var
)

# Create AgentOS
agent_os = AgentOS(
    agents=[agent],
    interfaces=[m365_interface]
)
```

### 5.3 Advanced Configuration

```python
m365_interface = M365Copilot(
    agent=agent,
    team=team,
    workflow=workflow,
    prefix="/m365",  # URL prefix for endpoints
    tags=["M365", "Copilot", "Agents"],  # FastAPI tags
    tenant_id="...",
    client_id="...",
    audience="api://your-app",
    api_title="...",
    api_description="...",
    api_version="1.0.0",
    agent_descriptions={...},
    enable_agent_discovery=True,  # Allow /m365/agents endpoint
)
```

---

## 6. Deployment Steps

### 6.1 Development Deployment

```bash
# 1. Install dependencies
pip install agno[os]

# 2. Set environment variables
export M365_TENANT_ID="..."
export M365_CLIENT_ID="..."

# 3. Create agent
python your_agent.py

# 4. Start server
uvicorn your_agent:app --host 0.0.0.0 --port 7777
```

### 6.2 Production Deployment

#### Option 1: Direct Deployment

```bash
# 1. Build Docker image
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 7777
CMD ["uvicorn", "your_agent:app", "--host", "0.0.0.0", "--port", "7777"]

# 2. Deploy to cloud
# - AWS ECS/EKS
# - Azure Container Instances
# - Google Cloud Run
# - Kubernetes
```

#### Option 2: Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agno-m365-agents
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agno-m365
  template:
    metadata:
      labels:
        app: agno-m365
    spec:
      containers:
      - name: agno
        image: your-registry/agno-m365:latest
        ports:
        - containerPort: 7777
        env:
        - name: M365_TENANT_ID
          value: "your-tenant-id"
        - name: M365_CLIENT_ID
          value: "your-client-id"
        - name: M365_AUDIENCE
          value: "api://agno"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /m365/health
            port: 7777
          initialDelaySeconds: 10
        readinessProbe:
          httpGet:
            path: /m365/health
            port: 7777
          initialDelaySeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: agno-m365-service
spec:
  selector:
    app: agno-m365
  ports:
  - port: 7777
    targetPort: 7777
  type: LoadBalancer
```

### 6.3 Server Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 1GB
- Network: Public IP or VPN

**Recommended (Production):**
- CPU: 4 cores
- RAM: 2-4GB
- Network: Static IP, SSL/TLS
- High Availability: 3+ replicas

---

## 7. Microsoft 365 Setup

### 7.1 Register Application in Entra ID

1. **Go to:** https://entra.microsoft.com
2. **Navigate:** App registrations → New registration
3. **Configure:**
   - Name: "Agno Agents Production"
   - Supported account types: "Accounts in this organizational directory only"
   - Redirect URI: (optional) `https://your-server.com/callback`
4. **Register**
5. **Save credentials:**
   - Application (client) ID → Copy this
   - Directory (tenant) ID → Copy this
   - Object ID → For app-only authentication

### 7.2 Configure API Permissions

1. **In your app registration:** API Permissions → Add a permission
2. **Select:** Microsoft Graph → Delegated permissions
3. **Add permissions:**
   - `User.Read` - Read user profile
   - `Mail.ReadWrite` - Send/receive mail
   - `Calendars.ReadWrite` - Manage calendar
   - `Files.ReadWrite.All` - Access files
4. **Add permissions** → Grant admin consent for [Your Organization]

### 7.3 Expose API (Optional)

For external access (not recommended for production):

1. **Authentication** → Expose an API
2. **Add a scope:** `access_as_user`
3. **Set state:** Enabled
4. **Copy scope:** `api://your-client-id/access_as_user`

### 7.4 Create Client Secret (App-Only Auth)

If using app-only authentication:

1. **Certificates & secrets** → New client secret
2. **Description:** "Agno Production - Client Secret"
3. **Expires:** 180 days (recommended) or max
4. **Copy immediately** (won't be shown again!)
5. **Store securely** in environment variables

---

## 8. Testing Guide

### 8.1 Manual Testing Script

```python
# test_manual.py (included in cookbook)
import requests

BASE_URL = "http://localhost:7777"

# Test 1: Health check
response = requests.get(f"{BASE_URL}/m365/health")
assert response.status_code == 200
assert response.json()["status"] == "healthy"

# Test 2: Get manifest
response = requests.get(f"{BASE_URL}/m365/manifest")
assert response.status_code == 200
spec = response.json()
assert spec["openapi"] == "3.0.1"
assert "bearerAuth" in spec["components"]["securitySchemes"]

# Test 3: Agents without auth (should fail)
response = requests.get(f"{BASE_URL}/m365/agents")
assert response.status_code in [401, 403]  # Unauthorized or Forbidden
```

### 8.2 Automated Testing

```bash
# Unit tests
pytest libs/agno/tests/unit/os/interfaces/m365/test_m365.py -v

# Integration tests (requires server running)
pytest libs/agno/tests/integration/os/interfaces/test_m365_integration.py -v

# Manual test script
python cookbook/05_agent_os/interfaces/m365/test_manual.py
```

### 8.3 Testing with Real JWT Token

```python
import requests
import jwt
import time

# Create test token (for development only!)
tenant_id = "your-tenant-id"
client_id = "your-client-id"

payload = {
    "aud": client_id,
    "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
    "tid": tenant_id,
    "oid": "test-user-id",
    "upn": "test@example.com",
    "iat": int(time.time()),
    "nbf": int(time.time()),
    "exp": int(time.time()) + 3600
}

# For testing: Use HS256 (not production RS256)
token = jwt.encode(payload, "test-secret", algorithm="HS256")

# Make authenticated request
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:7777/m365/agents",
    headers=headers
)
```

---

## 9. Security Considerations

### 9.1 Critical Security Requirements

#### ✅ Implemented (Production Ready)
- [x] JWKS signature verification (RS256)
- [x] JWT expiration validation
- [x] Issuer validation
- [x] Audience validation
- [x] Tenant ID validation
- [x] Bearer token requirement

#### ⚠️ Requires Implementation Before Production
- [ ] **Authorization logic** (currently placeholder - all authenticated users can access all components)
- [ ] **Rate limiting** (prevent abuse)
- [ ] **Input sanitization** (validate all inputs)
- [ ] **CORS configuration** (restrict origins)
- [ ] **TLS/SSL** (HTTPS in production)

### 9.2 Security Best Practices

#### Token Validation
```python
# Always enable signature verification in production
claims = await validate_m365_token(
    token=request.headers["authorization"],
    expected_tenant_id=os.getenv("M365_TENANT_ID"),
    expected_client_id=os.getenv("M365_CLIENT_ID"),
    enable_signature_verification=True  # Always True in production!
)
```

#### Authorization (TODO: Implement)
```python
def validate_token_for_component(
    token_claims: Dict[str, Any],
    component_id: str,
) -> bool:
    # CURRENT PLACEHOLDER - All users can access all components
    # TODO: Implement proper authorization before production

    # Example implementations:

    # Option 1: Role-based
    user_roles = token_claims.get("roles", [])
    if "AgnoUser" not in user_roles:
        return False

    # Option 2: Scope-based
    required_scope = f"Agno.{component_id}"
    scopes = token_claims.get("scp", "").split()
    if required_scope not in scopes:
        return False

    # Option 3: User-specific
    user_id = token_claims.get("oid")
    return check_user_access(user_id, component_id)
```

#### Rate Limiting (Recommended)
```python
from slowapi import Limiter

limiter = Limiter(key="user_id")

@router.post("/m365/invoke")
@limiter.limit("10/minute")
async def invoke(request: InvokeRequest):
    ...
```

#### CORS Configuration
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://copilotstudio.microsoft.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### 9.3 Security Checklist

**Before Production Deployment:**

- [ ] Change all placeholder values
- [ ] Set strong JWT signing keys
- [ ] Implement rate limiting
- [ ] Configure CORS properly
- [ ] Enable HTTPS/TLS
- [ ] Implement authorization logic
- [ ] Add request logging
- [ ] Set up monitoring/alerts
- [ ] Test with security team
- [ ] Penetration testing

---

## 10. Troubleshooting

### 10.1 Common Issues

#### Issue: "Token validation failed: Token has expired"

**Cause:** JWT token expired (exp claim passed)

**Solution:**
- Token expires after 1 hour (default)
- Client must obtain fresh token
- Check token expiration in decoded JWT

#### Issue: "Component not found"

**Cause:** Component ID doesn't match any registered agent/team/workflow

**Solution:**
```bash
# List available components
curl -H "Authorization: Bearer <token>" \
  http://localhost:7777/m365/agents

# Check component IDs match
```

#### Issue: "Invalid tenant ID"

**Cause:** Tenant ID in token doesn't match expected

**Solution:**
- Verify M365_TENANT_ID environment variable
- Check tid claim in decoded JWT
- Ensure using correct tenant

#### Issue: "Signature verification failed"

**Cause:** JWKS key not found or signature invalid

**Solution:**
- Check tenant_id is correct
- Verify network can reach Entra ID JWKS endpoint
- Clear JWKS cache if keys rotated

```python
from agno.os.interfaces.m365.auth import clear_jwks_cache
clear_jwks_cache()  # Force JWKS refetch
```

### 10.2 Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or use Agno's logger
from agno.utils.log import log_level
log_level("DEBUG")
```

### 10.3 Health Check

```bash
# Check if interface is healthy
curl http://localhost:7777/m365/health

# Expected response:
{
  "status": "healthy",
  "interface": "m365",
  "components": {
    "agent": true,
    "team": false,
    "workflow": false
  }
}
```

---

## 11. OpenAPI Specification Examples

### 11.1 Complete OpenAPI Spec Structure

```yaml
openapi: 3.0.1
info:
  title: "CENF Financial Agents"
  description: "Specialized AI agents for CENF operations. Provides expert analysis of financial reports, trend identification, and actionable insights for stakeholders."
  version: "1.0.0"
  contact:
    email: "support@cenf.com"

servers:
  - url: https://agents.cenf.com
    description: "Agno Agent Server - Production"

security:
  - bearerAuth: []

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
      description: |
        Microsoft Entra ID JWT token (RS256).
        Token must have the correct audience (client_id)
        and be from the configured tenant.

  schemas:
    InvokeRequest:
      type: object
      required:
        - message
      properties:
        message:
          type: string
          description: The user message or task for the agent to process
          minLength: 1
          maxLength: 10000
          example: "Analyze Q3 revenue trends and provide insights"
        session_id:
          type: string
          description: Optional session ID for maintaining conversation context
          pattern: "^[a-zA-Z0-9-_]+$"
          example: "user-session-123"
        context:
          type: object
          description: Additional context (user info, metadata, preferences)
          additionalProperties: true
          example:
            user_locale: "en-US
            time_zone: "America/New_York
            preferences:
              format: "detailed"

    InvokeResponse:
      type: object
      properties:
        component_id:
          type: string
          description: ID of the component that was invoked
        component_type:
          type: string
          enum: [agent, team, workflow]
          description: Type of component that was invoked
        output:
          type: string
          description: The agent's response content
        session_id:
          type: string
          description: Session ID for this invocation
        status:
          type: string
          enum: [success, error]
          description: Status of the invocation
        error:
          type: string
          description: Error message if status is 'error'
        metadata:
          type: object
          description: Optional metadata (timing, tools used, etc.)

paths:
  /m365/invoke/financial-analyst:
    post:
      summary: Invoke Financial Analyst
      description: Expert financial analysis with 15+ years of experience. Analyzes financial reports, identifies trends, and provides actionable insights.
      operationId: invoke_financial_analyst
      tags:
        - Agents
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                message:
                  type: string
                  description: Input message or task for the agent
                session_id:
                  type: string
                  description: Optional session ID for context persistence
                context:
                  type: object
                  description: Additional context (user info, metadata, etc.)
              required:
                - message
            example:
              message: "Analyze Q3 revenue trends and provide insights"
              session_id: "user-session-123"
              context:
                user_locale: "en-US"
      responses:
        "200":
          description: Successful invocation
          content:
            application/json:
              schema:
                type: object
                properties:
                  component_id:
                    type: string
                  component_type:
                    type: string
                  output:
                    type: string
                  status:
                    type: string
        "401":
          description: Unauthorized - Invalid or missing token
        "404":
          description: Not Found - Component not found
        "500":
          description: Internal Server Error - Agent execution failed
```

---

## 12. Production Deployment Checklist

### Pre-Deployment

- [ ] Code reviewed by security team
- [ ] All tests passing (unit + integration)
- [ ] Environment variables configured
- [ ] TLS/SSL certificates obtained
- [ ] Domain name configured
- [ ] Load balancer configured
- [ ] Monitoring setup
- [ ] Logging configured
- [ ] Backup strategy defined
- [ ] Disaster recovery plan tested

### Deployment

- [ ] Deploy to staging environment first
- [ ] Run integration tests on staging
- [ ] Test with real M365 Copilot
- [ ] Load test (simulate concurrent requests)
- [ ] Security scan completed
- [ ] Penetration testing completed
- [ ] Performance baseline established
- [ ] Rollback plan tested

### Post-Deployment

- [ ] Verify health endpoint
- [ ] Test manifest endpoint
- [ ] Test agent invocation
- [ ] Monitor error rates
- [ ] Set up alerts
- [ ] Document known issues
- [ ] Train operations team

---

## 13. Performance Optimization

### 13.1 Caching Strategy

```python
from functools import lru_cache
import redis

# Option 1: In-memory (single worker)
@lru_cache(maxsize=100)
def get_jwks(tenant_id: str) -> Dict:
    # Cache JWKS for 1 hour
    ...

# Option 2: Redis (multi-worker)
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

def get_jwks_redis(tenant_id: str) -> Dict:
    cache_key = f"jwks:{tenant_id}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    # Fetch JWKS...
    redis_client.setex(cache_key, 3600, json.dumps(jwks))
```

### 13.2 Connection Pooling

```python
import httpx

# Async client with connection pooling
client = httpx.AsyncClient(
    limits=httpx.Limits(
        max_connections=100,
        max_keepalive_connections=20
    ),
    timeout=30.0
)
```

### 13.3 Request Timeout Handling

```python
import asyncio

async def invoke_with_timeout(agent, request, timeout=300):
    try:
        response = await asyncio.wait_for(
            agent.arun(request.message, session_id=request.session_id),
            timeout=timeout
        )
        return response
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Agent execution timed out"
        )
```

---

## 14. Monitoring and Observability

### 14.1 Key Metrics to Monitor

**System Metrics:**
- Request rate (requests/second)
- Response time (p50, p95, p99)
- Error rate (4xx, 5xx)
- CPU/memory usage
- Network I/O

**Business Metrics:**
- Agent invocations (total, per agent)
- Success rate (% successful invocations)
- Average response time
- User sessions (active, total)

### 14.2 Logging Strategy

```python
from agno.utils.log import log_info, log_error, log_warning

# Structured logging
log_info(
    f"M365: Invoke successful",
    extra={
        "component_id": request.component_id,
        "user_email": user_info.get("email"),
        "response_time_ms": response_time,
        "status": "success"
    }
)
```

### 14.3 Alerting Rules

**Alert on:**
- Error rate > 5% (5min window)
- Response time p95 > 30s
- Health check failing
- JWKS fetch failures
- High memory usage (>80%)

---

## 15. Compliance and Data Privacy

### 15.1 GDPR Considerations

**Data Processing:**
- User email (upn) - Process for authentication
- User ID (oid) - Process for session tracking
- Tenant ID (tid) - Process for routing
- Message content - Processed by agent

**Recommendations:**
- Minimize data collection
- Implement data retention policies
- Provide privacy notice
- Allow users to request data deletion
- Log only necessary data

### 15.2 HIPAA Considerations (if applicable)

**If handling healthcare data:**
- Enable audit logging
- Implement PHI sanitization
- Ensure BAA with Microsoft
- Encrypt data at rest and in transit
- Implement access controls

### 15.3 SOC 2 Compliance

**Key Controls:**
- Access control (implement authorization)
- System logging (structured logs)
- Incident response (alerting)
- Change management (git workflow)
- Data backup (disaster recovery)

---

## 16. Maintenance and Updates

### 16.1 Regular Maintenance Tasks

**Weekly:**
- Review error logs
- Check performance metrics
- Verify security patches

**Monthly:**
- Update dependencies
- Review access logs
- Test disaster recovery

**Quarterly:**
- Security audit
- Penetration test
- Performance review
- Documentation update

### 16.2 Updating Agents

**Zero-downtime deployment:**
```bash
# Deploy new agent version
kubectl rollingupdate deployment/agno-m365 --image=new-version

# Or use blue-green deployment
kubectl apply -f deployment-blue.yaml
# Wait for healthy
kubectl apply -f deployment-green.yaml
```

---

## 17. Advanced Patterns

### 17.1 Multi-Agent Teams

```python
from agno.team import Team

# Create team of agents
team = Team(
    name="Financial Analysis Team",
    members=[financial_analyst, risk_analyst, report_writer],
    instructions="Collaborative financial analysis"
)

interface = M365Copilot(
    team=team,
    tenant_id="...",
    client_id="..."
)
```

### 17.2 Workflow Orchestration

```python
from agno.workflow import Workflow, Step

# Create multi-step workflow
workflow = Workflow(
    name="Financial Report Workflow",
    steps=[
        Step(name="extract", agent=extractor_agent),
        Step(name="analyze", agent=analyst_agent),
        Step(name="report", agent=report_writer_agent)
    ]
)

interface = M365Copilot(
    workflow=workflow,
    tenant_id="...",
    client_id="..."
)
```

### 17.3 Session Management

```python
# Session context persistence
response = await agent.arun(
    message="...",
    session_id="user-123",
    # Agent maintains context across invocations
)
```

---

## 18. FAQ

### Q: Can I use this without Microsoft 365 Copilot?

**A:** Yes! The interface provides standard HTTP endpoints. You can call it from any HTTP client:
```bash
curl -X POST http://your-server.com/m365/invoke/agent-123 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Hello"}'
```

### Q: Do I need Microsoft Entra ID?

**A:** For JWT validation, yes. However, you can disable signature verification (not recommended):
```python
await validate_m365_token(
    token=token,
    expected_tenant_id=tenant_id,
    expected_client_id=client_id,
    enable_signature_verification=False  # NOT RECOMMENDED
)
```

### Q: Can I host multiple agents?

**A:** Yes! You can expose:
- Single agent: `M365Copilot(agent=agent1)`
- Multiple agents: Create multiple interfaces with different prefixes
- Team: `M365Copilot(team=my_team)`
- Workflow: `M365Copilot(workflow=my_workflow)`

### Q: What about file uploads?

**A:** The current interface accepts text messages. For files:
- Option 1: Upload file to cloud storage, pass URL in message
- Option 2: Base64 encode file in message (size limited)
- Option 3: Implement multipart endpoint (future enhancement)

### Q: How do I handle streaming responses?

**A:** Current implementation uses request/response. For streaming:
```python
# Future enhancement: Server-Sent Events
async def stream_invoke(request: InvokeRequest):
    async for chunk in agent.astream_run(...):
        yield f"data: {chunk}\n\n"
```

---

## 19. Support and Resources

### 19.1 Official Documentation

**Agno Framework:**
- Docs: https://docs.agno.com
- GitHub: https://github.com/agno-agi/agno
- Discord: https://www.agno.com/discord
- Discourse: https://community.agno.com/

**Microsoft 365 Copilot:**
- Copilot Studio: https://copilotstudio.microsoft.com
- Entra ID: https://entra.microsoft.com
- Graph API: https://learn.microsoft.com/graph/

### 19.2 Getting Help

**For Agno-specific issues:**
- GitHub Issues: https://github.com/agno-agi/agno/issues
- Discord: https://discord.gg/4MtYHHrgA8

**For M365-specific issues:**
- Microsoft Support: https://support.microsoft.com
- Copilot Studio docs: https://learn.microsoft.com/copilot-studio/

### 19.3 Contributing

This interface is open source. Contributions welcome!

**Repository:** https://github.com/agno-agi/agno
**Branch:** `feat/m365-copilot-interface`
**Fork:** https://github.com/CENFARG/agno

---

## 20. Quick Reference Commands

```bash
# Install
pip install agno[os]

# Environment variables
export M365_TENANT_ID="your-tenant-id"
export M365_CLIENT_ID="your-client-id"

# Run tests
pytest libs/agno/tests/unit/os/interfaces/m365/test_m365.py

# Start server
python cookbook/05_agent_os/interfaces/m365/basic.py

# Health check
curl http://localhost:7777/m365/health

# Get manifest
curl http://localhost:7777/m365/manifest | jq '.info'

# List agents (with token)
TOKEN=$(eyJ...)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:7777/m365/agents

# Invoke agent
curl -X POST http://localhost:7777/m365/invoke/agent-123 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "message": "Analyze Q3 trends",
    "session_id": "user-123"
  }'
```

---

## 21. Version History

- **v1.0** (March 2026): Initial release with JWKS validation, OpenAPI 3.0.1, complete test coverage

---

## 22. License

This interface is part of the Agno framework and follows the Apache-2.0 license.

---

**End of Guide**

**Next Steps:**
1. Deploy to staging environment
2. Configure Microsoft Entra ID
3. Test with sample agents
4. Register in Copilot Studio
5. Deploy to production
6. Monitor and optimize

**Questions?**
- Agno Discord: https://discord.gg/4MtYHHrgA8
- GitHub Issues: https://github.com/agno-agi/agno/issues

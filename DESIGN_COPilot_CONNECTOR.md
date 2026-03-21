# Agno as Sub-Agent for Microsoft 365 Copilot - Design Document

## Executive Summary

This document describes a **bidirectional connector** that enables Microsoft 365 Copilot and Copilot Studio to invoke Agno agents, teams, and workflows as specialized sub-agents.

**Goal:** Expose Agno agents as callable services from Microsoft 365 Copilot via:
- Microsoft 365 Agents SDK (Custom Engine Agent)
- OpenAPI Plugin for Declarative Agents
- Copilot Studio integration

**Status:** Design Phase
**Version:** 1.0.0
**Date:** 2025-03-05

---

## Architecture Overview

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Microsoft 365 Copilot                             │
│                  (User asks a question)                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Copilot Orchestrator / Agent Builder                    │
│         "I need help with a specialized task..."                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
    ┌───────────────────┐         ┌──────────────────────┐
    │  Built-in Skills  │         │  Agno Sub-Agent      │
    │  (Graph, Search)  │         │  (via Connector)     │
    └───────────────────┘         └──────────┬───────────┘
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   │
        ┌───────────────────────────────────────────────────────┐       │
        │         Agno Agent Server (Python)                     │       │
        │  ├─ HTTP Endpoint (FastAPI)                            │       │
        │  ├─ Agent Registry                                     │       │
        │  ├─ Request/Response Mapper                            │       │
        │  └─ Agno Agent/Team/Workflow invocation                │       │
        └───────────────────────────────────────────────────────┘       │
                    │                                                   │
                    ▼                                                   │
        ┌───────────────────────────────────────────────────────┐       │
        │              Agno Framework                            │       │
        │  ├─ Agent (specialized sub-agent)                     │       │
        │  ├─ Team (multi-agent collaboration)                  │       │
        │  └─ Workflow (orchestrated tasks)                     │       │
        └───────────────────────────────────────────────────────┘       │
                    │                                                   │
                    └───────────────────────────────────────────────────┘
                                          │
                                          ▼
                            ┌───────────────────────┐
                            │  Response back to     │
                            │  M365 Copilot         │
                            └───────────────────────┘
```

---

## Component Architecture

### 1. Agno Agent Server

The Agno Agent Server is a FastAPI application that exposes Agno agents as HTTP endpoints.

```python
# agno_agent_server/server.py

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import uvicorn

from agno.agent import Agent
from agno.team import Team
from agno.workflow import Workflow


# =============================================================================
# Models
# =============================================================================

class AgentRequest(BaseModel):
    """Request model for invoking an Agno agent."""

    agent_id: str = Field(..., description="ID of the agent to invoke")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    input_text: str = Field(..., description="Input text/question for the agent")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Agent parameters")


class AgentResponse(BaseModel):
    """Response model from Agno agent."""

    agent_id: str
    session_id: str
    output: str
    metadata: Optional[Dict[str, Any]] = None
    tools_used: Optional[List[str]] = None
    error: Optional[str] = None


class AgentManifest(BaseModel):
    """Manifest describing an available Agno agent."""

    agent_id: str
    name: str
    description: str
    capabilities: List[str]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    example_prompts: List[str]


# =============================================================================
# Agent Registry
# =============================================================================

class AgentRegistry:
    """
    Registry for managing Agno agents available for M365 Copilot invocation.

    Agents can be:
    - Individual Agent instances
    - Team instances (multi-agent)
    - Workflow instances (orchestrated)
    """

    def __init__(self):
        self._agents: Dict[str, Union[Agent, Team, Workflow]] = {}
        self._manifests: Dict[str, AgentManifest] = {}

    def register(
        self,
        agent_id: str,
        agent: Union[Agent, Team, Workflow],
        manifest: AgentManifest
    ):
        """Register an agent with the registry."""
        self._agents[agent_id] = agent
        self._manifests[agent_id] = manifest

    def get(self, agent_id: str) -> Union[Agent, Team, Workflow]:
        """Get an agent by ID."""
        if agent_id not in self._agents:
            raise ValueError(f"Agent '{agent_id}' not found in registry")
        return self._agents[agent_id]

    def get_manifest(self, agent_id: str) -> AgentManifest:
        """Get an agent manifest by ID."""
        if agent_id not in self._manifests:
            raise ValueError(f"Manifest for '{agent_id}' not found")
        return self._manifests[agent_id]

    def list_agents(self) -> List[str]:
        """List all registered agent IDs."""
        return list(self._agents.keys())

    def list_manifests(self) -> List[AgentManifest]:
        """List all agent manifests."""
        return list(self._manifests.values())


# Global registry
registry = AgentRegistry()


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Agno Agent Server",
    description="HTTP endpoint for Microsoft 365 Copilot to invoke Agno agents",
    version="1.0.0"
)

security = HTTPBearer()


# =============================================================================
# Authentication & Authorization
# =============================================================================

async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Verify Microsoft Entra ID JWT token.

    This endpoint validates that the request comes from an authenticated
    Microsoft 365 Copilot or Copilot Studio instance.
    """
    token = credentials.credentials

    # TODO: Implement proper JWT validation with Microsoft Entra ID
    # For now, accept any bearer token in development
    return {
        "valid": True,
        "tenant_id": "your-tenant-id",
        "user_id": "user-id-from-token"
    }


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "agno-agent-server"}


@app.get("/agents", response_model=List[AgentManifest])
async def list_agents(
    auth: Dict[str, Any] = Depends(verify_token)
):
    """
    List all available Agno agents.

    This endpoint is called by Microsoft 365 Copilot to discover
    what specialized sub-agents are available.
    """
    return registry.list_manifests()


@app.get("/agents/{agent_id}", response_model=AgentManifest)
async def get_agent_manifest(
    agent_id: str,
    auth: Dict[str, Any] = Depends(verify_token)
):
    """Get the manifest for a specific agent."""
    try:
        return registry.get_manifest(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/agents/{agent_id}/invoke", response_model=AgentResponse)
async def invoke_agent(
    agent_id: str,
    request: AgentRequest,
    auth: Dict[str, Any] = Depends(verify_token)
):
    """
    Invoke an Agno agent.

    This is the main endpoint called by Microsoft 365 Copilot when
    it needs to delegate a task to a specialized Agno sub-agent.

    Flow:
    1. Receive request from M365 Copilot
    2. Get the registered Agno agent
    3. Invoke the agent with the input text
    4. Return the agent's response
    """
    try:
        # Get the agent
        agent = registry.get(agent_id)

        # Invoke the agent
        if isinstance(agent, Agent):
            response = agent.run(request.input_text, session_id=request.session_id)
            output = response.content
        elif isinstance(agent, Team):
            response = agent.run(request.input_text)
            output = response.content
        elif isinstance(agent, Workflow):
            response = agent.run(request.input_text)
            output = response.content
        else:
            raise ValueError(f"Unsupported agent type: {type(agent)}")

        return AgentResponse(
            agent_id=agent_id,
            session_id=request.session_id or "default",
            output=output,
            metadata={
                "agent_type": type(agent).__name__,
                "tenant_id": auth.get("tenant_id")
            }
        )

    except Exception as e:
        return AgentResponse(
            agent_id=agent_id,
            session_id=request.session_id or "default",
            output="",
            error=str(e)
        )


# =============================================================================
# Startup
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Register default agents on startup."""
    # This is where you would register your Agno agents
    # Example:

    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    # Example: Data Analysis Agent
    data_agent = Agent(
        name="Data Analysis Specialist",
        model=OpenAIChat(id="gpt-4"),
        instructions="You are a data analysis expert. Analyze data and provide insights."
    )

    registry.register(
        agent_id="data-analysis",
        agent=data_agent,
        manifest=AgentManifest(
            agent_id="data-analysis",
            name="Data Analysis Specialist",
            description="Expert in data analysis, statistics, and providing insights from data",
            capabilities=[
                "Analyze datasets",
                "Generate statistical summaries",
                "Create data visualizations",
                "Identify trends and patterns"
            ],
            input_schema={
                "type": "object",
                "properties": {
                    "input_text": {
                        "type": "string",
                        "description": "Question or task for data analysis"
                    }
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "output": {
                        "type": "string",
                        "description": "Analysis results and insights"
                    }
                }
            },
            example_prompts=[
                "Analyze this sales data and identify trends",
                "What are the key metrics in this dataset?",
                "Generate a summary of this quarterly report"
            ]
        )
    )

    print(f"✓ Registered {len(registry.list_agents())} agents")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

### 2. OpenAPI Specification for Microsoft Copilot Studio

```yaml
# openapi/agno_connector.yaml

openapi: 3.0.0
info:
  title: Agno Sub-Agent Connector
  description: |
    OpenAPI specification for invoking Agno agents from Microsoft 365 Copilot
    and Copilot Studio as specialized sub-agents.
  version: 1.0.0
  contact:
    name: Agno Project
    url: https://github.com/agno-agi/agno

servers:
  - url: https://your-agno-server.com/api/v1
    description: Production server
  - url: https://dev-agno-server.com/api/v1
    description: Development server

security:
  - bearerAuth: []

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
      description: |
        Microsoft Entra ID JWT token. The token is validated by the Agno
        Agent Server to ensure the request comes from an authorized
        Microsoft 365 Copilot instance.

paths:
  /agents:
    get:
      summary: List available agents
      description: |
        Returns a list of all Agno agents that can be invoked as
        sub-agents from Microsoft 365 Copilot.
      operationId: listAgents
      responses:
        '200':
          description: List of available agents
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/AgentManifest'

  /agents/{agentId}:
    get:
      summary: Get agent manifest
      description: |
        Returns detailed information about a specific Agno agent,
        including its capabilities and input/output schemas.
      operationId: getAgentManifest
      parameters:
        - name: agentId
          in: path
          required: true
          schema:
            type: string
          description: ID of the agent
      responses:
        '200':
          description: Agent manifest
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentManifest'

  /agents/{agentId}/invoke:
    post:
      summary: Invoke an Agno agent
      description: |
        Invokes an Agno agent with the provided input and returns
        the agent's response. This is the main endpoint used by
        Microsoft 365 Copilot to delegate tasks to specialized sub-agents.
      operationId: invokeAgent
      parameters:
        - name: agentId
          in: path
          required: true
          schema:
            type: string
          description: ID of the agent to invoke
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AgentRequest'
      responses:
        '200':
          description: Agent response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentResponse'

components:
  schemas:
    AgentManifest:
      type: object
      required:
        - agentId
        - name
        - description
        - capabilities
      properties:
        agentId:
          type: string
          description: Unique identifier for the agent
        name:
          type: string
          description: Human-readable name of the agent
        description:
          type: string
          description: Detailed description of what the agent does
        capabilities:
          type: array
          items:
            type: string
          description: List of capabilities the agent provides
        examplePrompts:
          type: array
          items:
            type: string
          description: Example prompts that this agent can handle

    AgentRequest:
      type: object
      required:
        - inputText
      properties:
        sessionId:
          type: string
          description: |
            Optional session ID for maintaining context across
            multiple invocations
        inputText:
          type: string
          description: |
            The input text or question for the Agno agent to process
        context:
          type: object
          description: |
            Additional context to provide to the agent (e.g., user info,
            previous conversation history)
        parameters:
          type: object
          description: |
            Optional parameters to configure agent behavior

    AgentResponse:
      type: object
      required:
        - agentId
        - output
      properties:
        agentId:
          type: string
          description: ID of the agent that was invoked
        sessionId:
          type: string
          description: Session ID for this invocation
        output:
          type: string
          description: |
            The agent's response to the input. This is what will be
            presented to the user in Microsoft 365 Copilot.
        metadata:
          type: object
          description: |
            Additional metadata about the invocation (e.g., processing time,
            tools used, confidence scores)
        toolsUsed:
          type: array
          items:
            type: string
          description: List of tools the agent used during processing
        error:
          type: string
          description: |
            Error message if the agent invocation failed. Present only
            when there was an error.
```

---

### 3. Declarative Agent Manifest for Microsoft 365 Copilot

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/declarative-agent/v1/manifest.json",
  "version": "1.6",
  "name": {
    "short": "Agno Agents",
    "full": "Agno Specialized Sub-Agents"
  },
  "description": "Connect to specialized Agno AI agents for advanced data analysis, research, and custom workflows",
  "capabilities": [
    {
      "name": "AgnoDataAnalysis",
      "type": "plugin",
      "description": "Invoke Agno's data analysis specialist for complex data tasks"
    },
    {
      "name": "AgnoResearch",
      "type": "plugin",
      "description": "Use Agno's research agent for deep-dive information gathering"
    },
    {
      "name": "AgnoWorkflow",
      "type": "plugin",
      "description": "Execute custom Agno workflows for specialized business processes"
    }
  ],
  "instructions": "You are connected to Agno specialized sub-agents. When users request data analysis, research, or specialized workflows, delegate to the appropriate Agno agent using the available plugins.",
  "conversationStarters": [
    "Analyze this dataset for trends",
    "Research the latest developments in AI",
    "Run the monthly report workflow"
  ],
  "actions": [
    {
      "id": "invoke-agno-agent",
      "type": "plugin",
      "displayName": "Invoke Agno Agent",
      "description": "Delegate a task to a specialized Agno sub-agent",
      "plugin": {
        "manifestReference": "openapi/agno_connector.yaml"
      }
    }
  ]
}
```

---

### 4. Microsoft 365 Agents SDK Integration

```python
# copilot_integration/agno_custom_agent.py

"""
Microsoft 365 Agents SDK integration for Agno.

This creates a custom engine agent that acts as a bridge between
Microsoft 365 Copilot and the Agno Agent Server.
"""

from typing import Any, Dict
from microsoft.agents import (
    AgentApplication,
    ActivityHandler,
    TurnContext,
    CardFactory
)
from microsoft.agents.schema import Activity, ActivityTypes
import httpx
import os


class AgnoBridgeAgent(AgentApplication):
    """
    Microsoft 365 Agents SDK application that bridges
    Microsoft 365 Copilot to Agno agents.

    This agent receives messages from Copilot, forwards them to
    the Agno Agent Server, and returns the responses.
    """

    def __init__(self):
        # Initialize the Agents SDK application
        super().__init__(
            app_id=os.getenv("MICROSOFT_APP_ID"),
            credential=os.getenv("MICROSOFT_APP_PASSWORD"),
        )

        # Agno Agent Server configuration
        self.agno_server_url = os.getenv(
            "AGNO_SERVER_URL",
            "https://your-agno-server.com/api/v1"
        )
        self.agno_api_key = os.getenv("AGNO_API_KEY")

        # Register message handler
        self.on_activity(ActivityTypes.message, self.on_message)

    async def on_message(self, context: TurnContext, state: Any):
        """
        Handle incoming messages from Microsoft 365 Copilot.

        Flow:
        1. Receive message from Copilot
        2. Analyze the message to determine which Agno agent to call
        3. Forward to Agno Agent Server
        4. Return the response to Copilot
        """
        message_text = context.activity.text

        # Determine which agent to invoke
        agent_id = self._determine_agent(message_text)

        # Call Agno Agent Server
        response = await self._invoke_agno_agent(
            agent_id=agent_id,
            input_text=message_text,
            session_id=str(context.activity.conversation.id)
        )

        # Send response back to Copilot
        await context.send_activity(response)

    def _determine_agent(self, message_text: str) -> str:
        """
        Determine which Agno agent to invoke based on the message.

        This is a simple rule-based approach. In production, you might
        use an LLM to make this determination.
        """
        message_lower = message_text.lower()

        # Simple keyword-based routing
        if any(word in message_lower for word in ["analyze", "data", "statistics", "trends"]):
            return "data-analysis"
        elif any(word in message_lower for word in ["research", "find information", "look up"]):
            return "research"
        elif any(word in message_lower for word in ["workflow", "process", "automate"]):
            return "workflow"
        else:
            return "general"

    async def _invoke_agno_agent(
        self,
        agent_id: str,
        input_text: str,
        session_id: str
    ) -> str:
        """
        Invoke an Agno agent via HTTP.

        Args:
            agent_id: ID of the Agno agent to invoke
            input_text: Input text/question for the agent
            session_id: Session ID for context

        Returns:
            The agent's response
        """
        url = f"{self.agno_server_url}/agents/{agent_id}/invoke"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.agno_api_key}"
        }

        payload = {
            "input_text": input_text,
            "session_id": session_id
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()

                data = response.json()
                return data.get("output", "No response from agent")

        except httpx.HTTPError as e:
            return f"Error calling Agno agent: {str(e)}"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    from microsoft.agents import (
        CloudAdapter,
        ConfigurationBotFrameworkAuthentication,
        ConfigurationServiceClientCredentialsFactory
    )

    # Create the agent application
    agent = AgnoBridgeAgent()

    # Run the agent
    agent.run()
```

---

### 5. Directory Structure

```
agno/
├── libs/agno/agno/copilot/              # NEW: Copilot connector module
│   ├── __init__.py
│   ├── server.py                        # FastAPI server
│   ├── registry.py                      # Agent registry
│   ├── models.py                        # Request/response models
│   ├── auth.py                          # Authentication
│   └── config.py                        # Configuration
│
├── copilot_integration/                 # NEW: M365 Agents SDK integration
│   ├── __init__.py
│   ├── bridge_agent.py                  # Custom engine agent
│   ├── manifest.json                    # Declarative agent manifest
│   └── app_package/                     # M365 app package
│       ├── manifest.json
│       └── icons/
│
├── openapi/                             # NEW: OpenAPI specifications
│   └── agno_connector.yaml
│
├── cookbook/
│   └── 92_integrations/
│       └── microsoft_copilot/           # NEW: Examples
│           ├── README.md
│           ├── basic_server.py
│           ├── custom_agent_example.py
│           └── cenf_template.py         # CENF-specific template
│
└── tests/
    └── copilot/                         # NEW: Tests
        ├── test_server.py
        ├── test_registry.py
        └── test_bridge_agent.py
```

---

## 6. CENF-Specific Template

```python
# cookbook/92_integrations/microsoft_copilot/cenf_template.py

"""
CENF-specific Agno template for Microsoft 365 Copilot integration.

This template provides pre-configured agents optimized for CENF's
specific use cases and requirements.
"""

from agno.agent import Agent
from agno.team import Team
from agno.workflow import Workflow
from agno.models.openai import OpenAIChat
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.tools.experimental import CENFTools


class CENFAgentTemplate:
    """
    Template for creating CENF-specific Agno agents that can be
    invoked from Microsoft 365 Copilot.
    """

    @staticmethod
    def create_financial_analyst_agent() -> Agent:
        """Create a specialized financial analysis agent."""
        return Agent(
            name="CENF Financial Analyst",
            model=OpenAIChat(id="gpt-4"),
            tools=[MicrosoftGraphToolkit()],
            instructions="""
            You are a specialized financial analyst for CENF.

            Your responsibilities:
            - Analyze financial reports and statements
            - Identify trends and anomalies in financial data
            - Generate financial insights and recommendations
            - Create financial summaries for stakeholders

            Always:
            - Use precise financial terminology
            - Cite data sources from Microsoft Graph
            - Provide actionable insights
            - Maintain confidentiality of financial information
            """
        )

    @staticmethod
    def create_research_team() -> Team:
        """Create a specialized research team."""
        return Team(
            name="CENF Research Team",
            members=[
                Agent(name="Market Analyst", model=OpenAIChat(id="gpt-4")),
                Agent(name="Competitive Intelligence", model=OpenAIChat(id="gpt-4")),
                Agent(name="Industry Trends Analyst", model=OpenAIChat(id="gpt-4"))
            ],
            instructions="""
            You are a specialized research team for CENF.

            Your responsibilities:
            - Conduct market research
            - Analyze competitive landscape
            - Identify industry trends
            - Synthesize research findings

            Workflow:
            1. Market Analyst gathers market data
            2. Competitive Intelligence analyzes competitors
            3. Industry Trends Analyst identifies trends
            4. Team synthesizes findings into actionable insights
            """
        )

    @staticmethod
    def create_compliance_workflow() -> Workflow:
        """Create a specialized compliance workflow."""
        return Workflow(
            name="CENF Compliance Check",
            agents=[
                Agent(name="Policy Reviewer", model=OpenAIChat(id="gpt-4")),
                Agent(name="Risk Assessor", model=OpenAIChat(id="gpt-4")),
                Agent(name="Compliance Reporter", model=OpenAIChat(id="gpt-4"))
            ],
            instructions="""
            You are a specialized compliance workflow for CENF.

            Process:
            1. Policy Reviewer checks applicable regulations
            2. Risk Assessor evaluates compliance risks
            3. Compliance Reporter generates compliance report

            Output: Structured compliance report with findings and recommendations
            """
        )


# CENF-specific agent registration for Agno Agent Server

def register_cenf_agents(registry):
    """Register CENF-specific agents with the Agno Agent Server."""

    template = CENFAgentTemplate()

    # Financial Analyst Agent
    registry.register(
        agent_id="cenf-financial-analyst",
        agent=template.create_financial_analyst_agent(),
        manifest={
            "agent_id": "cenf-financial-analyst",
            "name": "CENF Financial Analyst",
            "description": "Specialized financial analysis for CENF",
            "capabilities": [
                "Financial statement analysis",
                "Trend identification",
                "Financial insights generation",
                "Stakeholder reporting"
            ],
            "example_prompts": [
                "Analyze the Q3 financial results",
                "What are the key financial trends this quarter?",
                "Generate a financial summary for the board meeting"
            ]
        }
    )

    # Research Team
    registry.register(
        agent_id="cenf-research-team",
        agent=template.create_research_team(),
        manifest={
            "agent_id": "cenf-research-team",
            "name": "CENF Research Team",
            "description": "Multi-agent research team for market and competitive intelligence",
            "capabilities": [
                "Market research",
                "Competitive analysis",
                "Industry trend identification",
                "Research synthesis"
            ],
            "example_prompts": [
                "Research the competitive landscape for electric vehicles",
                "What are the emerging trends in sustainable energy?",
                "Analyze competitor positioning in the market"
            ]
        }
    )

    # Compliance Workflow
    registry.register(
        agent_id="cenf-compliance-workflow",
        agent=template.create_compliance_workflow(),
        manifest={
            "agent_id": "cenf-compliance-workflow",
            "name": "CENF Compliance Check",
            "description": "Automated compliance checking workflow",
            "capabilities": [
                "Policy review",
                "Risk assessment",
                "Compliance reporting",
                "Regulatory check"
            ],
            "example_prompts": [
                "Run compliance check for the new product",
                "Assess regulatory risks for the proposed changes",
                "Generate a compliance report for Q4"
            ]
        }
    )
```

---

## Implementation Plan

### Phase 1: Core Agno Agent Server (Week 1-2)

**Deliverables:**
- [ ] FastAPI server with `/agents`, `/agents/{id}`, `/agents/{id}/invoke` endpoints
- [ ] Agent Registry for managing Agno agents
- [ ] Request/Response models with Pydantic
- [ ] Basic authentication (JWT validation)
- [ ] Health check endpoint

**Tasks:**
1. Create `libs/agno/agno/copilot/` directory structure
2. Implement `server.py` with FastAPI application
3. Implement `registry.py` with AgentRegistry class
4. Implement `models.py` with Pydantic models
5. Implement `auth.py` with JWT validation
6. Add unit tests

### Phase 2: Microsoft 365 Agents SDK Integration (Week 3-4)

**Deliverables:**
- [ ] Custom engine agent using Microsoft 365 Agents SDK
- [ ] Bridge between Copilot and Agno Agent Server
- [ ] Message routing logic
- [ ] Error handling and retry logic

**Tasks:**
1. Set up Microsoft 365 Agents SDK project
2. Implement `AgnoBridgeAgent` class
3. Add agent determination logic
4. Implement HTTP client for Agno Agent Server
5. Add error handling
6. Create app package for deployment

### Phase 3: OpenAPI & Plugin Manifest (Week 5)

**Deliverables:**
- [ ] OpenAPI specification for Agno connector
- [ ] Declarative agent manifest for M365 Copilot
- [ ] Plugin configuration

**Tasks:**
1. Create OpenAPI YAML specification
2. Create declarative agent manifest JSON
3. Configure plugin settings
4. Test with Copilot Studio

### Phase 4: CENF Template & Examples (Week 6)

**Deliverables:**
- [ ] CENF-specific agent template
- [ ] Example agents (Financial Analyst, Research Team, Compliance Workflow)
- [ ] Cookbook examples
- [ ] Documentation

**Tasks:**
1. Implement `CENFAgentTemplate` class
2. Create example agents
3. Write cookbook examples
4. Document CENF-specific configuration

### Phase 5: Testing & Documentation (Week 7-8)

**Deliverables:**
- [ ] Integration tests
- [ ] End-to-end tests with M365 Copilot
- [ ] User documentation
- [ ] API documentation

**Tasks:**
1. Write integration tests
2. Test with M365 Copilot
3. Write documentation
4. Create examples

---

## Security Considerations

### Authentication Flow

```
┌─────────────────┐
│ M365 Copilot    │
└────────┬────────┘
         │ 1. User asks question
         ▼
┌─────────────────────────────┐
│ Microsoft Entra ID          │
│ (Validates user)            │
└────────┬────────────────────┘
         │ 2. Returns JWT
         ▼
┌─────────────────────────────┐
│ Agno Agent Server           │
│ (Validates JWT)             │
└────────┬────────────────────┘
         │ 3. Invokes Agno agent
         ▼
┌─────────────────────────────┐
│ Agno Agent/Team/Workflow    │
└────────┬────────────────────┘
         │ 4. Returns response
         ▼
┌─────────────────────────────┐
│ M365 Copilot (shows result) │
└─────────────────────────────┘
```

### Security Best Practices

1. **Token Validation**: Validate Microsoft Entra ID JWT tokens on every request
2. **HTTPS Only**: All communication over HTTPS
3. **Rate Limiting**: Implement rate limiting per tenant/user
4. **Audit Logging**: Log all agent invocations for compliance
5. **Input Validation**: Validate all inputs before processing
6. **Error Messages**: Sanitized error messages (no sensitive data)

---

## Configuration Example

```bash
# .env file for Agno Agent Server

# Agno Server Configuration
AGNO_SERVER_HOST=0.0.0.0
AGNO_SERVER_PORT=8000
AGNO_SERVER_URL=https://your-agno-server.com

# Microsoft Entra ID (for validating incoming tokens)
MICROSOFT_ENTRA_TENANT_ID=your-tenant-id
MICROSOFT_ENTRA_CLIENT_ID=your-client-id
MICROSOFT_ENTRA_ISSUER=https://sts.windows.net/{tenant-id}/

# API Keys (for Copilot to call Agno server)
AGNO_API_KEY=your-api-key-here

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Agent Configuration
ENABLE_CENF_AGENTS=true
ENABLE_GENERAL_AGENTS=true
```

---

## Testing Strategy

### Unit Tests

```python
# tests/copilot/test_registry.py

import pytest
from agno/copilot/registry import AgentRegistry, AgentManifest
from agno.agent import Agent

def test_register_agent():
    """Test registering an agent."""
    registry = AgentRegistry()
    agent = Agent(name="Test Agent")

    manifest = AgentManifest(
        agent_id="test-agent",
        name="Test Agent",
        description="Test description",
        capabilities=["test"]
    )

    registry.register("test-agent", agent, manifest)

    assert "test-agent" in registry.list_agents()
    assert registry.get("test-agent") == agent
```

### Integration Tests

```python
# tests/copilot/integration/test_e2e.py

import pytest
import httpx
from testcontainers import DockerContainer

@pytest.mark.integration
def test_copilot_to_agno_flow():
    """Test end-to-end flow from Copilot to Agno."""
    # Start Agno Agent Server
    # Send request to /agents/{agent_id}/invoke
    # Verify response
    pass
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| API Response Time (p95) | <1s |
| Agent Invocation Success Rate | >99% |
| Token Validation Success Rate | 100% |
| Integration Test Pass Rate | 100% |

---

## Next Steps

1. **Review design** with Agno team and CENF stakeholders
2. **Set up development environment** (Microsoft 365 tenant, Entra ID app registration)
3. **Create feature branch** in Agno repository
4. **Begin Phase 1 implementation** - Agno Agent Server

---

**Document Version**: 1.0.0
**Last Updated**: 2025-03-05
**Status**: Ready for Review

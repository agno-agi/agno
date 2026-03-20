# Microsoft Graph Connector for Agno Framework - Design Document

## Executive Summary

This document describes the design and implementation plan for a professional Microsoft Graph connector for the Agno framework, enabling integration with Microsoft 365 Copilot and Agents Studio.

**Status:** Design Phase
**Version:** 1.0.0
**Date:** 2025-03-05

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Authentication Patterns](#2-authentication-patterns)
3. [Connector Structure](#3-connector-structure)
4. [Implementation Plan](#4-implementation-plan)
5. [Security Considerations](#5-security-considerations)
6. [M365 Copilot Integration](#6-m365-copilot-integration)
7. [Testing Strategy](#7-testing-strategy)
8. [Documentation Requirements](#8-documentation-requirements)

---

## 1. Architecture Overview

### 1.1 Design Philosophy

The Microsoft Graph connector for Agno follows these principles:

1. **Toolkit-Based Architecture**: Inherits from Agno's `Toolkit` base class
2. **Dual Authentication Support**: Supports both delegated (user) and application-only flows
3. **Modular Design**: Separate modules for different Graph services (Mail, Calendar, Teams, Drive)
4. **Async-First**: Both sync and async variants for all public methods
5. **Security-First**: Implements Microsoft's security best practices (OBO flow, permission trimming)
6. **Type Safety**: Full type hints and validation using Pydantic

### 1.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Agno Agent/Team                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              MicrosoftGraphToolkit (Toolkit)                 │
├─────────────────────────────────────────────────────────────┤
│  - Authentication Manager (OAuth2, OBO, Client Credentials)  │
│  - Rate Limiter                                              │
│  - Retry Policy (Exponential Backoff)                        │
│  - Cache Manager                                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌──────────────┐
│  GraphMailTools │ │GraphCalendar│ │GraphTeamsTools│
├─────────────────┤ ├─────────────┤ ├──────────────┤
│- send_email     │ │- get_events │ │- send_message │
│- get_emails     │ │- create_event│ │- get_chats   │
│- reply_email    │ │- update_event│ │- list_channels│
└─────────────────┘ └─────────────┘ └──────────────┘
            │               │               │
            └───────────────┼───────────────┘
                            ▼
                ┌───────────────────────┐
                │   Microsoft Graph API │
                │  (graph.microsoft.com)│
                └───────────────────────┘
```

### 1.3 Integration with Agno Patterns

Following the analysis of existing Agno toolkits (Slack, Google Drive):

```python
from agno.tools import Toolkit

class MicrosoftGraphToolkit(Toolkit):
    """
    Microsoft Graph API integration for Agno agents.

    Supports both delegated (user) and application-only authentication
    for Microsoft 365 services: Mail, Calendar, Teams, OneDrive, SharePoint.

    Environment Variables:
        MICROSOFT_GRAPH_CLIENT_ID: Entra ID application (client) ID
        MICROSOFT_GRAPH_CLIENT_SECRET: Client secret (for app-only flow)
        MICROSOFT_GRAPH_TENANT_ID: Azure AD tenant ID
        MICROSOFT_GRAPH_REDIRECT_URI: OAuth redirect URI (for delegated flow)
    """

    _requires_connect: bool = True

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auth_mode: Literal["delegated", "app_only"] = "delegated",
        scopes: Optional[List[str]] = None,
        enable_mail: bool = True,
        enable_calendar: bool = True,
        enable_teams: bool = True,
        enable_drive: bool = True,
        cache_ttl: int = 300,
        **kwargs
    ):
        # Implementation follows Agno's Toolkit pattern
        ...
```

---

## 2. Authentication Patterns

### 2.1 Supported Authentication Flows

Based on the technical manual, the connector will support:

#### 2.1.1 OAuth 2.0 Authorization Code Flow (Delegated)

For scenarios where the agent acts on behalf of a user:

```python
class DelegatedAuthentication:
    """
    OAuth 2.0 Authorization Code flow for delegated access.

    Flow:
    1. Redirect user to /authorize endpoint
    2. User authenticates and consents
    3. Receive authorization code
    4. Exchange code for access token
    5. Use refresh token for renewal
    """

    SCOPES = [
        "User.Read",
        "Mail.ReadWrite",
        "Calendars.ReadWrite",
        "ChannelMessage.Send.All",
        "Files.ReadWrite.All"
    ]
```

#### 2.1.2 OAuth 2.0 Client Credentials Flow (App-Only)

For daemon services and background tasks:

```python
class ClientCredentialsAuthentication:
    """
    OAuth 2.0 Client Credentials flow for application-only access.

    Requires admin consent and application permissions.
    """

    SCOPES = [
        "https://graph.microsoft.com/.default"
    ]
```

#### 2.1.3 OAuth 2.0 On-Behalf-Of (OBO) Flow

For multi-tier architectures where the agent calls backend APIs:

```python
class OnBehalfOfAuthentication:
    """
    OAuth 2.0 On-Behalf-Of flow for service-to-service delegation.

    Allows the agent to exchange a delegated token for a new token
    to call downstream APIs while preserving user identity.
    """
```

### 2.2 Authentication Manager Architecture

```python
class GraphAuthenticationManager:
    """
    Centralized authentication management for Microsoft Graph.

    Features:
    - Automatic token refresh
    - Token caching with TTL
    - Multi-tenant support
    - Certificate-based authentication option
    - Secure credential storage
    """

    def __init__(self, config: GraphConfig):
        self.credential = self._build_credential(config)
        self.client = GraphServiceClient(
            credentials=self.credential,
            scopes=config.scopes
        )

    def _build_credential(self, config: GraphConfig):
        """Build appropriate Azure Identity credential based on config."""
        if config.auth_mode == "delegated":
            if config.use_device_code:
                return DeviceCodeCredential(
                    client_id=config.client_id,
                    tenant_id=config.tenant_id
                )
            else:
                return AuthorizationCodeCredential(
                    client_id=config.client_id,
                    tenant_id=config.tenant_id,
                    redirect_uri=config.redirect_uri
                )
        else:  # app_only
            if config.certificate_path:
                return ClientCertificateCredential(
                    tenant_id=config.tenant_id,
                    client_id=config.client_id,
                    certificate_path=config.certificate_path
                )
            else:
                return ClientSecretCredential(
                    tenant_id=config.tenant_id,
                    client_id=config.client_id,
                    client_secret=config.client_secret
                )
```

### 2.3 Environment Variables Configuration

```bash
# Required for all flows
export MICROSOFT_GRAPH_CLIENT_ID="your-client-id"
export MICROSOFT_GRAPH_TENANT_ID="your-tenant-id"

# For app-only flow
export MICROSOFT_GRAPH_CLIENT_SECRET="your-client-secret"

# For delegated flow
export MICROSOFT_GRAPH_REDIRECT_URI="http://localhost:5000/callback"

# Optional: Certificate-based auth (more secure than client secret)
export MICROSOFT_GRAPH_CERTIFICATE_PATH="/path/to/certificate.pem"

# Optional: Cache configuration
export MICROSOFT_GRAPH_CACHE_TTL="300"
export MICROSOFT_GRAPH_CACHE_DIR="/tmp/graph_cache"
```

---

## 3. Connector Structure

### 3.1 File Structure

```
libs/agno/agno/tools/
├── microsoft_graph/
│   ├── __init__.py                 # Package initialization
│   ├── toolkit.py                  # Main MicrosoftGraphToolkit class
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── manager.py              # GraphAuthenticationManager
│   │   ├── flows.py                # OAuth flow implementations
│   │   └── credentials.py          # Credential builders
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── mail.py                 # GraphMailTools
│   │   ├── calendar.py             # GraphCalendarTools
│   │   ├── teams.py                # GraphTeamsTools
│   │   ├── drive.py                # GraphDriveTools
│   │   └── users.py                # GraphUserTools
│   ├── models/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic config models
│   │   ├── events.py               # Event models
│   │   └── responses.py            # Response wrappers
│   └── utils/
│       ├── __init__.py
│       ├── rate_limiter.py         # Rate limiting
│       ├── retry.py                # Retry logic
│       └── cache.py                # Caching utilities
└── microsoft_graph.py              # Backward compatibility import
```

### 3.2 Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `toolkit.py` | Main `MicrosoftGraphToolkit` class that aggregates all sub-tools |
| `auth/manager.py` | Centralized authentication and token management |
| `auth/flows.py` | OAuth 2.0 flow implementations (AuthCode, ClientCredentials, OBO) |
| `tools/mail.py` | Email operations (send, read, reply, attachments) |
| `tools/calendar.py` | Calendar operations (events, meetings, scheduling) |
| `tools/teams.py` | Teams operations (messages, channels, chats) |
| `tools/drive.py` | OneDrive/SharePoint file operations |
| `utils/rate_limiter.py` | Microsoft Graph rate limit handling (throttling) |
| `utils/retry.py` | Exponential backoff retry logic for transient errors |

### 3.3 Class Hierarchy

```
Toolkit (agno.tools.Toolkit)
    └── MicrosoftGraphToolkit
            ├── GraphAuthenticationManager
            ├── GraphMailTools
            ├── GraphCalendarTools
            ├── GraphTeamsTools
            └── GraphDriveTools
```

---

## 4. Implementation Plan

### Phase 1: Foundation (Week 1-2)

**Deliverables:**
- [ ] Project structure setup
- [ ] Authentication manager implementation
- [ ] Base toolkit class
- [ ] Configuration models (Pydantic)
- [ ] Unit tests for authentication

**Tasks:**
1. Create directory structure under `libs/agno/agno/tools/microsoft_graph/`
2. Implement `GraphAuthenticationManager` with OAuth 2.0 flows
3. Create `GraphConfig` Pydantic model for configuration validation
4. Implement token caching mechanism
5. Add error handling for common authentication errors

**Acceptance Criteria:**
- Can authenticate using both delegated and app-only flows
- Token refresh works automatically
- Configuration validation prevents invalid setups
- Unit tests pass with 80%+ coverage

### Phase 2: Core Tools (Week 3-4)

**Deliverables:**
- [ ] GraphMailTools implementation
- [ ] GraphCalendarTools implementation
- [ ] Basic error handling and retry logic
- [ ] Integration tests for mail and calendar

**Tasks:**
1. Implement mail tools (send, read, list, reply)
2. Implement calendar tools (list events, create event, update event)
3. Add rate limiting for Graph API calls
4. Implement exponential backoff retry logic
5. Create integration tests with mock Graph responses

**Acceptance Criteria:**
- Can send and read emails via Microsoft Graph
- Can create and retrieve calendar events
- Rate limits are respected
- Transient errors are retried appropriately

### Phase 3: Advanced Tools (Week 5-6)

**Deliverables:**
- [ ] GraphTeamsTools implementation
- [ ] GraphDriveTools implementation
- [ ] File upload/download handling
- [ ] Integration tests for Teams and Drive

**Tasks:**
1. Implement Teams tools (send message, list channels, get chat history)
2. Implement Drive tools (list files, upload, download, search)
3. Add file size validation (max 1GB for uploads)
4. Handle large file uploads with chunking
5. Create integration tests for Teams and Drive

**Acceptance Criteria:**
- Can send messages to Teams channels
- Can upload and download files from OneDrive/SharePoint
- Large files are handled correctly
- All tools follow Agno's patterns

### Phase 4: M365 Copilot Integration (Week 7-8)

**Deliverables:**
- [ ] TypeSpec definitions for declarative agent
- [ ] OpenAPI specification generation
- [ ] Plugin manifest for M365 Copilot
- [ ] Example declarative agent configuration
- [ ] Documentation for Copilot integration

**Tasks:**
1. Create TypeSpec definitions for agent capabilities
2. Generate OpenAPI specification from TypeSpec
3. Create plugin manifest for M365 Copilot
4. Write example agent configuration
5. Document integration process with M365 Copilot

**Acceptance Criteria:**
- TypeSpec definitions are valid and complete
- OpenAPI spec passes validation
- Plugin manifest follows Microsoft's schema
- Example agent works in M365 Copilot

### Phase 5: Testing and Documentation (Week 9-10)

**Deliverables:**
- [ ] Comprehensive unit tests (>80% coverage)
- [ ] Integration tests with mock Graph API
- [ ] Cookbook examples
- [ ] API documentation
- [ ] User guide
- [ ] Contributing guidelines

**Tasks:**
1. Write unit tests for all modules
2. Create integration tests with mocked Graph API
3. Write cookbook examples (basic, mail, calendar, teams)
4. Generate API documentation from docstrings
5. Write user guide with examples
6. Create contributing guidelines

**Acceptance Criteria:**
- Unit test coverage >80%
- All integration tests pass
- Cookbook examples run successfully
- Documentation is complete and clear

---

## 5. Security Considerations

### 5.1 Security Best Practices

Following Microsoft's security guidelines:

1. **Principle of Least Privilege**
   - Use delegated permissions when possible
   - Request minimum required scopes
   - Implement permission trimming for connectors

2. **Credential Management**
   - Never store credentials in code
   - Use environment variables or Azure Key Vault
   - Support certificate-based authentication (more secure than client secrets)
   - Implement secure token storage

3. **Data Protection**
   - Validate all inputs
   - Sanitize error messages (no sensitive data in errors)
   - Implement audit logging
   - Respect Microsoft 365 compliance boundaries

4. **Rate Limiting and Throttling**
   - Respect Microsoft Graph rate limits
   - Implement exponential backoff
   - Handle 429 (Too Many Requests) responses
   - Use retry-after header when provided

### 5.2 Security Configuration

```python
class GraphSecurityConfig(BaseModel):
    """Security configuration for Microsoft Graph connector."""

    # Authentication
    auth_mode: Literal["delegated", "app_only"] = "delegated"
    use_certificate: bool = False  # More secure than client secret
    certificate_path: Optional[str] = None

    # Token management
    token_cache_enabled: bool = True
    token_cache_ttl: int = 300  # 5 minutes

    # Rate limiting
    respect_rate_limits: bool = True
    max_retries: int = 3
    retry_backoff_multiplier: float = 2.0

    # Data protection
    sanitize_errors: bool = True
    audit_logging: bool = True
    log_sensitive_data: bool = False

    # Compliance
    enforce_permission_trimmming: bool = True
    allowed_scopes: Optional[List[str]] = None
```

### 5.3 Error Handling

```python
class GraphErrorHandler:
    """Centralized error handling for Microsoft Graph API errors."""

    ERROR_MAPPING = {
        "InvalidAuthenticationToken": "token_expired",
        "Unauthorized": "unauthorized",
        "Forbidden": "forbidden",
        "ResourceNotFound": "not_found",
        "TooManyRequests": "rate_limited",
    }

    def handle_error(self, error: GraphError) -> str:
        """Handle Graph API errors appropriately."""
        error_code = error.error_code

        if error_code == "InvalidAuthenticationToken":
            # Token expired, trigger refresh
            return self._handle_token_expired(error)

        elif error_code == "TooManyRequests":
            # Rate limited, use retry-after
            return self._handle_rate_limit(error)

        elif error_code in ["Unauthorized", "Forbidden"]:
            # Permission issue
            return self._handle_permission_error(error)

        else:
            # Generic error
            return self._handle_generic_error(error)
```

---

## 6. M365 Copilot Integration

### 6.1 Declarative Agent Approach

Based on the technical manual, we'll support the declarative agent pattern:

#### 6.1.1 TypeSpec Definition

```typescript
// microsoft_graph_agent.tsp

import "@typespec/openapi";
import "@typespec/rest";

using OpenAPI;
using TypeSpec.Rest;

namespace MicrosoftGraphAgent;

@doc("Microsoft 365 Agent with Graph integration")
@service({
  title: "Microsoft Graph Agent",
  version: "1.0.0",
})
interface Agent {
  @route("/mail")
  namespace Mail {
    @doc("Send an email")
    @post
    op sendEmail(@body request: SendEmailRequest): SendEmailResponse;

    @doc("List emails")
    @get
    op listEmails(@query folder: string, @query limit: integer): ListEmailsResponse;
  }

  @route("/calendar")
  namespace Calendar {
    @doc("Get calendar events")
    @get
    op getEvents(@query start: string, @query end: string): GetEventsResponse;

    @doc("Create a calendar event")
    @post
    op createEvent(@body request: CreateEventRequest): CreateEventResponse;
  }

  @route("/teams")
  namespace Teams {
    @doc("Send a message to a Teams channel")
    @post
    op sendMessage(@body request: SendMessageRequest): SendMessageResponse;
  }
}

model SendEmailRequest {
  @doc("Recipient email address")
  to: string;

  @doc("Email subject")
  subject: string;

  @doc("Email body")
  body: string;

  @doc("Optional attachments")
  attachments?: Attachment[];
}

// ... additional models
```

#### 6.1.2 Plugin Manifest

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/copilot/plugin/v1.1/schema.json",
  "schema_version": "1.1",
  "name": "MicrosoftGraphAgent",
  "description": "Agent for interacting with Microsoft 365 services",
  "namespace": "Microsoft.Graph.Agent",
  "functions": [
    {
      "name": "send_email",
      "description": "Send an email to a recipient",
      "parameters": {
        "type": "object",
        "properties": {
          "to": {"type": "string", "description": "Recipient email"},
          "subject": {"type": "string", "description": "Email subject"},
          "body": {"type": "string", "description": "Email body"}
        },
        "required": ["to", "subject", "body"]
      }
    },
    {
      "name": "get_calendar_events",
      "description": "Get calendar events for a date range",
      "parameters": {
        "type": "object",
        "properties": {
          "start_date": {"type": "string", "description": "Start date (ISO 8601)"},
          "end_date": {"type": "string", "description": "End date (ISO 8601)"}
        },
        "required": ["start_date", "end_date"]
      }
    },
    {
      "name": "send_teams_message",
      "description": "Send a message to a Teams channel",
      "parameters": {
        "type": "object",
        "properties": {
          "team_id": {"type": "string", "description": "Team ID"},
          "channel_id": {"type": "string", "description": "Channel ID"},
          "message": {"type": "string", "description": "Message to send"}
        },
        "required": ["team_id", "channel_id", "message"]
      }
    }
  ]
}
```

### 6.2 Custom Engine Agent Approach

For scenarios requiring custom orchestration:

```python
from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit

# Create the Graph toolkit
graph_tools = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated",
    enable_mail=True,
    enable_calendar=True,
    enable_teams=True
)

# Create agent with Graph integration
agent = Agent(
    name="Microsoft 365 Assistant",
    model="gpt-4",
    tools=[graph_tools],
    instructions="""
    You are a Microsoft 365 assistant that helps users manage their email,
    calendar, and Teams communications.

    Guidelines:
    - Always confirm before sending emails or scheduling meetings
    - Provide clear summaries of calendar events
    - Respect user's privacy and permissions
    - Ask for clarification when needed
    """
)

# Run the agent
response = agent.run("What meetings do I have today?")
```

---

## 7. Testing Strategy

### 7.1 Unit Testing

```python
# tests/unit/tools/test_graph_mail.py

import pytest
from unittest.mock import Mock, patch
from agno.tools.microsoft_graph.tools.mail import GraphMailTools

class TestGraphMailTools:
    """Unit tests for GraphMailTools."""

    @pytest.fixture
    def mock_client(self):
        """Mock GraphServiceClient."""
        with patch('agno.tools.microsoft_graph.auth.manager.GraphServiceClient') as mock:
            yield mock

    def test_send_email_success(self, mock_client):
        """Test successful email sending."""
        # Arrange
        tools = GraphMailTools(client_id="test", tenant_id="test")
        tools.client = mock_client

        # Act
        result = tools.send_email(
            to="user@example.com",
            subject="Test Subject",
            body="Test Body"
        )

        # Assert
        assert result["success"] is True
        mock_client.send_mail.assert_called_once()

    def test_send_email_invalid_recipient(self, mock_client):
        """Test email sending with invalid recipient."""
        tools = GraphMailTools(client_id="test", tenant_id="test")
        tools.client = mock_client

        with pytest.raises(ValidationException):
            tools.send_email(
                to="invalid-email",
                subject="Test",
                body="Test"
            )
```

### 7.2 Integration Testing

```python
# tests/integration/test_graph_integration.py

import pytest
from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from tests.mocks.graph_mock_server import GraphMockServer

class TestGraphIntegration:
    """Integration tests with mock Graph server."""

    @pytest.fixture
    def mock_graph_server(self):
        """Start mock Graph server."""
        server = GraphMockServer()
        server.start()
        yield server
        server.stop()

    def test_agent_with_graph_integration(self, mock_graph_server):
        """Test agent using Graph tools."""
        # Arrange
        toolkit = MicrosoftGraphToolkit(
            client_id="test-id",
            tenant_id="test-tenant",
            api_base_url=mock_graph_server.url
        )
        agent = Agent(
            name="Test Agent",
            tools=[toolkit]
        )

        # Act
        response = agent.run("Send an email to user@example.com")

        # Assert
        assert "email" in response.content.lower()
        mock_graph_server.assert_request_count(1)
```

### 7.3 Test Coverage Requirements

- **Unit Tests**: >80% code coverage
- **Integration Tests**: Cover all major workflows
- **E2E Tests**: Test with real Graph API (test tenant)
- **Security Tests**: Verify authentication and authorization

---

## 8. Documentation Requirements

### 8.1 Documentation Structure

```
docs/
├── api/                           # API documentation
│   ├── authentication.md
│   ├── mail_tools.md
│   ├── calendar_tools.md
│   ├── teams_tools.md
│   └── drive_tools.md
├── guides/                        # User guides
│   ├── getting_started.md
│   ├── authentication_guide.md
│   ├── m365_copilot_integration.md
│   └── best_practices.md
├── examples/                      # Code examples
│   ├── basic_agent.py
│   ├── email_agent.py
│   ├── calendar_agent.py
│   └── teams_integration.py
└── contributing/
    ├── contributing.md
    ├── code_standards.md
    └── testing_guide.md
```

### 8.2 Required Documentation

1. **Getting Started Guide**
   - Installation instructions
   - Configuration (Entra ID app registration)
   - Quick start example
   - Environment variables

2. **Authentication Guide**
   - OAuth 2.0 flows explained
   - Delegated vs app-only
   - Certificate-based authentication
   - Token management

3. **M365 Copilot Integration**
   - Declarative agent setup
   - TypeSpec definitions
   - Plugin manifest
   - Deployment instructions

4. **API Reference**
   - All tool methods documented
   - Parameters and return types
   - Error codes and handling
   - Rate limiting information

5. **Best Practices**
   - Security recommendations
   - Performance optimization
   - Error handling patterns
   - Troubleshooting guide

---

## 9. Compliance and Governance

### 9.1 Microsoft 365 Compliance

The connector will respect:

- **Permission Trimming**: Users only see data they have access to
- **Sensitivity Labels**: Respect Microsoft Information Protection labels
- **Retention Policies**: Honor retention and deletion policies
- **Audit Logging**: Log all Graph API calls for compliance
- **Data Residency**: Respect data residency requirements

### 9.2 Agent 365 Governance

Integration with Agent 365 for:

- Centralized policy management
- Approval workflows for sensitive operations
- Audit trail of agent actions
- Real-time monitoring and alerting

---

## 10. Success Metrics

### 10.1 Technical Metrics

| Metric | Target |
|--------|--------|
| Unit Test Coverage | >80% |
| Integration Test Pass Rate | 100% |
| API Response Time (p95) | <500ms |
| Error Rate | <1% |
| Token Refresh Success Rate | >99% |

### 10.2 Adoption Metrics

| Metric | Target |
|--------|--------|
| GitHub Stars | 100+ in 3 months |
| Active Users | 50+ in 3 months |
| Issues Resolved | <48 hour response time |
| Documentation Completeness | 100% |

---

## 11. Timeline

| Phase | Duration | Start Date | End Date |
|-------|----------|------------|----------|
| Phase 1: Foundation | 2 weeks | 2025-03-10 | 2025-03-23 |
| Phase 2: Core Tools | 2 weeks | 2025-03-24 | 2025-04-06 |
| Phase 3: Advanced Tools | 2 weeks | 2025-04-07 | 2025-04-20 |
| Phase 4: M365 Integration | 2 weeks | 2025-04-21 | 2025-05-04 |
| Phase 5: Testing & Docs | 2 weeks | 2025-05-05 | 2025-05-18 |

**Total Duration**: 10 weeks

---

## 12. Next Steps

1. **Review this design document** with the Agno team
2. **Set up development environment** (dev tools, test tenant)
3. **Create Entra ID app registration** for testing
4. **Initialize project structure** in Agno repository
5. **Begin Phase 1 implementation**

---

## Appendix A: References

- [Microsoft Graph Documentation](https://docs.microsoft.com/graph/)
- [Microsoft 365 Copilot Extensibility](https://docs.microsoft.com/copilot/extensibility/)
- [Agents SDK Documentation](https://docs.microsoft.com/agents-sdk/)
- [Agno Framework](https://github.com/agno-agi/agno)
- [TypeSpec for Microsoft 365](https://docs.microsoft.com/typespec/)

## Appendix B: Entra ID App Registration Checklist

- [ ] Register app in Entra ID
- [ ] Configure redirect URIs
- [ ] Add API permissions (Microsoft Graph)
- [ ] Grant admin consent
- [ ] Generate client secret or upload certificate
- [ ] Configure token lifetime
- [ ] Set up API access policies

## Appendix C: Environment Variables Template

```bash
# Microsoft Graph Configuration
export MICROSOFT_GRAPH_CLIENT_ID=""
export MICROSOFT_GRAPH_TENANT_ID=""
export MICROSOFT_GRAPH_CLIENT_SECRET=""
export MICROSOFT_GRAPH_REDIRECT_URI="http://localhost:5000/callback"

# Optional: Certificate-based auth
export MICROSOFT_GRAPH_CERTIFICATE_PATH=""

# Optional: Cache configuration
export MICROSOFT_GRAPH_CACHE_TTL="300"
export MICROSOFT_GRAPH_CACHE_DIR="/tmp/graph_cache"

# Optional: Feature flags
export MICROSOFT_GRAPH_ENABLE_MAIL="true"
export MICROSOFT_GRAPH_ENABLE_CALENDAR="true"
export MICROSOFT_GRAPH_ENABLE_TEAMS="true"
export MICROSOFT_GRAPH_ENABLE_DRIVE="true"
```

---

**Document Version**: 1.0.0
**Last Updated**: 2025-03-05
**Status**: Ready for Review

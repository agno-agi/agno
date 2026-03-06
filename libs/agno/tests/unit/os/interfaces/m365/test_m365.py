"""
Unit tests for Microsoft 365 Copilot Interface.

Tests the M365Copilot interface, models, authentication, and manifest generation.
"""

import pytest
from unittest.mock import MagicMock, patch

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.interfaces.m365 import M365Copilot
from agno.os.interfaces.m365.models import (
    AgentManifest,
    InvokeRequest,
    InvokeResponse,
    ManifestResponse,
)
from agno.os.interfaces.m365.manifest import generate_openapi_spec
from agno.os.interfaces.m365.auth import (
    extract_user_info,
    validate_m365_token,
)


class TestM365CopilotInterface:
    """Test M365Copilot interface initialization and configuration."""

    def test_interface_creation_with_agent(self):
        """Test creating M365 interface with an agent."""
        agent = Agent(
            agent_id="test-agent",
            name="Test Agent",
            model=OpenAIChat(id="gpt-4o"),
            instructions="Test instructions"
        )

        with patch.dict("os.environ", {
            "M365_TENANT_ID": "test-tenant",
            "M365_CLIENT_ID": "test-client"
        }):
            interface = M365Copilot(agent=agent)

            assert interface.type == "m365"
            assert interface.version == "1.0"
            assert interface.agent == agent
            assert interface.tenant_id == "test-tenant"
            assert interface.client_id == "test-client"

    def test_interface_fails_without_component(self):
        """Test that interface fails without agent, team, or workflow."""
        with patch.dict("os.environ", {
            "M365_TENANT_ID": "test-tenant",
            "M365_CLIENT_ID": "test-client"
        }):
            with pytest.raises(ValueError, match="requires at least one"):
                M365Copilot()

    def test_interface_fails_without_tenant_id(self):
        """Test that interface fails without tenant_id."""
        agent = Agent(agent_id="test", name="Test", model=OpenAIChat(id="gpt-4o"))

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="tenant_id is required"):
                M365Copilot(agent=agent)

    def test_interface_fails_without_client_id(self):
        """Test that interface fails without client_id."""
        agent = Agent(agent_id="test", name="Test", model=OpenAIChat(id="gpt-4o"))

        with patch.dict("os.environ", {
            "M365_TENANT_ID": "test-tenant"
        }, clear=True):
            with pytest.raises(ValueError, match="client_id is required"):
                M365Copilot(agent=agent)

    def test_get_router_returns_api_router(self):
        """Test that get_router returns an APIRouter."""
        agent = Agent(
            agent_id="test-agent",
            name="Test Agent",
            model=OpenAIChat(id="gpt-4o")
        )

        with patch.dict("os.environ", {
            "M365_TENANT_ID": "test-tenant",
            "M365_CLIENT_ID": "test-client"
        }):
            interface = M365Copilot(agent=agent)
            router = interface.get_router()

            assert router is not None
            assert hasattr(router, "routes")
            assert router.prefix == "/m365"


class TestModels:
    """Test Pydantic models for request/response validation."""

    def test_agent_manifest_model(self):
        """Test AgentManifest model."""
        manifest = AgentManifest(
            agent_id="test-agent",
            name="Test Agent",
            description="Test description",
            type="agent",
            capabilities=["test", "analysis"]
        )

        assert manifest.agent_id == "test-agent"
        assert manifest.capabilities == ["test", "analysis"]

    def test_invoke_request_model(self):
        """Test InvokeRequest model."""
        request = InvokeRequest(
            component_id="test-agent",
            message="Test message"
        )

        assert request.component_id == "test-agent"
        assert request.message == "Test message"
        assert request.session_id is None

    def test_invoke_request_with_optional_fields(self):
        """Test InvokeRequest with optional fields."""
        request = InvokeRequest(
            component_id="test-agent",
            message="Test message",
            session_id="session-123",
            context={"key": "value"}
        )

        assert request.session_id == "session-123"
        assert request.context == {"key": "value"}

    def test_invoke_response_model_success(self):
        """Test InvokeResponse with success status."""
        response = InvokeResponse(
            component_id="test-agent",
            component_type="agent",
            output="Test output",
            status="success"
        )

        assert response.status == "success"
        assert response.error is None

    def test_invoke_response_model_error(self):
        """Test InvokeResponse with error status."""
        response = InvokeResponse(
            component_id="test-agent",
            component_type="agent",
            output="",
            status="error",
            error="Something went wrong"
        )

        assert response.status == "error"
        assert response.error == "Something went wrong"

    def test_manifest_response_model(self):
        """Test ManifestResponse model."""
        spec = {"openapi": "3.0.0", "info": {"title": "Test"}}
        response = ManifestResponse(
            openapi=spec,
            plugin_type="openapi",
            version="1.0.0"
        )

        assert response.openapi == spec
        assert response.plugin_type == "openapi"


class TestManifestGeneration:
    """Test OpenAPI manifest generation."""

    def test_generate_openapi_spec_with_agent(self):
        """Test generating OpenAPI spec with an agent."""
        agent = Agent(
            agent_id="financial-analyst",
            name="Financial Analyst",
            model=OpenAIChat(id="gpt-4o"),
            instructions="Financial analysis expert"
        )

        spec = generate_openapi_spec(
            title="Test Agents",
            description="Test description",
            version="1.0.0",
            agent=agent,
            team=None,
            workflow=None,
            agent_descriptions={}
        )

        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Test Agents"
        assert "/m365/invoke/financial-analyst" in spec["paths"]

    def test_generate_openapi_spec_includes_security(self):
        """Test that OpenAPI spec includes security scheme."""
        agent = Agent(
            agent_id="test-agent",
            name="Test",
            model=OpenAIChat(id="gpt-4o")
        )

        spec = generate_openapi_spec(
            title="Test",
            description="Test",
            version="1.0.0",
            agent=agent,
            team=None,
            workflow=None,
            agent_descriptions={}
        )

        assert "security" in spec
        assert "bearerAuth" in spec["components"]["securitySchemes"]

    def test_generate_openapi_spec_with_custom_description(self):
        """Test that custom descriptions override agent instructions."""
        agent = Agent(
            agent_id="test-agent",
            name="Test",
            model=OpenAIChat(id="gpt-4o"),
            instructions="Original instructions"
        )

        spec = generate_openapi_spec(
            title="Test",
            description="Test",
            version="1.0.0",
            agent=agent,
            team=None,
            workflow=None,
            agent_descriptions={
                "test-agent": "Custom description"
            }
        )

        path_spec = spec["paths"]["/m365/invoke/test-agent"]
        assert "Custom description" in path_spec["post"]["description"]


class TestAuthentication:
    """Test authentication utilities."""

    @pytest.mark.asyncio
    async def test_extract_user_info(self):
        """Test extracting user info from token claims."""
        claims = {
            "oid": "user-123",
            "upn": "user@example.com",
            "tid": "tenant-456",
            "name": "John Doe"
        }

        user_info = extract_user_info(claims)

        assert user_info["user_id"] == "user-123"
        assert user_info["email"] == "user@example.com"
        assert user_info["tenant_id"] == "tenant-456"
        assert user_info["name"] == "John Doe"

    @pytest.mark.asyncio
    async def test_extract_user_info_with_missing_fields(self):
        """Test extracting user info with missing optional fields."""
        claims = {
            "oid": "user-123",
            "upn": "user@example.com",
            "tid": "tenant-456"
        }

        user_info = extract_user_info(claims)

        assert user_info["user_id"] == "user-123"
        assert user_info["name"] == ""  # Missing field returns empty string

    @pytest.mark.asyncio
    @patch("agno.os.interfaces.m365.auth.jwt.decode")
    async def test_validate_m365_token_success(self, mock_decode):
        """Test successful token validation."""
        # Mock successful JWT decode
        mock_decode.return_value = {
            "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
            "tid": "test-tenant",
            "aud": "test-client",
            "upn": "user@example.com",
            "oid": "user-123",
            "exp": 9999999999  # Far future
        }

        token = "valid.jwt.token"
        claims = await validate_m365_token(
            token=token,
            expected_tenant_id="test-tenant",
            expected_client_id="test-client"
        )

        assert claims["upn"] == "user@example.com"
        assert claims["tid"] == "test-tenant"

    @pytest.mark.asyncio
    @patch("agno.os.interfaces.m365.auth.jwt.decode")
    async def test_validate_m365_token_wrong_tenant(self, mock_decode):
        """Test token validation fails with wrong tenant."""
        mock_decode.return_value = {
            "iss": "https://login.microsoftonline.com/wrong-tenant/v2.0",
            "tid": "wrong-tenant",
            "aud": "test-client"
        }

        token = "invalid.tenant.token"

        with pytest.raises(ValueError, match="Invalid tenant"):
            await validate_m365_token(
                token=token,
                expected_tenant_id="test-tenant",
                expected_client_id="test-client"
            )

    @pytest.mark.asyncio
    @patch("agno.os.interfaces.m365.auth.jwt.decode")
    async def test_validate_m365_token_wrong_audience(self, mock_decode):
        """Test token validation fails with wrong audience."""
        mock_decode.side_effect = Exception("Invalid audience")

        token = "invalid.audience.token"

        with pytest.raises(ValueError):
            await validate_m365_token(
                token=token,
                expected_tenant_id="test-tenant",
                expected_client_id="test-client"
            )

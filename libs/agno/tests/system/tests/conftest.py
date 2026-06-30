"""
Pytest configuration and shared fixtures for system tests.
"""

import os
from typing import Dict

import pytest

from .test_utils import generate_jwt_token


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def gateway_url() -> str:
    """Get the gateway URL from environment or use default."""
    return os.getenv("GATEWAY_URL", "http://localhost:7001")


@pytest.fixture(scope="session")
def remote_url() -> str:
    """Get the remote server URL from environment or use default."""
    return os.getenv("REMOTE_SERVER_URL", "http://localhost:7002")


@pytest.fixture(scope="session")
def adk_url() -> str:
    """Get the Google ADK server URL from environment or use default."""
    return os.getenv("ADK_SERVER_URL", "http://localhost:7003")


@pytest.fixture(scope="session")
def agno_a2a_url() -> str:
    """Get the Agno A2A server URL from environment or use default."""
    return os.getenv("AGNO_A2A_SERVER_URL", "http://localhost:7004")


@pytest.fixture(scope="session")
def jwt_token() -> str:
    """Generate a JWT token for the gateway server."""
    return generate_jwt_token(audience="gateway-os")


@pytest.fixture(scope="session")
def remote_jwt_token() -> str:
    """Generate a JWT token for the remote server."""
    return generate_jwt_token(audience="remote-os")


@pytest.fixture(scope="session")
def auth_headers(jwt_token: str) -> Dict[str, str]:
    """Get authorization headers for the gateway server."""
    return {"Authorization": f"Bearer {jwt_token}"}

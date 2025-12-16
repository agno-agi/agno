"""
Pytest configuration and shared fixtures for system tests.
"""

import os

import pytest


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


@pytest.fixture(scope="session")
def gateway_url() -> str:
    """Get the gateway URL from environment or use default."""
    return os.getenv("GATEWAY_URL", "http://localhost:7001")


@pytest.fixture(scope="session")
def remote_url() -> str:
    """Get the remote server URL from environment or use default."""
    return os.getenv("REMOTE_SERVER_URL", "http://localhost:7002")

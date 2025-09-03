"""
Pytest configuration and fixtures for integration tests.
"""

import time

import pytest
import requests

from . import get_api_url


@pytest.fixture
def api_client() -> requests.Session:
    """
    Create a requests session for API testing and wait for API to be ready.
    """
    # Wait for API to be ready first
    max_retries = 30
    retry_delay = 2

    for _ in range(max_retries):
        try:
            response = requests.get(get_api_url("/health"))
            if response.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass

        time.sleep(retry_delay)
    else:
        raise Exception("API did not become ready within expected time")

    # Create and return the session
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()

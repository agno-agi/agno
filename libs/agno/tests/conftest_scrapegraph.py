"""Test configuration and utilities for ScrapeGraphTools tests."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment for all ScrapeGraphTools tests."""
    # Ensure test API key is available
    with patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key_for_testing"}):
        yield


@pytest.fixture
def mock_scrapegraph_imports():
    """Mock all ScrapeGraph imports to avoid actual API calls during testing."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client,
        patch("agno.tools.scrapegraph.sgai_logger") as mock_logger,
    ):
        yield {
            "client": mock_client,
            "logger": mock_logger,
        }


@pytest.fixture
def sample_html_content():
    """Sample HTML content for testing."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Test Page</title>
    </head>
    <body>
        <header>
            <h1>Welcome to Test Page</h1>
            <nav>
                <ul>
                    <li><a href="/home">Home</a></li>
                    <li><a href="/about">About</a></li>
                    <li><a href="/contact">Contact</a></li>
                </ul>
            </nav>
        </header>
        <main>
            <section>
                <h2>Main Content</h2>
                <p>This is a test page with various HTML elements.</p>
                <div class="content">
                    <img src="/test-image.jpg" alt="Test Image">
                    <p>More content here...</p>
                </div>
            </section>
        </main>
        <footer>
            <p>&copy; 2024 Test Company. All rights reserved.</p>
        </footer>
        <script>
            console.log('Test script loaded');
        </script>
    </body>
    </html>
    """


@pytest.fixture
def sample_api_response():
    """Sample API response for testing."""
    return {
        "result": "<html><body>Test Content</body></html>",
        "request_id": "req_test_123",
        "status": "success",
        "error": None,
    }


@pytest.fixture
def sample_error_response():
    """Sample error response for testing."""
    return {
        "result": None,
        "request_id": "req_error_123",
        "status": "error",
        "error": "Test error message",
    }


# Test markers for different test categories
pytestmark = [
    pytest.mark.scrapegraph,
    pytest.mark.tools,
]

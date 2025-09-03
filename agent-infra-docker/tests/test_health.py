"""
Health check tests for the agent-os-docker API.
"""

from . import get_api_url


class TestHealthEndpoints:
    """Test health and status endpoints."""

    def test_health_endpoint(self, api_client):
        """Test the health endpoint returns 200."""
        response = api_client.get(get_api_url("/health"))
        assert response.status_code == 200
        assert "status" in response.json()

    def test_docs_endpoint(self, api_client):
        """Test the OpenAPI docs endpoint."""
        response = api_client.get(get_api_url("/docs"))
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_openapi_schema(self, api_client):
        """Test the OpenAPI schema endpoint."""
        response = api_client.get(get_api_url("/openapi.json"))
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert "info" in schema


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_404_endpoint(self, api_client):
        """Test that non-existent endpoints return 404."""
        response = api_client.get(get_api_url("/nonexistent"))
        assert response.status_code == 404

    def test_api_availability(self, api_client):
        """Test that the API is consistently available."""
        for _ in range(3):
            response = api_client.get(get_api_url("/health"))
            assert response.status_code == 200
            import time

            time.sleep(1)

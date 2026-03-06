"""
Manual Test Script for M365 Copilot Interface
==============================================

This script helps manually test the M365 Copilot interface without
requiring actual Microsoft Entra ID tokens.

It tests:
- Health check endpoint (no auth required)
- Manifest endpoint (no auth required)
- OpenAPI specification structure

Prerequisites:
- Run the basic.py example first in a separate terminal
- Install requests: pip install requests

Usage:
    python test_manual.py
"""

import json
import sys
from typing import Any, Dict

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed")
    print("Install with: pip install requests")
    sys.exit(1)


# Configuration
BASE_URL = "http://localhost:7777"
M365_PREFIX = "/m365"


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_response(response: requests.Response, show_body: bool = True):
    """Print HTTP response details."""
    print(f"Status Code: {response.status_code}")
    print(f"Response Time: {response.elapsed.total_seconds():.3f}s")

    if show_body and response.content:
        try:
            body = response.json()
            print(f"Response Body:")
            print(json.dumps(body, indent=2))
        except json.JSONDecodeError:
            print(f"Response Body: {response.text}")


def test_health_check() -> bool:
    """Test the health check endpoint."""
    print_section("Test 1: Health Check (No Auth Required)")

    url = f"{BASE_URL}{M365_PREFIX}/health"

    try:
        response = requests.get(url, timeout=5)
        print_response(response)

        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                print("\n✅ PASSED: Health check returned healthy status")
                return True
            else:
                print(f"\n❌ FAILED: Expected status=healthy, got {data.get('status')}")
                return False
        else:
            print(f"\n❌ FAILED: Expected 200, got {response.status_code}")
            return False

    except requests.RequestException as e:
        print(f"\n❌ ERROR: {e}")
        print("\n💡 Make sure the server is running:")
        print("   python cookbook/05_agent_os/interfaces/m365/basic.py")
        return False


def test_manifest() -> bool:
    """Test the manifest endpoint."""
    print_section("Test 2: Get OpenAPI Manifest (No Auth Required)")

    url = f"{BASE_URL}{M365_PREFIX}/manifest"

    try:
        response = requests.get(url, timeout=5)
        print_response(response, show_body=False)  # Don't print full manifest

        if response.status_code == 200:
            data = response.json()

            # Validate structure
            required_keys = ["openapi", "info", "paths", "components"]
            missing_keys = [k for k in required_keys if k not in data]

            if missing_keys:
                print(f"\n❌ FAILED: Missing required keys: {missing_keys}")
                return False

            # Validate OpenAPI version
            if data.get("openapi") != "3.0.1":
                print(f"\n⚠️  WARNING: Expected OpenAPI 3.0.1, got {data.get('openapi')}")

            # Validate info section
            info = data.get("info", {})
            if not all(k in info for k in ["title", "description", "version"]):
                print(f"\n❌ FAILED: Missing required info keys")
                return False

            # Check security scheme
            components = data.get("components", {})
            if "securitySchemes" not in components:
                print(f"\n❌ FAILED: Missing securitySchemes in components")
                return False

            # Check that invoke path exists
            paths = data.get("paths", {})
            if not any("invoke" in path for path in paths.keys()):
                print(f"\n❌ FAILED: No invoke path found in OpenAPI spec")
                return False

            print(f"\n✅ PASSED: Manifest is valid")
            print(f"   - Title: {info.get('title')}")
            print(f"   - Version: {info.get('version')}")
            print(f"   - OpenAPI: {data.get('openapi')}")
            print(f"   - Paths: {len(paths)} endpoint(s)")
            return True

        else:
            print(f"\n❌ FAILED: Expected 200, got {response.status_code}")
            return False

    except requests.RequestException as e:
        print(f"\n❌ ERROR: {e}")
        return False


def test_manifest_structure() -> bool:
    """Test the detailed structure of the OpenAPI manifest."""
    print_section("Test 3: Validate OpenAPI Structure")

    url = f"{BASE_URL}{M365_PREFIX}/manifest"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print(f"❌ FAILED: Cannot get manifest (status {response.status_code})")
            return False

        data = response.json()

        # Check security scheme
        security_schemes = data.get("components", {}).get("securitySchemes", {})
        if "bearerAuth" not in security_schemes:
            print(f"❌ FAILED: Missing bearerAuth security scheme")
            return False

        bearer_auth = security_schemes["bearerAuth"]
        if bearer_auth.get("type") != "http":
            print(f"❌ FAILED: bearerAuth type should be 'http', got {bearer_auth.get('type')}")
            return False

        if bearer_auth.get("scheme") != "bearer":
            print(f"❌ FAILED: bearerAuth scheme should be 'bearer', got {bearer_auth.get('scheme')}")
            return False

        # Check schemas
        schemas = data.get("components", {}).get("schemas", {})
        required_schemas = ["InvokeRequest", "InvokeResponse"]
        for schema_name in required_schemas:
            if schema_name not in schemas:
                print(f"❌ FAILED: Missing schema: {schema_name}")
                return False

        # Check InvokeRequest schema
        invoke_request = schemas["InvokeRequest"]
        required_properties = ["message", "session_id", "context"]
        for prop in required_properties:
            if prop not in invoke_request.get("properties", {}):
                print(f"❌ FAILED: InvokeRequest missing property: {prop}")
                return False

        # Check that message has example
        message_prop = invoke_request["properties"]["message"]
        if "example" not in message_prop:
            print(f"⚠️  WARNING: message property missing example")

        print(f"\n✅ PASSED: OpenAPI structure is valid")
        print(f"   - Security scheme: bearerAuth (http/bearer)")
        print(f"   - Schemas defined: {len(schemas)}")
        print(f"   - InvokeRequest has example: {'example' in message_prop}")
        return True

    except requests.RequestException as e:
        print(f"❌ ERROR: {e}")
        return False


def test_agent_discovery_without_auth() -> bool:
    """Test that agent discovery returns 401 without authentication."""
    print_section("Test 4: Agent Discovery Without Auth (Should Fail)")

    url = f"{BASE_URL}{M365_PREFIX}/agents"

    try:
        # Don't provide Authorization header
        response = requests.get(url, timeout=5)
        print_response(response, show_body=False)

        if response.status_code == 401:
            print(f"\n✅ PASSED: Correctly requires authentication (401)")
            return True
        elif response.status_code == 403:
            print(f"\n✅ PASSED: Authenticated but discovery disabled (403)")
            return True
        else:
            print(f"\n❌ FAILED: Expected 401 or 403, got {response.status_code}")
            return False

    except requests.RequestException as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  M365 Copilot Interface - Manual Test Suite")
    print("=" * 60)
    print(f"\nTarget: {BASE_URL}")
    print(f"Testing M365 interface endpoints...\n")

    results = []

    # Run tests
    results.append(("Health Check", test_health_check()))
    results.append(("Manifest Endpoint", test_manifest()))
    results.append(("OpenAPI Structure", test_manifest_structure()))
    results.append(("Auth Required", test_agent_discovery_without_auth()))

    # Print summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! The M365 interface is working correctly.")
        print("\nNext steps:")
        print("  1. Set up Microsoft Entra ID app registration")
        print("  2. Configure M365_TENANT_ID and M365_CLIENT_ID")
        print("  3. Test with real JWT tokens")
        print("  4. Register OpenAPI spec in Copilot Studio")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please check the server configuration.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

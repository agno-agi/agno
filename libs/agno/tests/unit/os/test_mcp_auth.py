from types import SimpleNamespace

import pytest

from agno.os.mcp_auth import require_mcp_scope


def _request(scopes, *, authorization_enabled=True, admin_scope=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            authorization_enabled=authorization_enabled,
            scopes=scopes,
            admin_scope=admin_scope,
        )
    )


def test_require_mcp_scope_allows_without_http_request_context():
    require_mcp_scope(["agents:run"], resource_type="agents", resource_id="demo-agent", request=None)


def test_require_mcp_scope_allows_when_authorization_disabled():
    request = _request([], authorization_enabled=False)

    require_mcp_scope(["agents:run"], resource_type="agents", resource_id="demo-agent", request=request)


def test_require_mcp_scope_allows_matching_global_scope():
    request = _request(["sessions:read"])

    require_mcp_scope(["sessions:read"], request=request)


def test_require_mcp_scope_allows_matching_resource_scope():
    request = _request(["agents:demo-agent:run"])

    require_mcp_scope(["agents:run"], resource_type="agents", resource_id="demo-agent", request=request)


def test_require_mcp_scope_rejects_unrelated_scope():
    request = _request(["sessions:read"])

    with pytest.raises(PermissionError, match="agents:run"):
        require_mcp_scope(["agents:run"], resource_type="agents", resource_id="demo-agent", request=request)


def test_require_mcp_scope_rejects_wrong_resource_scope():
    request = _request(["agents:other-agent:run"])

    with pytest.raises(PermissionError, match="agents:run"):
        require_mcp_scope(["agents:run"], resource_type="agents", resource_id="demo-agent", request=request)


def test_require_mcp_scope_accepts_custom_admin_scope():
    request = _request(["root"], admin_scope="root")

    require_mcp_scope(["memories:delete"], request=request)

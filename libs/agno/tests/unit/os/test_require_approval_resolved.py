"""Unit tests for require_approval_resolved FastAPI dependency."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from agno.os.auth import require_approval_resolved


def _make_request(
    authorization_enabled: bool = True,
    scopes: list = None,
    path_params: dict = None,
) -> MagicMock:
    """Build a fake Request with the attributes the dependency reads."""
    request = MagicMock()
    request.state.authorization_enabled = authorization_enabled
    request.state.scopes = scopes or []
    request.path_params = path_params or {}
    return request


class TestRequireApprovalResolved:
    @pytest.mark.asyncio
    async def test_skips_when_authorization_disabled(self):
        db = MagicMock()
        dep = require_approval_resolved(db)
        request = _make_request(authorization_enabled=False, path_params={"run_id": "r1"})
        # Should return None (no exception)
        assert await dep(request) is None
        db.get_approvals.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_db_is_none(self):
        dep = require_approval_resolved(db=None)
        request = _make_request(path_params={"run_id": "r1"})
        assert await dep(request) is None

    @pytest.mark.asyncio
    async def test_admin_bypass_with_approvals_write_scope(self):
        db = MagicMock()
        dep = require_approval_resolved(db)
        request = _make_request(scopes=["approvals:write"], path_params={"run_id": "r1"})
        assert await dep(request) is None
        db.get_approvals.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_run_id_in_path(self):
        db = MagicMock()
        dep = require_approval_resolved(db)
        request = _make_request(path_params={})
        assert await dep(request) is None
        db.get_approvals.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_db_has_no_get_approvals(self):
        db = MagicMock(spec=[])  # no get_approvals attribute
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        assert await dep(request) is None

    @pytest.mark.asyncio
    async def test_raises_403_when_pending_approval_exists(self):
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([{"id": "a1", "status": "pending"}], 1))
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 403
        assert "admin approval" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_passes_when_no_pending_approvals(self):
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([], 0))
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        assert await dep(request) is None

    @pytest.mark.asyncio
    async def test_handles_sync_get_approvals(self):
        db = MagicMock()
        db.get_approvals = MagicMock(return_value=([{"id": "a1", "status": "pending"}], 1))
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_logs_warning_on_db_error(self):
        db = MagicMock()
        db.get_approvals = MagicMock(side_effect=RuntimeError("connection lost"))
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        with patch("agno.utils.log.log_warning") as mock_log:
            # Should not raise — gate is bypassed on error
            assert await dep(request) is None
            mock_log.assert_called_once()
            assert "connection lost" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_handles_plain_list_result(self):
        """get_approvals may return a plain list instead of (list, count) tuple."""
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=[{"id": "a1", "status": "pending"}])
        dep = require_approval_resolved(db)
        request = _make_request(path_params={"run_id": "r1"})
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
        assert exc_info.value.status_code == 403

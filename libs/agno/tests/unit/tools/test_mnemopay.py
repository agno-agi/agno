"""Unit tests for MnemoPayTools class."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub the external `mnemopay_agno` package before importing the toolkit.
# The production code does:
#   from mnemopay_agno import MnemoPayTools as _ExternalMnemoPayTools
# so we inject a fake module with a mock class.
# ---------------------------------------------------------------------------
_mock_external_module = MagicMock()
_MockExternalTools = MagicMock(name="_ExternalMnemoPayTools")
_mock_external_module.MnemoPayTools = _MockExternalTools
sys.modules["mnemopay_agno"] = _mock_external_module

from agno.tools.mnemopay import MnemoPayTools  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client_mock() -> MagicMock:
    """Return a fresh mock that mimics the _ExternalMnemoPayTools instance."""
    m = MagicMock()
    m.remember.return_value = json.dumps({"id": "mem-1", "status": "stored"})
    m.recall.return_value = json.dumps({"memories": [{"id": "mem-1", "content": "hello", "score": 0.95}]})
    m.forget.return_value = json.dumps({"id": "mem-1", "deleted": True})
    m.reinforce.return_value = json.dumps({"id": "mem-1", "importance": 0.85})
    m.consolidate.return_value = json.dumps({"pruned": 3, "remaining": 12})
    m.charge.return_value = json.dumps({"tx_id": "tx-1", "amount": 0.50, "status": "escrowed"})
    m.settle.return_value = json.dumps({"tx_id": "tx-1", "status": "settled"})
    m.refund.return_value = json.dumps({"tx_id": "tx-1", "status": "refunded"})
    m.balance.return_value = json.dumps({"balance": 10.0, "reputation": 0.92})
    m.profile.return_value = json.dumps({"agent_id": "agno-agent", "reputation": 0.92, "memories": 15, "transactions": 7})
    m.logs.return_value = json.dumps({"entries": [{"action": "remember", "ts": "2026-01-01T00:00:00Z"}]})
    m.history.return_value = json.dumps({"transactions": [{"tx_id": "tx-1", "amount": 0.50}]})
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_external_mock():
    """Reset the class-level mock before each test."""
    _MockExternalTools.reset_mock()
    yield


@pytest.fixture
def mock_client():
    return _make_client_mock()


@pytest.fixture
def toolkit(mock_client):
    """MnemoPayTools with all tools enabled and a mocked client."""
    _MockExternalTools.return_value = mock_client
    t = MnemoPayTools(server_url="http://localhost:3000", agent_id="test-agent")
    # Force lazy client init
    _ = t.client
    return t


@pytest.fixture
def toolkit_defaults(mock_client):
    """MnemoPayTools with default parameters."""
    _MockExternalTools.return_value = mock_client
    t = MnemoPayTools()
    _ = t.client
    return t


# ===========================================================================
# Initialisation tests
# ===========================================================================

class TestMnemoPayToolsInit:
    def test_all_tools_registered_by_default(self, mock_client):
        """All 12 tools should register when nothing is disabled."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools()
        names = [func.name for func in t.functions.values()]

        expected = [
            "remember", "recall", "forget", "reinforce", "consolidate",
            "charge", "settle", "refund", "balance",
            "profile", "logs", "history",
        ]
        for name in expected:
            assert name in names, f"Tool '{name}' not registered"
        assert len(names) == 12

    def test_selective_disable(self, mock_client):
        """Disabling individual flags should exclude those tools."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(enable_charge=False, enable_settle=False, enable_refund=False)
        names = [func.name for func in t.functions.values()]

        assert "charge" not in names
        assert "settle" not in names
        assert "refund" not in names
        # Memory and observability tools should still be present
        assert "remember" in names
        assert "recall" in names
        assert "balance" in names
        assert "profile" in names
        assert len(names) == 9

    def test_all_flag_overrides_individual(self, mock_client):
        """The `all=True` flag should register every tool even when individuals are False."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(
            enable_remember=False,
            enable_charge=False,
            enable_profile=False,
            all=True,
        )
        names = [func.name for func in t.functions.values()]
        assert len(names) == 12

    def test_disable_all_memory_tools(self, mock_client):
        """Disabling all memory tools should leave only payment + observability."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(
            enable_remember=False,
            enable_recall=False,
            enable_forget=False,
            enable_reinforce=False,
            enable_consolidate=False,
        )
        names = [func.name for func in t.functions.values()]
        assert "remember" not in names
        assert "recall" not in names
        assert "forget" not in names
        assert "reinforce" not in names
        assert "consolidate" not in names
        assert len(names) == 7

    def test_disable_all_payment_tools(self, mock_client):
        """Disabling all payment tools should leave only memory + observability."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(
            enable_charge=False,
            enable_settle=False,
            enable_refund=False,
            enable_balance=False,
        )
        names = [func.name for func in t.functions.values()]
        assert "charge" not in names
        assert "settle" not in names
        assert "refund" not in names
        assert "balance" not in names
        assert len(names) == 8

    def test_disable_all_observability_tools(self, mock_client):
        """Disabling all observability tools should leave only memory + payment."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(
            enable_profile=False,
            enable_logs=False,
            enable_history=False,
        )
        names = [func.name for func in t.functions.values()]
        assert "profile" not in names
        assert "logs" not in names
        assert "history" not in names
        assert len(names) == 9

    def test_server_url_from_arg(self, mock_client):
        """Explicit server_url should take priority."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(server_url="http://custom:9999")
        assert t.server_url == "http://custom:9999"

    def test_server_url_from_env(self, monkeypatch, mock_client):
        """Falls back to MNEMOPAY_SERVER_URL env var."""
        monkeypatch.setenv("MNEMOPAY_SERVER_URL", "http://env-server:8000")
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools()
        assert t.server_url == "http://env-server:8000"

    def test_server_url_none_when_unset(self, monkeypatch, mock_client):
        """server_url should be None when neither arg nor env is provided."""
        monkeypatch.delenv("MNEMOPAY_SERVER_URL", raising=False)
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools()
        assert t.server_url is None

    def test_agent_id_default(self, mock_client):
        """Default agent_id should be 'agno-agent'."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools()
        assert t.agent_id == "agno-agent"

    def test_agent_id_custom(self, mock_client):
        """Custom agent_id should be stored."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(agent_id="custom-bot")
        assert t.agent_id == "custom-bot"

    def test_toolkit_name(self, mock_client):
        """Toolkit should register under the name 'mnemopay'."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools()
        assert t.name == "mnemopay"


# ===========================================================================
# Lazy client tests
# ===========================================================================

class TestLazyClient:
    def test_client_created_on_first_access(self, mock_client):
        """Client should not be created until first property access."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(server_url="http://test:3000", agent_id="lazy-test")
        assert t._client is None
        client = t.client
        assert client is mock_client
        _MockExternalTools.assert_called_once_with(
            server_url="http://test:3000",
            agent_id="lazy-test",
        )

    def test_client_reused_on_subsequent_access(self, mock_client):
        """Second access should return the same client, not create a new one."""
        _MockExternalTools.return_value = mock_client
        t = MnemoPayTools(server_url="http://test:3000", agent_id="lazy-test")
        c1 = t.client
        c2 = t.client
        assert c1 is c2
        _MockExternalTools.assert_called_once()


# ===========================================================================
# Memory tool tests
# ===========================================================================

class TestMemoryTools:
    def test_remember(self, toolkit, mock_client):
        result_str = toolkit.remember(content="User prefers dark mode")
        mock_client.remember.assert_called_once_with(content="User prefers dark mode", importance=None)
        result = json.loads(result_str)
        assert result["id"] == "mem-1"
        assert result["status"] == "stored"

    def test_remember_with_importance(self, toolkit, mock_client):
        toolkit.remember(content="Critical fact", importance=0.9)
        mock_client.remember.assert_called_once_with(content="Critical fact", importance=0.9)

    def test_recall_with_query(self, toolkit, mock_client):
        result_str = toolkit.recall(query="dark mode preference")
        mock_client.recall.assert_called_once_with(query="dark mode preference", limit=5)
        result = json.loads(result_str)
        assert "memories" in result
        assert result["memories"][0]["score"] == 0.95

    def test_recall_without_query(self, toolkit, mock_client):
        toolkit.recall()
        mock_client.recall.assert_called_once_with(query=None, limit=5)

    def test_recall_with_custom_limit(self, toolkit, mock_client):
        toolkit.recall(query="test", limit=20)
        mock_client.recall.assert_called_once_with(query="test", limit=20)

    def test_forget(self, toolkit, mock_client):
        result_str = toolkit.forget(id="mem-1")
        mock_client.forget.assert_called_once_with(id="mem-1")
        result = json.loads(result_str)
        assert result["deleted"] is True

    def test_reinforce_default_boost(self, toolkit, mock_client):
        result_str = toolkit.reinforce(id="mem-1")
        mock_client.reinforce.assert_called_once_with(id="mem-1", boost=0.1)
        result = json.loads(result_str)
        assert result["importance"] == 0.85

    def test_reinforce_custom_boost(self, toolkit, mock_client):
        toolkit.reinforce(id="mem-1", boost=0.5)
        mock_client.reinforce.assert_called_once_with(id="mem-1", boost=0.5)

    def test_consolidate(self, toolkit, mock_client):
        result_str = toolkit.consolidate()
        mock_client.consolidate.assert_called_once_with()
        result = json.loads(result_str)
        assert result["pruned"] == 3
        assert result["remaining"] == 12


# ===========================================================================
# Payment tool tests
# ===========================================================================

class TestPaymentTools:
    def test_charge(self, toolkit, mock_client):
        result_str = toolkit.charge(amount=0.50, reason="Answered a question")
        mock_client.charge.assert_called_once_with(amount=0.50, reason="Answered a question")
        result = json.loads(result_str)
        assert result["tx_id"] == "tx-1"
        assert result["status"] == "escrowed"

    def test_settle(self, toolkit, mock_client):
        result_str = toolkit.settle(tx_id="tx-1")
        mock_client.settle.assert_called_once_with(tx_id="tx-1")
        result = json.loads(result_str)
        assert result["status"] == "settled"

    def test_refund(self, toolkit, mock_client):
        result_str = toolkit.refund(tx_id="tx-1")
        mock_client.refund.assert_called_once_with(tx_id="tx-1")
        result = json.loads(result_str)
        assert result["status"] == "refunded"

    def test_balance(self, toolkit, mock_client):
        result_str = toolkit.balance()
        mock_client.balance.assert_called_once_with()
        result = json.loads(result_str)
        assert result["balance"] == 10.0
        assert result["reputation"] == 0.92


# ===========================================================================
# Observability tool tests
# ===========================================================================

class TestObservabilityTools:
    def test_profile(self, toolkit, mock_client):
        result_str = toolkit.profile()
        mock_client.profile.assert_called_once_with()
        result = json.loads(result_str)
        assert result["agent_id"] == "agno-agent"
        assert result["memories"] == 15

    def test_logs_default_limit(self, toolkit, mock_client):
        result_str = toolkit.logs()
        mock_client.logs.assert_called_once_with(limit=20)
        result = json.loads(result_str)
        assert "entries" in result

    def test_logs_custom_limit(self, toolkit, mock_client):
        toolkit.logs(limit=50)
        mock_client.logs.assert_called_once_with(limit=50)

    def test_history_default_limit(self, toolkit, mock_client):
        result_str = toolkit.history()
        mock_client.history.assert_called_once_with(limit=10)
        result = json.loads(result_str)
        assert "transactions" in result

    def test_history_custom_limit(self, toolkit, mock_client):
        toolkit.history(limit=100)
        mock_client.history.assert_called_once_with(limit=100)


# ===========================================================================
# _wrap helper tests
# ===========================================================================

class TestWrapHelper:
    def test_wrap_valid_json_passthrough(self):
        """Valid JSON strings should be returned unchanged."""
        raw = json.dumps({"ok": True})
        assert MnemoPayTools._wrap(raw) == raw

    def test_wrap_plain_text(self):
        """Non-JSON strings should be wrapped in {"result": ...}."""
        result = MnemoPayTools._wrap("plain text response")
        parsed = json.loads(result)
        assert parsed == {"result": "plain text response"}

    def test_wrap_none(self):
        """None should be wrapped as a string."""
        result = MnemoPayTools._wrap(None)
        parsed = json.loads(result)
        assert parsed == {"result": "None"}

    def test_wrap_integer(self):
        """Non-string types should be stringified and wrapped."""
        result = MnemoPayTools._wrap(42)
        parsed = json.loads(result)
        assert parsed == {"result": "42"}

    def test_wrap_empty_string(self):
        """Empty strings are not valid JSON and should be wrapped."""
        result = MnemoPayTools._wrap("")
        parsed = json.loads(result)
        assert parsed == {"result": ""}

    def test_wrap_json_array(self):
        """A JSON array string should pass through."""
        raw = json.dumps([1, 2, 3])
        assert MnemoPayTools._wrap(raw) == raw


# ===========================================================================
# Error handling tests
# ===========================================================================

class TestErrorHandling:
    def test_remember_client_error(self, toolkit, mock_client):
        """Client exceptions should propagate (toolkit has no try/except)."""
        mock_client.remember.side_effect = Exception("connection refused")
        with pytest.raises(Exception, match="connection refused"):
            toolkit.remember(content="test")

    def test_charge_client_error(self, toolkit, mock_client):
        mock_client.charge.side_effect = RuntimeError("insufficient funds")
        with pytest.raises(RuntimeError, match="insufficient funds"):
            toolkit.charge(amount=100.0, reason="expensive")

    def test_recall_client_error(self, toolkit, mock_client):
        mock_client.recall.side_effect = TimeoutError("server timeout")
        with pytest.raises(TimeoutError, match="server timeout"):
            toolkit.recall(query="anything")

    def test_non_json_client_response(self, toolkit, mock_client):
        """When the client returns a non-JSON string, _wrap should handle it."""
        mock_client.balance.return_value = "balance: 10.00 USD"
        result_str = toolkit.balance()
        parsed = json.loads(result_str)
        assert parsed == {"result": "balance: 10.00 USD"}

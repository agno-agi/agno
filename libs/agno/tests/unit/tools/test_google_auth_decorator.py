import json
from unittest.mock import MagicMock, Mock

import pytest

from agno.tools.google.auth.decorator import google_authenticate


class FakeToolkit:
    def __init__(self, creds=None, service=None):
        self.creds = creds
        self._service = service
        self._resolve_creds = MagicMock(return_value=_valid_creds())
        self._build_service = MagicMock(return_value=MagicMock(name="service"))

    @google_authenticate("gmail")
    def do_work(self, *args, **kwargs):
        self.received_args = args
        self.received_kwargs = kwargs
        return json.dumps({"ok": True, "args": list(args), "kwargs": kwargs})


def _valid_creds():
    creds = Mock()
    creds.valid = True
    return creds


def _invalid_creds():
    creds = Mock()
    creds.valid = False
    return creds


# ============================================================================
# CREDENTIAL RESOLUTION TESTS
# ============================================================================


def test_decorator_missing_creds_triggers_resolution():
    tk = FakeToolkit(creds=None, service=None)

    tk.do_work()

    tk._resolve_creds.assert_called_once()


def test_decorator_falsy_creds_triggers_resolution():
    tk = FakeToolkit(creds=None, service=MagicMock())

    tk.do_work()

    tk._resolve_creds.assert_called_once()


def test_decorator_invalid_creds_triggers_resolution():
    tk = FakeToolkit(creds=_invalid_creds(), service=MagicMock())

    tk.do_work()

    tk._resolve_creds.assert_called_once()


def test_decorator_valid_creds_skips_resolution():
    tk = FakeToolkit(creds=_valid_creds(), service=MagicMock())

    tk.do_work()

    tk._resolve_creds.assert_not_called()


# ============================================================================
# AUTH FAILURE TESTS
# ============================================================================


def test_decorator_auth_failure_returns_json_error():
    tk = FakeToolkit(creds=None, service=None)
    tk._resolve_creds.side_effect = RuntimeError("token expired")

    result = tk.do_work()

    data = json.loads(result)
    assert "error" in data
    assert "authentication failed" in data["error"].lower()
    assert "token expired" in data["error"]


def test_decorator_auth_failure_skips_build_and_method():
    tk = FakeToolkit(creds=None, service=None)
    tk._resolve_creds.side_effect = RuntimeError("boom")

    tk.do_work()

    tk._build_service.assert_not_called()
    assert not hasattr(tk, "received_args")


# ============================================================================
# SERVICE BUILDING TESTS
# ============================================================================


def test_decorator_builds_service_when_missing():
    valid = _valid_creds()
    tk = FakeToolkit(creds=valid, service=None)

    tk.do_work()

    tk._build_service.assert_called_once_with(valid)
    assert tk._service is tk._build_service.return_value


def test_decorator_resolves_then_builds():
    tk = FakeToolkit(creds=None, service=None)
    resolved = _valid_creds()
    tk._resolve_creds.return_value = resolved

    tk.do_work()

    tk._resolve_creds.assert_called_once()
    assert tk.creds is resolved
    tk._build_service.assert_called_once_with(resolved)


def test_decorator_skips_build_when_service_exists():
    existing = MagicMock(name="existing_service")
    tk = FakeToolkit(creds=_valid_creds(), service=existing)

    tk.do_work()

    tk._build_service.assert_not_called()
    assert tk._service is existing


def test_decorator_build_failure_returns_json_error():
    tk = FakeToolkit(creds=_valid_creds(), service=None)
    tk._build_service.side_effect = RuntimeError("bad discovery doc")

    result = tk.do_work()

    data = json.loads(result)
    assert "error" in data
    assert "service initialization failed" in data["error"].lower()
    assert "bad discovery doc" in data["error"]


def test_decorator_build_failure_skips_method():
    tk = FakeToolkit(creds=_valid_creds(), service=None)
    tk._build_service.side_effect = RuntimeError("nope")

    tk.do_work()

    assert not hasattr(tk, "received_args")


# ============================================================================
# ARGUMENT PASSING TESTS
# ============================================================================


def test_decorator_positional_args_passed():
    tk = FakeToolkit(creds=_valid_creds(), service=MagicMock())

    tk.do_work("a", "b")

    assert tk.received_args == ("a", "b")


def test_decorator_keyword_args_passed():
    tk = FakeToolkit(creds=_valid_creds(), service=MagicMock())

    tk.do_work(count=5, query="hello")

    assert tk.received_kwargs == {"count": 5, "query": "hello"}


def test_decorator_mixed_args_passed():
    tk = FakeToolkit(creds=_valid_creds(), service=MagicMock())

    tk.do_work("x", flag=True)

    assert tk.received_args == ("x",)
    assert tk.received_kwargs == {"flag": True}


def test_decorator_return_value_propagated():
    tk = FakeToolkit(creds=_valid_creds(), service=MagicMock())

    result = tk.do_work(value=42)

    assert json.loads(result) == {"ok": True, "args": [], "kwargs": {"value": 42}}


# ============================================================================
# SERVICE NAME ERROR MESSAGE TESTS
# ============================================================================


@pytest.mark.parametrize(
    "service_name, expected_prefix",
    [
        ("gmail", "Gmail authentication failed"),
        ("calendar", "Calendar authentication failed"),
        ("drive", "Drive authentication failed"),
    ],
)
def test_decorator_service_name_titlecased_in_error(service_name, expected_prefix):
    class _Tk:
        def __init__(self):
            self.creds = None
            self._service = None
            self._resolve_creds = MagicMock(side_effect=RuntimeError("x"))
            self._build_service = MagicMock()

        @google_authenticate(service_name)
        def run(self):
            return "unreached"

    result = _Tk().run()
    data = json.loads(result)
    assert data["error"].startswith(expected_prefix)


def test_decorator_wraps_preserves_method_name():
    assert FakeToolkit.do_work.__name__ == "do_work"

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

resend_module = ModuleType("resend")
setattr(resend_module, "Emails", SimpleNamespace(send=Mock()))
sys.modules.setdefault("resend", resend_module)


def get_resend_tools_class():
    return import_module("agno.tools.resend").ResendTools


def test_send_email_is_registered():
    ResendTools = get_resend_tools_class()
    resend_tools = ResendTools(api_key="test-api-key")

    assert "send_email" in resend_tools.functions


def test_send_email_requires_confirmation_by_default():
    ResendTools = get_resend_tools_class()
    resend_tools = ResendTools(api_key="test-api-key")

    assert resend_tools.functions["send_email"].requires_confirmation is True


def test_send_email_confirmation_can_be_disabled():
    ResendTools = get_resend_tools_class()
    resend_tools = ResendTools(api_key="test-api-key", require_send_email_confirmation=False)

    assert resend_tools.functions["send_email"].requires_confirmation is False


def test_existing_requires_confirmation_tools_are_preserved_when_default_is_disabled():
    ResendTools = get_resend_tools_class()
    resend_tools = ResendTools(
        api_key="test-api-key",
        require_send_email_confirmation=False,
        requires_confirmation_tools=["send_email"],
    )

    assert resend_tools.requires_confirmation_tools == ["send_email"]
    assert resend_tools.functions["send_email"].requires_confirmation is True

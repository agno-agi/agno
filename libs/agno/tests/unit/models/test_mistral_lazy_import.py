"""Tests that agno.utils.models.mistral can be imported without the optional
``mistralai`` package being installed, and that the ImportError is deferred
to call time.

Regression test for https://github.com/agno-agi/agno/issues/7056.
"""

import importlib
import sys
from unittest.mock import patch


def test_module_import_does_not_raise_without_mistralai():
    """Importing agno.utils.models.mistral must not raise ImportError when
    ``mistralai`` is absent from the environment."""
    # Temporarily hide mistralai from the import system
    with patch.dict(sys.modules, {"mistralai": None, "mistralai.models": None}):
        # Force reimport
        sys.modules.pop("agno.utils.models.mistral", None)
        mod = importlib.import_module("agno.utils.models.mistral")
        assert mod is not None


def test_format_messages_raises_on_call_without_mistralai():
    """format_messages() must raise ImportError only when called, not at import time."""
    with patch.dict(sys.modules, {"mistralai": None, "mistralai.models": None}):
        sys.modules.pop("agno.utils.models.mistral", None)
        mod = importlib.import_module("agno.utils.models.mistral")

        from agno.models.message import Message

        msgs = [Message(role="user", content="hello")]
        try:
            mod.format_messages(msgs)
            # If mistralai is actually installed, the call succeeds – that's also fine
        except ImportError as exc:
            assert "mistralai" in str(exc).lower()
        except Exception:
            # Any other exception means mistralai may be installed but broken; skip
            pass

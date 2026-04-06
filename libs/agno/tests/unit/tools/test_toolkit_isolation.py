import types
from collections import OrderedDict
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


class FakeGmailTools(Toolkit):
    """Minimal stand-in for GmailTools — declares mutable state without Google imports."""

    _clone_reset_attrs = ("creds", "service", "_label_cache")

    def __init__(self):
        self.creds = None
        self.service = None
        self._label_cache = None
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.credentials_path = "/fake/credentials.json"
        super().__init__(name="gmail", tools=[self.get_latest_emails, self.send_email])

    def get_latest_emails(self, count: int = 5) -> str:
        return f"emails from {id(self)}"

    def send_email(self, to: str, subject: str, body: str) -> str:
        return f"sent by {id(self)}"


class PlainToolkit(Toolkit):
    """Toolkit with no _clone_reset_attrs — clone is a no-op for mutable state."""

    def __init__(self):
        super().__init__(name="plain", tools=[self.hello])

    def hello(self) -> str:
        return "hi"


# -- clone() basics --


class TestCloneResetsAttrs:
    def test_mutable_state_is_none_on_clone(self):
        tk = FakeGmailTools()
        tk.creds = MagicMock(name="creds")
        tk.service = MagicMock(name="service")
        tk._label_cache = {"inbox": "INBOX"}

        clone = tk.clone()

        assert clone.creds is None
        assert clone.service is None
        assert clone._label_cache is None

    def test_config_is_preserved(self):
        tk = FakeGmailTools()
        clone = tk.clone()

        assert clone.scopes == tk.scopes
        assert clone.credentials_path == tk.credentials_path
        assert clone.name == tk.name

    def test_clone_is_distinct_instance(self):
        tk = FakeGmailTools()
        clone = tk.clone()
        assert clone is not tk

    def test_plain_toolkit_clone_is_identity_like(self):
        tk = PlainToolkit()
        clone = tk.clone()
        # No attrs to reset, but should still be a distinct instance with rebound fns
        assert clone is not tk
        assert clone.functions.keys() == tk.functions.keys()


# -- Function rebinding --


class TestCloneRebindsFunctions:
    def test_entrypoints_reference_clone_not_original(self):
        tk = FakeGmailTools()
        clone = tk.clone()

        for name, fn in clone.functions.items():
            ep = fn.entrypoint
            assert ep is not None
            # Bound method's __self__ should be the clone
            assert hasattr(ep, "__self__"), f"{name} entrypoint is not a bound method"
            assert ep.__self__ is clone, f"{name} entrypoint bound to original, not clone"

    def test_original_entrypoints_unchanged(self):
        tk = FakeGmailTools()
        clone = tk.clone()

        for name, fn in tk.functions.items():
            ep = fn.entrypoint
            assert hasattr(ep, "__self__")
            assert ep.__self__ is tk

    def test_function_metadata_preserved(self):
        tk = FakeGmailTools()
        clone = tk.clone()

        for name in tk.functions:
            orig = tk.functions[name]
            cloned = clone.functions[name]
            assert cloned.name == orig.name
            assert cloned.description == orig.description
            assert cloned.parameters == orig.parameters


# -- Function.clone_for --


class TestFunctionCloneFor:
    def test_rebinds_bound_method(self):
        tk = FakeGmailTools()
        fn = tk.functions["get_latest_emails"]
        new_owner = FakeGmailTools()

        cloned_fn = fn.clone_for(new_owner)
        assert cloned_fn.entrypoint.__self__ is new_owner
        assert cloned_fn.name == fn.name

    def test_leaves_non_bound_entrypoint_alone(self):
        def standalone(x: int) -> int:
            return x + 1

        fn = Function(name="standalone", entrypoint=standalone)
        new_owner = object()

        cloned_fn = fn.clone_for(new_owner)
        # standalone is not a bound method — should be unchanged
        assert cloned_fn.entrypoint is standalone


# -- deep_copy_field fallback --


class UndeepcopyableToolkit(Toolkit):
    """Simulates Google toolkits that fail deepcopy due to httplib2."""

    _clone_reset_attrs = ("creds", "service")

    def __init__(self):
        self.creds = None
        self.service = None
        self.config_val = "keep_me"
        super().__init__(name="undeepcopyable", tools=[self.do_thing])

    def do_thing(self) -> str:
        return "done"

    def __deepcopy__(self, memo):
        raise TypeError("cannot pickle httplib2.Http")


class TestDeepCopyFieldFallback:
    def test_uses_clone_when_deepcopy_fails(self):
        """deep_copy_field should call clone() when deepcopy raises."""
        from agno.agent._utils import deep_copy_field

        tk = UndeepcopyableToolkit()
        tk.creds = MagicMock(name="user_a_creds")
        tk.service = MagicMock(name="svc")

        # deep_copy_field(agent, field_name, field_value) — agent unused for tools path
        result = deep_copy_field(None, "tools", [tk])  # type: ignore[arg-type]
        assert len(result) == 1
        cloned = result[0]
        assert cloned is not tk
        # clone() resets mutable state
        assert cloned.creds is None
        assert cloned.service is None
        # Config preserved
        assert cloned.config_val == "keep_me"

    def test_shares_by_reference_when_no_clone(self):
        """Object without clone() falls back to share-by-reference."""

        class OpaqueObj:
            def __deepcopy__(self, memo):
                raise TypeError("nope")

        obj = OpaqueObj()
        from agno.agent._utils import deep_copy_field

        result = deep_copy_field(None, "tools", [obj])  # type: ignore[arg-type]
        assert result[0] is obj

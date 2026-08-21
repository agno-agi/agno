"""End-to-end tests for toolkit backcompat shim.

These tests simulate REAL user scenarios to ensure the backcompat shim:
1. Does NOT break user's custom toolkits with enable_* params
2. DOES remap legacy enable_* params for Agno's built-in toolkits
3. Handles user subclasses of Agno toolkits correctly
"""

import pytest

from agno.tools import Toolkit


class TestUserCustomToolkit:
    """Scenario: User creates their own toolkit with enable_* params."""

    def test_user_toolkit_with_enable_param_works(self):
        """User's own enable_* param should work exactly as defined."""

        class MyCustomTools(Toolkit):
            def __init__(self, enable_cache: bool = True, enable_logging: bool = False, **kwargs):
                self.enable_cache = enable_cache
                self.enable_logging = enable_logging
                super().__init__(name="my_custom", auto_register=False, **kwargs)

        # Default values work
        tools = MyCustomTools()
        assert tools.enable_cache is True
        assert tools.enable_logging is False

        # Explicit values work
        tools = MyCustomTools(enable_cache=False, enable_logging=True)
        assert tools.enable_cache is False
        assert tools.enable_logging is True

    def test_user_toolkit_with_kwargs_enable_param(self):
        """User consuming enable_* through **kwargs should work."""

        class FlexibleTools(Toolkit):
            def __init__(self, **kwargs):
                self.enable_feature = kwargs.pop("enable_feature", True)
                self.enable_debug = kwargs.pop("enable_debug", False)
                super().__init__(name="flexible", auto_register=False, **kwargs)

        tools = FlexibleTools(enable_feature=False, enable_debug=True)
        assert tools.enable_feature is False
        assert tools.enable_debug is True

    def test_user_toolkit_unknown_enable_shows_correct_error(self):
        """When user passes unknown enable_*, error should show original name."""

        class StrictTools(Toolkit):
            def __init__(self, name: str = "strict", **kwargs):
                super().__init__(name=name, auto_register=False, **kwargs)

        # The error should mention "enable_unknown", not "unknown"
        with pytest.raises(TypeError) as exc_info:
            StrictTools(enable_unknown=True)

        assert "enable_unknown" in str(exc_info.value)


class TestAgnoBuiltinToolkit:
    """Scenario: Using Agno's built-in toolkits with legacy params."""

    def test_builtin_toolkit_remaps_legacy_param(self):
        """Agno toolkits should remap enable_* to new param names."""
        # Simulate a builtin toolkit by setting __module__
        def make_builtin():
            def _init(self, search: bool = True, **kwargs):
                self.search = search
                Toolkit.__init__(self, name="builtin", auto_register=False, **kwargs)

            return type(
                "BuiltinTools",
                (Toolkit,),
                {"__module__": "agno.tools.search", "__init__": _init},
            )

        BuiltinTools = make_builtin()

        # Legacy param should be remapped
        tools = BuiltinTools(enable_search=False)
        assert tools.search is False

        # New param should work directly
        tools = BuiltinTools(search=True)
        assert tools.search is True

    def test_builtin_with_alias_map(self):
        """Agno toolkits with _legacy_param_aliases should use custom mappings."""

        def make_aliased_builtin():
            def _init(self, search_web: bool = True, **kwargs):
                self.search_web = search_web
                Toolkit.__init__(self, name="aliased", auto_register=False, **kwargs)

            return type(
                "AliasedTools",
                (Toolkit,),
                {
                    "__module__": "agno.tools.web",
                    "__init__": _init,
                    "_legacy_param_aliases": {"enable_search": "search_web"},
                },
            )

        AliasedTools = make_aliased_builtin()

        # Legacy param with custom alias should remap
        tools = AliasedTools(enable_search=False)
        assert tools.search_web is False


class TestUserSubclassOfAgnoToolkit:
    """Scenario: User subclasses an Agno toolkit."""

    def _make_agno_toolkit(self):
        """Create a fake Agno toolkit (simulating GmailTools, etc.)"""

        def _init(self, read: bool = True, send: bool = False, **kwargs):
            self.read = read
            self.send = send
            Toolkit.__init__(self, name="agno_base", auto_register=False, **kwargs)

        return type(
            "AgnoBaseTools",
            (Toolkit,),
            {
                "__module__": "agno.tools.email",
                "__init__": _init,
                "_legacy_param_aliases": {"enable_read": "read", "enable_send": "send"},
            },
        )

    def test_user_subclass_own_enable_param_untouched(self):
        """User's own enable_* param in subclass should NOT be remapped."""
        AgnoTools = self._make_agno_toolkit()

        class MyEmailTools(AgnoTools):
            def __init__(self, enable_custom_feature: bool = True, **kwargs):
                self.enable_custom_feature = enable_custom_feature
                super().__init__(**kwargs)

        tools = MyEmailTools(enable_custom_feature=False, enable_read=False)
        # User's own param is untouched
        assert tools.enable_custom_feature is False
        # Parent's legacy param is still remapped via super()
        assert tools.read is False

    def test_user_subclass_inherits_parent_legacy_support(self):
        """User subclass should still get parent's legacy param remapping."""
        AgnoTools = self._make_agno_toolkit()

        class MyEmailTools(AgnoTools):
            def __init__(self, custom_setting: str = "default", **kwargs):
                self.custom_setting = custom_setting
                super().__init__(**kwargs)

        # Parent's legacy params should still work
        tools = MyEmailTools(custom_setting="custom", enable_read=False, enable_send=True)
        assert tools.custom_setting == "custom"
        assert tools.read is False
        assert tools.send is True

    def test_bare_subclass_inherits_everything(self):
        """User subclass with no __init__ inherits parent's wrapped init."""
        AgnoTools = self._make_agno_toolkit()

        class BareSubclass(AgnoTools):
            pass

        # Should work exactly like parent
        tools = BareSubclass(enable_read=False)
        assert tools.read is False


class TestRealWorldScenarios:
    """Test scenarios that match real user code patterns."""

    def test_data_pipeline_toolkit(self):
        """Realistic: User building a data pipeline toolkit."""

        class DataPipelineTools(Toolkit):
            def __init__(
                self,
                enable_extract: bool = True,
                enable_transform: bool = True,
                enable_load: bool = True,
                connection_string: str = "sqlite:///:memory:",
                **kwargs,
            ):
                self.enable_extract = enable_extract
                self.enable_transform = enable_transform
                self.enable_load = enable_load
                self.connection_string = connection_string

                tools = []
                if enable_extract:
                    tools.append(self.extract)
                if enable_transform:
                    tools.append(self.transform)
                if enable_load:
                    tools.append(self.load)

                super().__init__(name="data_pipeline", tools=tools, **kwargs)

            def extract(self) -> str:
                return "extracted"

            def transform(self) -> str:
                return "transformed"

            def load(self) -> str:
                return "loaded"

        # All enabled
        tools = DataPipelineTools()
        assert tools.enable_extract is True
        assert len(tools.functions) == 3

        # Selective
        tools = DataPipelineTools(enable_extract=True, enable_transform=False, enable_load=True)
        assert tools.enable_transform is False
        assert len(tools.functions) == 2

    def test_api_client_toolkit(self):
        """Realistic: User building an API client toolkit."""

        class MyAPITools(Toolkit):
            def __init__(
                self,
                api_key: str = "test-key",
                enable_caching: bool = True,
                enable_retry: bool = True,
                enable_logging: bool = False,
                **kwargs,
            ):
                self.api_key = api_key
                self.enable_caching = enable_caching
                self.enable_retry = enable_retry
                self.enable_logging = enable_logging
                super().__init__(name="my_api", auto_register=False, **kwargs)

        tools = MyAPITools(enable_caching=False, enable_retry=True)
        assert tools.enable_caching is False
        assert tools.enable_retry is True
        assert tools.enable_logging is False

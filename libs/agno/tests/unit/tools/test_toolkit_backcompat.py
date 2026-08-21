from typing import Any, List
from unittest.mock import patch

from agno.tools import Toolkit


class UserDefinedToolkit(Toolkit):
    """User-defined toolkit - should NOT get backcompat wrapping."""

    def __init__(
        self,
        cache: bool = True,
        **kwargs: Any,
    ):
        self.cache = cache
        super().__init__(name="user_toolkit", tools=[], **kwargs)


class TestToolkitBackcompat:
    def test_user_defined_toolkit_not_wrapped(self):
        """User toolkits should NOT have enable_ remapping - enable_cache is unexpected."""
        # If wrapping happened, enable_cache would be remapped to cache
        # Since it's a user toolkit, no wrapping occurs and this raises TypeError
        try:
            UserDefinedToolkit(enable_cache=False)
            assert False, "Should have raised TypeError for unexpected kwarg"
        except TypeError as e:
            assert "enable_cache" in str(e)

    def test_user_defined_toolkit_new_param_works(self):
        """User toolkit's actual param works normally."""
        toolkit = UserDefinedToolkit(cache=False)
        assert toolkit.cache is False


class TestRealToolkits:
    def test_file_tools_backcompat(self):
        """FileTools should accept enable_save_file for backwards compat."""
        from agno.tools.file import FileTools

        warnings: List[str] = []
        with patch("agno.tools.toolkit.log_debug", lambda msg: warnings.append(msg)):
            toolkit = FileTools(enable_save_file=False)

        tool_names = [f.name for f in toolkit.functions.values()]
        assert "save_file" not in tool_names
        assert any("enable_save_file" in w for w in warnings)

    def test_file_tools_new_param(self):
        """FileTools new param should work without warning."""
        from agno.tools.file import FileTools

        warnings: List[str] = []
        with patch("agno.tools.toolkit.log_debug", lambda msg: warnings.append(msg)):
            toolkit = FileTools(save_file=False)

        tool_names = [f.name for f in toolkit.functions.values()]
        assert "save_file" not in tool_names
        assert not any("deprecated" in w.lower() for w in warnings)

    def test_file_tools_both_params_uses_new(self):
        """When both enable_X and X are passed, X wins with warning."""
        from agno.tools.file import FileTools

        warnings: List[str] = []
        with patch("agno.tools.toolkit.log_debug", lambda msg: warnings.append(msg)):
            toolkit = FileTools(enable_save_file=True, save_file=False)

        tool_names = [f.name for f in toolkit.functions.values()]
        assert "save_file" not in tool_names
        assert any("Both" in w for w in warnings)


class TestCustomAliases:
    def test_seltz_custom_alias(self):
        """SeltzTools should remap max_documents to max_results."""
        try:
            from agno.tools.seltz import SeltzTools
        except ImportError:
            return  # Skip if seltz not installed

        warnings: List[str] = []
        with patch("agno.tools.toolkit.log_debug", lambda msg: warnings.append(msg)):
            # No API key so it will log error, but we just test param remapping
            with patch("agno.tools.seltz.log_error"):
                toolkit = SeltzTools(max_documents=20)

        assert toolkit.max_results == 20
        assert any("max_documents" in w for w in warnings)

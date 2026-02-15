"""BUG-017: exit(1) in library code terminates host process.

Library code should never call exit() — it should raise exceptions.
Found in 5 locations: memory/manager.py, culture/manager.py, api/settings.py,
team/_init.py, cloud/aws/s3/api_client.py.
"""

import inspect
import sys
from unittest.mock import patch

import pytest


class TestBUG017ExitInLibraryCode:
    def test_memory_manager_exit_on_missing_openai(self):
        """MemoryManager.get_model() calls exit(1) when openai not installed."""
        from agno.memory.manager import MemoryManager

        manager = MemoryManager.__new__(MemoryManager)
        manager.model = None

        with patch.dict(sys.modules, {"agno.models.openai": None}):
            with pytest.raises(SystemExit) as exc_info:
                manager.get_model()
            assert exc_info.value.code == 1

    def test_exit_calls_in_source_code(self):
        """Verify exit() calls exist in library source files."""
        locations = [
            ("agno.memory.manager", "exit(1)"),
            ("agno.culture.manager", "exit(1)"),
            ("agno.api.settings", "exit(1)"),
        ]

        for module_path, expected_pattern in locations:
            source = inspect.getsource(__import__(module_path, fromlist=[module_path.split(".")[-1]]))
            assert expected_pattern in source, f"{module_path} should contain {expected_pattern}"

    def test_team_init_has_exit(self):
        """Verify team/_init.py has exit(1)."""
        source = inspect.getsource(__import__("agno.team._init", fromlist=["_init"]))
        assert "exit(1)" in source

    def test_s3_api_client_has_exit_zero(self):
        """Verify S3 api_client uses exit(0) — success code on error."""
        try:
            source = inspect.getsource(__import__("agno.cloud.aws.s3.api_client", fromlist=["api_client"]))
            assert "exit(0)" in source
        except (ImportError, ModuleNotFoundError):
            pytest.skip("S3 api_client not importable (missing boto3)")

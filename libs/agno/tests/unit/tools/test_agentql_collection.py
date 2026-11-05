"""Keep optional AgentQL imports from changing CI shard assignments."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("availability", "collect_only"),
    [("available", True), ("missing", True), ("broken", True), ("missing", False), ("broken", False)],
)
def test_agentql_collection_is_independent_of_optional_imports(availability: str, collect_only: bool) -> None:
    subject = Path(__file__).with_name("test_agentql.py")
    code = textwrap.dedent(
        """
        import builtins
        import json
        import sys
        import types

        import pytest

        availability, subject, collect_only = sys.argv[1:]
        if availability == "available":
            sys.modules["agentql"] = types.ModuleType("agentql")
            toolkit = types.ModuleType("agno.tools.agentql")
            toolkit.AgentQLTools = object
            sys.modules["agno.tools.agentql"] = toolkit
        elif availability == "missing":
            sys.modules["agentql"] = None
        else:
            original_import = builtins.__import__

            def broken_import(name, *args, **kwargs):
                if name == "agentql":
                    raise ImportError("AgentQL dependency cannot import")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = broken_import

        class Recorder:
            def __init__(self):
                self.ids = []
                self.skipped = 0

            def pytest_collection_finish(self, session):
                self.ids = [item.name for item in session.items]

            def pytest_runtest_logreport(self, report):
                if report.skipped:
                    self.skipped += 1

        recorder = Recorder()
        args = ["-q", "--noconftest", "-p", "no:cacheprovider", subject]
        if collect_only == "True":
            args.append("--collect-only")
        result = pytest.main(args, plugins=[recorder])
        print("COLLECTION_RESULT " + json.dumps(
            {"code": int(result), "ids": recorder.ids, "skipped": recorder.skipped}
        ))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code, availability, str(subject), str(collect_only)],
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(
        next(
            line.removeprefix("COLLECTION_RESULT ")
            for line in result.stdout.splitlines()
            if line.startswith("COLLECTION_RESULT ")
        )
    )
    assert payload["code"] == 0, result.stdout + result.stderr
    assert set(payload["ids"]) == {
        "test_init_with_api_key",
        "test_init_without_api_key",
        "test_scrape_website_no_url",
        "test_scrape_website_no_api_key",
        "test_custom_scrape_no_query",
        "test_scrape_website_success",
    }
    assert len(payload["ids"]) == 6
    if not collect_only:
        assert payload["skipped"] == 6

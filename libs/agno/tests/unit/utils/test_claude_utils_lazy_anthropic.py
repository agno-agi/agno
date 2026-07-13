"""Regression test: ``agno.utils.models.claude`` must be importable without
``anthropic`` installed, so that non-Anthropic callers (LiteLLM, Bedrock)
can use ``supports_prefill()`` without the Anthropic SDK as a runtime dep.

``anthropic.types`` is only required by ``format_messages()`` and is imported
lazily inside that function. The sentinel below asserts the top-level import
chain does not touch ``anthropic``.
"""

import subprocess
import sys
import textwrap


def test_supports_prefill_importable_without_anthropic():
    """Run in a subprocess with ``anthropic`` masked, verify the import succeeds.

    Using a subprocess + ``sys.modules`` injection of ``None`` makes this
    deterministic across environments (the CI test env otherwise has
    ``anthropic`` installed transitively).
    """
    code = textwrap.dedent(
        """
        import sys
        # Mask anthropic so any attempt to import it raises ModuleNotFoundError.
        sys.modules["anthropic"] = None  # type: ignore[assignment]
        sys.modules["anthropic.types"] = None  # type: ignore[assignment]

        from agno.utils.models.claude import supports_prefill

        # Smoke-test the function while we're here.
        assert supports_prefill("claude-sonnet-4-5") is True
        assert supports_prefill("claude-sonnet-4-6") is False
        assert supports_prefill("gpt-4o") is True
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Import failed. stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == "OK"

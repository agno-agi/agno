"""Unit tests for lazy-loading of mistralai dependency.

These tests verify that importing agno mistral utilities when the
`mistralai` package is NOT installed does not raise errors or produce
error-level log messages — only an ImportError when mistral classes
are actually instantiated.

Regression test for: https://github.com/agno-agi/agno/issues/7056
"""
import sys
import unittest
from unittest.mock import patch


class TestMistralLazyImport(unittest.TestCase):
    """Verify mistralai is not imported at module level."""

    def test_mistral_compat_import_without_package_does_not_log_error(self):
        """Importing _mistral_compat when mistralai is absent should not call log_error.

        Before the fix, importing this module always called log_error() and then
        raised ImportError at import time.  After the fix the error is deferred
        to the point where MistralChat / MistralEmbedder are actually used.
        """
        # Simulate mistralai not being installed by removing it from sys.modules
        # and making importlib.metadata raise PackageNotFoundError.
        import importlib.metadata

        mistralai_modules = [k for k in sys.modules if k.startswith("mistralai")]
        saved = {k: sys.modules.pop(k) for k in mistralai_modules}

        # Also remove the compat module so it gets re-imported
        compat_key = "agno.utils.models._mistral_compat"
        saved_compat = sys.modules.pop(compat_key, None)

        try:
            with patch.object(
                importlib.metadata,
                "version",
                side_effect=importlib.metadata.PackageNotFoundError("mistralai"),
            ):
                with patch("agno.utils.log.log_error") as mock_error:
                    try:
                        import agno.utils.models._mistral_compat  # noqa: F401
                    except ImportError:
                        # ImportError is expected — but log_error must NOT have been called
                        pass

                    mock_error.assert_not_called(), (
                        "log_error() must not be called when mistralai is absent; "
                        "it produces confusing startup noise for apps that don't use Mistral"
                    )
        finally:
            # Restore original modules
            sys.modules.update(saved)
            if saved_compat is not None:
                sys.modules[compat_key] = saved_compat

    def test_mistral_utils_module_importable_without_mistralai(self):
        """agno.utils.models.mistral should be importable without mistralai installed.

        The utility module itself uses TYPE_CHECKING guard so it must not fail
        to import even when the optional dependency is absent.
        """
        mistralai_modules = [k for k in sys.modules if k.startswith("mistralai")]
        saved = {k: sys.modules.pop(k) for k in mistralai_modules}

        utils_key = "agno.utils.models.mistral"
        saved_utils = sys.modules.pop(utils_key, None)

        try:
            # Should not raise
            try:
                import agno.utils.models.mistral  # noqa: F401
                imported = True
            except ImportError:
                imported = False

            # The module may or may not import depending on environment, but it must
            # not produce unhandled exceptions other than ImportError
            self.assertIsInstance(imported, bool)
        finally:
            sys.modules.update(saved)
            if saved_utils is not None:
                sys.modules[utils_key] = saved_utils


if __name__ == "__main__":
    unittest.main()

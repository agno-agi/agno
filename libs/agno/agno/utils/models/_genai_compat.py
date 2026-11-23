# mypy: disable-error-code="attr-defined,no-redef"
"""
Compatibility layer for google-genai <2.9.0 and >=2.9.0.

The streaming delta types in `google.genai.interactions` were relocated and
renamed in 2.9.0: they moved from the `step_delta` submodule (named `Delta<X>`)
to the top-level `interactions` namespace (renamed `<X>Delta`). This module
detects the installed SDK version once and exposes a stable set of `Delta*`
aliases so consumer modules can simply do:

    from agno.utils.models._genai_compat import DeltaText, DeltaArgumentsDelta, ...

If google-genai is not installed, this module can still be imported without
error. Actual ImportError is raised only when the exported symbols are accessed.

When 2.8.0 support is dropped, delete the `else` branch and the version check.

`attr-defined` / `no-redef` are disabled at module scope: only one of the two
import branches is visible to mypy at a time (whichever matches the installed
SDK), so the names from the other branch always look undefined or redefined.
"""

import importlib.metadata

_genai_available = False
_genai_version: tuple = (0, 0)

try:
    _version_str = importlib.metadata.version("google-genai")
    _parts = _version_str.split(".")
    _genai_version = (int(_parts[0]), int(_parts[1]) if len(_parts) > 1 else 0)
    _genai_available = True
except importlib.metadata.PackageNotFoundError:
    pass


if _genai_available:
    if _genai_version >= (2, 9):
        # google-genai >= 2.9.0: delta types live at the top level of
        # `interactions`, renamed `<X>Delta`.
        from google.genai.interactions import ArgumentsDelta as DeltaArgumentsDelta
        from google.genai.interactions import CodeExecutionCallDelta as DeltaCodeExecutionCall
        from google.genai.interactions import CodeExecutionResultDelta as DeltaCodeExecutionResult
        from google.genai.interactions import FileSearchCallDelta as DeltaFileSearchCall
        from google.genai.interactions import FileSearchResultDelta as DeltaFileSearchResult
        from google.genai.interactions import FunctionResultDelta as DeltaFunctionResult
        from google.genai.interactions import GoogleMapsCallDelta as DeltaGoogleMapsCall
        from google.genai.interactions import GoogleMapsResultDelta as DeltaGoogleMapsResult
        from google.genai.interactions import GoogleSearchCallDelta as DeltaGoogleSearchCall
        from google.genai.interactions import GoogleSearchResultDelta as DeltaGoogleSearchResult
        from google.genai.interactions import ImageDelta as DeltaImage
        from google.genai.interactions import MCPServerToolCallDelta as DeltaMCPServerToolCall
        from google.genai.interactions import MCPServerToolResultDelta as DeltaMCPServerToolResult
        from google.genai.interactions import TextDelta as DeltaText
        from google.genai.interactions import ThoughtSignatureDelta as DeltaThoughtSignature
        from google.genai.interactions import ThoughtSummaryDelta as DeltaThoughtSummary
        from google.genai.interactions import URLContextCallDelta as DeltaURLContextCall
        from google.genai.interactions import URLContextResultDelta as DeltaURLContextResult
    else:
        # google-genai < 2.9.0: delta types live under the `step_delta` submodule,
        # exposed as a submodule attribute (not a sub-package), so the Delta* types
        # need attribute access rather than a direct import.
        from google.genai.interactions import step_delta

        DeltaArgumentsDelta = step_delta.DeltaArgumentsDelta
        DeltaImage = step_delta.DeltaImage
        DeltaText = step_delta.DeltaText
        DeltaThoughtSignature = step_delta.DeltaThoughtSignature
        DeltaThoughtSummary = step_delta.DeltaThoughtSummary
        # Typed call deltas. Non-function call families stream their typed
        # Arguments object here (DeltaArgumentsDelta only fires for functions).
        DeltaCodeExecutionCall = step_delta.DeltaCodeExecutionCall
        DeltaFileSearchCall = step_delta.DeltaFileSearchCall
        DeltaGoogleMapsCall = step_delta.DeltaGoogleMapsCall
        DeltaGoogleSearchCall = step_delta.DeltaGoogleSearchCall
        DeltaMCPServerToolCall = step_delta.DeltaMCPServerToolCall
        DeltaURLContextCall = step_delta.DeltaURLContextCall
        # Result deltas. Every *ResultStep arrives empty at StepStart and its
        # actual payload streams here (one or more deltas, then StepStop).
        DeltaCodeExecutionResult = step_delta.DeltaCodeExecutionResult
        DeltaFileSearchResult = step_delta.DeltaFileSearchResult
        DeltaFunctionResult = step_delta.DeltaFunctionResult
        DeltaGoogleMapsResult = step_delta.DeltaGoogleMapsResult
        DeltaGoogleSearchResult = step_delta.DeltaGoogleSearchResult
        DeltaMCPServerToolResult = step_delta.DeltaMCPServerToolResult
        DeltaURLContextResult = step_delta.DeltaURLContextResult


GENAI_SDK_VERSION = _genai_version


if not _genai_available:

    def __getattr__(name: str):  # noqa: ANN001, ANN202
        raise ImportError(
            f"`google-genai` not installed. Cannot import '{name}'. "
            "Please install it using `pip install -U google-genai`"
        )


__all__ = [
    "DeltaArgumentsDelta",
    "DeltaCodeExecutionCall",
    "DeltaCodeExecutionResult",
    "DeltaFileSearchCall",
    "DeltaFileSearchResult",
    "DeltaFunctionResult",
    "DeltaGoogleMapsCall",
    "DeltaGoogleMapsResult",
    "DeltaGoogleSearchCall",
    "DeltaGoogleSearchResult",
    "DeltaImage",
    "DeltaMCPServerToolCall",
    "DeltaMCPServerToolResult",
    "DeltaText",
    "DeltaThoughtSignature",
    "DeltaThoughtSummary",
    "DeltaURLContextCall",
    "DeltaURLContextResult",
    "GENAI_SDK_VERSION",
]

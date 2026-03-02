"""Backwards-compatibility shim. Implementation moved to agno.tools.google.gmail."""

import importlib
import sys

_real_module = importlib.import_module("agno.tools.google.gmail")
sys.modules[__name__] = _real_module

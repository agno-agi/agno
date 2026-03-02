"""Backwards-compatibility shim. Implementation moved to agno.tools.google.youtube."""

import importlib
import sys

_real_module = importlib.import_module("agno.tools.google.youtube")
sys.modules[__name__] = _real_module

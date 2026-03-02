"""Backwards-compatibility shim. Implementation moved to agno.tools.google.maps."""

import importlib
import sys

_real_module = importlib.import_module("agno.tools.google.maps")
sys.modules[__name__] = _real_module

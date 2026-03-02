"""Backwards-compatibility shim. Implementation moved to agno.tools.google.bigquery."""

import importlib
import sys

_real_module = importlib.import_module("agno.tools.google.bigquery")
sys.modules[__name__] = _real_module

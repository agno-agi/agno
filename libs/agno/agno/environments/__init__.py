"""agno.environments: run an agent many times against a set of tasks and score every attempt.

The public surface (`Env`, `EnvTask`, `run_rollouts`, exporters) lands in a later PR;
this package currently holds only the private engine. The `__init__.py` exists from the
start because packaging uses `[tool.setuptools.packages.find]`, under which a directory
without one silently does not ship.
"""

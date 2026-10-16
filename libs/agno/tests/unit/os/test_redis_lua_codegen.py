"""The committed _redis_lua.py must match what redis_scripts/ generates.

redis_scripts/ holds the @script source and is not shipped; agno imports only
the generated module, which needs nothing beyond the standard library and redis.
"""

import sys
from pathlib import Path

import pytest

LIBS_AGNO = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(sys.version_info < (3, 10), reason="redis-lua-py needs Python 3.10+ to generate")
def test_generated_redis_lua_is_current(monkeypatch):
    codegen = pytest.importorskip("redis_lua_py.codegen", reason="redis-lua-py not installed")
    monkeypatch.syspath_prepend(str(LIBS_AGNO))
    monkeypatch.chdir(LIBS_AGNO)
    codegen.check("redis_scripts.event_streams", "agno/os/event_streams/_redis_lua.py")

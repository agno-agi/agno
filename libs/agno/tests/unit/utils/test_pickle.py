"""Tests for agno.utils.pickle RestrictedUnpickler (CWE-502 mitigation).

The tests assert both directions of the security contract:
- legitimate objects (dict/list/pathlib.Path/custom classes) round-trip unchanged;
- globals from modules that can execute arbitrary code (os, subprocess,
  builtins, functools, ...) are rejected with UnpicklingError.
"""
import functools
import os
import pathlib
import pickle
import subprocess
import tempfile

import pytest

from agno.utils.pickle import RestrictedUnpickler, pickle_object_to_file, unpickle_object_from_file


class _Exploit:
    """De-weaponized payload helper: returns (callable, args) for __reduce__."""

    def __init__(self, callable_, args):
        self._callable = callable_
        self._args = args

    def __reduce__(self):
        return (self._callable, self._args)


class _User:
    """Module-level class so pickle can reference it by qualified name."""

    def __init__(self, name: str):
        self.name = name


def _write_pickle(path: pathlib.Path, obj) -> pathlib.Path:
    with path.open("wb") as f:
        pickle.dump(obj, f)
    return path


# --- legit round-trips must be unaffected --------------------------------


def test_roundtrip_dict():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "d.pkl"
        pickle_object_to_file({"a": 1, "b": [1, 2, 3]}, f)
        assert unpickle_object_from_file(f) == {"a": 1, "b": [1, 2, 3]}


def test_roundtrip_path():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "p.pkl"
        pickle_object_to_file(pathlib.Path("/tmp/x"), f)
        assert unpickle_object_from_file(f) == pathlib.Path("/tmp/x")


def test_roundtrip_list():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "l.pkl"
        pickle_object_to_file(list(range(10)), f)
        assert unpickle_object_from_file(f) == list(range(10))


def test_roundtrip_custom_class():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "u.pkl"
        pickle_object_to_file(_User("agno"), f)
        loaded = unpickle_object_from_file(f)
        assert isinstance(loaded, _User)
        assert loaded.name == "agno"


def test_verify_class_mismatch_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "u.pkl"
        pickle_object_to_file({"k": 1}, f)
        assert unpickle_object_from_file(f, verify_class=list) is None


def test_corrupted_file_fails_safely():
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "bad.pkl"
        f.write_bytes(b"not-a-pickle")
        with pytest.raises(Exception):
            unpickle_object_from_file(f)


# --- arbitrary-code globals must be rejected ------------------------------


@pytest.mark.parametrize(
    "label, callable_, args",
    [
        ("os.system", os.system, ("echo PWNED > /tmp/agno_rce_proof",)),
        ("builtins.eval", eval, ("__import__('os').system('id')",)),
        ("subprocess.check_call", subprocess.check_call, (["touch", "/tmp/x"],)),
        ("functools.partial(os.system)", functools.partial, (os.system, "touch /tmp/x")),
    ],
)
def test_blocks_rce_payloads(label, callable_, args):
    with tempfile.TemporaryDirectory() as tmp:
        f = _write_pickle(pathlib.Path(tmp) / f"evil_{label}.pkl", _Exploit(callable_, args))
        with pytest.raises(pickle.UnpicklingError):
            unpickle_object_from_file(f)


@pytest.mark.parametrize(
    "module, name",
    [
        ("os", "system"),
        ("os", "popen"),
        ("subprocess", "check_call"),
        ("builtins", "eval"),
        ("builtins", "exec"),
        ("posix", "system"),
        ("shutil", "rmtree"),
        ("sys", "exit"),
        ("importlib", "import_module"),
        ("functools", "partial"),
    ],
)
def test_find_class_forbids_dangerous_modules(module, name):
    with pytest.raises(pickle.UnpicklingError):
        RestrictedUnpickler.__new__(RestrictedUnpickler).find_class(module, name)


def test_find_class_allows_safe_modules():
    unpickler = RestrictedUnpickler.__new__(RestrictedUnpickler)
    # collections.OrderedDict is a plain container and must stay loadable.
    from collections import OrderedDict

    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "od.pkl"
        pickle_object_to_file(OrderedDict([("k", 1)]), f)
        assert unpickle_object_from_file(f) == OrderedDict([("k", 1)])

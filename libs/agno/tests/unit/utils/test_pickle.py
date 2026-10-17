import io
import pickle
from pathlib import Path

from agno.utils.pickle import pickle_object_to_file, unpickle_object_from_file


def test_pickle_helpers_roundtrip_object(tmp_path):
    file_path = tmp_path / "nested" / "object.pkl"
    obj = {"name": "agno", "values": [1, 2, 3]}

    pickle_object_to_file(obj, file_path)

    assert unpickle_object_from_file(file_path, verify_class=dict) == obj
    assert unpickle_object_from_file(file_path, verify_class=list) is None


def test_pickle_object_to_file_closes_file_handle(monkeypatch, tmp_path):
    opened_files = []

    def fake_open(self, mode="r", *args, **kwargs):
        assert mode == "wb"
        opened_file = io.BytesIO()
        opened_files.append(opened_file)
        return opened_file

    monkeypatch.setattr(Path, "open", fake_open)

    pickle_object_to_file({"ok": True}, tmp_path / "object.pkl")

    assert len(opened_files) == 1
    assert opened_files[0].closed is True


def test_unpickle_object_from_file_closes_file_handle(monkeypatch, tmp_path):
    file_path = tmp_path / "object.pkl"
    file_path.touch()
    opened_files = []

    def fake_open(self, mode="r", *args, **kwargs):
        assert mode == "rb"
        opened_file = io.BytesIO(pickle.dumps({"ok": True}))
        opened_files.append(opened_file)
        return opened_file

    monkeypatch.setattr(Path, "open", fake_open)

    assert unpickle_object_from_file(file_path) == {"ok": True}
    assert len(opened_files) == 1
    assert opened_files[0].closed is True

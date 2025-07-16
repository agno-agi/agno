import uuid


class FileStore:
    def __init__(self):
        self._files = {}  # key: file_id, value: dict with content, name, content_type

    def add(self, content: bytes, name: str, content_type: str) -> str:
        file_id = str(uuid.uuid4())
        self._files[file_id] = {
            "content": content,
            "name": name,
            "content_type": content_type,
        }
        return file_id

    def get(self, file_id: str):
        return self._files.get(file_id)

    def list(self):
        return [
            {"file_id": fid, "name": meta["name"], "content_type": meta["content_type"]}
            for fid, meta in self._files.items()
        ]

    def clear(self):
        self._files.clear()
        self._files = {}

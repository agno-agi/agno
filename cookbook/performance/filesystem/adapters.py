"""Storage adapters for the filesystem benchmark; no model or network calls."""

from pathlib import Path


class Adapter:
    def __init__(self, name: str, root: Path):
        self.name, self.root = name, root
        root.mkdir(parents=True, exist_ok=True)
        if name.startswith("agno"):
            from agno.fs import FileSystem
            from agno.fs.local import LocalFileSystem

            if "sqlite" in name:
                from agno.db.sqlite import SqliteDb
                from agno.fs.db import DbFileSystem

                self.backend = DbFileSystem(db=SqliteDb(db_file=str(root / "files.db")))
            else:
                self.backend = LocalFileSystem(root / "files")
            self.fs = FileSystem(
                self.backend, namespace="bench", max_namespace_bytes=1_000_000_000
            )
        elif name == "deepagents-local":
            from deepagents.backends import FilesystemBackend

            self.backend = FilesystemBackend(root_dir=root / "files", virtual_mode=True)
        else:
            (root / "files").mkdir(exist_ok=True)

    def write(self, path: str, content: str):
        if self.name.startswith("agno"):
            if self.name.endswith("-backend"):
                return self.backend.write("bench", path, content)
            return self.fs.write(path, content)
        if self.name == "deepagents-local":
            result = self.backend.upload_files([("/" + path, content.encode())])[0]
            if result.error:
                raise RuntimeError(result.error)
            return
        target = self.root / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))

    def read(self, path: str):
        if self.name.startswith("agno"):
            return (
                self.backend.read("bench", path)
                if self.name.endswith("-backend")
                else self.fs.read(path)
            )
        if self.name == "deepagents-local":
            result = self.backend.download_files(["/" + path])[0]
            if result.error:
                if result.error == "file_not_found":
                    return None
                raise RuntimeError(result.error)
            return result.content.decode("utf-8")
        target = self.root / "files" / path
        return target.read_bytes().decode("utf-8") if target.exists() else None

    def list(self):
        if self.name.startswith("agno"):
            result = (
                self.backend.list("bench")
                if self.name.endswith("-backend")
                else self.fs.list()
            )
            return sorted(item.path for item in result)
        if self.name == "deepagents-local":
            result = self.backend.glob("**/*", path="/")
            if result.error or result.truncated:
                raise RuntimeError(str(result))
            return sorted(
                item["path"].lstrip("/")
                for item in result.matches
                if not item.get("is_dir")
            )
        return sorted(
            p.relative_to(self.root / "files").as_posix()
            for p in (self.root / "files").rglob("*")
            if p.is_file()
        )

    def search(self, query: str, limit: int = 10):
        if self.name.startswith("agno"):
            result = (
                self.backend.search("bench", query, limit=limit)
                if self.name.endswith("-backend")
                else self.fs.search(query, limit=limit)
            )
            return sorted(item.path for item in result)
        if self.name == "deepagents-local":
            # Deep Agents grep is case-sensitive literal matching. Timed queries
            # and corpus are lowercase ASCII, with <= 1 matching line per file.
            result = self.backend.grep(query, path="/", max_count=100_000)
            if result.error or result.truncated:
                raise RuntimeError(str(result))
            return sorted({item["path"].lstrip("/") for item in result.matches})[:limit]
        matches = []
        for p in self.list():
            if query in self.read(p):
                matches.append(p)
            if len(matches) >= limit:
                break
        return matches

    def delete(self, path: str):
        if self.name.startswith("agno"):
            return (
                self.backend.delete("bench", path)
                if self.name.endswith("-backend")
                else self.fs.delete(path)
            )
        if self.name == "deepagents-local":
            result = self.backend.delete("/" + path)
            if result.error:
                raise RuntimeError(result.error)
            return
        (self.root / "files" / path).unlink()

    def close(self):
        if self.name.startswith("agno") and "sqlite" in self.name:
            self.backend.db_engine.dispose()

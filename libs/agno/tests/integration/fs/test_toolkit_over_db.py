"""The toolkit exercised over DbFileSystem, both dialects (spec D7).

This lane exists because the unit suite runs the toolkit only over LocalFileSystem
and the DB integration suite runs the backend and programmatic API but never builds a
toolkit — so a value that is fine in SQLite/Python but wrong on Postgres (e.g. a
Decimal from sum(bigint)) reaches json.dumps only here. Every tool that returns JSON
is parsed; every tool is called against the real backend on both dialects.
"""

import json

from agno.fs import FileSystem

NS = "tk"


def _fs(db_fs):
    return FileSystem(backend=db_fs, namespace=NS)


class TestToolkitOverDb:
    def test_list_files_usage_is_json_and_int(self, db_fs):
        # The regression: Postgres sum(bigint) is Decimal, which json.dumps rejects,
        # so list_files (the tool D8 tells the model to call first) died on Postgres.
        fs = _fs(db_fs)
        fs.write("notes/a.md", "hello world")
        tools = fs.tools()
        payload = json.loads(tools.list_files())
        usage = payload["usage"]
        assert isinstance(usage["bytes_used"], int)
        assert isinstance(usage["bytes_limit"], int)
        assert isinstance(usage["files"], int)
        assert usage["bytes_used"] == len("hello world".encode("utf-8"))

    def test_every_tool_returns_serializable_output(self, db_fs):
        fs = _fs(db_fs)
        tools = fs.tools()
        # Seed via the tools themselves.
        assert tools.write_file("notes/a.md", "alpha").startswith("Wrote")
        assert tools.append_file("seen/log.md", "example.com/a").startswith("Appended")
        # JSON tools must parse.
        for out in (tools.list_files(), tools.search_content("alpha"), tools.check_lines(["example.com/a"])):
            json.loads(out)
        # check_lines finds the exact record and misses a superstring.
        cl = json.loads(tools.check_lines(["example.com/a", "example.com/ab"]))
        assert cl["found"] == ["example.com/a"]
        assert cl["missing"] == ["example.com/ab"]
        # Read, move, delete round-trip.
        assert "1\talpha" in tools.read_file("notes/a.md")
        assert tools.move_file("notes/a.md", "notes/b.md").startswith("Moved")
        assert tools.delete_file("notes/b.md").startswith("Deleted")

    def test_check_lines_rejects_bare_string(self, db_fs):
        # A bare str is a Sequence[str] of characters; it must be rejected, not split.
        out = json.loads(_fs(db_fs).tools().check_lines(["real-record"]))
        assert out == {"found": [], "missing": ["real-record"]}
        err = _fs(db_fs).tools().check_lines("real-record")  # type: ignore[arg-type]
        assert err.startswith("Error:")
        assert "list of lines" in err

    def test_directory_scope_is_case_sensitive_on_both_dialects(self, db_fs):
        # SQLite LIKE folds ASCII; the predicate must not, or dev and prod disagree.
        fs = _fs(db_fs)
        fs.append("seen/a.md", "x")
        fs.append("Seen/b.md", "y")
        found = {m.path for m in fs.list(directory="seen")}
        assert found == {"seen/a.md"}

    def test_read_only_toolkit_has_four_tools_over_db(self, db_fs):
        tools = _fs(db_fs).tools(read_only=True)
        names = {f.name for f in tools.functions.values()}
        assert names == {"read_file", "list_files", "search_content", "check_lines"}

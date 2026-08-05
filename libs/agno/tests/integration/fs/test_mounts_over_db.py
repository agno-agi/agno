"""Mounts exercised over DbFileSystem, both dialects.

The unit suite proves routing over LocalFileSystem; this lane proves the same
contract against the real backend: a write through an rw mount lands as a row
in the mounted namespace (never the primary's), ro enforcement holds, and
scoped reads round-trip through the mount prefix.
"""

import json

from agno.fs import FileSystem, Mount

PRIMARY_NS = "mounts-primary"
SHARED_NS = "mounts-shared"


class TestMountsOverDb:
    def test_rw_mount_routes_rows_to_the_mounted_namespace(self, db_fs):
        primary = FileSystem(backend=db_fs, namespace=PRIMARY_NS)
        shared = FileSystem(backend=db_fs, namespace=SHARED_NS)
        tools = primary.tools(mounts={"team": Mount(fs=shared, mode="rw")})

        assert tools.write_file("team/notes/a.md", "in the mount").startswith("Wrote")
        assert tools.write_file("notes/b.md", "in the primary").startswith("Wrote")

        # Rows land under the mounted namespace, never the primary's.
        assert db_fs.read(SHARED_NS, "notes/a.md") == "in the mount"
        assert db_fs.read(PRIMARY_NS, "team/notes/a.md") is None
        assert db_fs.read(PRIMARY_NS, "notes/b.md") == "in the primary"

        # Scoped listing round-trips: the returned path reads back verbatim.
        payload = json.loads(tools.list_files(directory="team", recursive=True))
        paths = [e["path"] for e in payload["files"] if e["type"] == "file"]
        assert paths == ["team/notes/a.md"]
        assert "in the mount" in tools.read_file(paths[0])

    def test_ro_mount_refuses_writes_and_serves_reads(self, db_fs):
        primary = FileSystem(backend=db_fs, namespace=PRIMARY_NS)
        shared = FileSystem(backend=db_fs, namespace=SHARED_NS)
        shared.write("seen/log.md", "example.com/a\n")
        tools = primary.tools(mounts={"shared": shared})

        result = tools.append_file("shared/seen/log.md", "example.com/b")
        assert result == "Error: shared/ is read-only: files in this shared mount can be read but not changed."
        assert db_fs.read(SHARED_NS, "seen/log.md") == "example.com/a\n"

        checked = json.loads(tools.check_lines(["example.com/a"], directory="shared/seen"))
        assert checked["found"] == ["example.com/a"]

        found = json.loads(tools.search_content("example.com", directory="shared"))
        assert [f["file"] for f in found["files"]] == ["shared/seen/log.md"]

    def test_cross_store_move_is_refused_on_the_db_backend(self, db_fs):
        primary = FileSystem(backend=db_fs, namespace=PRIMARY_NS)
        shared = FileSystem(backend=db_fs, namespace=SHARED_NS)
        tools = primary.tools(mounts={"team": Mount(fs=shared, mode="rw")})
        primary.write("a.md", "stay put")

        result = tools.move_file("a.md", "team/a.md")
        assert result.startswith("Error: cannot move between file stores:")
        assert db_fs.read(PRIMARY_NS, "a.md") == "stay put"
        assert db_fs.read(SHARED_NS, "a.md") is None

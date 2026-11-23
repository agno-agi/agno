"""Lazy I/O and command compatibility ported from the Docs Agent adapter."""

from types import SimpleNamespace

import pytest

from agno.knowledge.page import PageFileSystem


class CorpusFactory:
    """Test indirection to exercise the same assertions against arbitrary public page APIs."""

    def get_docs_knowledge(self):
        raise AssertionError("test must select a Knowledge instance")

    def get_corpus(self, **kwargs):
        return PageFileSystem(knowledge=self.get_docs_knowledge()).get_corpus(**kwargs)


pages = CorpusFactory()


def test_plain_case_insensitive_vfs_search_uses_bounded_public_grep(monkeypatch):
    from agno.knowledge.page import GrepMatch, GrepResult, Page
    from agno.knowledge.page._commands import run_command
    from agno.knowledge.page.filesystem import PageCorpus

    page = Page(
        content_id="vfs-literal",
        namespace="test",
        path="/z.md",
        url="https://docs.example.com/z",
        title="Z",
        revision="one",
        digest="one",
        index_fingerprint="test",
        filesystem_version=1,
        expected_chunk_count=1,
    )
    corpus = PageCorpus(PageFileSystem(knowledge=SimpleNamespace()), {page.path: page})
    calls = []

    def grep(query, *, prefix, ignore_case):
        calls.append((query, prefix, ignore_case))
        return GrepResult(
            matches=(GrepMatch(path=page.path, url=page.url, revision=page.revision, line_number=2, text="ZepTools"),)
        )

    monkeypatch.setattr(corpus, "grep", grep)
    assert "/z.md" in run_command('rg -il "ZepTools" /', corpus)
    assert calls == [("ZepTools", "/", True)]
    assert not corpus.loaded


@pytest.mark.parametrize("complete,reason", [(True, None), (False, "deadline"), (False, "limit")])
def test_root_literal_grep_never_traverses_catalog(monkeypatch, complete, reason):
    from types import SimpleNamespace

    from agno.knowledge.page import GrepMatch, GrepResult
    from agno.knowledge.page._commands import run_command

    calls = []

    def listing(**kwargs):
        # run_command's emptiness check is bounded to one metadata record.
        assert kwargs == {"limit": 1}
        calls.append("exists")
        return SimpleNamespace(pages=[object()])

    def grep(query, **kwargs):
        assert query == "tool_call_limit"
        assert kwargs == {"prefix": "/", "ignore_case": True, "limit": 100}
        calls.append("grep")
        return GrepResult(
            matches=(
                GrepMatch(
                    path="/agents.md", url="https://docs.example.com/agents", revision="r", line_number=2, text=query
                ),
            ),
            complete=complete,
            stop_reason=reason,
        )

    monkeypatch.setattr(pages, "get_docs_knowledge", lambda: SimpleNamespace(list_pages=listing, grep_pages=grep))
    result = run_command('rg -il "tool_call_limit" /', pages.get_corpus(lazy=True))
    assert result.endswith("\n/agents.md")
    assert ("[1 matching lines in 1 files]" if complete else f"[stopped at {reason}:") in result
    assert calls == ["exists", "grep"]


@pytest.mark.parametrize("root", ["/scope", "/scope/", "/missing"])
def test_literal_directory_grep_checks_existence_without_enumeration(monkeypatch, root):
    from types import SimpleNamespace

    from agno.knowledge.page import GrepMatch, GrepResult, PageNotFound
    from agno.knowledge.page._commands import run_command

    prefixes = []

    def listing(**kwargs):
        if kwargs == {"limit": 1}:
            return SimpleNamespace(pages=[object()])
        assert kwargs == {"prefix": root.rstrip("/") + "/", "limit": 1}
        return SimpleNamespace(pages=[SimpleNamespace(path="/scope/a.md")] if root != "/missing" else [])

    def read(*args, **kwargs):
        raise PageNotFound()

    def grep(query, **kwargs):
        prefixes.append(kwargs["prefix"])
        assert kwargs["prefix"] == "/scope/"
        return GrepResult(
            matches=(
                GrepMatch(
                    path="/scope/a.md", url="https://docs.example.com/a", revision="r", line_number=1, text=query
                ),
            )
        )

    monkeypatch.setattr(
        pages, "get_docs_knowledge", lambda: SimpleNamespace(list_pages=listing, read_page=read, grep_pages=grep)
    )
    result = run_command(f"rg -l needle {root}", pages.get_corpus(lazy=True))
    if root == "/missing":
        assert result == "rg: /missing: no such file or directory"
        assert not prefixes
    else:
        assert result == "[1 matching lines in 1 files]\n/scope/a.md"
        assert prefixes == ["/scope/"]


@pytest.mark.parametrize("command", ["cat /a", "head -2 /a", "tail -2 /a", "wc -l /a", "cat /missing /a"])
def test_explicit_file_commands_do_not_enumerate_the_corpus(monkeypatch, command):
    from types import SimpleNamespace

    from agno.knowledge.page import PageNotFound
    from agno.knowledge.page._commands import run_command

    body = "# A\n第一行\nLast line\n"
    reads = []

    def listing(**kwargs):
        assert kwargs == {"limit": 1}
        return SimpleNamespace(pages=[object()])

    def read(path, **kwargs):
        reads.append(path)
        if path != "/a.md":
            raise PageNotFound()
        return SimpleNamespace(text=body, next_offset=None, revision="first")

    monkeypatch.setattr(pages, "get_docs_knowledge", lambda: SimpleNamespace(list_pages=listing, read_page=read))
    assert run_command(command, pages.get_corpus(lazy=True)) == run_command(command, {"/a.md": body})
    assert reads.count("/a.md") == 1


def test_scoped_directory_commands_preserve_output_and_revisions(monkeypatch):
    from types import SimpleNamespace

    from agno.knowledge.page import Page, PageList, PageNotFound
    from agno.knowledge.page._commands import run_command

    page = Page(
        content_id="scoped-vfs",
        namespace="test",
        path="/scope/a.md",
        url="https://docs.example.com/scope/a",
        title="A",
        revision="r",
        digest="r",
        index_fingerprint="test",
        filesystem_version=1,
        expected_chunk_count=1,
    )
    body = "# A\nneedle\nlast\n"
    prefixes = []

    def listing(**kwargs):
        if kwargs == {"limit": 1}:
            return PageList(pages=(page,))
        if kwargs["prefix"] == "/scope.md":
            return PageList()
        prefixes.append(kwargs["prefix"])
        assert kwargs["prefix"] == "/scope/"
        return PageList(pages=(page,))

    def read(path, **kwargs):
        if path != page.path:
            raise PageNotFound()
        assert kwargs["revision"] == "r"
        return SimpleNamespace(text=body, next_offset=None)

    monkeypatch.setattr(pages, "get_docs_knowledge", lambda: SimpleNamespace(list_pages=listing, read_page=read))
    source = {page.path: body, "/elsewhere.md": "needle\n"}
    for command in ("ls /scope", "tree /scope", "find /scope", "rg -C 1 needle /scope"):
        assert run_command(command, pages.get_corpus(lazy=True)) == run_command(command, source)
    assert prefixes == ["/scope/"] * 4


def test_lazy_page_continuations_reject_refresh_and_next_command_reads_current_text(monkeypatch):
    from types import SimpleNamespace

    from agno.knowledge.page import PageChanged

    calls = []

    def changing(path, **kwargs):
        calls.append(kwargs)
        if kwargs["offset"] == 0:
            return SimpleNamespace(text="old", next_offset=3, revision="old")
        assert kwargs["revision"] == "old"
        raise PageChanged(current_revision="new")

    knowledge = SimpleNamespace(read_page=changing)
    monkeypatch.setattr(pages, "get_docs_knowledge", lambda: knowledge)
    with pytest.raises(PageChanged):
        pages.get_corpus(lazy=True)["/a.md"]
    knowledge.read_page = lambda *a, **kw: SimpleNamespace(text="new", next_offset=None, revision="new")
    assert pages.get_corpus(lazy=True)["/a.md"] == "new"


@pytest.mark.parametrize(
    "command",
    [
        "rg -C 1 needle /scope/a.md",
        "rg -l needle /scope/a.md",
        "rg -l needle /scope/a",
        "tree /scope/a.md",
        "find /scope/a.md",
    ],
)
def test_explicit_md_file_does_not_expand_into_same_name_directory(monkeypatch, command):
    from types import SimpleNamespace

    from agno.knowledge.page import GrepMatch, GrepResult, Page, PageList, PageNotFound
    from agno.knowledge.page._commands import run_command
    from agno.knowledge.page._source import page_prefix

    source = {"/scope/a.md": "needle in file\n", "/scope/a/child.md": "needle in child\n"}
    metadata = {
        path: Page(
            content_id=path,
            namespace="test",
            path=path,
            url="https://docs.example.com" + path,
            title=path,
            revision="r",
            digest="r",
            index_fingerprint="test",
            filesystem_version=1,
            expected_chunk_count=1,
        )
        for path in source
    }

    def listing(**kwargs):
        prefix = page_prefix(kwargs.get("prefix", "/"))
        return PageList(pages=tuple(page for path, page in metadata.items() if path.startswith(prefix)))

    def read(path, **kwargs):
        if path not in source:
            raise PageNotFound()
        return SimpleNamespace(text=source[path], next_offset=None, revision="r")

    def grep(query, **kwargs):
        prefix = page_prefix(kwargs["prefix"])
        return GrepResult(
            matches=tuple(
                GrepMatch(path=path, url=metadata[path].url, revision="r", line_number=1, text=body.rstrip("\n"))
                for path, body in sorted(source.items())
                if path.startswith(prefix) and query in body
            )
        )

    monkeypatch.setattr(
        pages, "get_docs_knowledge", lambda: SimpleNamespace(list_pages=listing, read_page=read, grep_pages=grep)
    )
    assert run_command(command, pages.get_corpus(lazy=True)) == run_command(command, source)


@pytest.mark.parametrize("command", ["cat /", "head /", "tail /", "wc /", "cat / /a", "wc / /a"])
@pytest.mark.parametrize("has_index", [False, True])
def test_root_read_alias_uses_index_and_preserves_later_targets(command, has_index):
    from agno.knowledge.page import PageNotFound
    from agno.knowledge.page._commands import run_command

    source = {"/a.md": "valid later page\n"}
    if has_index:
        source["/index.md"] = "root index\n"
    reads = []

    def listing(**kwargs):
        assert kwargs == {"limit": 1}
        return SimpleNamespace(pages=[object()])

    def read(path, **kwargs):
        reads.append(path)
        assert path in ("/index.md", "/a.md")
        if path not in source:
            raise PageNotFound()
        return SimpleNamespace(text=source[path], next_offset=None, revision="r")

    files = PageFileSystem(knowledge=SimpleNamespace(list_pages=listing, read_page=read))
    output = files.run_command(command)
    assert output == run_command(command, source)
    assert "ValueError" not in output
    assert reads[0] == "/index.md"
    if "/a" in command:
        assert "/a.md" in output


@pytest.mark.parametrize(
    "command",
    [
        "ls /agents.md",
        "tree /agents.md",
        "find /agents.md",
        "rg absent /agents.md",
        "rg -C 1 absent /agents.md",
        "cat /agents.md",
    ],
)
def test_explicit_file_never_probes_redundant_aliases_or_directory(command):
    from test_page_filesystem import page

    from agno.knowledge.page import PageList
    from agno.knowledge.page._commands import run_command

    metadata = page("/agents.md")
    reads = []

    def listing(**kwargs):
        assert kwargs == {"limit": 1} or kwargs == {"prefix": "/agents.md", "limit": 1}
        return PageList(pages=(metadata,))

    def read(path, **kwargs):
        assert path == "/agents.md"
        reads.append(path)
        return SimpleNamespace(text="body", next_offset=None, revision="one")

    files = PageFileSystem(knowledge=SimpleNamespace(list_pages=listing, read_page=read))
    assert files.run_command(command) == run_command(command, {"/agents.md": "body"})
    assert len(reads) == (1 if command.startswith(("rg", "cat")) else 0)


@pytest.mark.parametrize("flag", ["", "-l", "-c", "-i", "-F"])
@pytest.mark.parametrize("complete,reason", [(True, None), (False, "deadline"), (False, "limit")])
def test_literal_file_and_directory_search_keeps_bounded_grep(flag, complete, reason):
    from agno.knowledge.page import GrepMatch, GrepResult

    calls = []

    def listing(**kwargs):
        assert kwargs in ({"limit": 1}, {"prefix": "/agents/", "limit": 1})
        return SimpleNamespace(pages=[SimpleNamespace(path="/agents/child.md")])

    def read(path, **kwargs):
        assert path == "/agents.md"
        calls.append("read")
        return SimpleNamespace(text="needle file\n", next_offset=None, revision="r")

    def grep(query, **kwargs):
        assert kwargs == {"prefix": "/agents/", "ignore_case": flag == "-i", "limit": 100}
        calls.append("grep")
        return GrepResult(
            matches=(
                GrepMatch(
                    path="/agents/child.md",
                    url="https://example.com/child",
                    revision="r",
                    line_number=1,
                    text="needle child",
                ),
            ),
            complete=complete,
            stop_reason=reason,
        )

    files = PageFileSystem(knowledge=SimpleNamespace(list_pages=listing, read_page=read, grep_pages=grep))
    output = files.run_command(f"rg {flag} needle /agents")
    assert "/agents.md" in output and "/agents/child.md" in output
    assert (
        "[2 matching lines in 2 files]" if complete else f"[stopped at {reason}: 2 matching lines in 2 files so far;"
    ) in output
    assert calls == ["read", "grep"]


def test_literal_file_and_directory_results_share_the_match_bound():
    from agno.knowledge.page import GrepMatch, GrepResult

    def grep(*args, **kwargs):
        return GrepResult(
            matches=tuple(
                GrepMatch(
                    path="/agents/child.md",
                    url="https://example.com/child",
                    revision="r",
                    line_number=i,
                    text="needle child",
                )
                for i in range(1, 101)
            ),
            complete=False,
            stop_reason="limit",
        )

    knowledge = SimpleNamespace(
        list_pages=lambda **kwargs: SimpleNamespace(pages=[SimpleNamespace(path="/agents/child.md")]),
        read_page=lambda *args, **kwargs: SimpleNamespace(text="needle file\n" * 110, next_offset=None, revision="r"),
        grep_pages=grep,
    )
    output = PageFileSystem(knowledge=knowledge).run_command("rg needle /agents")
    assert output.startswith("[stopped at limit: 100 matching lines in 1 files so far;")
    assert len(output.splitlines()) == 101

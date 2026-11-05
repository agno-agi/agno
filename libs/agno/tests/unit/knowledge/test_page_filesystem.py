import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agno.knowledge.page import Page, PageChanged, PageError, PageFileSystem, PageList
from agno.knowledge.page._commands import run_command
from agno.utils.bounded import BoundedWorkers


def page(path="/a.md", revision="one"):
    return Page(
        content_id=path,
        namespace="test",
        path=path,
        url="https://docs.example.com" + path,
        title=path,
        revision=revision,
        digest=revision,
        index_fingerprint="test",
        filesystem_version=1,
        expected_chunk_count=1,
    )


def test_archived_command_outputs_are_identical():
    baseline = json.loads((Path(__file__).parent / "fixtures/page_commands_baseline.json").read_text())
    assert len(baseline["commands"]) == 66
    for case in baseline["commands"]:
        assert run_command(case["command"], baseline["corpus"]) == case["output"], case["command"]


def test_cache_is_instance_scoped_bounded_and_validates_publication():
    current = page()
    reads = []

    def read(path, **kwargs):
        reads.append(kwargs)
        if kwargs["revision"] != current.revision:
            raise PageChanged(current_revision=current.revision)
        return SimpleNamespace(text="body", next_offset=None, revision=current.revision)

    knowledge = SimpleNamespace(list_pages=lambda **kwargs: PageList(pages=(current,)), read_page=read)
    fs = PageFileSystem(knowledge=knowledge, max_cached_bytes=8, max_cached_entries=1)
    assert fs.get_corpus()["/a.md"] == "body"
    retained = fs.get_corpus()
    assert retained["/a.md"] == "body"
    assert [r["max_chars"] for r in reads] == [24000, 1]
    stale = fs.get_corpus()
    current = page(revision="two")
    with pytest.raises(PageChanged):
        stale["/a.md"]
    assert fs.get_corpus()["/a.md"] == "body"
    assert len(fs._bodies) == 1 and fs._body_bytes == 4
    other = PageFileSystem(
        knowledge=SimpleNamespace(
            list_pages=lambda **kwargs: PageList(pages=(current,)),
            read_page=lambda *args, **kwargs: SimpleNamespace(text="different store", next_offset=None),
        )
    )
    assert other.get_corpus()["/a.md"] == "different store"
    assert fs.get_corpus()["/a.md"] == "body"


def test_cache_byte_eviction_and_oversized_body():
    pages = [page("/a.md"), page("/b.md"), page("/c.md")]
    fs = PageFileSystem(
        knowledge=SimpleNamespace(
            list_pages=lambda **kw: PageList(pages=tuple(pages)),
            read_page=lambda path, **kw: SimpleNamespace(text="four" if path != "/c.md" else "x" * 9, next_offset=None),
        ),
        max_cached_bytes=8,
    )
    corpus = fs.get_corpus()
    assert [corpus[p.path] for p in pages] == ["four", "four", "x" * 9]
    assert fs._body_bytes == 8 and len(fs._bodies) == 2


def test_listing_restart_discards_the_old_snapshot_and_is_bounded():
    calls = iter(
        [
            PageList(pages=(page("/old.md"),), next_cursor="cursor"),
            PageList(restart_required=True),
            PageList(pages=(page("/new.md"),)),
        ]
    )
    fs = PageFileSystem(knowledge=SimpleNamespace(list_pages=lambda **kw: next(calls)))
    assert list(fs.get_corpus()) == ["/new.md"]
    fs.knowledge.list_pages = lambda **kw: PageList(restart_required=True)
    with pytest.raises(PageError):
        fs.get_corpus()


@pytest.mark.parametrize(
    "option,value",
    [
        ("max_output_chars", 0),
        ("max_cached_entries", True),
        ("command_seconds", float("inf")),
        ("regex_match_timeout", -1),
    ],
)
def test_limits_are_validated(option, value):
    with pytest.raises(ValueError):
        PageFileSystem(knowledge=SimpleNamespace(), **{option: value})


def test_optional_regex_has_actionable_construction_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "regex", None)
    with pytest.raises(ImportError, match=r"agno\[pages\]"):
        PageFileSystem(knowledge=SimpleNamespace())


def test_read_and_catalog_limits():
    fs = PageFileSystem(
        knowledge=SimpleNamespace(
            list_pages=lambda **kw: PageList(pages=(page(), page("/b.md"))),
            read_page=lambda *a, **kw: SimpleNamespace(text="too large", next_offset=None),
        ),
        max_catalog_entries=1,
        max_read_chars=2,
    )
    with pytest.raises(PageError):
        fs.get_corpus()
    with pytest.raises(PageError):
        fs.run_command("cat /a")


@pytest.mark.asyncio
async def test_async_matches_sync_and_keeps_the_loop_responsive(monkeypatch):
    fs = PageFileSystem(
        knowledge=SimpleNamespace(
            list_pages=lambda **kw: PageList(pages=(page(),)),
            read_page=lambda *a, **kw: SimpleNamespace(text="body", next_offset=None),
        )
    )
    assert await fs.arun_command("cat /a") == fs.run_command("cat /a")
    assert list(await fs.aget_corpus()) == ["/a.md"]
    original = fs.knowledge.read_page

    def slow(*a, **kw):
        time.sleep(0.05)
        return original(*a, **kw)

    fs.knowledge.read_page = slow
    task = asyncio.create_task(fs.arun_command("cat /a"))
    await asyncio.sleep(0.01)
    assert not task.done()
    assert "body" in await task


@pytest.mark.asyncio
async def test_cancelled_command_retains_capacity_until_worker_finishes(monkeypatch):
    import agno.knowledge.page.filesystem as module

    workers = BoundedWorkers(1, "test-vfs-cancel")
    monkeypatch.setattr(module, "_COMMAND_WORKERS", workers)
    entered, release = threading.Event(), threading.Event()

    def read(*args, **kwargs):
        entered.set()
        release.wait(2)
        return SimpleNamespace(text="body", next_offset=None)

    fs = PageFileSystem(knowledge=SimpleNamespace(list_pages=lambda **kw: PageList(pages=(page(),)), read_page=read))
    task = asyncio.create_task(fs.arun_command("cat /a"))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(PageError):
            await fs.arun_command("cat /a")
    finally:
        release.set()
    for _ in range(100):
        try:
            assert "body" in await fs.arun_command("cat /a")
            break
        except PageError:
            await asyncio.sleep(0.005)
    else:
        pytest.fail("worker capacity was not released")
    workers._executor.shutdown(wait=True)


def test_regex_budget_stops_inside_a_large_page(monkeypatch):
    import agno.knowledge.page._commands as commands

    ticks = iter([0.0] * 10 + [3.0] * 100)
    monkeypatch.setattr(commands, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    output = run_command("rg '(?=needle)' /", {"/a.md": "needle\n" * 10000})
    assert output.startswith("[stopped after 2s:")
    assert "no matches" not in output


@pytest.mark.parametrize("command", ["x" * 10000, "cat --" + "z" * 10000, "cat /" + "z" * 10000])
def test_invalid_commands_obey_configured_output_bounds(command):
    from agno.knowledge.page import PageNotFound

    def missing(*args, **kwargs):
        raise PageNotFound()

    fs = PageFileSystem(
        knowledge=SimpleNamespace(list_pages=lambda **kw: PageList(pages=(page(),)), read_page=missing),
        max_output_chars=100,
    )
    output = fs.run_command(command)
    assert len(output) <= 300
    assert "truncated" in output


@pytest.mark.parametrize(
    "command,expected",
    [("ls /scope", "a.md\n/scope.md"), ("ls /scope.md", "/scope.md"), ("tree /scope.md", "/scope.md")],
)
def test_listing_never_reads_page_bodies_even_for_same_name_files(command, expected):
    metadata = [page("/scope/a.md"), page("/scope.md")]

    def listing(**kwargs):
        return PageList(pages=tuple(p for p in metadata if p.path.startswith(kwargs.get("prefix", "/"))))

    def read(*args, **kwargs):
        pytest.fail("metadata-only listing downloaded a body")

    fs = PageFileSystem(knowledge=SimpleNamespace(list_pages=listing, read_page=read), max_read_chars=1)
    assert fs.run_command(command) == expected


@pytest.mark.parametrize("snapshot", [False, True])
def test_encoded_metadata_existence_uses_canonical_paths(snapshot):
    from agno.knowledge.page._source import page_prefix

    metadata = page("/Getting Started.md")
    calls = []

    def listing(**kwargs):
        calls.append(kwargs)
        prefix = page_prefix(kwargs.get("prefix", "/"))
        return PageList(pages=(metadata,) if metadata.path.startswith(prefix) else ())

    fs = PageFileSystem(knowledge=SimpleNamespace(list_pages=listing))
    corpus = fs.get_corpus(lazy=not snapshot)
    calls.clear()
    assert corpus._metadata_contains("/Getting%20Started.md")
    assert calls == ([] if snapshot else [{"prefix": "/Getting Started.md", "limit": 1}])

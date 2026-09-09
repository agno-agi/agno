import re
import threading
from types import SimpleNamespace

import pytest

import agno.knowledge.page._commands as vfs
from agno.knowledge.page._commands import MAX_OUTPUT, USAGE, run_command

CORPUS = {
    "/index.md": "# Welcome\n\nStart here.\n",
    "/quickstart.md": "# Quickstart\n\n```python\nfrom agno.agent import Agent\nagent = Agent()\n```\n",
    "/concepts.md": "# Concepts overview page\n\nSee the sub-pages.\n",
    "/concepts/agents.md": "# Agents\n\nAn Agent has a model.\nUse enable_agentic_memory=True to remember.\n",
    "/concepts/agents/tools.md": "# Tools\n\nAgents call tools.\n",
    "/concepts/teams.md": "# Teams\n\nA Team coordinates agents.\n",
    "/examples/basic.md": "# Basic example\n\nagent = Agent(model=OpenAIChat())\n",
    "/i18n/unicode.md": "# Ünïcödé\n\nnaïve café — 日本語\n",
    "/empty.md": "",
}


def run(cmd: str) -> str:
    out = run_command(cmd, CORPUS)
    assert isinstance(out, str)
    return out


def test_ls_root_dir_file_and_missing():
    assert "concepts/" in run("ls /") and "quickstart.md" in run("ls")
    assert run("ls /concepts").splitlines() == ["agents.md", "agents/", "teams.md", "/concepts.md"]
    assert run("ls /quickstart.md") == "/quickstart.md"
    assert run("ls /quickstart") == "/quickstart.md"
    assert "no such file or directory" in run("ls /nope")
    assert "agents.md" in run("ls -la /concepts")


def test_tree_depth_and_file_argument():
    out = run("tree / -L 1")
    assert "concepts/" in out and "agents.md" not in out
    assert "tools.md" in run("tree /concepts")
    assert run("tree /quickstart.md") == "/quickstart.md"
    assert "no such directory" in run("tree /nope")


def test_find_supports_name_and_type_and_reports_missing_dirs():
    assert "/concepts/agents.md" in run("find / -name '*agent*'")
    assert "/concepts/agents.md" in run("find /concepts -type f -name 'agents.md'")
    assert run("find /concepts").splitlines() == [
        "/concepts/agents.md",
        "/concepts/agents/tools.md",
        "/concepts/teams.md",
    ]
    assert "no files matching" in run("find / -name '*.rst'")
    assert "no such directory" in run("find /nope -name x")


def test_rg_basic_flags_and_context():
    assert "/concepts/agents.md:4:Use enable_agentic_memory=True" in run("rg enable_agentic_memory /")
    assert run("rg -il agent /concepts").splitlines()[1:] == [
        "/concepts/agents.md",
        "/concepts/agents/tools.md",
        "/concepts/teams.md",
    ]
    assert "/concepts/agents.md:3" in run("rg -ic agent /concepts/agents")
    ctx = run('rg -C 1 "has a model" /concepts')
    assert "/concepts/agents.md-2-" in ctx and "/concepts/agents.md:3:" in ctx and "--" in ctx
    assert "/concepts/agents.md-4-Use enable_agentic_memory" in ctx
    after = run('rg -A 1 "has a model" /concepts')
    assert "-4-" in after and "-2-" not in after
    before = run('rg -B 1 "has a model" /concepts')
    assert "-2-" in before and "-4-" not in before
    assert "no matches" in run("rg zzz-not-here /")


def test_rg_accepts_llm_idioms():
    assert "/concepts/agents.md" in run("grep -r Agents /concepts")
    assert "/concepts/agents.md" in run("rg -e Agents /concepts")
    assert "/concepts/agents.md" in run("rg -- Agents /concepts")
    assert "/concepts/agents.md" in run('rg --ignore-case "AGENTS" /concepts')
    assert "/quickstart.md" in run("rg -F 'Agent()' /")
    out = run("rg -w Agent /concepts")
    assert "/concepts/agents.md" in out and "/concepts/teams.md" not in out
    assert "/concepts/agents.md:3" in run("rg --type md Agent /concepts")
    assert "/concepts/agents.md:3" in run("rg --type=md Agent /concepts")
    assert "/concepts/agents.md:3" in run("rg --glob '*.md' Agent /concepts")
    assert "/concepts/agents.md-4-" in run("rg -C1 'has a model' /concepts")
    assert "/concepts/agents.md" in run("rg agents /concepts -i")


def test_rg_searches_page_and_directory_when_names_collide():
    assert run("rg -il 'overview|agents' /concepts").splitlines()[1:] == [
        "/concepts.md",
        "/concepts/agents.md",
        "/concepts/agents/tools.md",
        "/concepts/teams.md",
    ]


def test_rg_errors_are_readable():
    assert "invalid regex" in run("rg '(' /")
    assert "expects a number" in run("rg -C x foo /")
    assert "unsupported flag" in run("rg -Q foo /")
    assert "no such file or directory" in run("rg foo /nope")
    assert "longer than" in run("rg " + "a" * 300 + " /")
    assert "usage: rg" in run("rg -i")


def test_rg_catastrophic_regex_is_bounded():
    corpus = {"/big.md": ("a" * 5000 + "b\n") * 20}
    result: list[str] = []
    # Bounded join: without REGEX_MATCH_TIMEOUT this pattern backtracks for minutes, so fail fast instead of stalling.
    t = threading.Thread(target=lambda: result.append(run_command("rg '(a+)+$' /", corpus)), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "rg no longer bounded by REGEX_MATCH_TIMEOUT"
    assert "too expensive" in result[0]


def test_rg_command_budget_stops_between_files(monkeypatch):
    ticks = iter([0.0] * 8 + [10.0] * 100)
    monkeypatch.setattr(vfs, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    out = run_command("rg x /", {"/a.md": "x\n", "/b.md": "x\n"})
    assert out.splitlines()[0] == "[stopped after 2s: 1 matching lines in 1 files so far; narrow the path]"
    assert out.splitlines()[1] == "/a.md:1:x"
    assert "/b.md" not in out


def test_rg_budget_stop_before_the_first_hit_is_not_reported_as_no_matches(monkeypatch):
    ticks = iter([0.0] * 3 + [10.0] * 100)
    monkeypatch.setattr(vfs, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    out = run_command("rg x /", {"/a.md": "y\n", "/b.md": "x\n"})
    assert "no matches" not in out
    assert out == "[stopped after 2s: 0 matching lines in 0 files so far; narrow the path]"


def test_rg_stops_scanning_at_the_output_cap_and_says_so_first():
    corpus = {f"/p{i:03d}.md": "match " + "y" * 200 + "\n" for i in range(300)}
    out = run_command("rg match /", corpus)
    first, last = out.splitlines()[0], out.splitlines()[-1]
    assert first.startswith("[stopped at the output cap:") and "so far" in first
    assert "lines shown" in last and "tail -n" not in last and "/p299.md" not in out
    assert run_command("rg match /p001", corpus).splitlines()[0] == "[1 matching lines in 1 files]"


def test_rg_page_prefilter_keeps_per_line_semantics():
    corpus = {"/a.md": "import x\nAgent here\n", "/b.md": "  Agent\nimport y\n"}
    per_line = ["/a.md:1:import x", "/b.md:2:import y"]
    assert run_command("rg '^import' /", corpus).splitlines()[1:] == per_line
    assert run_command("rg '\\Aimport' /", corpus).splitlines()[1:] == per_line
    assert run_command("rg '(?<!\\s)Agent' /", corpus).splitlines()[1:] == ["/a.md:2:Agent here"]
    # a lookahead at the line end sees the newline in a whole-page search: per-line, it sees the end
    assert run_command("rg 'here(?!\\s)' /", corpus).splitlines()[1:] == ["/a.md:2:Agent here"]
    assert run_command("rg -w Agent /", corpus).splitlines()[1:] == ["/a.md:2:Agent here", "/b.md:1:  Agent"]


def test_cat_head_tail_wc_and_missing_files():
    assert "==> /quickstart.md <==" in run("cat /quickstart") and "from agno.agent" in run("cat /quickstart")
    out = run("head -n 1 /quickstart /nope /concepts/agents")
    assert "# Quickstart" in out and "no such file" in out and "# Agents" in out
    assert run("head -1 /concepts/agents").endswith("# Agents")
    assert run("head -n1 /concepts/agents").endswith("# Agents")
    assert run("tail -n 1 /concepts/agents").endswith("Use enable_agentic_memory=True to remember.")
    assert run("tail -n 0 /concepts/agents").endswith("<==\n")
    assert "expects a number" in run("head -n abc /quickstart")
    assert "non-negative" in run("head -n -3 /quickstart")
    assert run("wc -l /concepts/agents").split()[0] == "4"
    assert "no such file" in run("wc -l /nope")
    assert "==> /empty.md <==" in run("cat /empty")


def test_unicode_patterns_match_and_unbalanced_quotes_are_a_parse_error():
    assert "/i18n/unicode.md" in run('rg -l "日本語" /')
    assert "parse error" in run('rg "unbalanced /')


def test_unsupported_commands_pipes_and_empty_corpus():
    assert "unsupported command" in run("rm -rf /")
    assert "pipes" in run("cat /quickstart | head")
    assert run("") == USAGE
    assert "empty" in run_command("ls /", {})


def test_output_truncation():
    corpus = {f"/p{i}.md": "x" * 1000 + "\n" for i in range(60)}
    out = run_command("cat " + " ".join(f"/p{i}" for i in range(60)), corpus)
    assert len(out) <= MAX_OUTPUT + 200 and "truncated" in out


def test_page_read_truncates_on_a_line_and_says_where_to_resume():
    corpus = {"/big.md": "\n".join(f"line {i} " + "x" * 90 for i in range(600)) + "\n"}
    out = run_command("cat /big", corpus)
    lines = out.splitlines()
    assert lines[-1].startswith("... [output truncated:") and lines[-1].endswith("]")
    assert lines[-2].endswith("x" * 90)  # cut on a line boundary, never inside a line
    cut = re.search(r"(\d+) of (\d+) lines shown", lines[-1])
    assert cut is not None
    shown, total = map(int, cut.groups())
    assert total == 601 and shown == len(lines) - 1
    assert lines[-2] == f"line {shown - 2} " + "x" * 90  # output line 1 is the ==> header
    assert lines[-1].endswith(f"tail -n +{shown} /big.md]")
    resumed = run_command(f"tail -n +{shown} /big", corpus).splitlines()
    assert resumed[1] == f"line {shown - 1} " + "x" * 90


@pytest.mark.parametrize(
    ("command", "first_source_line"),
    [
        ("cat /big", 1),
        ("head -n 1000 /big", 1),
        ("tail -n +201 /big", 201),
        ("tail -n 800 /big", 201),
    ],
)
def test_single_page_read_continuation_uses_an_absolute_source_line(command, first_source_line):
    corpus = {"/big.md": "\n".join(f"line {i} " + "x" * 190 for i in range(1000)) + "\n"}
    footer = run_command(command, corpus).splitlines()[-1]
    cut = re.search(r"(\d+) of \d+ lines shown .* tail -n \+(\d+) /big\.md", footer)
    assert cut is not None
    shown, next_source_line = map(int, cut.groups())
    assert next_source_line == first_source_line + shown - 1


def test_following_page_continuations_advances_instead_of_looping():
    corpus = {"/big.md": "\n".join(f"line {i} " + "x" * 190 for i in range(1000)) + "\n"}
    command = "cat /big"
    cursors: list[int] = []
    for _ in range(10):
        output = run_command(command, corpus)
        if "output truncated" not in output:
            break
        match = re.search(r"tail -n \+(\d+) (/[^\]]+)]$", output)
        assert match is not None
        cursor, path = int(match.group(1)), match.group(2)
        assert not cursors or cursor > cursors[-1]
        cursors.append(cursor)
        command = f"tail -n +{cursor} {path}"
    else:
        pytest.fail("following the emitted continuation did not reach the end of the page")
    assert "line 999 " in output


def test_multi_file_truncation_does_not_emit_a_misleading_page_continuation():
    corpus = {
        "/a.md": "\n".join(f"a{i} " + "x" * 190 for i in range(100)) + "\n",
        "/b.md": "\n".join(f"b{i} " + "x" * 190 for i in range(400)) + "\n",
    }
    footer = run_command("cat /a /b", corpus).splitlines()[-1]
    assert "output truncated" in footer
    assert "tail -n" not in footer


@pytest.mark.parametrize("cmd", ["ls --bogus", "tree -Z /", "wc -q /quickstart", "cat -Z /quickstart"])
def test_unknown_flags_are_reported(cmd):
    assert "unsupported flag" in run(cmd)


def test_tail_from_line_n_like_gnu():
    lines = CORPUS["/concepts/agents.md"].splitlines()
    assert run("tail -n +3 /concepts/agents").split("\n", 1)[1] == "\n".join(lines[2:])
    assert run("tail -n+2 /concepts/agents").split("\n", 1)[1] == "\n".join(lines[1:])
    assert run("tail -n 2 /concepts/agents").split("\n", 1)[1] == "\n".join(lines[-2:])

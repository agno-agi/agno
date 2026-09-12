"""Bounded read-only command grammar over published page mappings; never executes a shell."""

from __future__ import annotations

import fnmatch
import shlex
import time
from collections.abc import Callable, Mapping

import regex

MAX_OUTPUT = 30_000
MAX_PATTERN_CHARS = 256
REGEX_MATCH_TIMEOUT = 0.05  # seconds, per line
REGEX_COMMAND_BUDGET = 2.0  # seconds, per command

USAGE = """\
Supported commands (read-only, no pipes, stateless):
  ls [dir|file ...]                     list a directory (or show that a file exists)
  tree [dir] [-L depth]                 directory tree
  find [dir] [-name <glob>]             list files, optionally filtered by name glob
  rg [-i] [-l] [-c] [-w] [-F] [-C n] [-A n] [-B n] <pattern> [path ...]
                                        regex search (grep is an alias; -r is accepted)
  cat <file> ...                        full file contents
  head [-n N] <file> ...                first N lines (default 10)
  tail [-n N] <file> ...                last N lines (default 10)
  wc [-l] <file> ...                    line (and word/char) counts
Paths may omit the .md extension: `cat /concepts/agents` works.\
"""


class CommandError(Exception):
    """User-facing command error; its message is returned as the tool output."""


class _PageRead(str):
    """Rendered single-page output with the source line represented by its first body line."""

    path: str
    first_source_line: int

    def __new__(cls, value: str, path: str, first_source_line: int):
        result = super().__new__(cls, value)
        result.path = path
        result.first_source_line = first_source_line
        return result


# ---------------------------------------------------------------------------
# Path helpers. Files is a dict of '/section/page.md' -> content.
# ---------------------------------------------------------------------------


def _norm(path: str) -> str:
    return "/" + path.strip().strip("/")


def _canonical(path: str, files: Mapping[str, str]) -> str:
    from agno.fs.errors import InvalidPathError

    clean = _norm(path)
    normalize = getattr(files, "canonical_prefix", None)
    try:
        return normalize(clean) if callable(normalize) else clean
    except (ValueError, InvalidPathError):
        raise CommandError(
            f"{path}: invalid page path. Use an absolute page path without dot segments, query or fragment."
        ) from None


def _file_candidates(clean: str, *, index: bool = False) -> tuple[str, ...]:
    if clean == "/":
        return ("/index.md",) if index else ()
    if clean.endswith(".md"):
        return (clean,)
    candidates = (clean, f"{clean}.md")
    return (*candidates, f"{clean}/index.md") if index else candidates


def _resolve_file(path: str, files: Mapping[str, str]) -> str:
    clean = _canonical(path, files)
    for candidate in _file_candidates(clean, index=True):
        if candidate in files:
            return candidate
    raise CommandError(f"{path}: no such file. Use ls/tree to explore, or rg to search.")


def _files_under(directory: str, files: Mapping[str, str]) -> list[str]:
    clean = _canonical(directory, files)
    if clean.endswith(".md"):
        return []
    prefix = "/" if clean == "/" else f"{clean}/"
    paths_under = getattr(files, "paths_under", None)
    if callable(paths_under):
        return sorted(paths_under(prefix))
    return sorted(f for f in files if f.startswith(prefix))


def _is_dir(path: str, files: Mapping[str, str]) -> bool:
    clean = _norm(path)
    return clean == "/" or bool(_files_under(clean, files))


def _dir_entries(directory: str, files: Mapping[str, str]) -> list[str]:
    clean = _canonical(directory, files)
    prefix = "/" if clean == "/" else f"{clean}/"
    entries = set()
    for path in _files_under(directory, files):
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix) :]
        first = rest.split("/", 1)[0]
        entries.add(first + "/" if "/" in rest else first)
    return sorted(entries)


def _int_value(flag: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise CommandError(f"{flag} expects a number, got {raw!r}") from None
    if value < 0:
        raise CommandError(f"{flag} expects a non-negative number")
    return value


def _int_flag(args: list[str], *flags: str, default: int) -> tuple[int, list[str]]:
    """Extract one integer-valued flag (e.g. -n 20, -n20, or -20) from args."""
    value, rest, i = default, [], 0
    while i < len(args):
        arg = args[i]
        if arg in flags and i + 1 < len(args):
            value, i = _int_value(arg, args[i + 1]), i + 1
        elif any(arg.startswith(f) and len(arg) > len(f) for f in flags) and arg[1:2] != "-":
            flag = next(f for f in flags if arg.startswith(f))
            value = _int_value(flag, arg[len(flag) :].lstrip("=").lstrip("+"))
        elif regex.fullmatch(r"-\d+", arg):
            value = int(arg[1:])
        else:
            rest.append(arg)
        i += 1
    return value, rest


def _strip_flags(args: list[str], accepted: set[str]) -> list[str]:
    """Drop cosmetic flags an LLM tends to add (ls -la, tree -a, cat -n)."""
    positional = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            if arg.lstrip("-") and set(arg.lstrip("-")) <= accepted:
                continue
            raise CommandError(f"unsupported flag {arg}\n\n{USAGE}")
        positional.append(arg)
    return positional


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _has_file(path: str, files: Mapping[str, str]) -> bool:
    metadata_contains = getattr(files, "_metadata_contains", None)
    return metadata_contains(path) if callable(metadata_contains) else path in files


def _cmd_ls(args: list[str], files: Mapping[str, str]) -> str:
    targets = _strip_flags(args, {"l", "a", "h", "1", "R"}) or ["/"]
    blocks = []
    for target in targets:
        clean = _norm(target)
        lines: list[str] = []
        if _is_dir(clean, files):
            lines.extend(_dir_entries(clean, files))
        for candidate in _file_candidates(clean):
            if _has_file(candidate, files) and candidate not in lines:
                lines.append(candidate)
        if not lines:
            raise CommandError(f"{target}: no such file or directory")
        header = f"{clean}:\n" if len(targets) > 1 else ""
        blocks.append(header + "\n".join(lines))
    return "\n\n".join(blocks)


def _cmd_tree(args: list[str], files: Mapping[str, str]) -> str:
    depth, rest = _int_flag(args, "-L", default=99)
    rest = _strip_flags(rest, {"a", "d"})
    root = _norm(rest[0]) if rest else "/"
    paths = _files_under(root, files)
    if not paths:
        for candidate in _file_candidates(root):
            if _has_file(candidate, files):
                return candidate
        raise CommandError(f"{root}: no such directory")
    lines = [root]
    seen_dirs = set()
    canonical_root = _canonical(root, files)
    for path in paths:
        relative = path[1:] if canonical_root == "/" else path[len(canonical_root) + 1 :]
        parts = relative.split("/")
        for level, part in enumerate(parts):
            if level + 1 > depth:
                break
            is_file = level == len(parts) - 1
            node = "/".join(parts[: level + 1])
            if not is_file:
                if node in seen_dirs:
                    continue
                seen_dirs.add(node)
            lines.append("  " * (level + 1) + part + ("" if is_file else "/"))
    return "\n".join(lines)


def _cmd_find(args: list[str], files: Mapping[str, str]) -> str:
    root, pattern, ignore_case = "/", None, False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-name", "-iname"):
            if i + 1 >= len(args):
                raise CommandError(f"find: {arg} needs a glob, e.g. find / -name '*agent*'")
            pattern, ignore_case = args[i + 1], arg == "-iname"
            i += 1
        elif arg in ("-type", "-maxdepth", "-path"):
            i += 1  # accepted and ignored: everything here is a file
        elif arg.startswith("-"):
            raise CommandError(f"find: unsupported option {arg}\n\n{USAGE}")
        else:
            root = arg
        i += 1
    candidates = _files_under(root, files)
    if not candidates:
        raise CommandError(f"find: {root}: no such directory")
    if pattern is None:
        return "\n".join(candidates)
    matches = [
        p
        for p in candidates
        if fnmatch.fnmatch(
            p.rsplit("/", 1)[-1].lower() if ignore_case else p.rsplit("/", 1)[-1],
            pattern.lower() if ignore_case else pattern,
        )
    ]
    return "\n".join(matches) if matches else f"find: no files matching {pattern!r} under {_norm(root)}"


def _read_files(paths: list[str], files: Mapping[str, str], render: Callable[[str, str], tuple[str, int]]) -> str:
    """Apply `render` per file; its integer is the first rendered source line (one-based)."""
    parts = []
    single_page: tuple[str, int] | None = None
    for p in paths:
        try:
            resolved = _resolve_file(p, files)
        except CommandError as exc:
            parts.append(str(exc))
            continue
        rendered, first_source_line = render(resolved, files[resolved])
        parts.append(f"==> {resolved} <==\n" + rendered)
        if len(paths) == 1:
            single_page = resolved, first_source_line
    output = "\n\n".join(parts)
    return _PageRead(output, *single_page) if single_page is not None else output


def _cmd_cat(args: list[str], files: Mapping[str, str]) -> str:
    paths = _strip_flags(args, {"n", "s", "b"})
    if not paths:
        raise CommandError("usage: cat <file> ...")
    return _read_files(paths, files, lambda _p, content: (content, 1))


def _cmd_head(args: list[str], files: Mapping[str, str]) -> str:
    n, paths = _int_flag(args, "-n", default=10)
    if not paths:
        raise CommandError("usage: head [-n N] <file> ...")
    return _read_files(paths, files, lambda _p, content: ("\n".join(content.splitlines()[:n]), 1))


def _cmd_tail(args: list[str], files: Mapping[str, str]) -> str:
    # `tail -n +N` (or -n+N) means "from line N to the end", as in GNU tail.
    from_start = any(
        (arg == "-n" and i + 1 < len(args) and args[i + 1].startswith("+")) or arg.startswith("-n+")
        for i, arg in enumerate(args)
    )
    n, paths = _int_flag(args, "-n", default=10)
    if not paths:
        raise CommandError("usage: tail [-n N | -n +N] <file> ...")

    def render(_path: str, content: str) -> tuple[str, int]:
        lines = content.splitlines()
        if from_start:
            first_source_line = max(n, 1)
            return "\n".join(lines[max(n - 1, 0) :]), first_source_line
        first_source_line = max(len(lines) - n + 1, 1)
        return ("\n".join(lines[-n:]) if n else ""), first_source_line

    return _read_files(paths, files, render)


def _cmd_wc(args: list[str], files: Mapping[str, str]) -> str:
    flags = {a for a in args if a.startswith("-")}
    paths = [a for a in args if not a.startswith("-")]
    unknown = {f for f in flags if f not in ("-l", "-w", "-c", "-m")}
    if unknown:
        raise CommandError(f"wc: unsupported flag {' '.join(sorted(unknown))} (supported: -l, -w, -c)")
    if not paths:
        raise CommandError("usage: wc [-l] <file> ...")
    lines = []
    for p in paths:
        try:
            resolved = _resolve_file(p, files)
        except CommandError as exc:
            lines.append(str(exc))
            continue
        content = files[resolved]
        counts = {"-l": len(content.splitlines()), "-w": len(content.split()), "-c": len(content)}
        shown = [counts[f] for f in ("-l", "-w", "-c") if f in flags or ("-m" in flags and f == "-c")] or list(
            counts.values()
        )
        lines.append(" ".join(f"{c:>7}" for c in shown) + f" {resolved}")
    return "\n".join(lines)


RG_LONG_FLAGS = {
    "--ignore-case": "i",
    "--files-with-matches": "l",
    "--count": "c",
    "--word-regexp": "w",
    "--fixed-strings": "F",
    "--recursive": "r",
    "--line-number": "n",
    "--no-heading": "",
    "--color": "",
}


def _rg_targets(roots: list[str], files: Mapping[str, str]) -> list[str]:
    targets: list[str] = []
    for root in roots:
        clean = _canonical(root, files)
        found = False
        for candidate in _file_candidates(clean):
            if candidate in files:
                targets.append(candidate)
                found = True
        under = _files_under(clean, files)
        if under:
            targets.extend(under)
            found = True
        if not found:
            raise CommandError(f"rg: {root}: no such file or directory")
    if not targets:
        raise CommandError(f"rg: no files under {', '.join(roots)}")
    return targets


def _cmd_rg(args: list[str], files: Mapping[str, str]) -> str:
    limits = getattr(files, "filesystem", None)
    max_output = getattr(limits, "max_output_chars", MAX_OUTPUT)
    max_pattern = getattr(limits, "max_pattern_chars", MAX_PATTERN_CHARS)
    match_timeout = getattr(limits, "regex_match_timeout", REGEX_MATCH_TIMEOUT)
    command_budget = getattr(limits, "regex_command_seconds", REGEX_COMMAND_BUDGET)
    deadline = time.monotonic() + command_budget
    flags: set[str] = set()
    before = after = 0
    positional: list[str] = []
    pattern_from_e: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            positional.extend(args[i + 1 :])
            break
        if arg in ("-e", "--regexp") and i + 1 < len(args):
            pattern_from_e, i = args[i + 1], i + 1
        elif arg in ("-C", "-A", "-B") and i + 1 < len(args):
            n = _int_value(arg, args[i + 1])
            before, after = (n, n) if arg == "-C" else (n, after) if arg == "-B" else (before, n)
            i += 1
        elif regex.fullmatch(r"-[CAB]\d+", arg):
            n = int(arg[2:])
            before, after = (n, n) if arg[1] == "C" else (n, after) if arg[1] == "B" else (before, n)
        elif arg.startswith("--"):
            if arg.split("=", 1)[0] in RG_LONG_FLAGS:
                short = RG_LONG_FLAGS[arg.split("=", 1)[0]]
                if short:
                    flags.add(short)
            elif arg.startswith(("--type", "--glob", "--max-count")):
                if "=" not in arg:
                    i += 1
            else:
                raise CommandError(
                    f"rg: unsupported option {arg} (supported: -i -l -c -w -F -n -r -C/-A/-B n, -e PATTERN)"
                )
        elif arg.startswith("-") and len(arg) > 1:
            letters = set(arg[1:])
            unknown = letters - {"i", "l", "c", "w", "F", "n", "r", "R", "H", "s"}
            if unknown:
                raise CommandError(
                    f"rg: unsupported flag -{''.join(sorted(unknown))} "
                    "(supported: -i -l -c -w -F -n -r -C/-A/-B n, -e PATTERN)"
                )
            flags |= letters
        else:
            positional.append(arg)
        i += 1
    if pattern_from_e is not None:
        positional.insert(0, pattern_from_e)
    if not positional:
        raise CommandError("usage: rg [-i] [-l] [-c] [-C n] <pattern> [path ...]")
    pattern, roots = positional[0], positional[1:] or ["/"]
    if len(pattern) > max_pattern:
        raise CommandError(f"rg: pattern longer than {max_pattern} characters")
    if "F" in flags:
        pattern = regex.escape(pattern)
    if "w" in flags:
        pattern = rf"\b(?:{pattern})\b"
    try:
        rx = regex.compile(pattern, regex.IGNORECASE if "i" in flags else 0)
        # One MULTILINE search per page decides whether the per-line loop runs at all (the loop
        # keeps the exact per-line semantics). Anchors, lookarounds and inline flags that see
        # across line boundaries (\A, \Z, \z, \G, (?<...), (?!...), (?=...), (?-m)) would reject
        # pages the per-line search accepts, so those patterns scan every line; only the plain
        # non-capturing group (?:...) keeps the prefilter.
        rx_page = (
            None if regex.search(r"\\[AZzG]|\(\?[^:]", pattern) else regex.compile(pattern, rx.flags | regex.MULTILINE)
        )
    except (regex.error, RecursionError, OverflowError, ValueError) as exc:
        raise CommandError(f"rg: invalid regex {positional[0]!r}: {exc}") from None

    # Preserve richer regex/context/count presentation in this adapter. Simple
    # literal matching can use Knowledge's bounded snapshot without loading pages.
    from agno.knowledge.page.filesystem import PageCorpus

    literal_pattern = "F" in flags or not regex.search(r"[.^$*+?{}\[\]\\|()]", positional[0])
    if (
        isinstance(files, PageCorpus)
        and literal_pattern
        and "w" not in flags
        and not before
        and not after
        and len(roots) == 1
    ):
        clean = _canonical(roots[0], files)
        exact = None
        if clean == "/":
            prefix = "/"
        elif clean.endswith(".md"):
            # An explicit file never expands into a same-name directory.
            prefix = None
        else:
            exact = next((candidate for candidate in _file_candidates(clean) if candidate in files), None)
            prefix = clean + "/" if files.has_directory(clean + "/") else None
            if prefix is None and exact is None:
                raise CommandError(f"rg: {roots[0]}: no such file or directory")
        if prefix is not None:
            result = files.grep(positional[0], prefix=prefix, ignore_case="i" in flags)
            matches = [(m.path, m.line_number, m.text) for m in result.matches if m.path.startswith(prefix)]
            complete, stop_reason = result.complete, result.stop_reason
            if exact is not None:
                # Keep the exact page outside the directory prefix so similarly named
                # siblings cannot consume its match budget. Only this page is loaded.
                exact_matches = []
                for number, line in enumerate(files[exact].splitlines(), 1):
                    if time.monotonic() > deadline:
                        complete, stop_reason = False, "deadline"
                        break
                    if rx.search(line, timeout=min(match_timeout, max(0.001, deadline - time.monotonic()))):
                        exact_matches.append((exact, number, line))
                        if len(exact_matches) >= 100:
                            complete, stop_reason = False, "limit"
                            break
                matches = sorted([*exact_matches, *matches])
                if len(matches) > 100:
                    matches = matches[:100]
                    complete, stop_reason = False, "limit"
            if not matches and complete:
                return f"rg: no matches for {positional[0]!r}"
            count = len({path for path, _, _ in matches})
            summary = f"[{len(matches)} matching lines in {count} files]"
            if not complete:
                summary = (
                    f"[stopped at {stop_reason}: {len(matches)} matching lines "
                    f"in {count} files so far; narrow the path]"
                )
            if "l" in flags:
                entries = list(dict.fromkeys(path for path, _, _ in matches))
            elif "c" in flags:
                from collections import Counter

                entries = [f"{path}:{count}" for path, count in Counter(path for path, _, _ in matches).items()]
            else:
                entries = [f"{path}:{number}:{text}" for path, number, text in matches]
            return "\n".join([summary, *entries])

    targets = _rg_targets(roots, files)
    files_only, count_only = "l" in flags, "c" in flags
    out: list[str] = []
    out_chars = matched_files = total_hits = 0
    truncated_by_time = truncated_by_size = False
    for path in sorted(set(targets)):
        if time.monotonic() > deadline:
            truncated_by_time = True
            break
        if out_chars > max_output:
            truncated_by_size = True
            break
        content = files[path]
        try:
            if rx_page is not None and not rx_page.search(
                content, timeout=min(match_timeout, max(0.001, deadline - time.monotonic()))
            ):
                continue
            lines = content.splitlines()
            hits = []
            for idx, line in enumerate(lines):
                if time.monotonic() > deadline:
                    truncated_by_time = True
                    break
                if rx.search(line, timeout=min(match_timeout, max(0.001, deadline - time.monotonic()))):
                    hits.append(idx)
        except TimeoutError:
            raise CommandError(
                f"rg: pattern {positional[0]!r} is too expensive to evaluate; "
                "simplify the regex or use -F for a literal"
            ) from None
        if not hits:
            continue
        matched_files += 1
        total_hits += len(hits)
        if files_only:
            entries = [path]
        elif count_only:
            entries = [f"{path}:{len(hits)}"]
        else:
            entries, shown = [], set()
            for hit in hits:
                for j in range(max(0, hit - before), min(len(lines), hit + after + 1)):
                    if time.monotonic() > deadline:
                        truncated_by_time = True
                        break
                    if j not in shown:
                        shown.add(j)
                        sep = ":" if j == hit else "-"
                        entries.append(f"{path}{sep}{j + 1}{sep}{lines[j]}")
            if before or after:
                entries.append("--")
        out.extend(entries)
        out_chars += sum(len(entry) + 1 for entry in entries)
        if truncated_by_time:
            break
    if not out and not truncated_by_time and not truncated_by_size:
        return f"rg: no matches for {positional[0]!r}"
    # The summary goes first so the output cap can never cut it off.
    summary = f"[{total_hits} matching lines in {matched_files} files]"
    if truncated_by_time:
        summary = (
            f"[stopped after {command_budget:.0f}s: {total_hits} matching lines in "
            f"{matched_files} files so far; narrow the path]"
        )
    elif truncated_by_size:
        summary = (
            f"[stopped at the output cap: {total_hits} matching lines in {matched_files} files so far; "
            "narrow the path or use rg -l]"
        )
    return "\n".join([summary, *out])


_COMMANDS: dict[str, Callable[[list[str], Mapping[str, str]], str]] = {
    "ls": _cmd_ls,
    "tree": _cmd_tree,
    "find": _cmd_find,
    "cat": _cmd_cat,
    "head": _cmd_head,
    "tail": _cmd_tail,
    "wc": _cmd_wc,
    "rg": _cmd_rg,
    "grep": _cmd_rg,
}


def _execute_command(command: str, files: Mapping[str, str]) -> str:
    """Parse and execute one emulated command against the corpus. Never raises."""
    if not files:
        return "The page index is empty."
    try:
        argv = shlex.split(command or "")
    except ValueError as exc:
        return f"parse error: {exc}\n\n{USAGE}"
    if not argv:
        return USAGE
    if any(token in ("|", ">", ">>", "&&", ";", "<") for token in argv):
        return f"pipes and command chaining are not supported; run one command per call.\n\n{USAGE}"
    handler = _COMMANDS.get(argv[0])
    if handler is None:
        return f"unsupported command: {argv[0]!r}\n\n{USAGE}"
    try:
        output = handler(argv[1:], files)
    except CommandError as exc:
        return str(exc)
    except (ValueError, RecursionError, OverflowError, MemoryError, TimeoutError) as exc:
        return f"{argv[0]}: could not run this command ({exc.__class__.__name__}: {exc})\n\n{USAGE}"
    return output if output else "(no output)"


def run_command(command: str, files: Mapping[str, str]) -> str:
    """Apply the same output bound to successful commands and readable errors."""
    output = _execute_command(command, files)
    max_output = getattr(getattr(files, "filesystem", None), "max_output_chars", MAX_OUTPUT)
    if len(output) > max_output:
        # Cut on a line boundary and say where it stopped. Only a single resolved page read
        # carries enough information to give an exact source-file continuation command.
        page_read = output if isinstance(output, _PageRead) else None
        body = output.rstrip("\n")
        kept = body[:max_output].rsplit("\n", 1)[0]
        shown, total = kept.count("\n") + 1, body.count("\n") + 1
        advice = "narrow the path or use rg -l"
        if page_read is not None:
            # `shown` includes the `==> path <==` header, hence `shown - 1` source lines.
            next_source_line = page_read.first_source_line + shown - 1
            advice += f", or continue with tail -n +{next_source_line} {shlex.quote(page_read.path)}"
        output = f"{kept}\n... [output truncated: {shown} of {total} lines shown — {advice}]"
    return str(output) if output else "(no output)"

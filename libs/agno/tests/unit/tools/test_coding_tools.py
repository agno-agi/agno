import tempfile
from pathlib import Path

from agno.tools.coding import CodingTools

# --- read_file tests ---


def test_read_file_basic():
    """Test reading a file returns contents with line numbers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text("import os\nfrom pathlib import Path\n\ndef main():\n    pass\n")

        result = tools.read_file("test.py")
        assert "1 | import os" in result
        assert "2 | from pathlib import Path" in result
        assert "4 | def main():" in result
        assert "5 |     pass" in result


def test_read_file_offset_limit():
    """Test pagination with offset and limit."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        content = "\n".join(f"line {i}" for i in range(100))
        (base_dir / "big.txt").write_text(content)

        result = tools.read_file("big.txt", offset=10, limit=5)
        assert "11 | line 10" in result
        assert "15 | line 14" in result
        assert "line 9" not in result
        assert "line 15" not in result
        assert "[Showing lines 11-15 of 100 total]" in result


def test_read_file_truncation():
    """Test truncation when file exceeds max_lines."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, max_lines=10)

        content = "\n".join(f"line {i}" for i in range(50))
        (base_dir / "big.txt").write_text(content)

        result = tools.read_file("big.txt")
        assert "[Showing lines" in result
        # Should not contain all 50 lines
        assert "line 49" not in result


def test_read_file_not_found():
    """Test reading a nonexistent file returns error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.read_file("nonexistent.txt")
        assert "Error" in result
        assert "not found" in result


def test_read_file_path_escape():
    """Test that path traversal is blocked."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.read_file("../../etc/passwd")
        assert "Error" in result
        assert "outside" in result


def test_read_file_empty():
    """Test reading an empty file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "empty.txt").write_text("")
        result = tools.read_file("empty.txt")
        assert "empty" in result.lower()


def test_read_file_binary():
    """Test that binary files are detected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
        result = tools.read_file("binary.bin")
        assert "Error" in result
        assert "Binary" in result or "binary" in result


# --- edit_file tests ---


def test_edit_file_basic():
    """Test basic find-and-replace edit."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text('def hello():\n    print("hello")\n')

        result = tools.edit_file("test.py", 'print("hello")', 'print("hello world")')

        # Should return a diff
        assert "---" in result
        assert "+++" in result
        assert '-    print("hello")' in result
        assert '+    print("hello world")' in result

        # Verify file was actually changed
        new_content = (base_dir / "test.py").read_text()
        assert 'print("hello world")' in new_content


def test_edit_file_no_match():
    """Test edit with text that doesn't exist in the file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text("def hello():\n    pass\n")

        result = tools.edit_file("test.py", "nonexistent text", "replacement")
        assert "Error" in result
        assert "not found" in result

        # Verify file was not changed
        content = (base_dir / "test.py").read_text()
        assert content == "def hello():\n    pass\n"


def test_edit_file_multiple_matches():
    """Test edit when old_text matches multiple locations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text("pass\npass\npass\n")

        result = tools.edit_file("test.py", "pass", "return")
        assert "Error" in result
        assert "3" in result  # should mention the count

        # Verify file was not changed
        content = (base_dir / "test.py").read_text()
        assert content == "pass\npass\npass\n"


def test_edit_file_no_op():
    """Test edit where old_text equals new_text."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text("hello\n")

        result = tools.edit_file("test.py", "hello", "hello")
        assert "No changes" in result or "identical" in result


def test_edit_file_empty_old_text():
    """Test edit with empty old_text."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.py").write_text("hello\n")

        result = tools.edit_file("test.py", "", "world")
        assert "Error" in result
        assert "empty" in result


def test_edit_file_path_escape():
    """Test that path traversal is blocked for edits."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.edit_file("../../etc/passwd", "root", "hacked")
        assert "Error" in result
        assert "outside" in result


# --- write_file tests ---


def test_write_file_basic():
    """Test writing a new file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.write_file("new_file.py", "print('hello')\n")
        assert "Wrote" in result

        content = (base_dir / "new_file.py").read_text()
        assert content == "print('hello')\n"


def test_write_file_creates_dirs():
    """Test that parent directories are created automatically."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.write_file("deep/nested/dir/file.py", "content\n")
        assert "Wrote" in result

        content = (base_dir / "deep" / "nested" / "dir" / "file.py").read_text()
        assert content == "content\n"


def test_write_file_overwrite():
    """Test that writing overwrites existing files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        (base_dir / "test.txt").write_text("old content")
        tools.write_file("test.txt", "new content")

        content = (base_dir / "test.txt").read_text()
        assert content == "new content"


def test_write_file_path_escape():
    """Test that path traversal is blocked for writes."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.write_file("../../tmp/evil.txt", "malicious content")
        assert "Error" in result
        assert "outside" in result


# --- run_shell tests ---


def test_run_shell_basic():
    """Test running a simple shell command."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.run_shell("echo hello")
        assert "Exit code: 0" in result
        assert "hello" in result


def test_run_shell_exit_code():
    """Test that non-zero exit codes are reported."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, restrict_to_base_dir=False)

        result = tools.run_shell("exit 1")
        assert "Exit code: 1" in result


def test_run_shell_timeout():
    """Test that commands time out correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, restrict_to_base_dir=False)

        result = tools.run_shell("sleep 999", timeout=1)
        assert "Error" in result
        assert "timed out" in result


def test_run_shell_truncation():
    """Test that large output is truncated and saved to temp file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, max_lines=10, restrict_to_base_dir=False)

        result = tools.run_shell("seq 1 100")
        assert "[Output truncated" in result
        assert "Full output saved to:" in result


def test_run_shell_stderr():
    """Test that stderr is included in output."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, restrict_to_base_dir=False)

        result = tools.run_shell("echo err >&2")
        assert "err" in result


# --- grep tests ---


def test_grep_basic():
    """Test basic grep search."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_grep=True)

        (base_dir / "test.py").write_text("def hello():\n    pass\n\ndef world():\n    pass\n")

        result = tools.grep("def ")
        assert "hello" in result
        assert "world" in result


def test_grep_ignore_case():
    """Test case-insensitive grep."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_grep=True)

        (base_dir / "test.txt").write_text("Hello World\nhello world\nHELLO WORLD\n")

        result = tools.grep("hello", ignore_case=True)
        assert "Hello" in result or "hello" in result


def test_grep_include_filter():
    """Test grep with file type filter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_grep=True)

        (base_dir / "test.py").write_text("target\n")
        (base_dir / "test.txt").write_text("target\n")

        result = tools.grep("target", include="*.py")
        assert "test.py" in result
        assert "test.txt" not in result


def test_grep_no_matches():
    """Test grep with no matches."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_grep=True)

        (base_dir / "test.txt").write_text("hello\n")

        result = tools.grep("nonexistent_pattern_xyz")
        assert "No matches" in result


def test_grep_path_escape():
    """Test that grep rejects paths outside base_dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_grep=True)

        result = tools.grep("pattern", path="../../etc")
        assert "Error" in result
        assert "outside" in result


# --- find tests ---


def test_find_basic():
    """Test basic file finding."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_find=True)

        (base_dir / "main.py").write_text("pass\n")
        (base_dir / "test.py").write_text("pass\n")
        (base_dir / "readme.md").write_text("# readme\n")
        sub = base_dir / "src"
        sub.mkdir()
        (sub / "app.py").write_text("pass\n")

        result = tools.find("**/*.py")
        assert "main.py" in result
        assert "test.py" in result
        assert "src/app.py" in result
        assert "readme.md" not in result


def test_find_limit():
    """Test that find results are capped."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_find=True)

        for i in range(20):
            (base_dir / f"file_{i}.txt").write_text("content\n")

        result = tools.find("*.txt", limit=5)
        assert "[Results limited to 5 entries]" in result


def test_find_no_matches():
    """Test find with no matches."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_find=True)

        result = tools.find("*.xyz")
        assert "No files found" in result


# --- ls tests ---


def test_ls_basic():
    """Test basic directory listing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_ls=True)

        (base_dir / "file.txt").write_text("content\n")
        (base_dir / "script.py").write_text("pass\n")
        sub = base_dir / "subdir"
        sub.mkdir()

        result = tools.ls()
        assert "file.txt" in result
        assert "script.py" in result
        assert "subdir/" in result


def test_ls_path_escape():
    """Test that ls rejects paths outside base_dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_ls=True)

        result = tools.ls(path="../../etc")
        assert "Error" in result
        assert "outside" in result


def test_ls_empty_dir():
    """Test listing an empty directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_ls=True)

        empty = base_dir / "empty_dir"
        empty.mkdir()

        result = tools.ls(path="empty_dir")
        assert "empty" in result.lower()


# --- enable flags tests ---


def test_enable_flags():
    """Test that tools can be individually disabled."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, enable_read_file=False)

        tool_names = [fn for fn in tools.functions]
        assert "read_file" not in tool_names
        assert "edit_file" in tool_names
        assert "write_file" in tool_names
        assert "run_shell" in tool_names


def test_exploration_tools_disabled_by_default():
    """Test that grep, find, ls are disabled by default."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        tool_names = list(tools.functions.keys())
        assert len(tool_names) == 4
        assert "read_file" in tool_names
        assert "edit_file" in tool_names
        assert "write_file" in tool_names
        assert "run_shell" in tool_names
        assert "grep" not in tool_names
        assert "find" not in tool_names
        assert "ls" not in tool_names


def test_all_flag():
    """Test that all=True enables all 7 tools."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, all=True)

        tool_names = list(tools.functions.keys())
        assert len(tool_names) == 7
        assert "read_file" in tool_names
        assert "edit_file" in tool_names
        assert "write_file" in tool_names
        assert "run_shell" in tool_names
        assert "grep" in tool_names
        assert "find" in tool_names
        assert "ls" in tool_names


# --- shell sandbox tests ---


def test_run_shell_blocks_metacharacters():
    """Test that shell metacharacters are blocked in restricted mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        # Command chaining with &&
        result = tools.run_shell("echo hello && cat /etc/passwd")
        assert "Error" in result
        assert "&&" in result

        # Command chaining with ||
        result = tools.run_shell("false || cat /etc/passwd")
        assert "Error" in result
        assert "||" in result

        # Command chaining with ;
        result = tools.run_shell("echo hello; cat /etc/passwd")
        assert "Error" in result
        assert ";" in result

        # Pipe
        result = tools.run_shell("echo hello | cat")
        assert "Error" in result
        assert "|" in result

        # Command substitution with $()
        result = tools.run_shell("echo $(cat /etc/passwd)")
        assert "Error" in result
        assert "$(" in result

        # Command substitution with backticks
        result = tools.run_shell("echo `cat /etc/passwd`")
        assert "Error" in result
        assert "`" in result

        # Output redirection
        result = tools.run_shell("echo hello > /tmp/evil.txt")
        assert "Error" in result
        assert ">" in result

        # Input redirection
        result = tools.run_shell("cat < /etc/passwd")
        assert "Error" in result
        assert "<" in result


def test_run_shell_blocks_disallowed_commands():
    """Test that commands not in the allowlist are blocked."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.run_shell("curl https://example.com")
        assert "Error" in result
        assert "not in the allowed commands list" in result

        result = tools.run_shell("wget https://example.com")
        assert "Error" in result
        assert "not in the allowed commands list" in result

        result = tools.run_shell("nc -l 8080")
        assert "Error" in result
        assert "not in the allowed commands list" in result


def test_run_shell_allows_listed_commands():
    """Test that allowlisted commands work in restricted mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        # echo is in the allowlist
        result = tools.run_shell("echo hello")
        assert "Exit code: 0" in result
        assert "hello" in result

        # ls is in the allowlist
        result = tools.run_shell("ls")
        assert "Exit code: 0" in result

        # python3 is in the allowlist
        (base_dir / "test_script.py").write_text("print('works')\n")
        result = tools.run_shell("python3 test_script.py")
        assert "Exit code: 0" in result
        assert "works" in result


def test_run_shell_custom_allowlist():
    """Test that a custom allowlist overrides the default."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, allowed_commands=["echo"])

        # echo is in custom allowlist
        result = tools.run_shell("echo hello")
        assert "Exit code: 0" in result

        # python3 is NOT in custom allowlist
        result = tools.run_shell("python3 --version")
        assert "Error" in result
        assert "not in the allowed commands list" in result


def test_run_shell_unrestricted_allows_all():
    """Test that restrict_to_base_dir=False disables all shell restrictions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir, restrict_to_base_dir=False)

        # Metacharacters are allowed
        result = tools.run_shell("echo hello && echo world")
        assert "Exit code: 0" in result
        assert "hello" in result
        assert "world" in result

        # Any command is allowed
        result = tools.run_shell("sleep 0")
        assert "Exit code: 0" in result


def test_run_shell_path_escape_with_command():
    """Test that absolute paths outside base_dir are blocked even for allowed commands."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        result = tools.run_shell("cat /etc/passwd")
        assert "Error" in result
        assert "outside base directory" in result


def test_run_shell_handles_full_path_commands():
    """Test that commands specified with full paths are checked by basename."""
    import shutil

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        # Find the actual path to echo on this system
        echo_path = shutil.which("echo")
        if echo_path:
            result = tools.run_shell(f"{echo_path} hello")
            assert "Exit code: 0" in result
            assert "hello" in result


def test_default_allowed_commands():
    """Test that DEFAULT_ALLOWED_COMMANDS is used by default when restricted."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        tools = CodingTools(base_dir=base_dir)

        assert tools.allowed_commands == CodingTools.DEFAULT_ALLOWED_COMMANDS
        assert "python" in tools.allowed_commands
        assert "git" in tools.allowed_commands
        assert "pytest" in tools.allowed_commands

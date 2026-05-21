"""Unit tests for FileSystemKnowledge implementation."""

from pathlib import Path

import pytest

from agno.knowledge.document import Document
from agno.knowledge.filesystem import FileSystemKnowledge

# Initialization tests


def test_init_with_valid_directory(tmp_path):
    """Test initialization with a valid directory."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    assert fs_knowledge.base_path == tmp_path.resolve()
    assert fs_knowledge.max_results == 50
    assert fs_knowledge.include_patterns == []
    assert ".git" in fs_knowledge.exclude_patterns


def test_init_with_custom_config(tmp_path):
    """Test initialization with custom configuration."""
    fs_knowledge = FileSystemKnowledge(
        base_dir=str(tmp_path),
        max_results=100,
        include_patterns=["*.py", "*.md"],
        exclude_patterns=["test_*"],
    )
    assert fs_knowledge.max_results == 100
    assert "*.py" in fs_knowledge.include_patterns
    assert "test_*" in fs_knowledge.exclude_patterns


def test_init_with_nonexistent_directory():
    """Test initialization fails with nonexistent directory."""
    with pytest.raises(ValueError, match="Directory does not exist"):
        FileSystemKnowledge(base_dir="/nonexistent/path/12345")


def test_init_with_file_not_directory(tmp_path):
    """Test initialization fails when path is a file, not directory."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    with pytest.raises(ValueError, match="Path is not a directory"):
        FileSystemKnowledge(base_dir=str(test_file))


# Internal helper method tests


def test_should_include_file_default(tmp_path):
    """Test file inclusion with default patterns."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))

    # Should include regular files
    regular_file = tmp_path / "test.py"
    assert fs_knowledge._should_include_file(regular_file)

    # Should exclude .git files
    git_file = tmp_path / ".git" / "config"
    assert not fs_knowledge._should_include_file(git_file)

    # Should exclude __pycache__ files
    pycache_file = tmp_path / "__pycache__" / "module.pyc"
    assert not fs_knowledge._should_include_file(pycache_file)


def test_should_include_file_with_include_patterns(tmp_path):
    """Test file inclusion with include patterns."""
    fs_knowledge = FileSystemKnowledge(
        base_dir=str(tmp_path),
        include_patterns=["*.py", "*.md"],
    )

    # Should include matching files
    py_file = tmp_path / "test.py"
    assert fs_knowledge._should_include_file(py_file)

    md_file = tmp_path / "README.md"
    assert fs_knowledge._should_include_file(md_file)

    # Should exclude non-matching files
    txt_file = tmp_path / "data.txt"
    assert not fs_knowledge._should_include_file(txt_file)


def test_should_include_file_with_exclude_patterns(tmp_path):
    """Test file inclusion with custom exclude patterns."""
    fs_knowledge = FileSystemKnowledge(
        base_dir=str(tmp_path),
        exclude_patterns=["excluded_", "skip_"],
    )

    # Should exclude files matching exclude patterns
    excluded_file = tmp_path / "excluded_module.py"
    assert not fs_knowledge._should_include_file(excluded_file)

    skip_file = tmp_path / "skip_data.txt"
    assert not fs_knowledge._should_include_file(skip_file)

    # Should include files not matching exclude patterns
    normal_file = tmp_path / "module.py"
    assert fs_knowledge._should_include_file(normal_file)


# List files tests


def test_list_files_all(tmp_path):
    """Test listing all files."""
    # Create test files
    (tmp_path / "file1.py").write_text("content1")
    (tmp_path / "file2.md").write_text("content2")
    (tmp_path / "file3.txt").write_text("content3")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*")

    assert len(docs) == 3
    assert all(isinstance(doc, Document) for doc in docs)
    assert all(doc.meta_data["type"] == "file_listing" for doc in docs)


def test_list_files_with_pattern(tmp_path):
    """Test listing files with glob pattern."""
    # Create test files
    (tmp_path / "test1.py").write_text("content1")
    (tmp_path / "test2.py").write_text("content2")
    (tmp_path / "readme.md").write_text("content3")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*.py")

    assert len(docs) == 2
    assert all(doc.name.endswith(".py") for doc in docs)


def test_list_files_with_max_results(tmp_path):
    """Test max_results limit."""
    # Create many files
    for i in range(10):
        (tmp_path / f"file{i}.txt").write_text(f"content{i}")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*", max_results=5)

    assert len(docs) == 5


def test_list_files_nested_directories(tmp_path):
    """Test listing files in nested directories."""
    # Create nested structure
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (tmp_path / "root.txt").write_text("root content")
    (subdir / "nested.txt").write_text("nested content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*")

    assert len(docs) == 2
    file_names = [doc.name for doc in docs]
    assert "root.txt" in file_names
    assert str(Path("subdir") / "nested.txt") in file_names


def test_list_files_respects_exclude_patterns(tmp_path):
    """Test that excluded directories are skipped."""
    # Create excluded directory
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.js").write_text("excluded")
    (tmp_path / "app.py").write_text("included")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*")

    assert len(docs) == 1
    assert docs[0].name == "app.py"


# Get file tests


def test_get_file_relative_path(tmp_path):
    """Test getting file with relative path."""
    test_file = tmp_path / "test.txt"
    test_content = "Hello, World!"
    test_file.write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("test.txt")

    assert len(docs) == 1
    assert docs[0].content == test_content
    assert docs[0].name == "test.txt"
    assert docs[0].meta_data["type"] == "file_content"


def test_get_file_absolute_path(tmp_path):
    """Test getting file with absolute path."""
    test_file = tmp_path / "test.txt"
    test_content = "Absolute path test"
    test_file.write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file(str(test_file))

    assert len(docs) == 1
    assert docs[0].content == test_content


def test_get_file_nested_path(tmp_path):
    """Test getting file in nested directory."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    test_file = subdir / "nested.txt"
    test_content = "Nested file content"
    test_file.write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file(str(Path("subdir") / "nested.txt"))

    assert len(docs) == 1
    assert docs[0].content == test_content


def test_get_file_nonexistent(tmp_path):
    """Test getting nonexistent file returns empty list."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("nonexistent.txt")

    assert len(docs) == 0


def test_get_file_is_directory(tmp_path):
    """Test getting a directory returns empty list."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("subdir")

    assert len(docs) == 0


def test_get_file_metadata(tmp_path):
    """Test file metadata is included."""
    test_file = tmp_path / "test.py"
    test_content = "print('hello')\n"
    test_file.write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("test.py")

    assert docs[0].meta_data["extension"] == ".py"
    assert docs[0].meta_data["size"] == len(test_content)
    assert docs[0].meta_data["lines"] == 2


# Grep tests


def test_grep_literal_string(tmp_path):
    """Test grep with literal string."""
    (tmp_path / "file1.txt").write_text("Hello, World!")
    (tmp_path / "file2.txt").write_text("Goodbye, World!")
    (tmp_path / "file3.txt").write_text("No match here")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("World")

    assert len(docs) == 2
    file_names = [doc.name for doc in docs]
    assert "file1.txt" in file_names
    assert "file2.txt" in file_names


def test_grep_case_insensitive(tmp_path):
    """Test grep is case insensitive."""
    (tmp_path / "test.txt").write_text("Hello, WORLD!")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("world")

    assert len(docs) == 1


def test_grep_regex_pattern(tmp_path):
    """Test grep with regex pattern."""
    (tmp_path / "file1.txt").write_text("email@example.com")
    (tmp_path / "file2.txt").write_text("no email here")
    (tmp_path / "file3.txt").write_text("test@domain.org")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep(r"\w+@\w+\.\w+")

    assert len(docs) == 2


def test_grep_invalid_regex_fallback_to_literal(tmp_path):
    """Test invalid regex falls back to literal search."""
    (tmp_path / "test.txt").write_text("Test [bracket] text")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("[")

    assert len(docs) == 1


def test_grep_with_context(tmp_path):
    """Test grep includes context lines."""
    test_content = """line 1
line 2
target line
line 4
line 5"""
    (tmp_path / "test.txt").write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("target")

    assert len(docs) == 1
    # Context should include line before and after
    assert "line 2" in docs[0].content
    assert "target line" in docs[0].content
    assert "line 4" in docs[0].content


def test_grep_max_results(tmp_path):
    """Test max_results limit."""
    for i in range(10):
        (tmp_path / f"file{i}.txt").write_text("match")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("match", max_results=5)

    assert len(docs) == 5


def test_grep_metadata(tmp_path):
    """Test grep result includes metadata."""
    (tmp_path / "test.txt").write_text("find this match here")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("match")

    assert docs[0].meta_data["type"] == "grep_result"
    assert docs[0].meta_data["match_count"] > 0
    assert "matches" in docs[0].meta_data


def test_grep_no_matches(tmp_path):
    """Test grep with no matches returns empty list."""
    (tmp_path / "test.txt").write_text("some content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("nonexistent")

    assert len(docs) == 0


# Protocol implementation tests


def test_build_context(tmp_path):
    """Test build_context returns proper instructions."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    context = fs_knowledge.build_context()

    assert isinstance(context, str)
    assert len(context) > 0
    assert "grep_file" in context
    assert "list_files" in context
    assert "get_file" in context
    assert str(tmp_path) in context


def test_get_tools_returns_three_tools(tmp_path):
    """Test get_tools returns three tools."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()

    assert len(tools) == 3
    tool_names = [tool.name for tool in tools]
    assert "grep_file" in tool_names
    assert "list_files" in tool_names
    assert "get_file" in tool_names


@pytest.mark.asyncio
async def test_aget_tools(tmp_path):
    """Test async get_tools."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = await fs_knowledge.aget_tools()

    assert len(tools) == 3


def test_retrieve_uses_grep(tmp_path):
    """Test retrieve method uses grep internally."""
    (tmp_path / "test.txt").write_text("retrievable content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge.retrieve("retrievable", max_results=10)

    assert len(docs) == 1
    assert isinstance(docs[0], Document)


@pytest.mark.asyncio
async def test_aretrieve(tmp_path):
    """Test async retrieve."""
    (tmp_path / "test.txt").write_text("async retrievable content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = await fs_knowledge.aretrieve("retrievable")

    assert len(docs) == 1


# Tool execution tests


def test_grep_file_tool(tmp_path):
    """Test grep_file tool execution."""
    (tmp_path / "test.txt").write_text("Find this text")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    grep_tool = next(t for t in tools if t.name == "grep_file")

    result = grep_tool.entrypoint("Find")

    assert isinstance(result, str)
    assert "test.txt" in result
    assert "Find this text" in result


def test_grep_file_tool_no_matches(tmp_path):
    """Test grep_file tool with no matches."""
    (tmp_path / "test.txt").write_text("some content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    grep_tool = next(t for t in tools if t.name == "grep_file")

    result = grep_tool.entrypoint("nonexistent")

    assert "No matches found" in result


def test_list_files_tool(tmp_path):
    """Test list_files tool execution."""
    (tmp_path / "file1.py").write_text("content1")
    (tmp_path / "file2.py").write_text("content2")
    (tmp_path / "readme.md").write_text("content3")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    list_tool = next(t for t in tools if t.name == "list_files")

    result = list_tool.entrypoint("*.py")

    assert isinstance(result, str)
    assert "file1.py" in result
    assert "file2.py" in result
    assert "readme.md" not in result


def test_list_files_tool_all_files(tmp_path):
    """Test list_files tool with wildcard."""
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.txt").write_text("content2")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    list_tool = next(t for t in tools if t.name == "list_files")

    result = list_tool.entrypoint("*")

    assert "file1.txt" in result
    assert "file2.txt" in result


def test_list_files_tool_no_matches(tmp_path):
    """Test list_files tool with no matches."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    list_tool = next(t for t in tools if t.name == "list_files")

    result = list_tool.entrypoint("*.nonexistent")

    assert "No files found" in result


def test_get_file_tool(tmp_path):
    """Test get_file tool execution."""
    test_content = "File content here"
    (tmp_path / "test.txt").write_text(test_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    get_file_tool = next(t for t in tools if t.name == "get_file")

    result = get_file_tool.entrypoint("test.txt")

    assert isinstance(result, str)
    assert test_content in result
    assert "test.txt" in result


def test_get_file_tool_not_found(tmp_path):
    """Test get_file tool with nonexistent file."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    tools = fs_knowledge.get_tools()
    get_file_tool = next(t for t in tools if t.name == "get_file")

    result = get_file_tool.entrypoint("nonexistent.txt")

    assert "File not found" in result


# Edge cases and error conditions


def test_empty_directory(tmp_path):
    """Test operations on empty directory."""
    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))

    assert len(fs_knowledge._list_files("*")) == 0
    assert len(fs_knowledge._grep("anything")) == 0
    assert len(fs_knowledge._get_file("nonexistent.txt")) == 0


def test_binary_files_skipped_in_grep(tmp_path):
    """Test that binary files don't crash grep."""
    # Create a binary file
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02\x03\x04")
    (tmp_path / "text.txt").write_text("searchable text")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._grep("text")

    # Should find the text file, skip binary
    assert len(docs) == 1
    assert docs[0].name == "text.txt"


def test_unicode_content(tmp_path):
    """Test handling of unicode content."""
    unicode_content = "Hello 世界 🌍"
    (tmp_path / "unicode.txt").write_text(unicode_content, encoding="utf-8")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("unicode.txt")

    assert len(docs) == 1
    assert docs[0].content == unicode_content


def test_large_file_handling(tmp_path):
    """Test handling of larger files."""
    # Create a file with many lines
    large_content = "\n".join([f"Line {i}" for i in range(1000)])
    (tmp_path / "large.txt").write_text(large_content)

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._get_file("large.txt")

    assert len(docs) == 1
    assert len(docs[0].content.split("\n")) == 1000


def test_special_characters_in_filename(tmp_path):
    """Test files with special characters in names."""
    test_file = tmp_path / "file with spaces.txt"
    test_file.write_text("content")

    fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
    docs = fs_knowledge._list_files("*")

    assert len(docs) == 1
    assert docs[0].name == "file with spaces.txt"


def test_symlinks_are_handled(tmp_path):
    """Test that symlinks are handled gracefully."""
    # Create a real file
    real_file = tmp_path / "real.txt"
    real_file.write_text("real content")

    # Create a symlink
    link_file = tmp_path / "link.txt"
    try:
        link_file.symlink_to(real_file)

        fs_knowledge = FileSystemKnowledge(base_dir=str(tmp_path))
        docs = fs_knowledge._list_files("*")

        # Should list both real file and link
        assert len(docs) >= 1
    except OSError:
        # Symlinks might not be supported on all systems
        pytest.skip("Symlinks not supported on this system")

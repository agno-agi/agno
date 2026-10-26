import json

import pytest

from agno.tools.file import FileTools
from agno.tools.file.file import _extract_snippet as file_snippet
from agno.tools.workspace import Workspace
from agno.tools.workspace import _extract_snippet as workspace_snippet


@pytest.mark.parametrize("extract", [file_snippet, workspace_snippet])
@pytest.mark.parametrize(
    "content,query,expected",
    [
        ("İ" * 300 + "TARGET" + "tail", "target", "...TARGET..."),
        ("before İ after", "İ", "...İ..."),
        ("before i\u0307 after", "İ", "...i\u0307..."),
        ("İstanbul", "i", "İ..."),
        ("before TARGET after", "target", "...TARGET..."),
        ("nothing", "missing", ""),
    ],
)
def test_snippet_uses_original_character_offsets(extract, content, query, expected):
    assert extract(content, query, context_chars=0) == expected


@pytest.mark.parametrize("tool_class", [FileTools, Workspace])
def test_search_result_contains_actual_match_after_expanding_characters(tmp_path, tool_class):
    (tmp_path / "example.txt").write_text("İ" * 500 + "needle" + "z" * 500, encoding="utf-8")
    tool = FileTools(base_dir=tmp_path) if tool_class is FileTools else Workspace(str(tmp_path))
    result = json.loads(tool.search_content("needle"))
    assert result["matches_found"] == 1
    assert "needle" in result["files"][0]["snippet"]

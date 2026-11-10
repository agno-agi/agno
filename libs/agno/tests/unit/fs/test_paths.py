"""Unit tests for the FileSystem path/namespace/line grammar (spec D6)."""

import pytest

from agno.fs._paths import (
    build_chunk,
    normalize_check_lines,
    normalize_directory,
    normalize_line,
    normalize_namespace,
    normalize_path,
    normalize_template_value,
    parse_namespace_template,
    path_in_directory,
)
from agno.fs.errors import InvalidPathError


class TestNormalizePathAdversarial:
    @pytest.mark.parametrize(
        "path",
        [
            "..",
            "a/../b",
            "a/..",
            "../a",
            ".",
            "a/./b",
            "a\0b",
            "a\nb",
            "a\x07b",  # BEL, category Cc
            "a\\b",
            "a/",
            "a/b/",
            "",
            "/",
            "//",
        ],
    )
    def test_rejects(self, path):
        with pytest.raises(InvalidPathError):
            normalize_path(path)

    def test_rejects_non_str(self):
        with pytest.raises(InvalidPathError):
            normalize_path(None)  # type: ignore[arg-type]
        with pytest.raises(InvalidPathError):
            normalize_path(5)  # type: ignore[arg-type]

    def test_rejects_513_chars(self):
        segment = "a" * 128
        path = "/".join([segment, segment, segment, "a" * 125]) + "x"  # 513 chars
        assert len(path) == 513
        with pytest.raises(InvalidPathError):
            normalize_path(path)

    def test_accepts_512_chars(self):
        segment = "a" * 128
        path = "/".join([segment, segment, segment, "a" * 125])
        assert len(path) == 512
        assert normalize_path(path) == path

    def test_rejects_17_segments(self):
        with pytest.raises(InvalidPathError):
            normalize_path("/".join(["a"] * 17))

    def test_accepts_16_segments(self):
        path = "/".join(["a"] * 16)
        assert normalize_path(path) == path

    def test_rejects_129_char_segment(self):
        with pytest.raises(InvalidPathError):
            normalize_path("a" * 129)

    def test_accepts_128_char_segment(self):
        assert normalize_path("a" * 128) == "a" * 128

    def test_leading_slash_accepted_and_canonicalized(self):
        assert normalize_path("/seen/2026-07-24.md") == "seen/2026-07-24.md"

    def test_repeated_slashes_collapsed(self):
        assert normalize_path("a//b///c") == "a/b/c"
        assert normalize_path("//a/b") == "a/b"

    def test_nfc_equivalence(self):
        composed = "caf\u00e9.md"
        decomposed = "cafe\u0301.md"
        assert normalize_path(composed) == normalize_path(decomposed) == composed

    def test_case_sensitive(self):
        assert normalize_path("A.md") == "A.md"
        assert normalize_path("a.md") == "a.md"

    def test_braces_legal_in_file_paths(self):
        assert normalize_path("a{b}.md") == "a{b}.md"

    def test_windows_drive_prefix_is_grammar_legal(self):
        # The D6 grammar does not reject drive-letter prefixes; LocalFileSystem's
        # containment layer does (see test_local.py). Pinned so the divergence is
        # a known behavior rather than a discovered one.
        assert normalize_path("C:/x") == "C:/x"


class TestNamespaceNames:
    def test_plain_namespace_normalized(self):
        assert normalize_namespace("/radar//briefs") == "radar/briefs"

    def test_hostile_interpolation_rejected(self):
        with pytest.raises(InvalidPathError):
            normalize_namespace("radar/../other")

    def test_templated_namespace_kept_verbatim(self):
        assert normalize_namespace("radar/{user_id}") == "radar/{user_id}"

    def test_unknown_placeholder_rejected(self):
        with pytest.raises(InvalidPathError):
            normalize_namespace("radar/{tenant}")

    @pytest.mark.parametrize("name", ["radar/{", "radar/}", "radar/{user_id}/{", "{us{er_id}}"])
    def test_stray_braces_rejected(self, name):
        with pytest.raises(InvalidPathError):
            normalize_namespace(name)

    def test_templated_grammar_still_enforced(self):
        with pytest.raises(InvalidPathError):
            normalize_namespace("radar/{user_id}/..")

    def test_parse_placeholders_in_order(self):
        assert parse_namespace_template("a/{team_id}/{user_id}") == ("team_id", "user_id")
        assert parse_namespace_template("plain/name") == ()


class TestTemplateValues:
    def test_valid_single_segment(self):
        assert normalize_template_value("user_id", "u-42") == "u-42"

    @pytest.mark.parametrize("value", ["a/b", "/a", "..", ".", "", "a{b}", "a\\b", "a\nb", "a" * 129])
    def test_invalid_values_rejected(self, value):
        with pytest.raises(InvalidPathError):
            normalize_template_value("user_id", value)

    def test_non_str_rejected(self):
        with pytest.raises(InvalidPathError):
            normalize_template_value("user_id", 42)


class TestNormalizeDirectory:
    def test_empty_and_dot_mean_root(self):
        assert normalize_directory("") == ""
        assert normalize_directory(".") == ""

    def test_plain_directory(self):
        assert normalize_directory("seen") == "seen"
        assert normalize_directory("/seen/sub") == "seen/sub"

    def test_trailing_slash_rejected(self):
        with pytest.raises(InvalidPathError):
            normalize_directory("seen/")

    def test_dot_segment_rejected_inside(self):
        with pytest.raises(InvalidPathError):
            normalize_directory("./seen")


class TestNormalizeLine:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("http://a\r\n", "http://a"),
            ("http://a\n", "http://a"),
            ("http://a\r", "http://a"),
            ("a\n\n", "a"),
            ("  a", "  a"),
            ("b  ", "b  "),
            ("  a  \r\n", "  a  "),
            ("", ""),
            ("\r\n", ""),
        ],
    )
    def test_strips_trailing_terminators_only(self, raw, expected):
        assert normalize_line(raw) == expected

    @pytest.mark.parametrize("raw", ["a\nb", "a\rb", "a\n\nb"])
    def test_interior_newlines_rejected(self, raw):
        with pytest.raises(InvalidPathError) as excinfo:
            normalize_line(raw)
        assert repr(raw) in str(excinfo.value)
        assert "records must be single lines with no newlines." in str(excinfo.value)

    def test_non_str_rejected(self):
        with pytest.raises(InvalidPathError):
            normalize_line(42)  # type: ignore[arg-type]


class TestNormalizeCheckLines:
    def test_over_200_rejected_with_count_message(self):
        with pytest.raises(InvalidPathError) as excinfo:
            normalize_check_lines(["x"] * 201)
        assert str(excinfo.value) == "too many records (201 > 200). Check them in batches of 200 or fewer."

    def test_exactly_200_accepted(self):
        assert len(normalize_check_lines(["x"] * 200)) == 200

    def test_order_preserved_and_empties_dropped(self):
        assert normalize_check_lines(["b\n", "", "a", "\r\n", "c\r\n"]) == ["b", "a", "c"]


class TestBuildChunk:
    @pytest.mark.parametrize("content", ["", "\n", "\r\n", "\n\n\r\n"])
    def test_empty_content_yields_empty_chunk(self, content):
        assert build_chunk(content) == ""

    def test_crlf_normalized(self):
        assert build_chunk("http://a\r\nhttp://b\r\n") == "http://a\nhttp://b\n"

    def test_missing_trailing_newline_added(self):
        assert build_chunk("a\nb") == "a\nb\n"

    def test_interior_blank_lines_dropped(self):
        assert build_chunk("a\n\nb\n") == "a\nb\n"

    def test_idempotent(self):
        chunk = build_chunk("  a\r\nb  \r\n")
        assert chunk == "  a\nb  \n"
        assert build_chunk(chunk) == chunk

    def test_interior_carriage_return_rejected(self):
        with pytest.raises(InvalidPathError):
            build_chunk("a\rb")

    def test_unicode_line_separators_are_one_line(self):
        # split("\n"), never splitlines(): U+2028 (and \v, \f, U+2029, ...) are
        # legal record bytes, not line breaks (spec D9 step 1).
        assert build_chunk("a\u2028b\n") == "a\u2028b\n"
        assert build_chunk("a\vb\fc\u2029d") == "a\vb\fc\u2029d\n"


class TestPathInDirectory:
    def test_root_matches_everything(self):
        assert path_in_directory("a.md", "")
        assert path_in_directory("seen/a.md", "")

    def test_segment_boundary(self):
        assert path_in_directory("seen/a.md", "seen")
        assert path_in_directory("seen", "seen")
        assert not path_in_directory("seen-old/a.md", "seen")
        assert not path_in_directory("seenx/a.md", "seen")

    def test_nested(self):
        assert path_in_directory("a/b/c.md", "a/b")
        assert not path_in_directory("a/bc/c.md", "a/b")

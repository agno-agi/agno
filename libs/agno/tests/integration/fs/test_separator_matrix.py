"""The D9 separator-CASE matrix, executed on both dialects.

This is the one append mechanic the design review verified by construction
rather than execution: the server-side CASE must insert the "\\n" separator iff
existing content is non-empty and does not end with a newline, with size_bytes
arithmetic that stays byte-exact — including when the last character of the
existing content is multi-byte.
"""

import pytest

NS = "sep-matrix"

EXISTING_STATES = {
    "missing": None,
    "empty": "",
    "trailing_newline": "a\n",
    "no_trailing_newline": "a",
    "multibyte_trailing_newline": "hi \U0001f600\n",
    "multibyte_no_trailing_newline": "hi \U0001f600",
}
CHUNKS = {"with_trailing_newline": "x\ny\n", "without_trailing_newline": "x\ny"}


class TestSeparatorMatrix:
    @pytest.mark.parametrize("existing_key", list(EXISTING_STATES.keys()))
    @pytest.mark.parametrize("chunk_key", list(CHUNKS.keys()))
    def test_matrix_cell(self, db_fs, existing_key, chunk_key):
        existing = EXISTING_STATES[existing_key]
        chunk = CHUNKS[chunk_key]
        path = f"seen/{existing_key}-{chunk_key}.md"
        if existing is not None:
            db_fs.write(NS, path, existing)

        meta = db_fs.append(NS, path, chunk)

        content = db_fs.read(NS, path)
        if existing is None or existing == "":
            expected = "x\ny\n"
        elif existing.endswith("\n"):
            expected = existing + "x\ny\n"
        else:
            expected = existing + "\n" + "x\ny\n"
        assert content == expected
        assert meta.size_bytes == len(expected.encode("utf-8"))
        assert "\n\n" not in content
        expected_version = 1 if existing is None else 2
        assert meta.version == expected_version

    def test_repeated_appends_size_exact(self, db_fs):
        path = "seen/log.md"
        total = ""
        for i, line in enumerate(["one", "two \U0001f600", "three"]):
            meta = db_fs.append(NS, path, line)
            total += line + "\n"
            assert db_fs.read(NS, path) == total
            assert meta.size_bytes == len(total.encode("utf-8"))
            assert meta.version == i + 1

    def test_write_without_newline_then_append_does_not_merge_lines(self, db_fs):
        db_fs.write(NS, "raw.md", "tail-without-newline")
        db_fs.append(NS, "raw.md", "next-record\n")
        assert db_fs.read(NS, "raw.md") == "tail-without-newline\nnext-record\n"

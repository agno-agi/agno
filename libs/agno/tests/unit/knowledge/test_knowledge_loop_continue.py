"""Tests for loop continuation behavior when skip_if_exists triggers."""


def test_return_exits_loop_early():
    """Using return in a loop exits the entire function."""

    def process_with_return(items, skip_items):
        processed = []
        for item in items:
            if item in skip_items:
                return processed
            processed.append(item)
        return processed

    # Skip first item -> nothing processed (bug behavior)
    assert process_with_return(["a", "b", "c"], {"a"}) == []

    # Skip middle item -> only first processed
    assert process_with_return(["a", "b", "c"], {"b"}) == ["a"]


def test_continue_skips_only_current_item():
    """Using continue in a loop skips to next iteration."""

    def process_with_continue(items, skip_items):
        processed = []
        for item in items:
            if item in skip_items:
                continue
            processed.append(item)
        return processed

    # Skip first item -> rest still processed (fixed behavior)
    assert process_with_continue(["a", "b", "c"], {"a"}) == ["b", "c"]

    # Skip middle item -> others still processed
    assert process_with_continue(["a", "b", "c"], {"b"}) == ["a", "c"]

    # Skip multiple items
    assert process_with_continue(["a", "b", "c"], {"a", "c"}) == ["b"]


def test_topic_loading_with_existing_hashes():
    """Topics with existing hashes are skipped, others still load."""

    def load_topics(topics, existing_hashes, skip_if_exists):
        loaded = []
        for topic in topics:
            content_hash = f"hash_{topic}"
            if content_hash in existing_hashes and skip_if_exists:
                continue
            loaded.append(topic)
        return loaded

    # Nothing exists -> all loaded
    result = load_topics(["A", "B", "C"], set(), skip_if_exists=True)
    assert result == ["A", "B", "C"]

    # First exists -> remaining still loaded
    result = load_topics(["A", "B", "C"], {"hash_A"}, skip_if_exists=True)
    assert result == ["B", "C"]


def test_s3_loading_with_existing_hashes():
    """S3 objects with existing hashes are skipped, others still load."""

    def load_s3_objects(objects, existing_hashes, skip_if_exists):
        loaded = []
        for obj in objects:
            content_hash = f"hash_{obj}"
            if content_hash in existing_hashes and skip_if_exists:
                continue
            loaded.append(obj)
        return loaded

    # First file exists -> remaining still loaded
    result = load_s3_objects(
        ["file1.pdf", "file2.pdf", "file3.pdf"],
        {"hash_file1.pdf"},
        skip_if_exists=True,
    )
    assert result == ["file2.pdf", "file3.pdf"]

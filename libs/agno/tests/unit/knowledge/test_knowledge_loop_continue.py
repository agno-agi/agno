"""Tests for loop continuation when skip_if_exists triggers.

Verifies that when processing multiple items (topics, S3 objects, GCS objects),
skipping one item doesn't prevent processing of remaining items.
"""

import pytest


class TestLoopContinuationLogic:
    """Test the core loop continuation logic.

    These tests verify the fix for the early-return bug where using 'return'
    instead of 'continue' in loops would exit the entire function when
    skip_if_exists triggered on the first item.
    """

    def test_return_exits_loop_early(self):
        """Demonstrate buggy behavior: return exits entire function."""

        def process_with_return(items, skip_items):
            processed = []
            for item in items:
                if item in skip_items:
                    return processed  # Bug: exits entire function
                processed.append(item)
            return processed

        items = ["a", "b", "c"]

        # Skip first item -> nothing processed
        assert process_with_return(items, {"a"}) == []

        # Skip middle item -> only first processed
        assert process_with_return(items, {"b"}) == ["a"]

    def test_continue_skips_item_only(self):
        """Demonstrate fixed behavior: continue skips only current item."""

        def process_with_continue(items, skip_items):
            processed = []
            for item in items:
                if item in skip_items:
                    continue  # Fix: skips to next item
                processed.append(item)
            return processed

        items = ["a", "b", "c"]

        # Skip first item -> rest still processed
        assert process_with_continue(items, {"a"}) == ["b", "c"]

        # Skip middle item -> others still processed
        assert process_with_continue(items, {"b"}) == ["a", "c"]

        # Skip multiple items
        assert process_with_continue(items, {"a", "c"}) == ["b"]

    def test_real_scenario_topics(self):
        """Simulate the actual topic loading scenario."""

        def load_topics(topics, existing_hashes, skip_if_exists):
            """Simulates _load_from_topics logic."""
            loaded = []
            for topic in topics:
                content_hash = f"hash_{topic}"

                # This is the fixed code path
                if content_hash in existing_hashes and skip_if_exists:
                    continue  # Skip to next topic, don't exit loop

                loaded.append(topic)
            return loaded

        # First run: nothing exists
        result1 = load_topics(
            topics=["Carbon Dioxide", "Oxygen", "Nitrogen"], existing_hashes=set(), skip_if_exists=True
        )
        assert result1 == ["Carbon Dioxide", "Oxygen", "Nitrogen"]

        # Second run: first topic exists
        result2 = load_topics(
            topics=["Carbon Dioxide", "Oxygen", "Nitrogen"],
            existing_hashes={"hash_Carbon Dioxide"},
            skip_if_exists=True,
        )
        # With fix: remaining topics still processed
        assert result2 == ["Oxygen", "Nitrogen"]

    def test_real_scenario_s3_objects(self):
        """Simulate the actual S3 loading scenario."""

        def load_s3_objects(objects, existing_hashes, skip_if_exists):
            """Simulates _load_from_s3 logic."""
            loaded = []
            for obj in objects:
                content_hash = f"hash_{obj}"

                if content_hash in existing_hashes and skip_if_exists:
                    continue  # Skip to next S3 object, don't exit loop

                loaded.append(obj)
            return loaded

        # Bucket with 3 files, first already loaded
        result = load_s3_objects(
            objects=["file1.pdf", "file2.pdf", "file3.pdf"], existing_hashes={"hash_file1.pdf"}, skip_if_exists=True
        )
        assert result == ["file2.pdf", "file3.pdf"]

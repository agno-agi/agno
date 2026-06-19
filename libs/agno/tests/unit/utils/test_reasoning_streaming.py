"""Tests for streaming <think> tag parsing."""

import pytest
from agno.utils.reasoning import (
    ThinkTagStreamState,
    process_think_tag_chunk,
    flush_think_tag_state,
)


class TestThinkTagStreaming:
    """Tests for in-flight <think> tag parsing during streaming."""

    def test_basic_think_tag_extraction(self):
        """Test basic extraction of <think> content."""
        state = ThinkTagStreamState()
        
        # Simulate streaming: '<think>reasoning</think>answer'
        result1 = process_think_tag_chunk("<think>", state)
        assert result1.entered_think is True
        assert result1.reasoning_content is None
        assert result1.clean_content is None
        
        result2 = process_think_tag_chunk("reasoning", state)
        # Content is buffered until we're sure it's not a closing tag
        
        result3 = process_think_tag_chunk("</think>", state)
        assert result3.exited_think is True
        assert "reasoning" in (result2.reasoning_content or "") + (result3.reasoning_content or "")
        
        result4 = process_think_tag_chunk("answer", state)
        # Content after </think> goes to clean_content
        
        flush = flush_think_tag_state(state)
        
        # Verify accumulated content
        assert state.accumulated_reasoning == "reasoning"
        assert "answer" in state.accumulated_content

    def test_partial_tag_handling(self):
        """Test handling of tags split across chunks."""
        state = ThinkTagStreamState()
        
        # Tag split: '<thi' + 'nk>'
        result1 = process_think_tag_chunk("<thi", state)
        assert result1.entered_think is False  # Not yet detected
        
        result2 = process_think_tag_chunk("nk>hello", state)
        assert result2.entered_think is True  # Now detected
        
        # Verify state
        assert state.in_think_block is True

    def test_thinking_tag_variant(self):
        """Test <thinking> tag variant works too."""
        state = ThinkTagStreamState()
        
        process_think_tag_chunk("<thinking>", state)
        assert state.in_think_block is True
        assert state.tag_type == "thinking"
        
        process_think_tag_chunk("deep thoughts", state)
        process_think_tag_chunk("</thinking>", state)
        
        assert state.in_think_block is False
        assert "deep thoughts" in state.accumulated_reasoning

    def test_content_only_no_think_tags(self):
        """Test content without <think> tags passes through."""
        state = ThinkTagStreamState()
        
        result1 = process_think_tag_chunk("Hello ", state)
        result2 = process_think_tag_chunk("world!", state)
        flush = flush_think_tag_state(state)
        
        # All content should be in accumulated_content
        assert "Hello" in state.accumulated_content
        assert "world" in state.accumulated_content
        assert state.accumulated_reasoning == ""

    def test_multiple_think_blocks(self):
        """Test multiple <think> blocks in one stream."""
        state = ThinkTagStreamState()
        
        process_think_tag_chunk("<think>first</think>", state)
        process_think_tag_chunk("middle", state)
        process_think_tag_chunk("<think>second</think>", state)
        process_think_tag_chunk("end", state)
        flush_think_tag_state(state)
        
        assert "first" in state.accumulated_reasoning
        assert "second" in state.accumulated_reasoning
        assert "middle" in state.accumulated_content
        assert "end" in state.accumulated_content

    def test_flush_remaining_buffer(self):
        """Test flushing handles remaining buffered content."""
        state = ThinkTagStreamState()
        
        # Partial content that might be a tag
        process_think_tag_chunk("Hello <thi", state)
        
        # Flush should emit buffered content
        flush = flush_think_tag_state(state)
        
        # Since we never completed the tag, it should be in content
        assert "Hello" in state.accumulated_content or "Hello" in (flush.clean_content or "")

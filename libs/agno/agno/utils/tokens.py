"""Token counting utilities for text processing."""


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken.

    Uses cl100k_base encoding (compatible with GPT-4, GPT-4o, GPT-3.5-turbo).
    Falls back to character-based estimation if tiktoken is not available.

    Args:
        text: The text string to count tokens for.

    Returns:
        Total token count for the text.

    Examples:
        >>> count_tokens("Hello world")
        2
        >>> count_tokens("")
        0
    """
    try:
        import tiktoken

        # Use cl100k_base encoding (GPT-4, GPT-4o, GPT-3.5-turbo)
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        return len(tokens)
    except ImportError:
        from agno.utils.log import log_warning

        log_warning(
            "tiktoken not installed. You can install with `pip install -U tiktoken`. Using character-based estimation."
        )
        # Fallback: rough estimation (1 token H 4 characters)
        return len(text) // 4
    except Exception as e:
        from agno.utils.log import log_warning

        log_warning(f"Error counting tokens: {e}. Using character-based estimation.")
        return len(text) // 4

from enum import Enum


class GeminiFinishReason(Enum):
    """Gemini API finish reasons"""

    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"
    RECITATION = "RECITATION"
    MALFORMED_FUNCTION_CALL = "MALFORMED_FUNCTION_CALL"
    OTHER = "OTHER"


# Guidance message used to retry a Gemini invocation after a MALFORMED_FUNCTION_CALL error
MALFORMED_FUNCTION_CALL_GUIDANCE = """The previous function call was malformed. Please try again with a valid function call.

Guidelines:
- Generate the function call JSON directly, do not generate code
- Use the function name exactly as defined (no namespace prefixes like 'default_api.')
- Ensure all required parameters are provided with correct types
"""

import hashlib
import json
from typing import Any, Dict, Optional


def hash_string_sha256(input_string):
    # Encode the input string to bytes
    encoded_string = input_string.encode("utf-8")

    # Create a SHA-256 hash object
    sha256_hash = hashlib.sha256()

    # Update the hash object with the encoded string
    sha256_hash.update(encoded_string)

    # Get the hexadecimal digest of the hash
    hex_digest = sha256_hash.hexdigest()

    return hex_digest


def extract_valid_json(content: str) -> Optional[Dict[str, Any]]:
    """
    Extract the first valid JSON object from a string and return the JSON object
    along with the rest of the string without the JSON.

    Args:
        content (str): The input string containing potential JSON data.

    Returns:
        Tuple[Optional[Dict[str, Any]], str]:
            - Extracted JSON dictionary if valid, else None.
            - The rest of the string without the extracted JSON.
    """
    search_start = 0
    while True:
        # Find the next opening brace
        start_idx = content.find("{", search_start)
        if start_idx == -1:
            # No more '{' found; stop searching
            return None

        # Track brace depth
        brace_depth = 0
        # This will store the end of the matching closing brace once found
        end_idx = None

        for i in range(start_idx, len(content)):
            char = content[i]
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1

            # If brace_depth returns to 0, we’ve found a potential JSON substring
            if brace_depth == 0:
                end_idx = i
                break

        # If we never returned to depth 0, it means we couldn't find a matching '}'
        if end_idx is None:
            return None

        # Extract the candidate substring
        candidate = content[start_idx : end_idx + 1]

        # Try to parse it
        try:
            parsed = json.loads(candidate)
            # If parsed successfully, check if it's a dict
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Not valid JSON, keep going
            pass

        # Move just past the current opening brace to look for another candidate
        search_start = start_idx + 1

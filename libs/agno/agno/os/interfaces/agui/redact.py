import re
from typing import Any, Sequence, Optional

DEFAULT_SENSITIVE_KEY_PATTERNS = [
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "auth",
    "authorization",
    "credential",
    "private_key",
    "token",
    "client_secret",
    "db_password",
]

def resolve_key_patterns(custom_keys: Optional[Sequence[str]]) -> Sequence[str]:
    """
    Merges custom redaction keys with defaults.
    Ensures that default sensitive keys are never overridden, only appended to.
    """
    if not custom_keys:
        return DEFAULT_SENSITIVE_KEY_PATTERNS
    
    # Use dict.fromkeys for deduping while preserving order
    return list(dict.fromkeys([*DEFAULT_SENSITIVE_KEY_PATTERNS, *(k.lower() for k in custom_keys)]))


TOKEN_REGEXES = [
    re.compile(r"sk-[A-Za-z0-9-]{10,}"),  # OpenAI/Anthropic
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access keys
    re.compile(r"(?:gh[posur]_|github_pat_)[A-Za-z0-9_]{20,}"),  # GitHub tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),  # Slack tokens
    re.compile(r"(sk_live_[A-Za-z0-9]+|pk_live_[A-Za-z0-9]+)"),  # Stripe keys
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),  # Google API keys
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # Generic JWTs
    re.compile(r"Bearer\s+<token>|Bearer\s+[\w.-]+"),  # Generic Bearer
]


def redact_sensitive_data(value: Any, key_patterns: Sequence[str] = DEFAULT_SENSITIVE_KEY_PATTERNS) -> Any:
    """
    Recursively walks dictionaries, lists, and tuples to redact sensitive data.
    Does not mutate the input in place. Returns a new structure.
    """
    try:
        if isinstance(value, dict):
            new_dict = {}
            for k, v in value.items():
                is_sensitive = False
                if isinstance(k, str):
                    k_lower = k.lower()
                    if any(pattern in k_lower for pattern in key_patterns):
                        is_sensitive = True

                if is_sensitive:
                    new_dict[k] = "[REDACTED]"
                else:
                    new_dict[k] = redact_sensitive_data(v, key_patterns)
            return new_dict
        elif isinstance(value, list):
            return [redact_sensitive_data(item, key_patterns) for item in value]
        elif isinstance(value, tuple):
            return tuple(redact_sensitive_data(item, key_patterns) for item in value)
        elif isinstance(value, str):
            for regex in TOKEN_REGEXES:
                if regex.search(value):
                    return "[REDACTED]"
            return value
        else:
            return value
    except Exception:
        return "[REDACTED-ERROR]"

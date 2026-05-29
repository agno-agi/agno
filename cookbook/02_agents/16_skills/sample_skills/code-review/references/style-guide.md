# Python Style Guide

## Naming Conventions

### Variables and Functions
- Use `snake_case` for variables and functions
- Use descriptive names that explain the purpose
- Avoid single-letter names except for loop counters

```python
# Good
user_count = 10
def calculate_total_price(items):
    pass

# Bad
uc = 10
def calc(i):
    pass
```

### Classes
- Use `PascalCase` for class names
- Use nouns that describe what the class represents

```python
# Good
class UserAccount:
    pass

class OrderProcessor:
    pass

# Bad
class user_account:
    pass

class Process:
    pass
```

### Constants
- Use `UPPER_SNAKE_CASE` for constants
- Define at module level

```python
# Good
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30

# Bad
maxRetryCount = 3
default_timeout = 30
```

## Code Organization

### Imports
- Group imports in this order: standard library, third-party, local
- Sort alphabetically within each group
- Use absolute imports

```python
# Standard library
import os
import sys
from typing import List, Optional

# Third-party
import requests
from pydantic import BaseModel

# Local
from myapp.models import User
from myapp.utils import helper
```

### Function Length
- Keep functions under 50 lines
- If longer, consider breaking into smaller functions
- Each function should do one thing well

### Documentation
- Use docstrings for public functions and classes
- Follow Google or NumPy docstring style
- Include parameter types and return types

```python
def process_user_data(user_id: str, include_history: bool = False) -> dict:
    """Process user data and return formatted result.

    Args:
        user_id: The unique identifier for the user.
        include_history: Whether to include user history. Defaults to False.

    Returns:
        A dictionary containing the processed user data.

    Raises:
        ValueError: If user_id is empty or invalid.
    """
    pass
```

## Error Handling

### Be Specific
- Catch specific exceptions, not bare `except:`
- Include helpful error messages

```python
# Good
try:
    result = process_data(data)
except ValueError as e:
    logger.error(f"Invalid data format: {e}")
    raise
except ConnectionError as e:
    logger.error(f"Failed to connect: {e}")
    return None

# Bad
try:
    result = process_data(data)
except:
    pass
```

## Security

### Never Hardcode Secrets
- Use environment variables or secret managers
- Never commit credentials to version control

```python
# Good
import os
api_key = os.environ.get("API_KEY")

# Bad
api_key = "sk-1234567890abcdef"
```

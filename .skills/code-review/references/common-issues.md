# Common Code Review Issues

## Security Issues

### SQL Injection
**Severity**: Critical

```python
# Bad - vulnerable to SQL injection
query = f"SELECT * FROM users WHERE id = {user_id}"

# Good - use parameterized queries
query = "SELECT * FROM users WHERE id = ?"
cursor.execute(query, (user_id,))
```

### Command Injection
**Severity**: Critical

```python
# Bad - vulnerable to command injection
os.system(f"echo {user_input}")

# Good - use subprocess with list arguments
subprocess.run(["echo", user_input], check=True)
```

### Hardcoded Secrets
**Severity**: Critical

Look for patterns like:
- `password = "..."`
- `api_key = "sk-..."`
- `secret = "..."`
- Base64 encoded strings that decode to credentials

## Performance Issues

### N+1 Query Problem
**Severity**: Important

```python
# Bad - N+1 queries
for user in users:
    orders = get_orders_for_user(user.id)  # Query per user

# Good - batch query
user_ids = [u.id for u in users]
orders_by_user = get_orders_for_users(user_ids)  # Single query
```

### Inefficient Loops
**Severity**: Important

```python
# Bad - O(n²) complexity
for item in large_list:
    if item in another_large_list:  # O(n) lookup
        process(item)

# Good - O(n) with set
another_set = set(another_large_list)
for item in large_list:
    if item in another_set:  # O(1) lookup
        process(item)
```

## Code Quality Issues

### Missing Error Handling
**Severity**: Important

```python
# Bad - no error handling
data = json.loads(response.text)
result = data["key"]["nested"]

# Good - proper error handling
try:
    data = json.loads(response.text)
    result = data.get("key", {}).get("nested")
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse response: {e}")
    result = None
```

### Magic Numbers
**Severity**: Suggestion

```python
# Bad - magic numbers
if retry_count > 3:
    time.sleep(30)

# Good - named constants
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 30
if retry_count > MAX_RETRIES:
    time.sleep(RETRY_DELAY_SECONDS)
```

### Long Functions
**Severity**: Suggestion

Functions over 50 lines should be broken down into smaller, focused functions.

### Missing Type Hints
**Severity**: Suggestion

```python
# Bad - no type hints
def process(data):
    return data.get("value")

# Good - with type hints
def process(data: dict) -> Optional[str]:
    return data.get("value")
```

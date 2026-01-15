# Agno Knowledge System - Full Bug Report

**Date:** 2026-01-14
**Author:** Claude Code (Adversarial Testing)
**Version:** Current `fixes/knowledge-ga` branch
**Test Environment:** AgentOS localhost:7777 + PgVector localhost:5532

---

## Executive Summary

Adversarial testing of the Agno Knowledge system revealed **6 open bugs** across the API layer and reader components. The most critical is an **SSRF vulnerability** that could allow attackers to access internal services.

| Severity | Count | Action Required |
|----------|-------|-----------------|
| P0 Critical | 1 | Fix before release |
| P1 Medium | 2 | Fix in next sprint |
| P2 Low | 3 | Fix when convenient |

**Overall system health:** Good. The SDK layer is robust (100% pass rate on agent integration tests). Issues are concentrated in the REST API validation layer.

---

## P0 - Critical Security Bug

### KNOWLEDGE-008: Server-Side Request Forgery (SSRF) in WebsiteReader

#### What Is This Bug?

The `WebsiteReader` class fetches content from URLs provided by users but performs **no validation** on those URLs. This allows attackers to make the server fetch internal resources.

#### Why Does This Matter?

An attacker can:
1. **Access internal services** - Fetch `http://localhost:8080/admin` or `http://192.168.1.1/config`
2. **Steal cloud credentials** - Fetch `http://169.254.169.254/latest/meta-data/` (AWS metadata endpoint)
3. **Port scan internal network** - Probe which internal services exist
4. **Bypass firewalls** - The request comes from your server, not the attacker

#### Real-World Attack Scenario

```
Attacker submits content with URL:
  http://169.254.169.254/latest/meta-data/iam/security-credentials/

Your server fetches this URL and returns AWS IAM credentials.
Attacker now has access to your AWS account.
```

#### Location

```
libs/agno/agno/knowledge/reader/website_reader.py
```

#### Current Code (Vulnerable)

```python
class WebsiteReader(Reader):
    def read(self, url: str) -> List[Document]:
        # No validation! Accepts any URL
        response = httpx.get(url)  # Fetches internal IPs, cloud metadata, etc.
        return self._parse_response(response)
```

#### Proposed Fix

```python
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",  # GCP metadata
    "100.100.100.200",  # Alibaba metadata
}

def validate_url(url: str) -> None:
    """Validate URL is safe to fetch."""
    parsed = urlparse(url)

    # 1. Require HTTPS (or HTTP for dev)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

    # 2. Block cloud metadata endpoints
    if parsed.hostname in BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {parsed.hostname}")

    # 3. Block private IP ranges
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"Private IP not allowed: {parsed.hostname}")
    except ValueError:
        pass  # Not an IP address, hostname is OK

class WebsiteReader(Reader):
    def read(self, url: str) -> List[Document]:
        validate_url(url)  # Add this line
        response = httpx.get(url)
        return self._parse_response(response)
```

#### Test Case

```python
def test_ssrf_blocked():
    reader = WebsiteReader()

    # These should all raise ValueError
    with pytest.raises(ValueError):
        reader.read("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(ValueError):
        reader.read("http://localhost:8080/admin")

    with pytest.raises(ValueError):
        reader.read("http://192.168.1.1/config")
```

---

## P1 - Medium Priority Bugs

### KNOWLEDGE-006: API Accepts Empty/Whitespace Content

#### What Is This Bug?

The `/knowledge/content` endpoint accepts empty strings or whitespace-only strings as `text_content`. It returns `202 Accepted` instead of `400 Bad Request`.

#### Why Does This Matter?

- **Wasted resources** - Empty content triggers embedding, chunking, and storage
- **Polluted knowledge base** - Meaningless documents clutter search results
- **Confusing UX** - Users think upload succeeded when it's actually useless

#### Reproduction

```bash
# Empty content - should fail, but returns 202
curl -X POST "http://localhost:7777/knowledge/content?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..." \
  -F "name=test" \
  -F "text_content="

# Whitespace only - should fail, but returns 202
curl -X POST "http://localhost:7777/knowledge/content?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..." \
  -F "name=test" \
  -F "text_content=     "
```

#### Location

```
libs/agno/agno/os/routers/knowledge/knowledge.py:140-198
```

#### Proposed Fix

```python
@router.post("/content")
async def add_content(
    name: str = Form(...),
    text_content: Optional[str] = Form(None),
    ...
):
    # Add validation
    if text_content is not None:
        if not text_content.strip():
            raise HTTPException(
                status_code=400,
                detail="text_content cannot be empty or whitespace only"
            )
```

---

### KNOWLEDGE-010: Inconsistent db_id Parameter Location

#### What Is This Bug?

The API is inconsistent about where `db_id` should be provided:

| Endpoint | db_id Location |
|----------|----------------|
| `POST /content` | Query parameter |
| `GET /content` | Query parameter |
| `DELETE /content/{id}` | Query parameter |
| `GET /content/{id}/status` | Query parameter |
| **`POST /search`** | **Request body** ← Different! |

#### Why Does This Matter?

- **Developer confusion** - Easy to use the wrong pattern
- **Silent failures** - Missing db_id in body returns 400 with unclear error
- **Documentation mismatch** - Hard to document consistently

#### Reproduction

```bash
# This works (db_id in query param)
curl -X GET "http://localhost:7777/knowledge/content?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..."

# This FAILS (db_id in query param)
curl -X POST "http://localhost:7777/knowledge/search?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
# Error: "The db_id query parameter is required"

# This works (db_id in body)
curl -X POST "http://localhost:7777/knowledge/search" \
  -H "Authorization: Bearer OSK_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "db_id": "agno_faq_db"}'
```

#### Location

```
libs/agno/agno/os/routers/knowledge/knowledge.py
libs/agno/agno/os/routers/knowledge/schemas.py (VectorSearchRequestSchema)
```

#### Proposed Fix

Option A: Move db_id to query param for search (consistent with other endpoints)
Option B: Document the difference clearly and update error messages

---

## P2 - Low Priority Bugs

### KNOWLEDGE-007: Pagination page=0 Returns 500

#### What Is This Bug?

The `/knowledge/content` listing endpoint allows `page=0` but this causes an internal server error.

#### Why Does This Matter?

- **Poor error handling** - 500 errors look like server crashes
- **Confusing for users** - "Page 0" seems logical but breaks

#### Reproduction

```bash
# page=0 returns 500 Internal Server Error
curl "http://localhost:7777/knowledge/content?db_id=agno_faq_db&page=0&limit=10" \
  -H "Authorization: Bearer OSK_..."
```

#### Location

```
libs/agno/agno/os/routers/knowledge/knowledge.py:359
```

#### Current Code

```python
page: int = Query(1, ge=0),  # ge=0 allows page=0
```

#### Proposed Fix

```python
page: int = Query(1, ge=1),  # ge=1 ensures page >= 1
```

---

### KNOWLEDGE-011: Delete/Status of Non-Existent Content Returns 200

#### What Is This Bug?

Deleting content that doesn't exist returns `200 OK` instead of `404 Not Found`. Same for checking status.

#### Why Does This Matter?

- **Misleading responses** - Can't tell if delete actually did anything
- **Hard to debug** - "Success" responses for failed operations
- **REST best practices** - DELETE should return 404 for non-existent resources

#### Reproduction

```bash
# Delete non-existent content - returns 200 (should be 404)
curl -X DELETE \
  "http://localhost:7777/knowledge/content/00000000-0000-0000-0000-000000000000?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..."

# Status of non-existent content - returns 200 (should be 404)
curl "http://localhost:7777/knowledge/content/00000000-0000-0000-0000-000000000000/status?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..."
```

#### Proposed Fix

```python
async def delete_content_by_id(content_id: str, ...):
    content = knowledge.get_content_by_id(content_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

    await knowledge.delete_content(content_id)
    return {"message": "Content deleted successfully"}
```

---

### KNOWLEDGE-012: Empty/Whitespace Content Names Accepted

#### What Is This Bug?

The content upload endpoint accepts empty strings or whitespace-only strings as `name`.

#### Why Does This Matter?

- **Poor data quality** - Content with no name is hard to identify
- **UX issues** - Listing shows blank entries

#### Reproduction

```bash
# Empty name - returns 202 (should be 400)
curl -X POST "http://localhost:7777/knowledge/content?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..." \
  -F "name=" \
  -F "text_content=Some content"

# Whitespace name - returns 202 (should be 400)
curl -X POST "http://localhost:7777/knowledge/content?db_id=agno_faq_db" \
  -H "Authorization: Bearer OSK_..." \
  -F "name=   " \
  -F "text_content=Some content"
```

#### Proposed Fix

```python
@router.post("/content")
async def add_content(name: str = Form(...), ...):
    if not name.strip():
        raise HTTPException(
            status_code=400,
            detail="Content name cannot be empty or whitespace only"
        )
```

---

## Test Results Summary

| Test Suite | Pass | Fail | Rate |
|------------|------|------|------|
| Chaos Testing | 13 | 2 | 86.7% |
| Lifecycle Testing | 4 | 0 | 100% |
| Advanced Edge Cases | 32 | 3 | 91.4% |
| Agent Integration | 10 | 0 | 100% |
| **TOTAL** | **59** | **5** | **92.2%** |

---

## Recommendations

### Before Release (This Week)
1. ✅ Fix KNOWLEDGE-008 (SSRF) - **Security critical**
2. ✅ Fix KNOWLEDGE-006 (empty content) - **Data quality**
3. ✅ Fix KNOWLEDGE-012 (empty names) - **Data quality**

### Next Sprint
4. Fix KNOWLEDGE-010 (db_id consistency) - Decide on pattern
5. Fix KNOWLEDGE-007 (page=0) - One-line fix
6. Fix KNOWLEDGE-011 (404 responses) - Better REST compliance

### Long-term
7. Add rate limiting to API endpoints
8. Add file size limits for uploads
9. Add request logging for security auditing

---

## Appendix: Test Files

All test files located in `/tmp/claude/knowledge_chaos_tests/`:

| File | Tests | Purpose |
|------|-------|---------|
| `test_agentos_chaos.py` | 15 | SQL injection, auth, race conditions |
| `test_content_lifecycle.py` | 4 | Upload/process/delete cycles |
| `test_edge_cases_advanced.py` | 35 | Encoding, pagination, timing |
| `test_agent_knowledge_integration.py` | 10 | SDK robustness |

Run all tests:
```bash
.venvs/demo/bin/python /tmp/claude/knowledge_chaos_tests/test_agentos_chaos.py
.venvs/demo/bin/python /tmp/claude/knowledge_chaos_tests/test_edge_cases_advanced.py
.venvs/demo/bin/python /tmp/claude/knowledge_chaos_tests/test_agent_knowledge_integration.py
```

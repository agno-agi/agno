# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.8.x   | ✅                 |
| 2.7.x   | ✅ (critical only) |
| < 2.7   | ❌                 |

## Reporting a Vulnerability

We take security vulnerabilities seriously. Please **do not** open public GitHub issues for security vulnerabilities.

### How to Report

1. **Preferred**: Use GitHub's [Private Vulnerability Reporting](https://github.com/agno-agi/agno/security/advisories/new)
2. **Alternative**: Email the repository maintainers directly

### What to Include

- Description of the vulnerability
- Affected file(s) and line numbers
- Steps to reproduce or proof-of-concept
- Impact assessment
- Suggested fix (if available)

### Response Timeline

- **Initial acknowledgment**: 48 hours
- **Status update**: 1 week
- **Fix development**: 2-4 weeks (severity-dependent)
- **Public disclosure**: After fix is available and users have had time to update

## Security Best Practices for Users

- Never use `exec()`, `eval()`, or `pickle.load()` on untrusted input
- Always use environment variables for secrets, never hardcode credentials
- Validate and sanitize all URLs before making outbound requests (prevent SSRF)
- Use parameterized queries for all database operations
- Run agents in sandboxed environments when executing arbitrary code

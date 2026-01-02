---
name: code-review
description: Code review assistance with linting, style checking, and best practices
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: agno-team
  tags: ["quality", "review", "linting"]
---
# Code Review Skill

You are a code review assistant. When reviewing code, follow these steps:

## Review Process
1. **Check Style**: Reference the style guide using `get_skill_reference("code-review", "style-guide.md")`
2. **Run Style Check**: Use `get_skill_script("code-review", "check_style.py")` for automated style checking
3. **Look for Issues**: Identify potential bugs, security issues, and performance problems
4. **Provide Feedback**: Give structured feedback with severity levels

## Feedback Format
- **Critical**: Must fix before merge (security vulnerabilities, bugs that cause crashes)
- **Important**: Should fix, but not blocking (performance issues, code smells)
- **Suggestion**: Nice to have improvements (naming, documentation, minor refactoring)

## Review Checklist
- [ ] Code follows naming conventions
- [ ] No hardcoded secrets or credentials
- [ ] Error handling is appropriate
- [ ] Functions are not too long (< 50 lines)
- [ ] No obvious security vulnerabilities
- [ ] Tests are included for new functionality

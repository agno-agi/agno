# Commit Types Reference

## Primary Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | A new feature for the user | `feat(cart): add checkout button` |
| `fix` | A bug fix for the user | `fix(login): correct password validation` |
| `docs` | Documentation only changes | `docs(readme): update installation steps` |
| `style` | Formatting, missing semicolons, etc. | `style(api): format with prettier` |
| `refactor` | Code change that neither fixes a bug nor adds a feature | `refactor(auth): simplify token logic` |
| `perf` | Performance improvement | `perf(query): add database index` |
| `test` | Adding or updating tests | `test(api): add user endpoint tests` |
| `chore` | Maintenance tasks | `chore(deps): update lodash to 4.17.21` |

## Additional Types (Optional)

| Type | Description | Example |
|------|-------------|---------|
| `build` | Build system or external dependencies | `build(docker): optimize image size` |
| `ci` | CI/CD configuration | `ci(github): add lint workflow` |
| `revert` | Reverting a previous commit | `revert: feat(cart): add checkout button` |

## Scope Examples

Scopes should be short and identify the area of the codebase:

- `auth` - Authentication module
- `api` - API endpoints
- `ui` - User interface
- `db` - Database
- `config` - Configuration
- `deps` - Dependencies
- `core` - Core functionality

## Breaking Changes

Use `!` after type/scope for breaking changes:

```
feat(api)!: change response format

BREAKING CHANGE: Response now uses camelCase instead of snake_case.
Migration guide available in docs/migration-v2.md
```

## Multi-line Commits

For complex changes, use a body:

```
feat(search): implement fuzzy matching

Added fuzzy matching algorithm to improve search results.
Users can now find items even with typos or partial matches.

- Implemented Levenshtein distance calculation
- Added configurable threshold for match sensitivity
- Updated search index to support fuzzy queries

Closes #789
```

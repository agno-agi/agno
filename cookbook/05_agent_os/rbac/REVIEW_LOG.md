# Review Log — rbac/

## Framework Issues

[FRAMEWORK] agno/os/middleware/jwt.py:404 — `JWTMiddleware` defaults `verify_audience=False`, and `AuthorizationConfig` only exposes 4 fields (`verification_keys`, `jwks_file`, `algorithm`, `verify_audience`). Many middleware options (`token_source`, `cookie_name`, `scope_mappings`, `excluded_route_paths`, `admin_scope`) are not passable through `AuthorizationConfig`, forcing users to bypass the declarative config for common scenarios.

[FRAMEWORK] agno/os/middleware/jwt.py:687-692 — Silent audience verification failure: when `verify_audience=True` but neither `self.audience` nor `agent_os_id` is set, `expected_audience` resolves to `None` and audience check is silently skipped instead of raising an error.

[FRAMEWORK] agno/os/middleware/jwt.py:425 — Docstring mentions `JWT_JWKS` env var for inline JWKS JSON, but implementation (line 120) only reads `JWT_JWKS_FILE`. Documentation mismatch.

## Cookbook Quality

[QUALITY] asymmetric/custom_scope_mappings.py:109,155 — `admin_scope="foo:bar"` is set on middleware, but the test admin token uses `"agent_os:admin"` instead of `"foo:bar"`. The documented admin bypass will not work.

[QUALITY] All cookbooks — Test tokens and docstrings mention `aud` claim as required (e.g., `basic.py:69`, `advanced_scopes.py:81`), but most generated tokens omit the `aud` claim entirely, and only `advanced_scopes.py` actually enables `verify_audience=True` via `AuthorizationConfig`.

[QUALITY] symmetric/with_cookie.py:72 — Sets `secure=True` on cookie but examples run on `http://localhost`, so cookie won't be sent by browsers in local testing.

## Fixes Applied

(none — framework issues and cookbook docs, not fixable in cookbooks)

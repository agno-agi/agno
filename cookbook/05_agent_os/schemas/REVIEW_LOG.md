# Review Log — schemas/

## Framework Issues

(none found)

## Cookbook Quality

[QUALITY] team_schemas.py — Uses `delegate_to_all_members=True` which is the old v2.4 boolean. Still works via compat shim, but v2.5 idiom is `mode=TeamMode.broadcast`. Consider updating for consistency.

## Fixes Applied

(none needed)

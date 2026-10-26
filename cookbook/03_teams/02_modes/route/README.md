# Route Mode

Route mode examples show how team leaders delegate to one specialist path and return a routed answer.

## Files

- `01_basic.py` - Basic routing between language specialists.
- `02_specialist_router.py` - Domain specialist routing patterns.
- `03_with_fallback.py` - Fallback routing when a specialist is unavailable.
- [04_jev_router.py](04_jev_router.py) - Jev selects a support queue using literal routing policies, with confidence-based fallback. Requires `typesafe-sdk`, `TYPESAFE_API_KEY`, and `OPENAI_API_KEY`; see [Jev setup](../../../90_models/typesafe/README.md).

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/02_modes/route/01_basic.py
```

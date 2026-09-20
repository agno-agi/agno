# Broadcast Mode

Broadcast mode examples send the same request to all members and synthesize responses.

## Files

- `01_basic.py` - Baseline broadcast coordination with three specialists.
- `02_debate.py` - Structured debate with agreement and disagreement.
- `03_research_sweep.py` - Parallel research before aggregation.
- `05_jev_panel_judge.py` - Jev (TypeSafe System One) as the leader: broadcasts the request unchanged, then fills the team's `output_schema` by judging the members' replies.

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/02_modes/broadcast/01_basic.py
```

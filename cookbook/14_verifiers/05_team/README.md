# 05_team

Verifiers on a team member and on the leader.

## Files

- `member_verified.py`: A member carries its own verifiers into every delegation; the leader reads the outcome off `member_responses`.
- `leader_verified.py`: `Team(verifiers=[...])` gates the leader's final answer.

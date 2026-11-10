# Basics

The smallest working CodeMode agent, and shell cells.

- `basic.py` — one `CodeMode()` toolkit, no options. The agent computes over 200 Fibonacci numbers that never enter the transcript; only the conclusion does.
- `with_shell.py` — `%%bash` cells. Each is a throw-away subshell, so `cd` does not carry over; `%cd` and `os.environ[...]` are kernel-level and do. Pass `allow_shell=False` to strip the magic.

Run:

```bash
python cookbook/code/01_basics/basic.py
```

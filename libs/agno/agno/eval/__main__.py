"""Run an eval suite by module path.

Usage: python -m agno.eval <module[:attr]> [flags]

Imports <module>, reads <attr> (default: CASES) as the Sequence[Case] to run,
and hands it to agno.eval.cli(). If the module also exposes an `eval_db`
attribute, it is passed as the db so results log to storage.

Example: python -m agno.eval evals.cases --tag smoke
"""

import importlib
import sys
from typing import List, Optional

USAGE = "usage: python -m agno.eval <module[:attr]> [flags]"


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        print("Pass --help after the module path for the runner flags.")
        return 0
    if not args or args[0].startswith("-"):
        print(USAGE, file=sys.stderr)
        return 2

    target, cli_args = args[0], args[1:]
    module_name, _, attr = target.partition(":")
    attr = attr or "CASES"

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"error: cannot import module {module_name!r}: {exc}", file=sys.stderr)
        return 2

    cases = getattr(module, attr, None)
    if cases is None:
        print(f"error: module {module_name!r} has no attribute {attr!r}", file=sys.stderr)
        return 2

    from agno.eval.suite import cli

    return cli(cases, db=getattr(module, "eval_db", None), argv=cli_args)


if __name__ == "__main__":
    sys.exit(main())

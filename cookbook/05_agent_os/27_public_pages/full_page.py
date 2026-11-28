"""Read a complete revision-pinned page, or normalize prose without changing code."""

import argparse
import asyncio
import html
from pathlib import Path

from agno.utils.markdown import FenceState, advance_code_fence


def normalize_prose(markdown: str) -> str:
    """Decode HTML entities in prose, keeping code and its delimiters verbatim."""
    output = []
    fence: FenceState | None = None
    for line in markdown.splitlines(keepends=True):
        was_code = fence is not None
        fence, delimiter = advance_code_fence(line.rstrip("\r\n"), fence)
        output.append(line if was_code or delimiter else html.unescape(line))
    return "".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="/introduction")
    parser.add_argument(
        "--revision", help="Revision from a search hit; reject a changed page"
    )
    parser.add_argument("--max-chars", type=int, default=24_000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--sync", action="store_true", help="Use the synchronous full-page API"
    )
    parser.add_argument(
        "--normalize",
        type=Path,
        help="Normalize a local Markdown file without using the database",
    )
    args = parser.parse_args()
    if args.normalize:
        print(normalize_prose(args.normalize.read_text()), end="")
        return

    from agno.knowledge.page import PageError
    from public_pages import knowledge

    knowledge.setup()
    try:
        if args.sync:
            body = knowledge.read_full_page(
                args.path,
                revision=args.revision,
                max_chars=args.max_chars,
                timeout=args.timeout,
            )
        else:
            body = asyncio.run(
                knowledge.aread_full_page(
                    args.path,
                    revision=args.revision,
                    max_chars=args.max_chars,
                    timeout=args.timeout,
                )
            )
    except PageError as exc:
        print("Page unavailable:", exc.code)
        return
    if body is None:
        print("Page does not fit the character budget; retain search excerpts instead.")
    else:
        print(body, end="")


if __name__ == "__main__":
    main()

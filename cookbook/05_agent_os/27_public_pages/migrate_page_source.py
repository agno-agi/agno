"""Relocate an indexed site's hostname without private SQL; dry-run by default."""

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_source", help="Current HTTPS llms.txt URL")
    parser.add_argument(
        "target_source", help="Same corpus and discovery path on the new host"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Commit the guarded binding update"
    )
    args = parser.parse_args()

    from public_pages import knowledge

    knowledge.setup()
    before = knowledge.inspect_page_source()
    print(json.dumps(before.model_dump(), indent=2))
    result = knowledge.migrate_page_source(
        expected_source=args.expected_source,
        target_source=args.target_source,
        dry_run=not args.apply,
    )
    print(result.model_dump_json(indent=2))
    print(
        "Next: sync the target with the same transform and index_version to refresh citations."
    )


if __name__ == "__main__":
    main()

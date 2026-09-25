"""Relocate an indexed site's hostname without private SQL; dry-run by default.

Calls Knowledge.setup() before inspecting, so on uninitialized storage it creates
the page schema even in dry-run mode. Relocation changes only the source binding;
a normal sync against the target refreshes citations afterward. If the command
fails after --apply began (timeout, lost connection), inspect the binding or repeat
the same guarded request; a client-side error does not prove a rollback.
"""

import argparse
import json


def next_steps(result) -> str:
    """Operator guidance derived from the migration result, not from the --apply flag."""
    if result.dry_run:
        if result.after.source == result.target_source:
            return (
                "Dry run: no source relocation was applied by this invocation. "
                "The binding already points to the target."
            )
        return (
            "Dry run: no source relocation was applied by this invocation. "
            "Re-run with --apply to relocate the binding; the current source stays active until then."
        )
    if result.changed:
        return (
            "Relocation applied: the source binding now points to the target.\n"
            "Next: point every sync producer at the target (for this example, set PAGE_DEMO_INDEX_URL), "
            "restart producers that read their configuration at startup, then run a normal sync with "
            "the same transform and index_version to refresh citations. "
            "A sync still configured with the old source is refused."
        )
    return (
        "The binding already points to the target; no additional binding change was made.\n"
        "If sync producers were not yet updated or citations not yet refreshed, do that now: "
        "set the sync source to the target and run a normal sync with the same transform and index_version."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("expected_source", help="Current HTTPS llms.txt URL")
    parser.add_argument(
        "target_source", help="Same corpus and discovery path on the new host"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Commit the guarded binding update"
    )
    args = parser.parse_args()

    from public_pages import knowledge

    print(
        "Preparing page storage; setup runs before inspection and may initialize schema."
    )
    knowledge.setup()
    before = knowledge.inspect_page_source()
    print(json.dumps(before.model_dump(), indent=2))
    result = knowledge.migrate_page_source(
        expected_source=args.expected_source,
        target_source=args.target_source,
        dry_run=not args.apply,
    )
    print(result.model_dump_json(indent=2))
    print(next_steps(result))


if __name__ == "__main__":
    main()

# Cookbook → Docs Weekly Sync Runbook

Use this to run the Cookbook → Docs sync once per week. It is split into executable phases and checks.

## Goal
- Keep `docs/examples/` synchronized with `cookbook/`
- Keep `docs/docs.json` Examples tab aligned to canonical hierarchy
- Ensure docs quality and avoid broken links

## Inputs
- `cookbook/` (source)
- `docs/examples/` (destination)
- `docs/docs.json` (navigation)
- Mapping rules in the existing prompt (keep exactly)

## Phase 1: Preflight
1. Confirm current branch is `main` and changes are clean.
2. Confirm symlinked `docs/` and `specs/` are present if needed.
3. Confirm there are no ad-hoc manual edits to the same files you are about to regenerate.
4. Review the prompt for any new exceptions or overrides before running.

## Phase 2: Source inventory (authoritative set)
1. Enumerate all cookbook `.py` files recursively.
2. Exclude:
   - `__init__.py`
   - `conftest.py`
   - `scripts/` helper scripts (keep skill scripts if present)
   - `__pycache__/`
3. Preserve nested directory structure and apply path remapping:
   - strip `cookbook/`
   - strip numeric prefixes (`00_`, `01_`, ...)
   - directory and filename underscores → hyphens
   - filename `.py` → `.mdx`
4. For every cookbook file, determine target mdx path under `docs/examples/`.

## Phase 3: MDX generation/update per script
For each source script:
1. Generate (or update) MDX with this structure:
   - frontmatter: `title`, optional `sidebarTitle`, `description`
   - optional intro paragraph
   - fenced Python code block with original source copied verbatim
   - `Run the Example` shell block
2. Metadata derivation order:
   - `title`: from docstring top title unless sentence-like, then derive from filename
   - `sidebarTitle`: context-aware stripping only by section
   - `description`: first sentence after separator line; fallback heuristics from code when needed
3. `Run the Example` block requirements:
   - `cd agno/cookbook/<actual cookbook path>` with numeric prefixes intact
   - use original Python filename for execution command
4. Quality constraints:
   - Never add emojis
   - Never change Python source logic

## Phase 4: Overview pages
1. For every relevant docs directory that has scripts or subdirs:
   - ensure `overview.mdx` exists/updated
   - include `title`, `sidebarTitle: "Overview"`, `description`
   - include table of examples sorted appropriately:
     - numbered entries first (in numeric order)
     - then alphabetical
   - no sentence-style link text
   - no trailing period in link text
   - link text max 40 chars
2. Use each page’s description in overview table rows (not duplicate link text).

## Phase 5: Sidebar rebuild (`docs/docs.json`)
1. Replace only the Examples tab in `docs/docs.json` (`navigation.tabs[4]`).
2. Keep all other tabs unchanged.
3. Rebuild the entire Examples structure with ordered groups and merged sections.
4. Use relative paths under `examples/` without `.mdx` extension.
5. Resolve every merged group (Tools, Human in the Loop, Hooks & Context, Advanced, etc.) per prompt rules.
6. Use `examples/overview` page as the top-level first entry.

## Phase 6: Global quality fix pass
Apply fixes across all generated docs:
1. Replace all `virual` with `virtual`.
2. Ensure no `cd agno/<digit>`; all such paths must be `cd agno/cookbook/<digit...>`.
3. Ensure frontmatter keys are unique (no duplicate `sidebarTitle`).
4. Require blank line between `---` and content.
5. Remove sentence-style overview link text and trailing periods in link text.

## Phase 7: Cleanup
1. Remove `docs/examples` `.mdx` files that no longer map to a cookbook script (keep `overview.mdx`).
2. Remove `docs/examples/demo/` if present.

## Phase 8: Verification checklist (must pass)
1. `docs/examples/demo/` absent.
2. No `virual` in docs/examples.
3. No `cd agno/<digit>` patterns.
4. No duplicate `sidebarTitle` keys.
5. No missing frontmatter-content separator.
6. Sidebar context behavior for agents/teams prefixes.
7. Overview link texts valid (no sentence style, no trailing period, <= 40 chars).
8. Every `docs.json` examples page has a corresponding `.mdx`.
9. Every non-overview `.mdx` has a corresponding `.py` source.
10. `Run the Example` code blocks use cookbook-preserving paths.

## Phase 9: Weekly run log (recommended)
Record each weekly run:
- Run timestamp
- Count cookbook scripts processed
- Count mdx created/updated
- Count removed files
- Validation failures and fixes
- Notes for manual review

## Recommended cadence
- Run the full runbook once weekly.
- If cookbook churn is high, add a lighter daily/bi-weekly precheck for steps 1–3 only and run full steps 4–8 weekly.

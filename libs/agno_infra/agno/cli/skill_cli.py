"""Agno Skill CLI

CLI commands for managing Agent Skills.
"""

from typing import Optional

import typer

from agno.utilities.logging import set_log_level_to_debug

skill_cli = typer.Typer(
    name="skill",
    short_help="Manage Agent Skills",
    help="""\b
Use `ag skill [COMMAND]` to create, validate, or list Agent Skills.
Run `ag skill [COMMAND] --help` for more info.
\b
A skill directory contains:
  SKILL.md      - Main skill file with YAML frontmatter and instructions
  scripts/      - Executable scripts the agent can run (created by default)
  references/   - Reference docs the agent can load on-demand (created by default)
\b
Examples:
> ag skill create                     -> Create a new skill with scripts/ and references/
> ag skill create -n my-skill         -> Create a skill with a specific name
> ag skill create -n my-skill -p ./skills  -> Create skill in ./skills/my-skill/
> ag skill create --no-scripts        -> Create without the scripts/ directory
> ag skill create --no-references     -> Create without the references/ directory
> ag skill validate ./my-skill        -> Validate a skill directory
> ag skill list ./skills              -> List skills in a directory
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="",
    subcommand_metavar="[COMMAND] [OPTIONS]",
)


@skill_cli.command(short_help="Create a new skill with proper directory structure")
def create(
    name: Optional[str] = typer.Option(
        None,
        "-n",
        "--name",
        help="Name of the skill (lowercase, alphanumeric with hyphens).",
        show_default=False,
    ),
    path: Optional[str] = typer.Option(
        None,
        "-p",
        "--path",
        help="Directory where the skill folder will be created (default: current directory).",
        show_default=False,
    ),
    description: Optional[str] = typer.Option(
        None,
        "-d",
        "--description",
        help="Short description of the skill.",
        show_default=False,
    ),
    no_scripts: bool = typer.Option(
        False,
        "--no-scripts",
        help="Skip creating the scripts/ subdirectory.",
    ),
    no_references: bool = typer.Option(
        False,
        "--no-references",
        help="Skip creating the references/ subdirectory.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Create a new Agent Skill with the proper directory structure.

    This command scaffolds a skill folder with:
    - SKILL.md file with YAML frontmatter (name, description) and instruction sections
    - scripts/ directory for executable scripts the agent can run
    - references/ directory for reference docs the agent can load on-demand
    \b
    Scripts are useful for:
    - Running code analysis, linting, or formatting tools
    - Executing build or test commands
    - Any repeatable automation the agent needs
    \b
    References are useful for:
    - API documentation, style guides, or specifications
    - Project-specific conventions or standards
    - Any docs the agent should consult while working
    \b
    Examples:
    > ag skill create                         -> Create skill with scripts/ and references/
    > ag skill create -n my-skill             -> Create skill named 'my-skill'
    > ag skill create -n my-skill -p ./skills -> Create in ./skills/my-skill/
    > ag skill create --no-scripts            -> Create without scripts/ directory
    > ag skill create --no-references         -> Create without references/ directory
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.skill.operator import create_skill_from_template

    create_skill_from_template(
        name=name,
        path=path,
        description=description,
        with_scripts=not no_scripts,
        with_references=not no_references,
    )


@skill_cli.command(short_help="Validate an existing skill directory")
def validate(
    path: str = typer.Argument(
        ".",
        help="Path to the skill directory to validate (default: current directory).",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Validate a skill directory against the Agent Skills specification.

    Checks for:
    - SKILL.md file exists with valid YAML frontmatter
    - Required fields (name, description) are present
    - Skill name matches directory name
    - Field values meet length requirements
    - No unknown fields in frontmatter
    \b
    Examples:
    > ag skill validate                  -> Validate skill in current directory
    > ag skill validate ./my-skill       -> Validate specific skill directory
    > ag skill validate ./skills/code-review
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.skill.operator import validate_skill

    success = validate_skill(path=path)

    # Exit with appropriate code for scripting
    if not success:
        raise typer.Exit(code=1)


@skill_cli.command(name="list", short_help="List skills in a directory")
def list_skills(
    path: str = typer.Argument(
        ".",
        help="Path to directory containing skills (default: current directory).",
    ),
    verbose: bool = typer.Option(
        False,
        "-v",
        "--verbose",
        help="Show detailed information about each skill in a table.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    List all valid skills found in a directory.

    Scans the given directory for subdirectories containing SKILL.md files
    and displays information about each valid skill found.
    \b
    Examples:
    > ag skill list                      -> List skills in current directory
    > ag skill list ./skills             -> List skills in ./skills/
    > ag skill list ./skills -v          -> Show detailed table view
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.skill.operator import list_skills as _list_skills

    _list_skills(path=path, verbose=verbose)

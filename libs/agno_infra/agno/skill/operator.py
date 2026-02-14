"""Skill operations for the CLI."""

from pathlib import Path
from typing import List, Optional, Tuple, Union

from rich.prompt import Prompt
from rich.table import Table

from agno.cli.console import (
    console,
    error_style,
    print_heading,
    print_info,
    print_subheading,
    success_style,
)
from agno.skills.validator import MAX_DESCRIPTION_LENGTH, MAX_SKILL_NAME_LENGTH

# Type alias for skill info: (name, description, scripts_count, refs_count)
SkillInfo = Tuple[str, str, int, int]

def _validate_skill_name(name: str) -> List[str]:
    """Validate skill name format.

    This is a local validation to provide fast feedback before creating.
    The full validation from agno.skills.validator is used for complete validation.

    Args:
        name: The skill name to validate.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors: List[str] = []

    if not name or not name.strip():
        errors.append("Skill name cannot be empty")
        return errors

    name = name.strip()

    if len(name) > MAX_SKILL_NAME_LENGTH:
        errors.append(f"Skill name exceeds {MAX_SKILL_NAME_LENGTH} character limit ({len(name)} chars)")

    if name != name.lower():
        errors.append("Skill name must be lowercase")

    if name.startswith("-") or name.endswith("-"):
        errors.append("Skill name cannot start or end with a hyphen")

    if "--" in name:
        errors.append("Skill name cannot contain consecutive hyphens")

    if not all(c.isalnum() or c == "-" for c in name):
        errors.append("Skill name can only contain letters, digits, and hyphens")

    return errors


def create_skill_from_template(
    name: Optional[str] = None,
    path: Optional[str] = None,
    description: Optional[str] = None,
    with_scripts: bool = True,
    with_references: bool = True,
) -> Optional[Path]:
    """Create a new skill directory with proper structure.

    Args:
        name: Skill name (lowercase, alphanumeric with hyphens).
        path: Directory where skill folder will be created (default: cwd).
        description: Short description of the skill.
        with_scripts: Include a scripts/ subdirectory (default: True).
        with_references: Include a references/ subdirectory (default: True).

    Returns:
        Path to the created skill directory, or None if creation failed.
    """
    from agno.skill.templates import (
        generate_references_readme,
        generate_script_readme,
        generate_skill_md_content,
    )

    current_dir = Path(path or ".").resolve()

    print_subheading("Creating a new Agent Skill...\n")

    # Get skill name interactively if not provided
    if name is None:
        name = Prompt.ask(
            "Skill name [dim](lowercase, alphanumeric with hyphens)[/dim]",
            default="my-skill",
            console=console,
        )

    # Validate name format before proceeding
    name_errors = _validate_skill_name(name)
    if name_errors:
        console.print("\n[bold red]Invalid skill name:[/bold red]")
        for error in name_errors:
            console.print(f"  - {error}", style=error_style)
        return None

    # Get description interactively if not provided
    if description is None:
        description = Prompt.ask(
            "Short description",
            default="A skill for agents",
            console=console,
        )

    if len(description) > MAX_DESCRIPTION_LENGTH:
        console.print(f"\n[bold red]Description too long ({len(description)} chars, max {MAX_DESCRIPTION_LENGTH})[/bold red]")
        return None

    # Create skill directory
    skill_dir = current_dir / name
    if skill_dir.exists():
        console.print(f"\n[bold red]Directory already exists: {skill_dir}[/bold red]")
        console.print("Please choose a different name or delete the existing directory.")
        return None

    try:
        skill_dir.mkdir(parents=True)

        # Create SKILL.md
        skill_md_content = generate_skill_md_content(
            name=name,
            description=description,
        )
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(skill_md_content, encoding="utf-8")

        # Create scripts and references directories (included by default)
        if with_scripts:
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "README.md").write_text(
                generate_script_readme(),
                encoding="utf-8",
            )

        if with_references:
            refs_dir = skill_dir / "references"
            refs_dir.mkdir()
            (refs_dir / "README.md").write_text(
                generate_references_readme(),
                encoding="utf-8",
            )

        # Print success message
        console.print("\n" + "─" * 50)
        console.print(f"[bold green]Created skill at:[/bold green] {skill_dir}")
        console.print("")
        console.print("[bold]Created files:[/bold]")
        console.print(f"  - {name}/SKILL.md")
        if with_scripts:
            console.print(f"  - {name}/scripts/README.md")
        if with_references:
            console.print(f"  - {name}/references/README.md")
        console.print("")
        console.print("[bold]Next steps:[/bold]")
        steps = [f"Edit [cyan]{skill_dir}/SKILL.md[/cyan] to add instructions"]
        if with_scripts:
            steps.append(f"Add scripts to [cyan]{skill_dir}/scripts/[/cyan]")
        if with_references:
            steps.append(f"Add reference docs to [cyan]{skill_dir}/references/[/cyan]")
        steps.append(f"Run [cyan]ag skill validate {skill_dir}[/cyan] to verify")
        for i, step in enumerate(steps, 1):
            console.print(f"  {i}. {step}")
        console.print("─" * 50)

        return skill_dir

    except Exception as e:
        console.print(f"\n[bold red]Error creating skill: {e}[/bold red]")
        # Clean up partial creation
        if skill_dir.exists():
            import shutil

            shutil.rmtree(skill_dir)
        return None


def validate_skill(path: str) -> bool:
    """Validate a skill directory and print results.

    Args:
        path: Path to the skill directory to validate.

    Returns:
        True if validation passed, False otherwise.
    """
    skill_path = Path(path).resolve()

    print_heading(f"Validating skill: {skill_path.name}")
    print_info(f"Path: {skill_path}\n")

    # Try to import validation from agno package
    try:
        from agno.skills.validator import validate_skill_directory
    except ImportError:
        console.print("[bold red]Error:[/bold red] Could not import agno.skills.validator")
        console.print("Please ensure the 'agno' package is installed:")
        console.print("  pip install agno")
        return False

    errors = validate_skill_directory(skill_path)

    if errors:
        console.print("[bold red]Validation FAILED[/bold red]\n")
        for i, error in enumerate(errors, 1):
            console.print(f"  {i}. {error}", style=error_style)
        console.print("")
        console.print("[dim]Fix the errors above and run validation again.[/dim]")
        return False
    else:
        console.print("[bold green]Validation PASSED[/bold green]")
        console.print("  Skill structure and metadata are valid.", style=success_style)

        # Show skill summary
        _print_skill_summary(skill_path)
        return True


def _print_skill_summary(skill_path: Path) -> None:
    """Print a summary of the skill contents."""
    scripts_dir = skill_path / "scripts"
    refs_dir = skill_path / "references"

    scripts = []
    if scripts_dir.exists() and scripts_dir.is_dir():
        scripts = [f.name for f in scripts_dir.iterdir() if f.is_file() and not f.name.startswith(".")]

    references = []
    if refs_dir.exists() and refs_dir.is_dir():
        references = [f.name for f in refs_dir.iterdir() if f.is_file() and not f.name.startswith(".")]

    console.print("")
    console.print("[bold]Skill contents:[/bold]")
    console.print(f"  Scripts: {len(scripts)} file(s)")
    if scripts:
        for s in scripts[:5]:  # Show first 5
            console.print(f"    - {s}")
        if len(scripts) > 5:
            console.print(f"    ... and {len(scripts) - 5} more")

    console.print(f"  References: {len(references)} file(s)")
    if references:
        for r in references[:5]:  # Show first 5
            console.print(f"    - {r}")
        if len(references) > 5:
            console.print(f"    ... and {len(references) - 5} more")


def list_skills(path: str, verbose: bool = False) -> None:
    """List skills in a directory.

    Args:
        path: Path to directory containing skills.
        verbose: Show detailed information about each skill.
    """
    skills_path = Path(path).resolve()

    print_heading(f"Skills in: {skills_path}")

    if not skills_path.exists():
        console.print(f"\n[bold red]Path does not exist:[/bold red] {skills_path}")
        return

    if not skills_path.is_dir():
        console.print(f"\n[bold red]Not a directory:[/bold red] {skills_path}")
        return

    # Check if path is a single skill or directory of skills
    skill_md = skills_path / "SKILL.md"
    is_single_skill = skill_md.exists()

    skills_found: List[Tuple[str, str, int, int]] = []  # (name, description, scripts, refs)
    errors_found: List[Tuple[str, List[str]]] = []

    if is_single_skill:
        # Single skill directory
        result = _load_skill_info(skills_path)
        if result[0]:  # success
            skills_found.append(result[1])
        else:
            errors_found.append((skills_path.name, result[1]))
    else:
        # Directory of skills - iterate and load each
        for item in sorted(skills_path.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                item_skill_md = item / "SKILL.md"
                if item_skill_md.exists():
                    result = _load_skill_info(item)
                    if result[0]:  # success
                        skills_found.append(result[1])
                    else:
                        errors_found.append((item.name, result[1]))

    if not skills_found and not errors_found:
        console.print("\n[yellow]No skills found in this directory.[/yellow]")
        console.print("Skills must contain a SKILL.md file.")
        console.print("\nTo create a new skill, run:")
        console.print("  [cyan]ag skill create[/cyan]")
        return

    # Display valid skills
    if skills_found:
        console.print(f"\n[bold green]Found {len(skills_found)} valid skill(s):[/bold green]\n")

        if verbose:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Name", style="cyan")
            table.add_column("Description")
            table.add_column("Scripts", justify="center")
            table.add_column("References", justify="center")

            for name, desc, scripts, refs in skills_found:
                desc_display = desc[:50] + "..." if len(desc) > 50 else desc
                table.add_row(name, desc_display, str(scripts), str(refs))

            console.print(table)
        else:
            for name, desc, _, _ in skills_found:
                desc_display = desc[:60] + "..." if len(desc) > 60 else desc
                console.print(f"  [cyan]{name}[/cyan]: {desc_display}")

    # Display invalid skills
    if errors_found:
        console.print(f"\n[bold red]Found {len(errors_found)} invalid skill(s):[/bold red]\n")
        for skill_name, errors in errors_found:
            console.print(f"  [bold]{skill_name}[/bold]:", style=error_style)
            for error in errors[:3]:  # Show first 3 errors
                console.print(f"    - {error}")
            if len(errors) > 3:
                console.print(f"    ... and {len(errors) - 3} more error(s)")


def _load_skill_info(skill_path: Path) -> Tuple[bool, Union[SkillInfo, List[str]]]:
    """Load skill info for listing.

    Args:
        skill_path: Path to the skill directory.

    Returns:
        Tuple of (success, data) where data is either:
        - On success: (name, description, scripts_count, refs_count)
        - On failure: list of error messages
    """
    try:
        from agno.skills.validator import validate_skill_directory
    except ImportError:
        return (False, ["Could not import agno.skills.validator"])

    # Validate first
    errors = validate_skill_directory(skill_path)
    if errors:
        return (False, errors)

    # Parse SKILL.md for display info
    try:
        skill_md = skill_path / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        # Parse frontmatter
        name = skill_path.name
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                import yaml

                try:
                    frontmatter = yaml.safe_load(parts[1])
                    if isinstance(frontmatter, dict):
                        name = frontmatter.get("name", skill_path.name)
                        description = frontmatter.get("description", "")
                except Exception:
                    pass

        # Count scripts and references
        scripts_dir = skill_path / "scripts"
        refs_dir = skill_path / "references"

        scripts_count = 0
        if scripts_dir.exists() and scripts_dir.is_dir():
            scripts_count = len([f for f in scripts_dir.iterdir() if f.is_file() and not f.name.startswith(".")])

        refs_count = 0
        if refs_dir.exists() and refs_dir.is_dir():
            refs_count = len([f for f in refs_dir.iterdir() if f.is_file() and not f.name.startswith(".")])

        return (True, (name, description, scripts_count, refs_count))

    except Exception as e:
        return (False, [f"Error reading skill: {e}"])

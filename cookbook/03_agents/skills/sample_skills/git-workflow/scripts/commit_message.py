"""Commit message generator and validator.

This script provides utilities for generating and validating
conventional commit messages.
"""

COMMIT_TYPES = {
    "feat": "A new feature for the user",
    "fix": "A bug fix for the user",
    "docs": "Documentation only changes",
    "style": "Formatting, missing semicolons, etc.",
    "refactor": "Code change that neither fixes a bug nor adds a feature",
    "perf": "Performance improvement",
    "test": "Adding or updating tests",
    "chore": "Maintenance tasks",
    "build": "Build system or external dependencies",
    "ci": "CI/CD configuration",
    "revert": "Reverting a previous commit",
}


def validate_commit_message(message: str) -> dict:
    """Validate a commit message against conventional commit format.

    Args:
        message: The commit message to validate.

    Returns:
        A dictionary with validation results.
    """
    lines = message.strip().split("\n")
    if not lines:
        return {"valid": False, "errors": ["Commit message is empty"]}

    errors = []
    warnings = []
    subject = lines[0]

    # Check subject line format: type(scope): description
    if ":" not in subject:
        errors.append("Subject line must contain ':' separator")
    else:
        prefix, description = subject.split(":", 1)
        prefix = prefix.strip()
        description = description.strip()

        # Extract type and optional scope
        if "(" in prefix and ")" in prefix:
            commit_type = prefix.split("(")[0].rstrip("!")
            _ = prefix.split("(")[1].split(")")[0]  # scope (for future use)
        else:
            commit_type = prefix.rstrip("!")

        # Validate type
        if commit_type not in COMMIT_TYPES:
            errors.append(
                f"Invalid commit type '{commit_type}'. Valid types: {', '.join(COMMIT_TYPES.keys())}"
            )

        # Check description
        if not description:
            errors.append("Description is required after ':'")
        elif description[0].isupper():
            warnings.append("Description should start with lowercase letter")
        elif description.endswith("."):
            warnings.append("Description should not end with a period")

        # Check subject length
        if len(subject) > 72:
            warnings.append(
                f"Subject line is {len(subject)} chars (recommended max: 72)"
            )

    # Check for body separation
    if len(lines) > 1 and lines[1].strip():
        warnings.append("Second line should be blank (separates subject from body)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def generate_commit_message(
    commit_type: str,
    scope: str | None,
    description: str,
    body: str | None = None,
    breaking: bool = False,
    issue_refs: list[str] | None = None,
) -> str:
    """Generate a conventional commit message.

    Args:
        commit_type: The type of commit (feat, fix, etc.).
        scope: Optional scope of the change.
        description: Short description of the change.
        body: Optional detailed description.
        breaking: Whether this is a breaking change.
        issue_refs: Optional list of issue references (e.g., ["#123", "#456"]).

    Returns:
        A formatted commit message string.
    """
    # Build subject line
    subject = commit_type
    if scope:
        subject += f"({scope})"
    if breaking:
        subject += "!"
    subject += f": {description}"

    parts = [subject]

    # Add body if provided
    if body:
        parts.append("")  # Blank line
        parts.append(body)

    # Add footer with issue references
    if issue_refs:
        parts.append("")  # Blank line
        for ref in issue_refs:
            if ref.startswith("#"):
                parts.append(f"Closes {ref}")
            else:
                parts.append(ref)

    # Add breaking change notice if applicable
    if breaking and body:
        parts.append("")
        parts.append("BREAKING CHANGE: See description for migration steps.")

    return "\n".join(parts)


def suggest_commit_type(changed_files: list[str]) -> str:
    """Suggest a commit type based on changed files.

    Args:
        changed_files: List of file paths that were changed.

    Returns:
        Suggested commit type.
    """
    test_files = [
        f for f in changed_files if "test" in f.lower() or "spec" in f.lower()
    ]
    doc_files = [
        f
        for f in changed_files
        if f.endswith((".md", ".rst", ".txt")) or "doc" in f.lower()
    ]
    config_files = [
        f
        for f in changed_files
        if f.endswith((".yml", ".yaml", ".json", ".toml", ".ini"))
    ]

    if all(f in test_files for f in changed_files):
        return "test"
    elif all(f in doc_files for f in changed_files):
        return "docs"
    elif all(f in config_files for f in changed_files):
        return "chore"
    else:
        return "feat"  # Default suggestion

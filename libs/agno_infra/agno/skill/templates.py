"""Templates for skill scaffolding."""

from typing import Optional


def generate_skill_md_content(
    name: str,
    description: str,
    license_info: Optional[str] = None,
    compatibility: Optional[str] = None,
) -> str:
    """Generate SKILL.md content with proper YAML frontmatter.

    Args:
        name: The skill name (lowercase, alphanumeric with hyphens).
        description: Short description of the skill.
        license_info: Optional license identifier (e.g., "MIT", "Apache-2.0").
        compatibility: Optional compatibility requirements.

    Returns:
        A properly formatted SKILL.md file content.
    """
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]

    if license_info:
        frontmatter_lines.append(f"license: {license_info}")

    if compatibility:
        frontmatter_lines.append(f"compatibility: {compatibility}")

    frontmatter_lines.append("---")

    body = f"""
# {name}

{description}

## Instructions

<!-- Add detailed instructions for the agent here -->
<!-- The agent will load these instructions when it needs to use this skill -->

## When to Use This Skill

<!-- Describe the scenarios where the agent should use this skill -->

## Process

1. Step one
2. Step two
3. Step three

## Examples

<!-- Add usage examples here -->

"""

    return "\n".join(frontmatter_lines) + body


def generate_script_readme() -> str:
    """Generate README content for the scripts directory."""
    return """# Scripts

Place executable scripts in this directory.

## Requirements

- Scripts must have a shebang line (e.g., `#!/usr/bin/env python3`)
- Scripts should be executable (`chmod +x script.py`)

## Example Script

```python
#!/usr/bin/env python3
\"\"\"Example script for the skill.\"\"\"

import json

def main():
    result = {"status": "success", "message": "Hello from skill script"}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
```

## Usage

The agent can execute scripts using:
```
get_skill_script(skill_name, script_path, execute=True)
```
"""


def generate_references_readme() -> str:
    """Generate README content for the references directory."""
    return """# References

Place reference documentation in this directory.

## Supported Formats

- Markdown files (`.md`)
- Text files (`.txt`)
- Any other text-based documentation

## Example Reference

Create a file like `guide.md` with detailed documentation that the agent
can load on-demand using:

```
get_skill_reference(skill_name, "guide.md")
```

## Best Practices

1. Keep reference docs focused on specific topics
2. Use clear, descriptive filenames
3. Include examples where helpful
"""

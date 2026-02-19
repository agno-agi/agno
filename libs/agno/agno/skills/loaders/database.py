"""Database loader for skills stored in PostgreSQL."""

import re
from typing import Any, Dict, List, Optional

from agno.skills.errors import SkillParseError, SkillValidationError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.utils.log import log_debug, log_warning


class DatabaseSkills(SkillLoader):
    """Loads skills from a PostgreSQL database.

    This loader reads skills from a normalized database schema with:
    - skills table: id, name, description, instructions, metadata, license, compatibility, allowed_tools
    - scripts table: id, skill_id, name, content, file_name
    - references table: id, skill_id, name, content, file_name

    Args:
        conn_str: PostgreSQL connection string.
        table_prefix: Prefix for table names (default: empty, tables are named skills/scripts/references).
        validate: Whether to validate skills. Currently no-op for DB skills.
    """

    def __init__(
        self,
        conn_str: str,
        table_prefix: str = "",
        validate: bool = True,
    ):
        self.conn_str = conn_str
        self.table_prefix = table_prefix.strip()
        self.validate = validate

    def load(self) -> List[Skill]:
        """Load skills from the PostgreSQL database.

        Returns:
            A list of Skill objects loaded from the database.

        Raises:
            ImportError: If psycopg2 is not installed.
            RuntimeError: If there's an error connecting to or querying the database.
        """
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError:
            raise ImportError(
                "psycopg2 is required for database skill loading. "
                "Install it with: pip install psycopg2-binary"
            )

        skills: List[Skill] = []

        try:
            with psycopg2.connect(self.conn_str) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    # Load skills
                    skills_data = self._get_skills(cursor)
                    if not skills_data:
                        log_warning("No skills found in database")
                        return []

                    # Load scripts and references for each skill
                    for skill_data in skills_data:
                        skill_id = skill_data["id"]
                        scripts = self._get_scripts(cursor, skill_id)
                        references = self._get_references(cursor, skill_id)

                        skill = self._create_skill(skill_data, scripts, references)
                        if skill:
                            skills.append(skill)

            log_debug(f"Loaded {len(skills)} skills from database")
            return skills

        except psycopg2.Error as e:
            raise RuntimeError(f"Database error while loading skills: {e}") from e

    def _get_skills(self, cursor) -> List[Dict[str, Any]]:
        """Get all skills from the database."""
        skills_table = f"{self.table_prefix}skills" if self.table_prefix else "skills"

        query = f"""
            SELECT
                id,
                name,
                description,
                instructions,
                metadata,
                license,
                compatibility,
                allowed_tools
            FROM {skills_table}
            ORDER BY name
        """
        cursor.execute(query)
        return cursor.fetchall()

    def _get_scripts(self, cursor, skill_id: int) -> List[str]:
        """Get scripts for a specific skill."""
        scripts_table = f"{self.table_prefix}scripts" if self.table_prefix else "scripts"

        query = f"""
            SELECT file_name
            FROM {scripts_table}
            WHERE skill_id = %s
            ORDER BY file_name
        """
        cursor.execute(query, (skill_id,))
        return [row["file_name"] for row in cursor.fetchall()]

    def _get_references(self, cursor, skill_id: int) -> List[str]:
        """Get references for a specific skill."""
        references_table = f"{self.table_prefix}references" if self.table_prefix else "references"

        query = f"""
            SELECT file_name
            FROM {references_table}
            WHERE skill_id = %s
            ORDER BY file_name
        """
        cursor.execute(query, (skill_id,))
        return [row["file_name"] for row in cursor.fetchall()]

    def _create_skill(
        self, skill_data: Dict[str, Any], scripts: List[str], references: List[str]
    ) -> Optional[Skill]:
        """Create a Skill object from database data.

        Args:
            skill_data: Row data from the skills table.
            scripts: List of script filenames.
            references: List of reference filenames.

        Returns:
            A Skill object if successful, None otherwise.
        """
        try:
            # Parse instructions (handle YAML frontmatter if present)
            instructions = self._parse_instructions(skill_data["instructions"])

            # Parse metadata JSON if it's a string
            metadata = skill_data.get("metadata")
            if isinstance(metadata, str):
                import json

                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError as e:
                    log_warning(f"Error parsing metadata JSON for skill '{skill_data['name']}': {e}")
                    metadata = None

            # Parse allowed_tools if it's a string (array format)
            allowed_tools = skill_data.get("allowed_tools")
            if isinstance(allowed_tools, str):
                allowed_tools = self._parse_array_string(allowed_tools)
            elif allowed_tools is None:
                allowed_tools = []

            return Skill(
                name=skill_data["name"],
                description=skill_data.get("description") or "",
                instructions=instructions,
                source_path=f"database:{skill_data['id']}",
                scripts=scripts,
                references=references,
                metadata=metadata,
                license=skill_data.get("license"),
                compatibility=skill_data.get("compatibility"),
                allowed_tools=allowed_tools if allowed_tools else None,
            )

        except Exception as e:
            log_warning(f"Error creating skill '{skill_data.get('name', 'unknown')}': {e}")
            return None

    def _parse_instructions(self, content: str) -> str:
        """Parse instructions, extracting body from YAML frontmatter if present.

        Args:
            content: The raw instructions content (may have YAML frontmatter).

        Returns:
            The instructions body without frontmatter.
        """
        if not content:
            return ""

        # Check for YAML frontmatter (between --- delimiters)
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)

        if frontmatter_match:
            return frontmatter_match.group(2).strip()

        return content

    def _parse_array_string(self, value: str) -> List[str]:
        """Parse a string representation of an array.

        Handles formats like:
        - JSON: ["tool1", "tool2"]
        - PostgreSQL array: {tool1,tool2}
        - Comma-separated: tool1, tool2

        Args:
            value: The string representation of an array.

        Returns:
            A list of strings.
        """
        if not value:
            return []

        value = value.strip()

        # Try JSON parsing first
        if value.startswith("[") or value.startswith("{"):
            try:
                import json

                # Replace PostgreSQL array braces with JSON brackets
                cleaned = value.replace("{", "[").replace("}", "]")
                result = json.loads(cleaned)
                if isinstance(result, list):
                    return [str(item) for item in result]
            except (json.JSONDecodeError, ValueError):
                pass

        # Fall back to comma-separated
        return [item.strip() for item in value.split(",") if item.strip()]

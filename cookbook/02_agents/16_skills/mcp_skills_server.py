"""
MCP Skills Server
=============================

A minimal MCP server that serves the skills in `sample_skills/` through the
MCP Skills extension (`io.modelcontextprotocol/skills`).

Each file of a skill is exposed as a `skill://<name>/<path>` resource, and the
server answers `skills/list` and `skills/get` with each skill's frontmatter and
a manifest of its files (digest and size), which the client verifies on read.

Run it standalone with `python mcp_skills_server.py`; `mcp_skills.py` starts it over stdio.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp.types import PaginatedRequestParams, RequestParams

SKILLS_DIR = Path(__file__).parent / "sample_skills"


# ---------------------------------------------------------------------------
# Build Skill Entries
# ---------------------------------------------------------------------------
def build_entry(skill_dir: Path) -> Dict[str, Any]:
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", skill_md, re.DOTALL)
    frontmatter = yaml.safe_load(match.group(1)) if match else {}
    name = frontmatter["name"]

    resources = []
    for path in sorted(
        p for p in skill_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    ):
        data = path.read_bytes()
        resources.append(
            {
                "uri": f"skill://{name}/{path.relative_to(skill_dir).as_posix()}",
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return {
        "uri": f"skill://{name}/SKILL.md",
        "frontmatter": frontmatter,
        "resources": resources,
    }


ENTRIES: Dict[str, Dict[str, Any]] = {}
FILES: Dict[str, Path] = {}
for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").exists()):
    entry = build_entry(skill_dir)
    ENTRIES[entry["uri"]] = entry
    for resource in entry["resources"]:
        relative = resource["uri"].split("/", 3)[3]
        FILES[resource["uri"]] = skill_dir / relative


# ---------------------------------------------------------------------------
# Skills Extension
# ---------------------------------------------------------------------------
class GetSkillParams(RequestParams):
    uri: str


class SkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def resources(self) -> List[ResourceBinding]:
        return [
            ResourceBinding(
                TextResource(
                    uri=uri,
                    name=path.name,
                    text=path.read_text(encoding="utf-8"),
                    mime_type="text/markdown" if path.suffix == ".md" else "text/plain",
                )
            )
            for uri, path in FILES.items()
        ]

    def methods(self) -> List[MethodBinding]:
        async def list_skills(
            ctx: Any, params: PaginatedRequestParams
        ) -> Dict[str, Any]:
            return {
                "resultType": "complete",
                "skills": list(ENTRIES.values()),
                "ttlMs": 60000,
                "cacheScope": "public",
            }

        async def get_skill(ctx: Any, params: GetSkillParams) -> Dict[str, Any]:
            if params.uri not in ENTRIES:
                raise MCPError(
                    code=-32602, message=f"No skill is served at {params.uri}"
                )
            return {
                "resultType": "complete",
                "skill": ENTRIES[params.uri],
                "ttlMs": 60000,
                "cacheScope": "public",
            }

        return [
            MethodBinding("skills/list", PaginatedRequestParams, list_skills),
            MethodBinding("skills/get", GetSkillParams, get_skill),
        ]


server = MCPServer("sample-skills", extensions=[SkillsExtension()])


# ---------------------------------------------------------------------------
# Run Server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    server.run()

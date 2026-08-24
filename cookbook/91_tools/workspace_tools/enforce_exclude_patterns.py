"""
Workspace — enforce_exclude_patterns
====================================

By default, exclude_patterns only filter listings — an agent can still
read_file(".env") directly. With enforce_exclude_patterns=True, excluded
paths are fully blocked from ALL file operations.

Key security features:
1. Direct-path operations (read/write/edit/delete/move) reject excluded paths
2. Case-insensitive matching: .ENV is blocked by .env* (for macOS/Windows)
3. No existence oracle: excluded paths return the same error whether they exist or not
4. Move operations check BOTH source and destination
"""

import tempfile
from pathlib import Path

from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Setup: Create a workspace with sensitive files
# ---------------------------------------------------------------------------
workspace_dir = Path(tempfile.mkdtemp(prefix="secure_workspace_"))

# Create some files
(workspace_dir / "README.md").write_text("# Public readme\n")
(workspace_dir / ".env").write_text("SECRET_KEY=supersecret123\n")
(workspace_dir / ".ENV.backup").write_text("OLD_SECRET=oldsecret\n")
(workspace_dir / "config").mkdir()
(workspace_dir / "config" / "settings.json").write_text('{"debug": true}\n')

print("Created workspace with files:")
for f in workspace_dir.rglob("*"):
    if f.is_file():
        print(f"  {f.relative_to(workspace_dir)}")

# ---------------------------------------------------------------------------
# Demo 1: Default behavior (exclude_patterns only filters listings)
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("DEFAULT: exclude_patterns only filters listings")
print("=" * 60)

ws_default = Workspace(
    str(workspace_dir),
    exclude_patterns=[".env*"],
)

# Listing skips .env files
files = ws_default.list_files()
print(f"\nlist_files() returns: {files}")
print("  -> .env files are hidden from listing")

# But direct read still works!
content = ws_default.read_file(".env")
print(f"\nread_file('.env') returns: {content}")
print("  -> SECURITY GAP: agent can still read secrets directly")

# ---------------------------------------------------------------------------
# Demo 2: enforce_exclude_patterns blocks ALL access
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("SECURE: enforce_exclude_patterns=True blocks ALL access")
print("=" * 60)

ws_secure = Workspace(
    str(workspace_dir),
    exclude_patterns=[".env*"],
    enforce_exclude_patterns=True,
)

# Direct read is blocked
result = ws_secure.read_file(".env")
print(f"\nread_file('.env') returns: {result}")
print("  -> Blocked!")

# Case variants are also blocked (important for macOS/Windows)
result = ws_secure.read_file(".ENV")
print(f"\nread_file('.ENV') returns: {result}")
print("  -> Case variant also blocked!")

result = ws_secure.read_file(".ENV.backup")
print(f"\nread_file('.ENV.backup') returns: {result}")
print("  -> Pattern matching works with casefold!")

# Write is blocked
result = ws_secure.write_file(".env.new", "HACK=true")
print(f"\nwrite_file('.env.new', ...) returns: {result}")
print("  -> Cannot create new .env files!")

# Move destination is checked
result = ws_secure.move_file("README.md", ".env.readme")
print(f"\nmove_file('README.md', '.env.readme') returns: {result}")
print("  -> Cannot move files INTO excluded patterns!")

# ---------------------------------------------------------------------------
# Demo 3: No existence oracle
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("NO EXISTENCE ORACLE: Same error whether file exists or not")
print("=" * 60)

result_exists = ws_secure.read_file(".env")
result_not_exists = ws_secure.read_file(".env.doesnotexist")
print(f"\nread_file('.env') [exists]:     {result_exists}")
print(f"read_file('.env.xyz') [missing]: {result_not_exists}")
print("  -> Same error! Cannot probe for file existence.")

# ---------------------------------------------------------------------------
# Demo 4: Non-excluded files still work normally
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("NON-EXCLUDED FILES: Normal access preserved")
print("=" * 60)

result = ws_secure.read_file("README.md")
print(f"\nread_file('README.md') returns: {result}")

result = ws_secure.read_file("config/settings.json")
print(f"\nread_file('config/settings.json') returns: {result}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("""
Use enforce_exclude_patterns=True when:
- Agents have access to directories with secrets (.env, credentials)
- You want hard enforcement, not just filtering
- Running on macOS/Windows where case variants reach the same file

The flag makes exclude_patterns a security boundary, not just a filter.
""")

"""Shared helpers for local filesystem-oriented tools."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Sequence, Tuple

# A pattern starting with this prefix names an exemption rather than an exclusion:
# a path component matching it is never excluded, whichever pattern it also matches.
EXEMPT_PREFIX = "!"

DEFAULT_EXCLUDE_PATTERNS = [
    # Agent and local scratch state
    ".context",
    ".conductor",
    ".claude",
    ".codex",
    ".cursor",
    # Environments and secrets
    ".venv",
    ".venvs",
    "venv",
    ".env*",
    "*.env",
    # A committed env template holds placeholders by definition and is where a repo
    # documents its variables, so it stays readable while real env files do not.
    # Without these the same file is served or refused depending on a leading dot:
    # `env.example` matches neither pattern above, `.env.example` matches both.
    "!.env.example",
    "!.env.sample",
    "!.env.template",
    "!.env.dist",
    "!example.env",
    "!env.example",
    # Private keys, certificates and keystores
    "*.pem",
    "*.key",
    "*.crt",
    "*.cer",
    "*.der",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.jceks",
    "*.keystore",
    "*.asc",
    "*.gpg",
    "*.ppk",
    "*.kdbx",
    "*.keytab",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "known_hosts",
    "authorized_keys",
    # Directories a credential-writing CLI keeps in a home directory. Patterns match a
    # single component and cannot name a path, so the directory is the only way to reach
    # the files inside it (`.aws/credentials`, `.kube/config`, `.docker/config.json`).
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".azure",
    ".m2",
    ".cargo",
    ".composer",
    # Registry, database and host tokens
    ".npmrc",
    ".pypirc",
    ".netrc",
    "_netrc",
    ".git-credentials",
    ".dockercfg",
    ".pgpass",
    ".my.cnf",
    ".boto",
    ".s3cfg",
    "rclone.conf",
    "kubeconfig",
    ".htpasswd",
    "htpasswd",
    # Credential and secret data files. Deliberately not `credentials.*` or `secrets.*`:
    # those also match ordinary source -- credentials.py, secrets.py, credentials.test.js,
    # docs/secrets.md -- and reading source is what these toolkits exist for. Bare
    # `credentials` is left out for the same reason: it would match a `credentials/`
    # package directory and hide every file under it.
    "credentials.json",
    "credentials.yaml",
    "credentials.yml",
    "credentials.ini",
    "credentials.cfg",
    "credentials.csv",
    "credentials.toml",
    "credentials.xml",
    "credentials.properties",
    "*-credentials.json",
    "*-credentials.yaml",
    "*-credentials.yml",
    "*-credentials.ini",
    "*-credentials.csv",
    "*_credentials.json",
    "*_credentials.yaml",
    "*_credentials.yml",
    "*_credentials.csv",
    "secret.json",
    "secret.yaml",
    "secret.yml",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.ini",
    "secrets.cfg",
    "secrets.toml",
    "secrets.properties",
    "*-secrets.json",
    "*-secrets.yaml",
    "*-secrets.yml",
    "token.json",
    "tokens.json",
    "accessKeys.csv",
    "azureProfile.json",
    # Cloud service accounts, in every spelling the providers hand out
    "service_account*.json",
    "serviceAccount*.json",
    "service-account*.json",
    "*-service-account*.json",
    "*_service_account*.json",
    # Terraform inputs
    "*.tfvars",
    "*.tfvars.json",
    # Version control
    ".git",
    ".hg",
    ".svn",
    # Python caches and build artifacts
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".ipynb_checkpoints",
    "dist",
    "build",
    "*.egg-info",
    # JavaScript and TypeScript
    "node_modules",
    ".next",
    ".turbo",
    ".nuxt",
    ".svelte-kit",
    ".docusaurus",
    ".parcel-cache",
    ".nyc_output",
    "*.tsbuildinfo",
    ".serverless",
    # JVM (Java, Kotlin, Android, Gradle)
    ".gradle",
    ".kotlin",
    "*.class",
    # Dart and Flutter
    ".dart_tool",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
    # Swift and Xcode
    ".build",
    "xcuserdata",
    "*.xcuserstate",
    # Ruby
    ".bundle",
    "*.gem",
    ".yardoc",
    # Elixir
    "_build",
    ".elixir_ls",
    # .NET / Visual Studio
    ".vs",
    # Infrastructure as Code
    ".terraform",
    "*.tfstate",
    "*.tfstate.*",
    ".terragrunt-cache",
    # OS artifacts
    ".DS_Store",
]


def split_exclude_patterns(exclude_patterns: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split exclude patterns into the deny list and the exemption list.

    An entry starting with ``!`` names an exemption: a path component matching it is
    never excluded, whatever deny pattern it also matches. Exemptions are
    order-independent — an exemption always wins. A bare ``!`` names no pattern and is
    treated as a literal deny entry.
    """
    deny: List[str] = []
    exempt: List[str] = []
    for pattern in exclude_patterns:
        if len(pattern) > 1 and pattern.startswith(EXEMPT_PREFIX):
            exempt.append(pattern[1:])
        else:
            deny.append(pattern)
    return deny, exempt


def path_matches_exclude(path: Path, root: Path, exclude_patterns: Sequence[str]) -> bool:
    """Return True when a path component matches a deny pattern and no exemption."""
    if not exclude_patterns:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    deny, exempt = split_exclude_patterns(exclude_patterns)
    return any(
        any(fnmatch(part, pattern) for pattern in deny) and not any(fnmatch(part, pattern) for pattern in exempt)
        for part in rel.parts
    )

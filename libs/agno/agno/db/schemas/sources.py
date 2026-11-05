"""Validation for configured Company readers; credentials are names, never values."""

import re
from typing import Any, Dict
from urllib.parse import urlsplit


def validate_source_fields(fields: Dict[str, Any]) -> None:
    unknown = set(fields) - {"product_id", "type", "reference", "credential_ref", "config"}
    if unknown:
        raise ValueError(f"Unsupported source fields: {sorted(unknown)}")
    if "type" in fields and fields["type"] not in {"git", "markdown", "website"}:
        raise ValueError("Source type must be git, markdown or website")
    if "reference" in fields:
        reference = fields["reference"]
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("reference must be a non-empty string")
        url = urlsplit(reference)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Source references cannot contain credentials, query strings or fragments")
        if fields.get("type") == "website" and url.scheme not in {"http", "https"}:
            raise ValueError("Website sources require an HTTP or HTTPS URL")
        if fields.get("type") == "website":
            from agno.knowledge.reader.utils.public_fetch import public_url

            public_url(reference)
    credential = fields.get("credential_ref")
    if credential is not None and (
        not isinstance(credential, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential)
    ):
        raise ValueError("credential_ref must name an environment variable")
    config = fields.get("config")
    if config is not None:
        if not isinstance(config, dict) or set(config) - (
            {"paths", "branch"} if fields.get("type") == "git" else {"paths"}
        ):
            raise ValueError("Source config supports paths and a git branch; credentials belong in the environment")
        paths = config.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(path, str) and path.strip() for path in paths):
            raise ValueError("paths must be a list of non-empty relative file paths")

    if fields.get("type") == "git":
        from agno.sandbox.repository import Repository

        reference = fields.get("reference", "")
        branch = (config or {}).get("branch", "main")
        # A URL must satisfy Repository's exact GitHub HTTPS rule. Local paths remain read-only.
        local_absolute = reference.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", reference)
        if not local_absolute and (urlsplit(reference).scheme or reference.startswith("git@")):
            Repository(reference, branch)
        elif config is not None and "branch" in config:
            Repository("https://github.com/validation/repository", branch)

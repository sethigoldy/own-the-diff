"""Best-effort exclusions applied when evidence leaves the private workspace."""

import re
from pathlib import PurePosixPath

_SECRET_LINE = re.compile(
    r"""(?:api[_-]?key|secret|password|token)\s*[:=]\s*["'][^"']{4,}|-----BEGIN .*PRIVATE KEY-----|\b(?:sk-|ghp_|AKIA)[A-Za-z0-9_-]{12,}""",
    re.I,
)


def eligible(path):
    p = PurePosixPath(path.lower())
    sensitive = (
        ".env",
        "credentials",
        "id_rsa",
        "id_ed25519",
        ".npmrc",
        ".netrc",
        "secret",
    )
    return not any(part.startswith(sensitive) for part in p.parts) and p.suffix not in {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
    }


def redact(text):
    if not _SECRET_LINE.search(text):
        return text
    return "\n".join(
        "[sensitive line omitted]" if _SECRET_LINE.search(line) else line
        for line in text.split("\n")
    )

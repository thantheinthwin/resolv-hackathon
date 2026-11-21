"""Read a private local .env without committing or logging API credentials."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
ALLOWED_SETTINGS = frozenset({"OPENAI_API_KEY", "OPENAI_MODEL"})


class ConfigError(ValueError):
    """A local configuration file cannot be loaded safely."""


def get_secret(name: str) -> str | None:
    """Read an environment setting, or a restrictive local KEY=value file.

    Codespaces secrets and exported environment variables take priority.
    The simple parser does not interpolate variables or execute shell syntax.
    """
    if name not in ALLOWED_SETTINGS:
        raise ConfigError("Unsupported application setting.")
    value = os.environ.get(name)
    if value:
        return value

    path = ENV_FILE
    if path.is_symlink():
        raise ConfigError("Refusing to load a symlinked .env file.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ConfigError("Local .env must be a regular file.")
    if path.stat().st_mode & 0o077:
        raise ConfigError("Make local .env private with: chmod 600 .env")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, setting = line.split("=", 1)
        if key.strip() != name:
            continue
        setting = setting.strip()
        if len(setting) > 1 and setting[0] == setting[-1] and setting[0] in "'\"":
            setting = setting[1:-1]
        return setting or None
    return None

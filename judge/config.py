"""Read a private local .env without committing or logging API credentials."""

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
ALLOWED_SETTINGS = frozenset({"OPENAI_API_KEY", "OPENAI_MODEL"})


class ConfigError(ValueError):
    """A local configuration file cannot be loaded safely."""


def get_secret(name: str) -> str | None:
    """Return an explicit environment setting or its private .env fallback.

    Environment settings (including Codespaces secrets) always take priority.
    A local .env must be a regular file, not a symlink, and private to the user.
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
    return dotenv_values(path).get(name) or None

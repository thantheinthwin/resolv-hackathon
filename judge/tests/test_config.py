"""Secret-loading tests: the root .env is never committed or echoed."""

import os
from pathlib import Path

import pytest

from judge import config


def test_environment_values_take_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=unused-file-value\nOPENAI_MODEL=unused-model\n")
    env.chmod(0o600)
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.setenv("OPENAI_API_KEY", "in-memory-value")
    assert config.get_secret("OPENAI_API_KEY") == "in-memory-value"


def test_private_env_file_is_loaded_without_exporting_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=local-test-only\nOPENAI_MODEL=gpt-4.1-mini\n")
    env.chmod(0o600)
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert config.get_secret("OPENAI_API_KEY") == "local-test-only"
    assert "OPENAI_API_KEY" not in os.environ


def test_world_readable_env_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=example\n")
    env.chmod(0o644)
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="chmod 600"):
        config.get_secret("OPENAI_API_KEY")


def test_symlinked_env_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private"
    target.write_text("OPENAI_API_KEY=test\n")
    target.chmod(0o600)
    path = tmp_path / ".env"
    path.symlink_to(target)
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(config.ConfigError, match="symlink"):
        config.get_secret("OPENAI_API_KEY")


def test_missing_settings_return_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert config.get_secret("OPENAI_API_KEY") is None


def test_only_explicit_settings_supported() -> None:
    with pytest.raises(config.ConfigError, match="Unsupported"):
        config.get_secret("SOME_OTHER_SETTING")

"""bonfire.toml y su carga (src/config.py), sin red."""

import pytest
from pydantic import ValidationError

from src import config


def test_the_repo_config_loads():
    assert config.settings.agent.model
    assert config.settings.agent.max_model_calls > 0


def test_a_misspelled_field_fails_instead_of_being_ignored(tmp_path):
    path = tmp_path / "bonfire.toml"
    path.write_text('[agent]\nmodel = "openai:x"\nmax_model_calls = 8\nmax_model_cals = 3\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        config.load_settings(path)


def test_bonfire_model_env_overrides_the_file(monkeypatch):
    monkeypatch.delenv("BONFIRE_MODEL", raising=False)
    assert config.generator_model() == config.settings.agent.model
    monkeypatch.setenv("BONFIRE_MODEL", "openai:other")
    assert config.generator_model() == "openai:other"

"""bonfire.toml y su carga (src/config.py), sin red."""

import pytest
from pydantic import ValidationError

from src import config


def test_the_repo_config_loads():
    assert config.settings.agent.model
    assert config.settings.agent.max_model_calls > 0


def test_a_misspelled_field_fails_instead_of_being_ignored(tmp_path):
    path = tmp_path / "bonfire.toml"
    valid = '[agent]\nmodel = "openai:x"\nmax_model_calls = 8\nsystem_prompt = "prompt/sql_agent.md"\n'
    path.write_text(valid, encoding="utf-8")
    config.load_settings(path)  # sin el error, carga: así el test de abajo falla por el typo y no por otra cosa
    path.write_text(valid + "max_model_cals = 3\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        config.load_settings(path)


def test_bonfire_model_env_overrides_the_file(monkeypatch):
    monkeypatch.delenv("BONFIRE_MODEL", raising=False)
    assert config.generator_model() == config.settings.agent.model
    monkeypatch.setenv("BONFIRE_MODEL", "openai:other")
    assert config.generator_model() == "openai:other"


def test_the_system_prompt_is_fully_rendered():
    from src.agent.build import SYSTEM_PROMPT
    from src.agent.tools import MAX_ROWS

    assert SYSTEM_PROMPT.startswith("You are a data analyst for Olist")
    assert f"At most {MAX_ROWS} rows come back" in SYSTEM_PROMPT
    assert "$" not in SYSTEM_PROMPT  # ninguna variable quedó sin completar


def test_a_missing_prompt_variable_fails_before_reaching_the_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "p.md").write_text("At most $max_rows rows, cost {not a variable}", encoding="utf-8")
    assert config.render_prompt("p.md", max_rows=5) == "At most 5 rows, cost {not a variable}"
    with pytest.raises(KeyError):
        config.render_prompt("p.md")


def test_prompt_sha_changes_with_the_prompt():
    assert config.prompt_sha("a") == config.prompt_sha("a")
    assert config.prompt_sha("a") != config.prompt_sha("b")

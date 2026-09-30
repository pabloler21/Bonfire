"""Configuración del agente: bonfire.toml, en la raíz del repo, y los prompts de prompt/.
tomllib (stdlib) lee el TOML y Pydantic lo valida; los prompts se completan con string.Template.
"""

import hashlib
import os
import tomllib
from pathlib import Path
from string import Template

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")  # un campo mal escrito en bonfire.toml falla acá, no en silencio

    model: str
    max_model_calls: int
    system_prompt: Path  # relativo a la raíz del repo


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentSettings


def load_settings(path: Path = ROOT / "bonfire.toml") -> Settings:
    with path.open("rb") as f:
        return Settings.model_validate(tomllib.load(f))


settings = load_settings()


def generator_model() -> str:
    """El modelo pedido: BONFIRE_MODEL (.env) si está, si no el de bonfire.toml."""
    return os.environ.get("BONFIRE_MODEL", settings.agent.model)


def render_prompt(path: Path, **values) -> str:
    """Lee un prompt y completa sus $variables. Una variable sin valor tira KeyError acá, no llega rota al LLM.
    Template y no str.format: las llaves {} que tenga el prompt no rompen nada.
    """
    return Template((ROOT / path).read_text(encoding="utf-8")).substitute(values)


def prompt_sha(text: str) -> str:
    """Huella corta del prompt ya completado: identifica con qué versión corrió cada experimento."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

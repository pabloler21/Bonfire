"""Configuración del agente: bonfire.toml, en la raíz del repo. tomllib (stdlib) lo lee y Pydantic lo valida."""

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")  # un campo mal escrito en bonfire.toml falla acá, no en silencio

    model: str
    max_model_calls: int


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

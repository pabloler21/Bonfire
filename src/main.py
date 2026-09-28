"""Fase 2 — Entry point: recibe una pregunta, invoca el agente de agent/build.py e imprime la respuesta.

Uso: uv run python -m src.main "How many orders are there?"
"""

import sys

from dotenv import load_dotenv

from src.agent.build import build_agent


def ask(question: str) -> str:
    result = build_agent().invoke({"messages": [{"role": "user", "content": question}]})
    return result["messages"][-1].text  # .text: el contenido puede venir como lista de bloques (Responses API)


if __name__ == "__main__":
    load_dotenv()
    print(ask(" ".join(sys.argv[1:]) or "How many orders are there?"))

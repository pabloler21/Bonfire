"""Fase 7 — API: POST /ask devuelve la respuesta final y el resumen de intentos (SQL, decisión de Jev, motivo) en JSON.

uv run uvicorn src.api:app --port 8000       (local, con la base levantada)
docker compose up -d --wait                  (la API en Docker, en http://127.0.0.1:8000)

Sin estado entre requests: cada POST /ask es una pregunta nueva. Si la revisión decide `ask_user`, la respuesta es la
pregunta aclaratoria con `kind = "clarification"`, y el usuario reformula en otro POST /ask (plan.md, Fase 7).
La traza de cada pregunta va a Langfuse igual que con src.main: el callback de build_agent y el instrumentor de Jev.
"""

from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI
from langfuse import get_client
from pydantic import BaseModel, Field

from src.agent.build import build_agent
from src.middleware.review import attempts

agent = None  # se arma una vez al arrancar (lifespan), no en cada request


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    load_dotenv()  # en Docker las variables ya vienen del entorno; load_dotenv no pisa las que existen
    agent = build_agent()
    yield
    get_client().flush()  # al apagar: manda a Langfuse las trazas que quedaron en cola


app = FastAPI(title="Bonfire", summary="Preguntas de negocio sobre Olist, con Jev revisando cada consulta.",
              lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, examples=["How many customers are there?"])


class Attempt(BaseModel):
    sql: str | None
    error: str | None
    row_count: int
    decision: str = Field(description="answer, retry o ask_user: lo que decidió la revisión sobre este intento")
    reason: str = Field(description="El motivo que leyó el LLM; con retry, lo que tiene que corregir")


class AskResponse(BaseModel):
    answer: str
    kind: Literal["answer", "clarification"] = Field(
        description="clarification: la revisión pidió aclarar la pregunta; reformulala en otro POST /ask")
    attempts: list[Attempt]


@app.post("/ask")
def ask(request: AskRequest) -> AskResponse:
    # def y no async def: agent.invoke es sincrónico, y FastAPI corre estas funciones en un thread aparte
    state = agent.invoke({"messages": [{"role": "user", "content": request.question}]})
    return AskResponse(
        answer=state["messages"][-1].text,
        kind="clarification" if state.get("review_kind") == "ask_user" else "answer",
        attempts=[
            Attempt(sql=a["sql"], error=a["result"].error, row_count=a["result"].row_count, decision=a["decision"],
                    reason=a["reason"])
            for a in attempts(state["messages"])
        ],
    )

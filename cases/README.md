# Casos para revisar a mano

Preguntas para hacerle al agente **una por una** y mirar qué responde. No hay nada automatizado: vos corrés,
vos leés la traza en Langfuse y vos anotás. Las fallas que encuentres son la materia prima de los golden cases
(Fase 3 de `plan.md`).

## `cases.jsonl`

Un caso por línea:

```json
{"id": "b01", "kind": "paraphrase", "question": "cuantos pedidos hay en total??", "watch": "Mismo resultado que d01 ...: 99441.", "of": "d01"}
```

| Campo | Qué es |
|---|---|
| `id` | Para nombrar el caso en tus notas y en Langfuse |
| `kind` | `paraphrase` (otra forma de una pregunta dev), `unanswerable` (Olist no tiene el dato), `ambiguous` (más de una lectura), `injection` (intenta manipular al agente) |
| `question` | Lo que le preguntás al agente |
| `watch` | Qué mirar en la respuesta. En los parafraseos, el resultado correcto, sacado de `eval/results/pilot.json` |
| `of` | Solo en parafraseos: la pregunta de `eval/questions_dev.jsonl` que reformula |

Agregá los casos que quieras. Los parafraseos salen solo de preguntas **dev**, nunca de las de test de la Fase 3.

## Cómo correr una ronda

Necesitás la base levantada (`docker compose up -d --wait`) y en `.env` la `OPENAI_API_KEY` y las tres
variables `LANGFUSE_*`.

1. Copiá la `question` de un caso y corré:
   ```
   uv run python -m src.main "cuantos pedidos hay en total??"
   ```
2. En Langfuse, **Tracing**: la traza más nueva es esa pregunta. Mirá el SQL que escribió (`run_sql`), la tabla
   que volvió y la respuesta final. Comparala con el `watch` del caso.
3. Anotala con el botón **Annotate** de la traza: un score y un comentario con lo que viste ("contó customer_id",
   "respondió en portugués", "inventó un número"). La primera vez tenés que crear una *Score Config* en
   Langfuse (por ejemplo, categórica: `correcta` / `incorrecta` / `dudosa`).
4. Siguiente caso.

Para comparar modelos, cambiá `BONFIRE_MODEL` en `.env` (o `model` en `bonfire.toml`) y repetí la ronda. Cambiá una
sola cosa por ronda, así sabés qué causó la diferencia. Ojo: gpt-5-nano no responde igual dos veces; una
diferencia en un solo caso puede ser ruido.

## Qué no se puede probar a mano

La prompt injection **indirecta** (un texto malicioso dentro de una reseña de la base) necesita sembrar ese texto
en los datos. Con la base de solo lectura y sin código extra no se puede; queda anotado como límite conocido.

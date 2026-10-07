# NOTES

Discrepancias entre plan.md y la documentación, con fecha.

## 2026-09-22 — D2 (PLAN_REVIEW.md): los settings por rol no impiden el override

- **Links:**
  - <https://www.postgresql.org/docs/current/sql-alterrole.html>
  - <https://www.postgresql.org/docs/current/runtime-config-client.html>
- **Qué dice la documentación (PostgreSQL 18):** `ALTER ROLE ... SET` fija el valor como *default de sesión* al hacer login. La sesión puede cambiarlo después con `SET`. `statement_timeout` se puede cambiar por sesión, y `default_transaction_read_only` también (cambiarlo equivale a `SET TRANSACTION`).
- **Qué suponía la revisión:** presentaba `ALTER ROLE bonfire_agent SET statement_timeout = '10s'` y `default_transaction_read_only = on` como la corrección al bypass `SET statement_timeout = 0; SELECT ...`.
- **Versión aplicada en plan.md:** los dos `ALTER ROLE ... SET` se mantienen, como defaults. La barrera contra el bypass es la re-verificación de sentencia única de lectura dentro de `run_sql`: `SET ...; SELECT ...` son dos sentencias y `SET` no es una raíz de lectura. Fase 1, tareas.

## 2026-09-22 — Fase 0: rate limit publicado

- **Link:** <https://docs.typesafe.ai/models>
- **Qué dice la documentación:** Jev 1.13 (`jev-1.13.0`) publica un rate limit de 1.200 requests por minuto y 250.000 tokens por segundo. El contexto es de 64k tokens por request, con 32k para `state` + la pregunta más larga (coincide con m1).
- **Impacto:** ninguno. No se mide el rate limit por separado (decisión del 24/09/2026: la Fase 0 solo confirma la conexión). A la escala de este proyecto no es un límite relevante.

## 2026-09-24 — Fase 0: el exceso de tokens devuelve 400, no 422

- **Link:** <https://docs.typesafe.ai/api> (tabla de errores)
- **Qué dice la documentación:** los errores listados son 401, 422 (validación del body), 429 y 529.
- **Qué se vio** (llamada real del 24/09/2026, SDK 0.7.0, `jev-1.13.0`): un request que pasa el tope de 32k (`state` + pregunta más larga) o el de 64k (`state` + todas las preguntas) devuelve **HTTP 400** con body `{'detail': {'error_type': 'max_tokens_exceeded'}}`. En el SDK es `TypeSafeBadRequestError`.
- **Impacto:** el cliente de Jev (Fase 4) tiene que tratar el 400 `max_tokens_exceeded` como un error propio y no reintentarlo. Los dos topes coinciden con lo publicado: 30k OK y 34k rechazado; 56k OK y 68k rechazado.

## 2026-09-28 — Fase 2: el límite de iteraciones no va ni en `create_agent` ni como parámetro propio

- **Links:**
  - <https://docs.langchain.com/oss/python/langchain/middleware/built-in> (sección *Model call limit*)
  - <https://docs.langchain.com/oss/python/langgraph/graph-api> (sección *Recursion limit*)
- **Qué preguntaba el plan:** si el límite se pasa a `create_agent` o al `invoke`.
- **Qué dice la documentación (langchain 1.4.2 instalado):** `create_agent` no tiene parámetro de iteraciones. Hay dos mecanismos: `recursion_limit` en el `config` del `invoke` (LangGraph; al pasarse lanza `GraphRecursionError`) y `ModelCallLimitMiddleware(run_limit=..., exit_behavior="end")`, que termina el loop sin excepción.
- **Versión aplicada:** `ModelCallLimitMiddleware` con `run_limit=8` en `src/agent/build.py`. `tests/test_agent.py` verifica que corta un loop infinito en exactamente 8 llamadas.

## 2026-09-28 — Fase 2: con los modelos nuevos de OpenAI, `AIMessage.content` es una lista de bloques

- **Qué pasó:** con `openai:gpt-6-sol` (langchain-openai 1.6.6) la respuesta final llega como `[{"type": "text", "text": "...", ...}]`, no como `str`. Es el formato de la Responses API.
- **Versión aplicada:** leer la respuesta con `AIMessage.text` (property en langchain-core 1.x), que concatena el texto de los bloques y también funciona con `str`. `src/main.py` y `eval/run_eval.py`.

## 2026-09-29 — Langfuse se adelanta de la Fase 7 (decisión del owner)

- **Links:**
  - <https://langfuse.com/integrations/frameworks/langchain>
  - <https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk>
- **Qué decía el plan:** Langfuse entra en la Fase 7, junto con la API.
- **Qué se hizo:** Langfuse Cloud desde ahora (langfuse 4.15.6). `build_agent()` agrega `CallbackHandler()` con `with_config` si hay `LANGFUSE_PUBLIC_KEY`; sin la key no hay callback ni red. Suma la suite de comportamiento del generador (`eval/behavior_dev.jsonl`, `eval/run_behavior.py`) como experimento de Langfuse con datos locales. Spec: `docs/superpowers/specs/2026-09-29-langfuse-behavior-suite-design.md`.
- **Qué dice la documentación (SDK 4.x):** el handler ya no acepta `update_trace` (tira `TypeError`); los atributos de traza van con `propagate_attributes()`. Los experimentos con datos locales aparecen en *Experiments* sin dataset hosteado. En el código instalado, `run_experiment` llama a una `task` sincrónica directamente dentro del loop async, así que las tasks sync corren de a una.
- **La Fase 7 sigue:** API y `@observe` sobre la request a Jev (Fase 5), que no pasa por LangChain.

## 2026-10-01 — Se quita la suite automatizada de comportamiento (decisión del owner)

- **Qué había:** `eval/run_behavior.py` corría los casos de `eval/behavior_dev.jsonl` como `langfuse.run_experiment` con evaluators deterministas (29/09).
- **Qué pidió el owner:** revisar el comportamiento del LLM a mano, caso por caso, leyendo y anotando las trazas en Langfuse (análisis de errores), y construir los golden cases a partir de lo que encuentre. Es un proyecto de estudio: la automatización le sacaba la parte de leer cada respuesta.
- **Qué se hizo:** se borraron `run_behavior.py`, sus tests, su spec y el parámetro `sql_tool` de `build_agent()`. Los casos pasaron a `cases/cases.jsonl` con una nota `watch` por caso; `cases/README.md` explica cómo correr una ronda con `src.main` y anotar con *Annotate* (Score Config) en Langfuse. Los 3 casos de injection indirecta se descartaron porque necesitaban sembrar datos.
- **Fuente:** <https://langfuse.com/docs/evaluation/evaluation-methods/annotation> (anotación manual y Annotation Queues, consultada el 30/09/2026).
- **Se mantiene:** Langfuse en `build_agent()`, `bonfire.toml`, `prompts/`, y `eval/run_eval.py`, `eval/grading.py`, `eval/questions_dev.jsonl` (Fases 2 y 6 del plan).

## 2026-10-01 — El agente responde siempre en inglés (decisión del owner)

- **Qué decía el prompt:** "answer in the same language as the question".
- **Qué se vio:** en la primera ronda de `cases/`, gpt-5-nano respondió en portugués a "How many orders are there?" (ya había pasado en el piloto).
- **Qué se hizo:** `prompts/sql_agent.md` pide responder en inglés sea cual sea el idioma de la pregunta. Cambia `prompt_sha`; las trazas y corridas anteriores usan la regla vieja. Los casos en otros idiomas (`b03`, por ejemplo) ahora miden esta regla.

## 2026-10-06 — `d08`: "vendidos" son los pedidos entregados (decisión del owner)

- **Qué decía la referencia:** contar los productos distintos de `perfumaria` en `order_items`, con cualquier `order_status` (868).
- **Qué se vio:** en el piloto, gpt-5-nano filtró `order_status = 'delivered'` (857) y avisó qué lectura usaba.
- **Qué se hizo:** el owner decidió que "vendidos" incluye solo los pedidos entregados. La referencia de `d08` en `eval/questions_dev.jsonl` es ahora la consulta del piloto, y `acceptable_sql` sigue vacío. `eval/results/pilot.json` queda como estaba: se calificó con la referencia vieja.

## 2026-10-07 — La Fase 3 se reduce a revisar el SQL del generador a mano (decisión del owner)

- **Qué decía el plan:** 40 preguntas de test, 20 + 40 casos etiquetados para Jev y un congelado con hashes (`eval-frozen`) antes de que exista `src/middleware/`.
- **Qué se había armado (06–07/10):** 22 preguntas de cosecha corridas con `run_eval` (14/22), y `cases_dev.jsonl` y `cases_test.jsonl` con etiquetas `next_step` / `pitfalls`.
- **Qué pidió el owner:** no testear a Jev sin tener Jev. Por ahora alcanza con ver cómo escribe SQL el LLM: 10 preguntas normales y 10 con trampa, revisar cada respuesta en Langfuse y ajustar a mano.
- **Qué se hizo:** se borraron los casos, las preguntas de cosecha y su resultado (recuperables desde el commit 4db5522). Quedan `eval/questions_dev.jsonl` (10 normales) y `eval/questions_traps.jsonl` (10, dos por trampa, sacadas de la cosecha). `eval/README.md` guarda las convenciones de las referencias y las trampas medidas sobre la base. `plan.md` lleva una nota en la regla general y en la Fase 3.

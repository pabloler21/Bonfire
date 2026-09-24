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

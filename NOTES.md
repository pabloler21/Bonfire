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
- **Impacto:** la Fase 0 mide el rate limit real y lo compara contra el publicado. El plan no cambia.

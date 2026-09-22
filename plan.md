# Bonfire — Plan de implementación por fases

Agente de análisis SQL con control plane en Jev (TypeSafe System One).

> El nombre viene de las hogueras de los Souls: el punto donde el estado se
> persiste y desde donde la ejecución se reanuda. Es exactamente lo que hace
> el `interrupt()` del gate de riesgo junto con el checkpointer.

**Última revisión del plan:** 19 de septiembre de 2026.

---

## Cómo usar este plan con Claude Code

Este proyecto se apoya en tres piezas que se mueven rápido:

| Pieza | Estado | Riesgo |
|---|---|---|
| `langchain` v1 | `create_agent` reemplazó a `create_react_agent`; lo legacy se movió a `langchain-classic` | tutoriales viejos no compilan |
| `langchain-typesafe` | middleware marcado **experimental** | la API puede romperse entre versiones |
| `typesafe-sdk` / Jev | modelo publicado el 15/09/2026 | firmas, límites y precios pueden haber cambiado |

**Regla para Claude Code, a aplicar en cada fase:**

1. Antes de escribir código contra cualquiera de esas tres, **leer la fuente
   viva** listada al final de la fase. No escribir firmas de memoria.
2. Si lo que dice la documentación contradice este plan, **gana la
   documentación**. Anotar la discrepancia en `NOTES.md` con fecha.
3. Fijar versiones exactas en `uv.lock` y no actualizar en medio de una fase.
4. Registrar en cada corrida la **versión de modelo devuelta por la API**.
   `jev-latest` es un alias móvil y no sirve como identificador reproducible.

**Atajo:** LangChain publica el índice completo de su documentación en
<https://docs.langchain.com/llms.txt>. Pasárselo a Claude Code como contexto
evita buscar página por página.

---

## Regla general del plan

Cada fase tiene **criterio de salida explícito**. No se avanza sin cumplirlo.
Las fases marcadas 🚦 son gates duros: si no se cumplen, el trabajo posterior
queda inválido.

El orden no es negociable en dos puntos:

1. El **baseline sin middleware** (Fase 2) se corre **antes** de escribir un
   solo middleware.
2. Los **datasets de evaluación** (Fase 3) se congelan **antes** de
   implementar los middlewares.

---

## Fase 0 — Sonda y presupuesto 🚦

**Objetivo:** confirmar que el proyecto es viable antes de invertir tiempo.

**Tareas**

- Generar la API key en la consola de TypeSafe.
- Correr una llamada mínima con las tres primitivas (`Choice`, `Score`,
  `Noul`) sobre una sentencia SQL pegada a mano.
- Registrar: **rate limit real**, **latencia medida desde Buenos Aires**,
  **versión de modelo devuelta**, y el **presupuesto de tokens del request**
  (reportado en torno a 32.000 tokens — verificar el valor vigente).
- Estimar costo total: (40 preguntas × ~3 vueltas × 2 decisiones) +
  (60 sentencias × 1 decisión) × número de corridas de eval.

**Entregable:** `notebooks/00_probe.ipynb` con los números medidos.

**🚦 Criterio de salida:** el rate limit permite completar una corrida de eval
sin throttling. Si no, se reducen los datasets *ahora*.

**Fuentes a verificar antes de codear**

- Introducción: <https://docs.typesafe.ai/introduction>
- Quickstart y SDK: <https://docs.typesafe.ai/introduction/quickstart>
- Consola / API key: <https://console.typesafe.ai/settings/keys>
- Post de lanzamiento (precios y latencias declaradas):
  <https://typesafe.ai/blog/introducing-system-one-models-and-jev>

> Verificar puntualmente: nombre del endpoint, forma del request (no sigue la
> convención de chat-completions de OpenAI), precio por millón de tokens de
> entrada, y si hay créditos gratuitos o tier de prueba.

---

## Fase 1 — Base de datos y tool de SQL 🚦

**Objetivo:** tener una base real con permisos correctos.

**Tareas**

- `docker-compose.yml` con PostgreSQL.
- `init.sql`: cargar el dataset público de Olist (e-commerce brasileño,
  multi-tabla, dominio de pedidos y pagos).
- Crear **dos usuarios**:
  - `bonfire_agent` — únicamente `SELECT`, sin `INSERT`/`UPDATE`/`DELETE`/DDL.
  - `bonfire_admin` — para las pruebas de seguridad de la Fase 3.
- Implementar `src/agent/tools.py::run_sql(query)` con:
  - conexión mediante `bonfire_agent`
  - `statement_timeout` de 10 segundos
  - límite de filas devueltas
  - errores de Postgres capturados como texto, sin excepción que rompa el loop

**Entregable:** base levantada, `run_sql` funcionando desde un script suelto.

**🚦 Criterio de salida:** ejecutar `DELETE FROM orders` con el usuario del
agente **tiene que fallar por permisos**. Jev es la segunda línea de defensa,
nunca la única.

**Fuentes a verificar**

- Guardrails y defensa en profundidad en agentes:
  <https://docs.langchain.com/oss/python/langchain/guardrails>
- `GRANT` / `REVOKE` y `statement_timeout`: documentación oficial de
  PostgreSQL de la versión que levantes en Docker.
- Dataset de Olist: buscar "Brazilian E-Commerce Public Dataset by Olist" en
  Kaggle y verificar licencia y esquema vigente.

---

## Fase 2 — Agente desnudo (baseline A)

**Objetivo:** tener el agente funcionando sin ningún control, y medirlo.

**Tareas**

- `src/agent/build.py` con `create_agent`:
  - un solo modelo generativo
  - la tool `run_sql`
  - el esquema de la base en el system prompt
  - límite de iteraciones
- Checkpointer de **Postgres**, no de memoria (se necesita en la Fase 5; el
  de memoria pierde la pausa al reiniciar el proceso).
- Correr 10 preguntas de prueba y guardar trazas completas: vueltas, SQL de
  cada vuelta, costo, latencia.

**Entregable:** agente funcional + `eval/results/baseline_a_pilot.json`.

**Criterio de salida:** responde correctamente al menos la mitad de las
preguntas simples. Si no llega, el problema está en el prompt del esquema.

**Fuentes a verificar**

- Agentes y el loop: <https://docs.langchain.com/oss/python/langchain/agents>
- Referencia de `create_agent`:
  <https://reference.langchain.com/python/langchain/agents/factory/create_agent>
- Novedades de v1 (qué cambió de nombre):
  <https://docs.langchain.com/oss/python/releases/langchain-v1>
- Checkpointers y `thread_id`:
  <https://docs.langchain.com/oss/python/langgraph/checkpointers>

> Verificar puntualmente: el nombre del paquete del checkpointer de Postgres,
> si hace falta llamar a `setup()` una vez para crear el esquema, y si el
> límite de iteraciones se pasa a `create_agent` o al `invoke`.

---

## Fase 3 — Datasets de evaluación 🚦

**Objetivo:** construir la verdad contra la que se mide todo lo demás.

### `eval/questions.jsonl` — 40 preguntas de negocio

Cada registro: pregunta en lenguaje natural + SQL de referencia escrito a mano
+ resultado esperado.

| Tipo | Cantidad |
|---|---|
| Una tabla, agregación simple | 10 |
| Join de dos o más tablas | 12 |
| Ventana temporal / comparación entre períodos | 8 |
| Ambiguas (admiten más de una lectura) | 5 |
| Sin respuesta posible con este esquema | 5 |

Las dos últimas categorías son las que ejercitan el control de loop.

### `eval/statements.jsonl` — 60 sentencias SQL etiquetadas

Etiquetas: `readonly`, `destructive`, `privileged`, `expensive`.

Casos límite obligatorios:

- `SELECT` con producto cartesiano (join sin condición)
- `WITH` que esconde un `DELETE` en la CTE
- `SELECT ... FOR UPDATE`
- `SELECT` sobre tabla grande sin filtro selectivo
- `GRANT` / `CREATE USER`
- `SELECT` legítimo que *parece* peligroso (para medir falsos positivos)

**Entregable:** ambos archivos + `eval/README.md` con el criterio de etiquetado.

**🚦 Criterio de salida:** los dos archivos commiteados y hasheados **antes**
de que exista un solo archivo en `src/middleware/`.

**Fuentes a verificar**

- Trabajo previo, para inspirarse en el esquema de etiquetas (no copiar):
  buscar en GitHub `themsquared/jev-benchmark` (clasificación de riesgo de
  tool calls: readonly / destructive / privileged / exfiltration) y
  `AbdelStark/jev-benchmarks` (calibración y riesgo selectivo).
- Matriz de confusión y tasa base: <https://scikit-learn.org/stable/modules/calibration.html>

---

## Fase 4 — Cliente de Jev y rúbricas

**Objetivo:** la capa de acceso al modelo, aislada y medible.

**Tareas**

- `src/jev/client.py`: wrapper del SDK que registra en cada llamada la versión
  de modelo devuelta, tokens, latencia y el question set usado.
- `src/questions/risk.py` — rúbrica del gate de riesgo:

  ```
  stmt_type      Choice  readonly | destructive | privileged | expensive
  modifies_data  Noul    la sentencia modifica o borra datos
  full_scan      Noul    escanea una tabla grande sin filtro selectivo
  cartesian      Noul    join sin condición, producto cartesiano
  touches_pii    Noul    lee información personal identificable
  ```

- `src/questions/loop.py` — rúbrica del control de loop:

  ```
  answers_question  Noul   el resultado responde la pregunta original
  is_empty          Noul   el resultado está vacío o es sospechoso
  needs_more        Noul   falta información para responder
  ```

- `src/models.py`: `RiskVerdict`, `LoopVerdict` con Pydantic.

**Entregable:** las rúbricas corriendo sobre `statements.jsonl`.

**Criterio de salida:** medir latencia con 3 preguntas y con 5 sobre la misma
sentencia. Si la diferencia es marginal, el paralelismo está confirmado. Si
escala con la cantidad, la request está mal armada.

**Fuentes a verificar**

- Primitivas y composición: <https://docs.typesafe.ai/primitives>
- <https://docs.typesafe.ai/primitives/noul>
- <https://docs.typesafe.ai/primitives/choice>
- <https://docs.typesafe.ai/primitives/score>
- Confidence y Patterns: enlazadas desde la página de primitivas.

> Puntos a confirmar contra la documentación, porque afectan el diseño de
> `policy.py`:
> - `Noul` **no tiene** campo `confidence`: la probabilidad es la respuesta.
>   Solo `Choice` y `Score` traen `confidence`.
> - `Score` devuelve un promedio ponderado por probabilidad y **puede caer
>   entre niveles**; redondear a un bucket puede tapar dónde está la masa.
> - `Choice` admite hasta 255 opciones; conviene incluir una opción `other`.
> - Cada pregunta se evalúa de forma independiente: la respuesta de A no es
>   contexto de B. Si B depende de A, hacen falta dos requests.

---

## Fase 5 — Middleware de riesgo (`before_tool`)

**Objetivo:** la pieza central del proyecto.

**Tareas**

- `src/sqlcheck.py`: verificación determinista con `sqlglot` — tipo de
  sentencia, presencia de DML/DDL, joins sin condición. Corre **en paralelo**
  a Jev, no en lugar de.
- `src/policy.py` — código puro, sin red:

  ```python
  def gate(verdict: RiskVerdict) -> Action:
      if verdict.modifies_data > 0.5:
          return Action.BLOCK
      if verdict.stmt_type_confidence < 0.70:
          return Action.INTERRUPT
      if verdict.full_scan > 0.6 or verdict.cartesian > 0.6:
          return Action.INTERRUPT
      return Action.ALLOW
  ```

- `src/middleware/risk_gate.py`: hook `before_tool` que aplica la política.
  - `BLOCK` → la tool no se ejecuta; el agente recibe un mensaje de error.
  - `INTERRUPT` → `interrupt()`; el estado se persiste y el humano decide.
  - `ALLOW` → pasa.
- Registrar **siempre** las discrepancias entre `sqlglot` y Jev.

**Entregable:** middleware funcionando + tests de `policy.py` y `sqlcheck.py`.

**Criterio de salida:** matriz de confusión sobre las 60 sentencias, por
etiqueta. Documentar al menos 3 discrepancias con `sqlglot`.

**Fuentes a verificar**

- Overview de middleware y diagrama de hooks:
  <https://docs.langchain.com/oss/python/langchain/middleware/overview>
- Firmas exactas de los hooks:
  <https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware>
- `HumanInTheLoopMiddleware` (el patrón de aprobación previa, ya escrito):
  <https://docs.langchain.com/oss/python/langchain/guardrails>
- `AutoModeMiddleware` y `NoulCriteria` — el equivalente oficial de este gate:
  <https://docs.langchain.com/oss/python/integrations/providers/typesafe>
- `sqlglot`: buscar `tobymao/sqlglot` en GitHub; leer el *expression tree
  primer* y `parse_one` / `find_all`.

> Advertencias de las fuentes:
> - `sqlglot` **no es un validador**: puede no detectar ciertos errores de
>   sintaxis. Razón de más para que corra junto a Jev, no en su lugar.
> - La documentación de la integración advierte no poner secretos en
>   argumentos de tools ni en el estado, porque viajan a TypeSafe.

---

## Fase 6 — Middleware de control de loop (`after_tool`)

**Objetivo:** la decisión que justifica todo el diseño.

**Tareas**

- `src/middleware/loop_control.py`: hook `after_tool` que evalúa el resultado
  y decide si el agente termina o da otra vuelta.
- Política: confianza alta + `answers_question` alto → termina. Cualquier otra
  combinación → otra vuelta, con el resultado incorporado al contexto.
- Tope de iteraciones como red de seguridad.

**Entregable:** el loop completo funcionando end to end.

**🚦 Criterio de salida:** latencia y costo **por vuelta** contra el baseline A.
La diferencia contra una decisión tomada por LLM tiene que ser de al menos un
orden de magnitud.

**Fuentes a verificar**

- Hooks `after_tool` / `wrap_tool_call`:
  <https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware>
- Cómo se decide la condición de parada del agente:
  <https://docs.langchain.com/oss/python/langchain/agents>

---

## Fase 7 — Baseline B (middleware con LLM)

**Objetivo:** la comparación honesta.

**Tareas**

- Reimplementar las dos decisiones con un LLM en lugar de Jev, con structured
  outputs, **sin tocar nada más** del sistema.
- Mismas rúbricas, mismos umbrales, misma política.

**Entregable:** `eval/baselines.py` con las tres configuraciones por flag.

**Criterio de salida:** los tres sistemas corren sobre los mismos datasets con
un solo comando.

**Fuentes a verificar**

- Structured output en LangChain v1 y sus limitaciones con modelos
  pre-bindeados: <https://docs.langchain.com/oss/python/langchain/agents>

---

## Fase 8 — Medición

**Objetivo:** la tabla que es el resultado del proyecto.

**Tareas**

- `eval/run_eval.py` corriendo las tres configuraciones.
- Métricas, con **falsos positivos primero**:

  | | Falsos positivos | Acierto | Latencia p95 | Costo / consulta |
  |---|---|---|---|---|
  | Sin middleware | | | | |
  | Middleware con LLM | | | | |
  | Middleware con Jev | | | | |

- Además: vueltas promedio por consulta, y calibración del gate (Brier y ECE
  sobre las etiquetas de `statements.jsonl`).

**Entregable:** `eval/results/` con datos crudos + tablas.

**🚦 Criterio de salida:** los falsos positivos encabezan la tabla. Un gate que
bloquea el 5% de las consultas legítimas hace el agente inusable.

**Fuentes a verificar**

- Calibración, `calibration_curve`, `brier_score_loss`:
  <https://scikit-learn.org/stable/modules/calibration.html>

> Advertencia metodológica que vale citar en el README: la calibración es una
> propiedad de **grupos** de predicciones, no de una respuesta individual, y
> las cifras publicadas por TypeSafe se midieron sobre sus datos. Hay que
> validarla en el dominio propio antes de confiar en un umbral.

---

## Fase 9 — API y observabilidad

**Objetivo:** que el proyecto sea demostrable.

**Tareas**

- `src/api.py`: `POST /ask` con SSE streameando cada paso del loop — qué SQL
  se propuso, qué decidió el gate, qué devolvió la base, si el loop siguió.
- `POST /approve/{thread_id}`: reanudar tras un `interrupt()`.
- Langfuse trazando el árbol completo.

**Entregable:** API corriendo en Docker Compose.

**Criterio de salida:** una consulta que dispara `interrupt()` se pausa, se
aprueba desde el endpoint, y se reanuda correctamente **después de reiniciar
el contenedor**.

**Fuentes a verificar**

- Interrupts, `Command` y `__interrupt__`:
  <https://docs.langchain.com/oss/python/langgraph/interrupts>
- Human-in-the-loop y `thread_id` como cursor persistente:
  <https://docs.langchain.com/oss/python/langgraph/human-in-the-loop>
- `StreamingResponse` / SSE: documentación de FastAPI.
- Integración de Langfuse con LangChain: documentación de Langfuse.

> **Trampa documentada:** al reanudar desde un `interrupt()`, el nodo se
> **re-ejecuta completo desde el principio**. Todo lo que esté antes del
> `interrupt()` tiene que ser idempotente, o se duplican los efectos.

---

## Fase 10 — README y cierre

**Contenido obligatorio del README**

1. Diagrama del flujo.
2. Qué recibe y qué devuelve Jev, con un ejemplo real de request y response.
3. Las dos rúbricas completas, con la justificación de cada pregunta.
4. La tabla comparativa de la Fase 8.
5. Los casos de discrepancia entre `sqlglot` y Jev, y cuál tuvo razón.
6. **Limitaciones**: tamaño de los datasets, versión de modelo usada, fecha de
   las corridas, qué familias de ataque no cubre el gate.
7. Cómo reproducir todo con un comando.

**Criterio de salida:** un revisor puede verificar los 7 criterios de
aceptación sin correr nada.

---

## Estructura final de archivos

```
bonfire/
├── README.md
├── NOTES.md                          # discrepancias plan vs documentación
├── docker-compose.yml
├── Dockerfile
├── init.sql                          # esquema, dataset y los dos usuarios
├── pyproject.toml / uv.lock          # versiones FIJADAS
├── .env.example
│
├── src/
│   ├── main.py                       # entry point: pregunta -> respuesta
│   ├── models.py                     # RiskVerdict, LoopVerdict, Action
│   ├── policy.py                     # umbrales, codigo puro
│   ├── sqlcheck.py                   # verificacion determinista con sqlglot
│   ├── api.py                        # POST /ask (SSE), POST /approve
│   │
│   ├── agent/
│   │   ├── build.py                  # create_agent + checkpointer Postgres
│   │   └── tools.py                  # run_sql, usuario de solo lectura
│   │
│   ├── jev/
│   │   └── client.py                 # wrapper del SDK, registra version
│   │
│   ├── questions/
│   │   ├── risk.py                   # 5 preguntas del gate
│   │   └── loop.py                   # 3 preguntas del control de loop
│   │
│   └── middleware/
│       ├── risk_gate.py              # before_tool
│       └── loop_control.py           # after_tool
│
├── eval/
│   ├── questions.jsonl               # 40 preguntas + SQL de referencia
│   ├── statements.jsonl              # 60 sentencias etiquetadas
│   ├── README.md                     # criterio de etiquetado
│   ├── baselines.py                  # sin middleware / con LLM / con Jev
│   ├── run_eval.py
│   └── results/
│
├── tests/
│   ├── test_policy.py                # sin red
│   └── test_sqlcheck.py              # sin red
│
└── notebooks/
    └── 00_probe.ipynb                # sonda de la Fase 0
```

---

## Índice de fuentes

### LangChain — agentes y middleware
- Agentes y el loop — <https://docs.langchain.com/oss/python/langchain/agents>
- Middleware, overview y diagrama de hooks — <https://docs.langchain.com/oss/python/langchain/middleware/overview>
- `AgentMiddleware`, firmas de hooks — <https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware>
- `create_agent`, referencia — <https://reference.langchain.com/python/langchain/agents/factory/create_agent>
- Guardrails y human-in-the-loop middleware — <https://docs.langchain.com/oss/python/langchain/guardrails>
- Novedades de v1 — <https://docs.langchain.com/oss/python/releases/langchain-v1>
- Índice completo para pasarle a un agente — <https://docs.langchain.com/llms.txt>

### LangGraph — persistencia y pausa
- Human-in-the-loop — <https://docs.langchain.com/oss/python/langgraph/human-in-the-loop>
- Interrupts — <https://docs.langchain.com/oss/python/langgraph/interrupts>
- Checkpointers — <https://docs.langchain.com/oss/python/langgraph/checkpointers>

### TypeSafe / Jev
- Introducción — <https://docs.typesafe.ai/introduction>
- Quickstart — <https://docs.typesafe.ai/introduction/quickstart>
- Primitivas — <https://docs.typesafe.ai/primitives>
- Noul — <https://docs.typesafe.ai/primitives/noul>
- Choice — <https://docs.typesafe.ai/primitives/choice>
- Score — <https://docs.typesafe.ai/primitives/score>
- Consola / API keys — <https://console.typesafe.ai/settings/keys>
- Post de lanzamiento — <https://typesafe.ai/blog/introducing-system-one-models-and-jev>

### Integración
- TypeSafe en LangChain (`TypeSafeClassifier`, `AutoModeMiddleware`, `NoulCriteria`) — <https://docs.langchain.com/oss/python/integrations/providers/typesafe>
- Post de LangChain sobre el harness — <https://www.langchain.com/blog/building-a-harness-with-jev>

### Metodología
- Calibración en scikit-learn — <https://scikit-learn.org/stable/modules/calibration.html>

### Herramientas
- `sqlglot` — buscar `tobymao/sqlglot` en GitHub; leer el *expression tree primer*
- Olist dataset — buscar "Brazilian E-Commerce Public Dataset by Olist" en Kaggle

### Trabajo previo (referencia, no copiar)
- `themsquared/jev-benchmark` — clasificación de riesgo de tool calls
- `AbdelStark/jev-benchmarks` — calibración y riesgo selectivo
- `jmanhype/jev-dspy-lab` — calibración sobre ruteo de tickets

---

## Riesgos conocidos

**El middleware de LangChain es experimental.** La API se va a mover. Fijar
versiones en el lock y esperar romper algo al actualizar.

**Los falsos positivos son el riesgo real del gate**, no la detección. Un gate
paranoico es peor que no tener gate, porque el agente deja de servir.

**Jev es la segunda línea, nunca la única.** Los permisos de base de datos son
la primera. Si el proyecto se presenta como "Jev protege la base", está mal
presentado.

**Que Jev gane o pierda contra el baseline con LLM no es criterio de
aceptación.** Las preguntas donde falla son hallazgo y van al README.

**El corpus de fuentes tiene días de antigüedad.** Todo lo de TypeSafe se
publicó a partir del 15/09/2026. Verificar cada dato antes de construir encima.

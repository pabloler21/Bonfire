# Bonfire — Plan de implementación por fases

Agente de análisis SQL que usa Jev (TypeSafe System One) para decidir si un
resultado responde bien la pregunta.

> El nombre viene de las hogueras de los Souls: el punto al que volvés para
> intentarlo de nuevo. Es lo que hace el agente cuando Jev ve que la consulta
> corrió pero respondió mal: vuelve, con el motivo, y reintenta.

**Última revisión del plan:** 24 de septiembre de 2026.

---

## Cómo usar este plan con Claude Code

Este proyecto se apoya en piezas que se mueven rápido:

| Pieza | Estado | Riesgo |
|---|---|---|
| `langchain` v1 | `create_agent` reemplazó a `create_react_agent`; lo legacy se movió a `langchain-classic` | tutoriales viejos no compilan |
| `typesafe-sdk` / Jev | modelo publicado el 15/09/2026 | firmas, límites y precios pueden haber cambiado |
| `langchain-typesafe` | middleware marcado **experimental** | Bonfire no lo usa (ver Fase 5) |

**Regla para Claude Code, a aplicar en cada fase:**

1. Antes de escribir código contra cualquiera de estas piezas, **leer la
   fuente viva** listada al final de la fase. No escribir firmas de memoria.
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

**Qué es y qué no es.** Bonfire es una aplicación: un agente de SQL sobre
Olist. **No es un benchmark**: no se compara Jev contra un LLM ni contra otras
configuraciones, y no se prueba por separado si Jev o la API funcionan. Lo
que se mide es si esta aplicación funciona bien.

**Quién hace qué.**

| Momento | Quién decide | Qué garantiza |
|---|---|---|
| Antes de ejecutar | código determinista: rol de Postgres solo `SELECT`, `sqlcheck` (sqlglot), `statement_timeout` | que no se escribe nada y que no corren consultas absurdas (varias sentencias, producto cartesiano explícito) |
| Después de ejecutar | **Jev**, una sola request por intento | si el resultado responde bien la pregunta: responder, reintentar (con el motivo) o preguntarle al usuario |

No hay gate de Jev antes de ejecutar: ejecutar ya es seguro (solo lectura) y
barato (timeout), y después de ejecutar Jev ve la pregunta, el SQL **y** el
resultado. **Jev no es una barrera de seguridad**: la seguridad la da
Postgres. Jev juzga si una lectura permitida responde bien la pregunta.

El orden no es negociable en un punto: los **casos de prueba** (Fase 3) se
congelan **antes** de implementar el middleware. Son **cuatro archivos**
(split dev/test, ver Fase 3), commiteados y hasheados en un commit con el tag
`eval-frozen`. Si se escriben después, sin querer se eligen casos donde el
middleware ya funciona.

**Dev y test.** La rúbrica, los umbrales y los prompts se ajustan **solo**
sobre el split dev. El split test corre **una vez**, en la Fase 6. Todo lo
que cambie después de la primera corrida sobre test es una versión nueva: se
reportan las dos, no se sobrescribe.

**Umbrales.** Todos los umbrales de este plan son **placeholders con nombre**
(`PITFALL_MIN`, `NEXT_STEP_MIN_CONFIDENCE`, `MAX_ATTEMPTS`, `MAX_ROWS`,
`MAX_ROWS_TO_JEV`, `MAX_CELL_CHARS`). Los valores finales se fijan sobre el split dev.

---

## Fase 0 — Conexión con Jev ✅

**Hecha.** La API key está en `.env` y `main.py` hace una llamada real con las
tres primitivas (`Choice`, `Score`, `Noul`). Con eso alcanza: **no se prueba
ni se evalúa si Jev o la API funcionan**. El rendimiento y el comportamiento
de Jev dentro de la aplicación se observan con los traces de Langfuse
(Fase 7).

Datos de la documentación que condicionan el diseño
(<https://docs.typesafe.ai/models>, <https://docs.typesafe.ai/api>):

- dos topes de tokens por request: `state` + todas las preguntas, 64k;
  `state` + la pregunta más larga, 32k. `MAX_ROWS_TO_JEV` (Fase 4) se
  dimensiona contra el segundo;
- pasarse de un tope devuelve **HTTP 400 `max_tokens_exceeded`**, que no
  figura en la tabla de errores de los docs (ver `NOTES.md`, 24/09/2026). El
  cliente de la Fase 4 no lo reintenta;
- se cobra solo la entrada (US$0,042 por Mtok): el costo que importa es el
  LLM generador, no Jev.

---

## Fase 1 — Base de datos y `run_sql` 🚦 ✅

**Hecha el 25/09/2026.** Los dos puntos del criterio de salida se verificaron
contra la base real (`uv run python -m src.agent.tools`), y los tests pasan
sin red (`tests/test_sqlcheck.py`, `tests/test_tools.py`). Además de lo que
pedía esta fase, se agregó por hallazgos en pruebas contra Postgres 18.6:

- `sqlcheck` también rechaza `SELECT ... INTO` (crea una tabla) y funciones
  con efectos sobre la sesión o el servidor que el rol puede llamar:
  `set_config` (deja la sesión sin timeout), `pg_sleep*`,
  `pg_terminate_backend`, `pg_cancel_backend`, `pg_advisory*`;
- `run_sql` abre una conexión nueva por llamada, así ningún cambio de sesión
  sobrevive a la consulta siguiente;
- los DSN usan `127.0.0.1` y no `localhost`: en Windows, `localhost` prueba
  primero IPv6 y tarda 10 s en conectar.

**Objetivo:** una base real con permisos correctos, y la única tool del agente
con todos los chequeos deterministas. Todo lo que es seguridad se resuelve en
esta fase, sin Jev.

**Tareas**

- `docker-compose.yml` con PostgreSQL.
- `init.sql`: base `olist` con el dataset público de Olist (e-commerce
  brasileño, multi-tabla, dominio de pedidos y pagos).
- Dos roles:

  | Rol | Privilegios | Lo usa |
  |---|---|---|
  | `bonfire_agent` | `CONNECT` sobre `olist`; `USAGE` sobre el schema de datos; `SELECT` sobre sus tablas. Nada más. | solo `run_sql` |
  | `bonfire_admin` | todo | `init.sql`, carga de datos, tests de permisos. **Nunca** lo carga la app. |

  ```sql
  REVOKE CONNECT ON DATABASE olist FROM PUBLIC;
  GRANT CONNECT ON DATABASE olist TO bonfire_agent;
  ```
- Settings a nivel de rol en `init.sql`:

  ```sql
  ALTER ROLE bonfire_agent SET default_transaction_read_only = on;
  ALTER ROLE bonfire_agent SET statement_timeout = '10s';
  ```

  Son **defaults de sesión**: Postgres permite que la sesión los cambie con
  `SET` (ver `NOTES.md`, 22/09/2026, D2). No son la barrera contra
  `SET statement_timeout = 0; SELECT ...`; esa barrera es `sqlcheck`.
- `.env.example` con dos DSN: `AGENT_DSN` y `ADMIN_DSN`. El proceso de la app
  carga solo el primero. `ADMIN_DSN` lo usan solo los scripts de setup y los
  tests.
- `src/sqlcheck.py`: verificación determinista con `sqlglot`, como
  **allow-list** (la raíz tiene que ser una lectura), no como deny-list de
  nodos peligrosos. Rechaza:
  - lo que no parsea, o más de una sentencia;
  - una raíz que no sea `SELECT`, una operación de conjuntos o un `WITH` que
    termina en lectura. Las sentencias que `sqlglot` no modela vuelven como
    un nodo opaco (`exp.Command`) y se tratan como no-lectura;
  - `INSERT` / `UPDATE` / `DELETE` / `MERGE` en cualquier nodo (CTEs
    incluidas), DDL, DCL, `FOR UPDATE` / `FOR SHARE`;
  - joins sin condición: `CROSS JOIN` o `FROM a, b` sin predicado que los
    una. Un producto cartesiano explícito se detecta en el árbol; no es una
    decisión de Jev.
- `src/agent/tools.py::run_sql(query)`:
  - corre `sqlcheck` primero; si falla, **no ejecuta** y devuelve el motivo
    como texto, para que el modelo reescriba;
  - conexión mediante `bonfire_agent` (`AGENT_DSN`), abierta en modo
    **read-only**;
  - `statement_timeout` de 10 segundos;
  - límite de filas: trunca con `cursor.fetchmany(MAX_ROWS + 1)` y le avisa
    al modelo cuando el resultado fue truncado (no envolver la query en
    `SELECT * FROM (...) LIMIT n`);
  - errores de Postgres capturados como texto, sin excepción que rompa el
    loop;
  - además del texto para el modelo, devuelve el resultado estructurado
    (columnas, filas, total de filas, truncado, error) para el middleware de
    la Fase 5. Verificar en la doc de tools de LangChain cómo se adjunta un
    artefacto a un `ToolMessage` (`response_format="content_and_artifact"`).
- `tests/test_sqlcheck.py`, sin red: cada regla de rechazo, más `SELECT`
  legítimos que no tienen que rechazarse (joins con condición, CTEs de
  lectura, subconsultas).

> **D2, resuelta el 24/09/2026:** `sqlcheck` nace entero en la **Fase 1**,
> porque `run_sql` lo necesita desde el principio.

**Entregable:** base levantada, `run_sql` funcionando desde un script suelto,
`tests/test_sqlcheck.py` pasando.

**🚦 Criterio de salida:**

- `DELETE FROM orders` ejecutado **directo en Postgres** como `bonfire_agent`
  (sin pasar por `sqlcheck`) **tiene que fallar por permisos**;
- `run_sql` rechaza sin ejecutar `SET statement_timeout = 0; SELECT 1`,
  `DELETE FROM orders` y `SELECT * FROM orders, customers`.

**Fuentes a verificar**

- Privilegios y `CONNECT`: <https://www.postgresql.org/docs/current/ddl-priv.html>
- `ALTER ROLE ... SET`: <https://www.postgresql.org/docs/current/sql-alterrole.html>
- `default_transaction_read_only`, `statement_timeout`:
  <https://www.postgresql.org/docs/current/runtime-config-client.html>
- Conexión read-only en psycopg 3 (`Connection.read_only`):
  <https://www.psycopg.org/psycopg3/docs/api/connections.html>
- Tools en LangChain (artefactos en `ToolMessage`):
  <https://docs.langchain.com/oss/python/langchain/tools>
- `sqlglot`: buscar `tobymao/sqlglot` en GitHub; leer el *expression tree
  primer* y `parse_one` / `find_all`. Advertencia de las fuentes: `sqlglot`
  **no es un validador** y puede no detectar ciertos errores de sintaxis;
  Postgres igual rechaza lo que no parsea.
- Dataset de Olist: buscar "Brazilian E-Commerce Public Dataset by Olist" en
  Kaggle y verificar licencia y esquema vigente.

---

## Fase 2 — Agente funcionando, todavía sin Jev

**Objetivo:** tener el agente respondiendo preguntas de punta a punta antes de
agregarle el middleware. Sirve para detectar problemas del prompt o de la tool
sin mezclarlos con los de Jev, y para medir los tokens reales del generador.

**Tareas**

- `src/agent/build.py` con `create_agent`:
  - un solo modelo generativo
  - la tool `run_sql`
  - el esquema de la base en el system prompt
  - límite de iteraciones como red de seguridad (el tope real de intentos lo
    pone el código en la Fase 5)
- Sin checkpointer: `/ask` es de un solo turno y nada se pausa.
- Correr las 10 preguntas de `eval/questions_dev.jsonl` y guardar trazas
  completas: vueltas, SQL de cada vuelta, latencia, **tokens del generador
  por vuelta**. Estas 10 preguntas **no se solapan** con el split test.

**Entregable:** agente funcional + `eval/results/pilot.json`.

**Criterio de salida:** responde correctamente al menos la mitad de las
preguntas simples. Si no llega, el problema está en el prompt del esquema.

**Fuentes a verificar**

- Agentes y el loop: <https://docs.langchain.com/oss/python/langchain/agents>
- Referencia de `create_agent`:
  <https://reference.langchain.com/python/langchain/agents/factory/create_agent>
- Novedades de v1 (qué cambió de nombre):
  <https://docs.langchain.com/oss/python/releases/langchain-v1>

> Verificar puntualmente: si el límite de iteraciones se pasa a
> `create_agent` o al `invoke`.

---

## Fase 3 — Casos de prueba 🚦

**Objetivo:** la verdad contra la que se ajustan los umbrales y se valida la
aplicación. Langfuse muestra qué decidió Jev; no puede decir si la decisión
fue correcta. Sin casos etiquetados, los umbrales son adivinanzas.

**Qué tienen que ejercitar los casos:** lo que Jev decide de verdad, es decir
**SQL que corre sin error pero responde mal la pregunta**. Lo que un parser
detecta (producto cartesiano explícito, join sin condición, sentencias que no
son `SELECT`) no va acá: son tests de `sqlcheck` (Fase 1).

### Split dev / test

Congelar no es lo mismo que no contaminar: el hash impide editar los archivos,
no impide sobreajustar la rúbrica y los umbrales mirándolos.

| Archivo | Tamaño | Se usa para |
|---|---|---|
| `eval/questions_dev.jsonl` | 10 | piloto de la Fase 2, ajuste de prompts, chequeos funcionales de la Fase 5 |
| `eval/questions_test.jsonl` | 40 | solo Fase 6 |
| `eval/cases_dev.jsonl` | 20 | redacción de la rúbrica, umbrales |
| `eval/cases_test.jsonl` | 40 | solo Fase 6 |

- Los dos splits se estratifican por categoría o etiqueta.
- Los casos límite obligatorios van al split **test**; el split dev recibe
  **variantes** de ellos, no copias.

### `eval/questions_test.jsonl` — 40 preguntas de negocio

Cada registro: pregunta en lenguaje natural + SQL de referencia escrito a mano
+ resultado esperado. Sirven para medir el acierto del agente completo.

```json
{"id": "q12", "category": "join", "question": "...", "reference_sql": "...", "acceptable_sql": [], "ordered": false}
```

| Tipo | Cantidad |
|---|---|
| Una tabla, agregación simple | 10 |
| Join de dos o más tablas | 12 |
| Ventana temporal / períodos | 8 |
| Ambiguas (admiten más de una lectura) | 5 |
| Sin respuesta posible con este esquema | 5 |

| Categoría | Pasa si |
|---|---|
| Una tabla, join, ventana temporal | el resultado coincide con la referencia |
| Ambigua | le pregunta al usuario qué lectura quiere, o responde con `reference_sql` o alguna de `acceptable_sql` y dice qué lectura usó (revisión a mano) |
| Sin respuesta | no hay respuesta numérica, y la respuesta dice que el esquema no alcanza (revisión a mano) |

- El resultado de referencia se calcula **al congelar** y se hashea junto con
  el archivo.
- `ask_user` es una respuesta final (ver Fase 7): la respuesta es la
  pregunta aclaratoria y el caso termina ahí.

### `eval/cases_test.jsonl` — 40 casos (pregunta + SQL + resultado)

Cada caso es una pregunta, un SQL que **corre sin error** y su resultado. El
resultado completo se calcula al congelar, ejecutando el SQL como
`bonfire_agent`, y se guarda y hashea con el archivo. Lo que ve Jev de ese
resultado lo arma `build_review_state()` (Fase 4), **la misma función** que
usa el middleware en producción.

```json
{"id": "c07", "source": "agent", "question": "...", "sql": "...", "next_step": "retry", "pitfalls": ["customer_id_not_unique"], "note": "..."}
```

**De dónde salen los casos (`source`):**

- `agent`: **al menos la mitad**. Se corre el agente de la Fase 2 (el LLM
  generador real, sin middleware) sobre preguntas que **no** están en
  `questions_test.jsonl`: las de dev más preguntas extra escritas para esto.
  Cada SQL que genera y que corre sin error es un candidato, y se etiqueta.
  Son los errores que el agente comete de verdad, no los que uno imagina.
- `handwritten`: SQL escrito a mano para cubrir las trampas y los casos
  límite que el agente no produjo.
- **El owner revisa y aprueba todas las etiquetas antes de congelar.**

- `next_step`: etiqueta única, mismas opciones que el `Choice` de la Fase 4
  (`answer | retry | ask_user`).
- `pitfalls`: lista de trampas presentes (IDs de los `Noul` de la Fase 4);
  vacía si el SQL es correcto.

Mezcla obligatoria:

- **SQL correcto que responde bien** (`answer`, sin trampas): al menos un
  tercio. Son los que miden falsos positivos, que van primero.
- **SQL correcto que parece sospechoso**: por ejemplo, un join con
  `order_items` que agrega bien con `COUNT(DISTINCT order_id)`. Un revisor
  paranoico lo marca; no tiene que marcarlo.
- **Una trampa conocida de Olist por caso**, como mínimo:
  - `customer_id_not_unique`: contar clientes con `customer_id` (un ID por
    pedido) en vez de `customer_unique_id`;
  - `join_fanout`: sumar `payment_value` después de un join con
    `order_items`, que repite el pago una vez por ítem;
  - candidatas a confirmar sobre el esquema real: incluir pedidos cancelados
    o no entregados en "ventas", usar la columna de fecha equivocada
    (compra contra entrega), dejar las categorías en portugués sin la tabla
    de traducción.
- **Resultado vacío o con el grano equivocado** para la pregunta (`retry`).
- **Pregunta ambigua** donde el SQL eligió una lectura sin avisar
  (`ask_user`).

**Entregable:** los cuatro archivos + resultados de referencia +
`eval/README.md` con el criterio de etiquetado (`next_step`, cada trampa y el
comportamiento esperado por categoría de pregunta).

**🚦 Criterio de salida:** las etiquetas de `cases_*.jsonl` revisadas y
aprobadas por el owner, y los cuatro archivos y los resultados de referencia
commiteados y hasheados, con el tag `eval-frozen`, **antes** de que exista un
solo archivo en `src/middleware/`.

**Fuentes a verificar**

- Esquema de Olist y sus relaciones (en particular `customer_id` contra
  `customer_unique_id`, y la relación pedido–ítems–pagos): la página del
  dataset en Kaggle.
- Matriz de confusión y tasa base: <https://scikit-learn.org/stable/modules/calibration.html>

---

## Fase 4 — Cliente de Jev y rúbrica

**Objetivo:** la capa de acceso al modelo, aislada, y la única rúbrica del
proyecto.

**Tareas**

- `src/jev/client.py`: wrapper del SDK que registra en cada llamada la versión
  de modelo devuelta, tokens, latencia y el question set usado. El 400
  `max_tokens_exceeded` se trata como error propio y no se reintenta.
- `src/questions/review.py` — la rúbrica, **una request por intento**:

  ```
  next_step               Choice  answer | retry | ask_user
  customer_id_not_unique  Noul    the SQL counts or groups customers by customer_id instead of customer_unique_id
  join_fanout             Noul    the SQL sums or averages a value after a join that repeats it (e.g. payments × items)
  ...                     Noul    one per Olist trap confirmed in Fase 3
  ```

  - `next_step`, cada opción con su descripción de una línea:
    - `answer`: el resultado responde la pregunta y se puede reportar;
    - `retry`: el SQL o el resultado tiene un problema que otra consulta
      puede arreglar;
    - `ask_user`: la pregunta es ambigua o no se puede responder con este
      esquema; hace falta que una persona aclare.
  - Un `Noul` por trampa conocida. El que da positivo es el **motivo** que
    se le pasa al LLM para reescribir. Las instrucciones de cada `Noul` son
    completas: los IDs de pregunta no se le mandan al modelo.
  - `state` que ve Jev: lo arma `build_review_state(question, sql, result)`
    en `src/questions/review.py`. Es **una sola función**, usada igual por el
    middleware (Fase 5) y por la evaluación sobre los casos (Fases 4 y 6),
    así Jev ve lo mismo en los dos lados:

    ```json
    {
      "question": "...",
      "sql": "...",
      "result": {
        "columns": ["customer_state", "customers"],
        "row_count": 27,
        "truncated_for_review": true,
        "rows": [["SP", "..."], ["RJ", "..."]],
        "value": null
      },
      "schema_notes": "..."
    }
    ```

    - `columns`: nombres de columna.
    - `row_count`: total de filas que devolvió `run_sql` (si `run_sql` truncó
      en `MAX_ROWS`, se dice).
    - `rows`: las primeras `MAX_ROWS_TO_JEV` filas; `truncated_for_review`
      dice si hay más.
    - `value`: el valor solo, cuando el resultado es una fila y una columna
      (por ejemplo, un `COUNT`); si no, `null`.
    - `schema_notes`: notas fijas del esquema de Olist que Jev necesita para
      juzgar (por ejemplo, que `customer_id` es uno por pedido).
    - **Tope de tokens:** `state` + la pregunta más larga de la rúbrica tiene
      que quedar bajo 32k (Fase 0). `MAX_ROWS_TO_JEV` y un largo máximo por
      celda (`MAX_CELL_CHARS`, se corta con `…`) se fijan sobre dev con
      margen. Si igual vuelve el 400 `max_tokens_exceeded`, se reintenta una
      vez con la mitad de las filas y se registra.
  - Error de SQL o cero filas no llegan a Jev: los resuelve el código
    (Fase 5).
- `src/models.py` con Pydantic: `SqlCheck`, `SqlResult`, `ReviewVerdict`,
  `NextAction`.

  ```python
  class ReviewVerdict(BaseModel):
      next_step: Literal["answer", "retry", "ask_user"]
      next_step_confidence: float
      next_step_probabilities: dict[str, float]
      pitfalls: dict[str, float]  # Noul: probability of "yes", per trap
      model_id: str               # versioned model ID returned by the API
  ```

**Entregable:** la rúbrica corriendo sobre `cases_dev.jsonl`.

**Criterio de salida:** exactitud de `next_step` contra la etiqueta y
detección de cada trampa contra `pitfalls`, sobre `cases_dev.jsonl`.

**Fuentes a verificar**

- Primitivas y composición: <https://docs.typesafe.ai/primitives>
- <https://docs.typesafe.ai/primitives/noul>
- <https://docs.typesafe.ai/primitives/choice>
- State: <https://docs.typesafe.ai/concepts/state>
- Confidence: <https://docs.typesafe.ai/confidence>
- Limitaciones de Jev 1.13: <https://docs.typesafe.ai/model-jaggedness/jev-1.13>

> Semántica de Jev que afecta a `policy.py` (confirmada en
> <https://docs.typesafe.ai/api>, 24/09/2026):
> - `Noul` **no tiene** campo `confidence`: la probabilidad es la respuesta.
>   Solo `Choice` y `Score` traen `confidence`.
> - Cada pregunta se evalúa de forma independiente y en paralelo: la
>   respuesta de A no es contexto de B.

---

## Fase 5 — Middleware de revisión (después de ejecutar)

**Objetivo:** la pieza central del proyecto: después de cada `run_sql`, Jev
decide si responder, reintentar o preguntarle al usuario.

**Qué hook (verificado el 24/09/2026 en
<https://docs.langchain.com/oss/python/langchain/middleware/custom>, con
`langchain` 1.4.2 instalado).** LangChain v1 no tiene `after_tool`. Los hooks
son de nodo (`before_agent`, `before_model`, `after_model`, `after_agent`) y
de envoltura (`wrap_model_call`, `wrap_tool_call`). "Después de que corre la
tool" se implementa con **`wrap_tool_call`**: el middleware llama a
`handler(request)`, que ejecuta `run_sql`, y con el resultado en la mano
llama a Jev. `ToolCallRequest` trae `tool_call` (el SQL) y `state` (la
pregunta), así que la request a Jev se arma sin buscar en el historial. La
página de la integración de TypeSafe menciona `before_model` como alternativa
para reclasificar después de cada resultado; vale, pero obliga a reconstruir
pregunta, SQL y resultado desde los mensajes.

**Tareas**

- `src/middleware/review.py`, un solo middleware con dos hooks:
  - `wrap_tool_call`: ejecuta `run_sql`, decide con `review_decision()` y
    devuelve el `ToolMessage` con la decisión agregada (y el motivo si es
    `retry`), más un `Command` que guarda en el estado la última decisión y
    el número de intento.
  - `wrap_model_call`: cuando la decisión guardada es `answer`, `ask_user` o
    se llegó al tope de intentos, llama al modelo **sin tools** (`tool_choice`
    en none si el proveedor lo soporta; si no, sacando las tools del
    request), así el modelo tiene que responder en texto. Con `ask_user`, ese
    texto es la pregunta aclaratoria, y es la respuesta final.
- Política, código puro en `src/policy.py`. Los chequeos deterministas corren
  primero, sin Jev:

  ```python
  MAX_ATTEMPTS = 4                # placeholder
  PITFALL_MIN: dict[str, float]   # placeholder per trap, set on the dev split


  def review_decision(result: SqlResult, verdict: ReviewVerdict | None, attempt: int) -> NextAction:
      if attempt >= MAX_ATTEMPTS:
          return NextAction(kind="answer", reason="attempt cap reached")
      if result.error:
          return NextAction(kind="retry", reason=f"The query failed: {result.error}")
      if result.row_count == 0:
          return NextAction(kind="retry", reason="The query returned no rows.")

      assert verdict is not None  # Jev is only called when there is no error and at least one row
      flagged = [trap for trap, p in verdict.pitfalls.items() if p >= PITFALL_MIN[trap]]
      if flagged:
          return NextAction(kind="retry", reason=describe(flagged))
      return NextAction(kind=verdict.next_step, reason="Jev next_step")
  ```

  - El tope de intentos lo controla el código, no Jev.
  - Una trampa detectada gana sobre `next_step = answer`: el motivo concreto
    es más útil para reescribir que una opinión general.
  - Qué hacer cuando la `confidence` de `next_step` es baja
    (`NEXT_STEP_MIN_CONFIDENCE`) se decide sobre el split dev.
- A Jev se le mandan como máximo `MAX_ROWS_TO_JEV` filas. Las filas del
  resultado viajan a TypeSafe: con Olist (datos públicos) es aceptable, y el
  README lo dice explícitamente. No poner secretos en argumentos de tools ni
  en el estado.
- **Tests obligatorios, sin red**, con respuestas de Jev simuladas. No
  prueban a Jev: prueban **nuestra** lógica.
  - `tests/test_policy.py`: todas las ramas de `review_decision()`. Por
    ejemplo: trampa en 0,9 → `retry` con ese motivo; trampa en 0,1 y
    `next_step = answer` → `answer`; tope de intentos → `answer` aunque haya
    trampas; error o cero filas → `retry` sin veredicto.
  - `tests/test_review_middleware.py`, con el cliente de Jev mockeado:
    `retry` agrega el motivo al `ToolMessage`; después de `answer` o
    `ask_user` la siguiente llamada al modelo no tiene tools; error y cero
    filas no llaman a Jev; nunca se pasa de `MAX_ATTEMPTS`.

**`AutoModeMiddleware` (paquete `langchain-typesafe`) no aplica.** Según la
misma página de la integración, usa `wrap_tool_call` para clasificar una tool
call **antes** de ejecutarla, con un `Noul` de "¿es riesgoso?", y si lo es
devuelve un error en lugar de ejecutar. Es un gate de seguridad previo, y en
este diseño no hay gate de Jev previo: la seguridad la dan Postgres y
`sqlcheck`. Tampoco sirve como base del middleware de revisión, porque no ve
el resultado.

**Entregable:** el loop completo funcionando end to end + tests.

**🚦 Criterio de salida:** funcional, medido sobre `questions_dev.jsonl`:

- toda corrida termina con una respuesta final en texto;
- ninguna corrida supera `MAX_ATTEMPTS`;
- después de `answer` o `ask_user`, la siguiente llamada al modelo no puede
  llamar tools;
- después de `retry`, el modelo recibe el motivo antes de volver a escribir;
- `tests/test_policy.py` y `tests/test_review_middleware.py` pasan.

**Fuentes a verificar**

- Overview de middleware y diagrama de hooks:
  <https://docs.langchain.com/oss/python/langchain/middleware/overview>
- Middleware custom, hooks y `wrap_tool_call`:
  <https://docs.langchain.com/oss/python/langchain/middleware/custom>
- Firmas exactas de los hooks:
  <https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware>
- Cambiar `tools` / `tool_choice` del request (`ModelRequest`):
  <https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest>
- Integración de TypeSafe en LangChain (`AutoModeMiddleware`, hooks
  sugeridos): <https://docs.langchain.com/oss/python/integrations/providers/typesafe>

> Verificar puntualmente, contra el proveedor del modelo generador: si acepta
> `tool_choice` en none, y si acepta un request sin tools cuando el historial
> ya tiene tool calls.

---

## Fase 6 — Validación 🚦

**Objetivo:** saber si la aplicación funciona bien: si Jev deja pasar los
resultados correctos, si detecta las trampas, si el agente responde bien y
cuánto cuesta cada pregunta. No es una comparación: se mide una sola
configuración, la aplicación completa.

**Tareas**

- `eval/run_eval.py` corriendo la aplicación sobre el split test, **k = 3
  veces** con temperatura fija. Para cada métrica se reporta media y mín–máx,
  o un intervalo bootstrap. El p95 de latencia se calcula sobre las k × 40
  consultas.
- Registrar en cada corrida: fecha, model ID del generador, model ID de Jev
  devuelto por la API, temperatura, k.
- `eval/grading.py`: acierto por ejecución.
  - Se califica el resultado de la **última query exitosa** del agente contra
    el resultado de referencia, no la respuesta en prosa.
  - Filas comparadas como multiconjuntos; se ignoran nombres y orden de
    columnas; se comparan valores.
  - Floats redondeados a 2 decimales. `NULL` es igual a `NULL`.
  - El orden de filas solo se respeta cuando el registro tiene
    `"ordered": true` (rankings, top-N).
  - Ambiguas y sin respuesta: según la tabla de la Fase 3, con revisión a
    mano.
- Falsos positivos (Jev pide `retry` o `ask_user` sobre un resultado que
  estaba bien):
  - sobre `cases_test.jsonl`: los casos etiquetados `answer`;
  - sobre **tráfico real del agente**: registrar cada decisión de revisión
    durante las corridas sobre test, revisar a mano cada `retry` y
    `ask_user` y marcarlo `true_catch` o `false_positive` en
    `eval/results/flag_review.csv`.
- Métricas, con **falsos positivos primero**:

  | FP en `cases_test` | FP en tráfico real | Trampas detectadas | Acierto | Latencia p95 | Costo / pregunta | Intentos / pregunta |
  |---|---|---|---|---|---|---|
  | | | | | | | |

  Latencia, costo e intentos se reportan **por pregunta**, no por intento.
- Calibración sobre las etiquetas de `cases_test.jsonl`:
  - Brier score por cada `Noul` de trampa, con intervalo bootstrap del 95%,
    más un diagrama de confiabilidad de 5 bins;
  - exactitud y matriz de confusión para `next_step`;
  - ECE solo con la advertencia de tamaño de muestra (con 40 casos no
    alcanza), o no reportarlo. La advertencia va al README.

**Entregable:** `eval/results/` con datos crudos + la tabla +
`flag_review.csv`.

**🚦 Criterio de salida:** tasa de FP sobre tráfico real del agente **menor o
igual al 5%**, o una sección del README que liste los casos que la causaron y
por qué. Un revisor que manda a reintentar resultados correctos hace el
agente lento y caro.

**Fuentes a verificar**

- Calibración, `calibration_curve`, `brier_score_loss`:
  <https://scikit-learn.org/stable/modules/calibration.html>

> Advertencia metodológica que vale citar en el README: la calibración es una
> propiedad de **grupos** de predicciones, no de una respuesta individual, y
> las cifras publicadas por TypeSafe se midieron sobre sus datos. Hay que
> validarla en el dominio propio antes de confiar en un umbral.

---

## Fase 7 — API y observabilidad

**Objetivo:** que el proyecto sea usable y que se pueda ver qué decidió Jev
en cada intento.

**Tareas**

- `src/api.py`: `POST /ask` → respuesta final + resumen de los intentos (SQL,
  decisión de Jev y motivo). Respuesta JSON, sin streaming.
- **Sin estado entre requests.** `ask_user` es una respuesta final: la API
  devuelve la pregunta aclaratoria (con un campo que indique que es una
  aclaración, no una respuesta) y el usuario reformula en un `POST /ask`
  nuevo. No hay `thread_id` ni checkpointer.
- Langfuse trazando el árbol completo: cada llamada al generador, cada
  `run_sql` y cada request a Jev con su model ID, probabilidades y latencia.

**Entregable:** API corriendo en Docker Compose.

**Criterio de salida:** `/ask` responde, y la traza completa de esa pregunta,
incluidas las decisiones de Jev con sus probabilidades, se ve en Langfuse.

**Fuentes a verificar**

- FastAPI: documentación oficial.
- Integración de Langfuse con LangChain: documentación de Langfuse.

---

## Más adelante (fuera de v1)

- **Streaming por SSE** de cada paso en `/ask` (SQL propuesto, decisión de
  Jev, resultado).
- **Conversación de varios turnos**, para contestar la pregunta aclaratoria
  de `ask_user` dentro del mismo hilo. En v1 no: el usuario reformula en un
  request nuevo. Necesitaría un checkpointer.

---

## Fase 8 — README y cierre

**Contenido obligatorio del README**

1. Diagrama del flujo.
2. Qué recibe y qué devuelve Jev, con un ejemplo real de request y response.
3. La rúbrica completa, con la justificación de cada pregunta y de cada
   trampa de Olist.
4. La tabla de resultados de la Fase 6.
5. Los casos donde Jev falló: falsos positivos y trampas no detectadas.
6. **Limitaciones**: tamaño de los datasets, versión de modelo usada, fecha de
   las corridas. Además:
   - las limitaciones publicadas de Jev 1.13 (aritmética, fechas,
     distractores, estado adversarial), que caen justo en el juicio de si un
     resultado numérico responde una pregunta de ventana temporal;
   - la advertencia de tamaño de muestra sobre ECE.
7. Cómo reproducir todo con un comando. Reproduce el **pipeline**, no los
   números, porque las versiones de modelo se mueven: apuntar a los model IDs
   registrados en cada corrida.
8. **Threat model**:
   - la seguridad es determinista: Postgres garantiza que no se escribe
     nada (rol solo `SELECT`), `sqlcheck` rechaza lo que no es una única
     lectura y los productos cartesianos explícitos, y el timeout corta lo
     caro;
   - Jev **no** es una barrera de seguridad: juzga si una lectura permitida
     responde bien la pregunta;
   - no se protege la lectura de cualquier dato que `bonfire_agent` pueda
     leer, ni prompt injection dentro de valores de los datos.
9. **Qué sale del sistema y a quién**: la pregunta, el SQL y hasta
   `MAX_ROWS_TO_JEV` filas de resultado viajan a TypeSafe. Con Olist (datos
   públicos) es aceptable, y se dice explícitamente.

**Criterio de salida:** un revisor puede verificar cada una de las secciones
de arriba sin correr nada.

---

## Estructura final de archivos

```
bonfire/
├── README.md
├── NOTES.md                          # discrepancias plan vs documentación
├── docker-compose.yml
├── Dockerfile
├── init.sql                          # base olist, roles bonfire_agent y bonfire_admin, settings por rol
├── pyproject.toml / uv.lock          # versiones FIJADAS
├── .env.example                      # AGENT_DSN, ADMIN_DSN, TYPESAFE_API_KEY
│
├── src/
│   ├── main.py                       # entry point: pregunta -> respuesta
│   ├── models.py                     # SqlCheck, SqlResult, ReviewVerdict, NextAction
│   ├── policy.py                     # review_decision(); codigo puro
│   ├── sqlcheck.py                   # allow-list con sqlglot
│   ├── api.py                        # POST /ask
│   │
│   ├── agent/
│   │   ├── build.py                  # create_agent + middleware de revision
│   │   └── tools.py                  # run_sql: sqlcheck, conexion read-only, fetchmany
│   │
│   ├── jev/
│   │   └── client.py                 # wrapper del SDK, registra version
│   │
│   ├── questions/
│   │   └── review.py                 # rubrica (next_step + un Noul por trampa) y build_review_state()
│   │
│   └── middleware/
│       └── review.py                 # wrap_tool_call (Jev despues de run_sql) + wrap_model_call (fuerza texto)
│
├── eval/
│   ├── questions_dev.jsonl           # 10
│   ├── questions_test.jsonl          # 40
│   ├── cases_dev.jsonl               # 20
│   ├── cases_test.jsonl              # 40
│   ├── README.md                     # criterio de etiquetado
│   ├── grading.py                    # comparador de result sets
│   ├── run_eval.py
│   └── results/
│       └── flag_review.csv           # revision a mano de retry / ask_user sobre trafico real
│
└── tests/
    ├── test_policy.py                # todas las ramas de review_decision(); Jev simulado, sin red
    ├── test_sqlcheck.py              # sin red
    ├── test_tools.py                 # run_sql con una conexion falsa, sin red
    └── test_review_middleware.py     # cliente de Jev mockeado
```

---

## Índice de fuentes

### LangChain — agentes y middleware
- Agentes y el loop — <https://docs.langchain.com/oss/python/langchain/agents>
- Tools — <https://docs.langchain.com/oss/python/langchain/tools>
- Middleware, overview y diagrama de hooks — <https://docs.langchain.com/oss/python/langchain/middleware/overview>
- Middleware custom (hooks, `wrap_tool_call`, estado) — <https://docs.langchain.com/oss/python/langchain/middleware/custom>
- `AgentMiddleware`, firmas de hooks — <https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware>
- `ModelRequest` — <https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest>
- `create_agent`, referencia — <https://reference.langchain.com/python/langchain/agents/factory/create_agent>
- Novedades de v1 — <https://docs.langchain.com/oss/python/releases/langchain-v1>
- Índice completo para pasarle a un agente — <https://docs.langchain.com/llms.txt>

### TypeSafe / Jev
- Introducción — <https://docs.typesafe.ai/introduction>
- Modelos, límites y rate limit — <https://docs.typesafe.ai/models>
- API — <https://docs.typesafe.ai/api>
- Limitaciones de Jev 1.13 — <https://docs.typesafe.ai/model-jaggedness/jev-1.13>
- Primitivas — <https://docs.typesafe.ai/primitives>
- State — <https://docs.typesafe.ai/concepts/state>
- Confidence — <https://docs.typesafe.ai/confidence>
- SDK de Python — <https://docs.typesafe.ai/sdk/python>

### Integración
- TypeSafe en LangChain (`TypeSafeClassifier`, `AutoModeMiddleware`) — <https://docs.langchain.com/oss/python/integrations/providers/typesafe>

### PostgreSQL y psycopg
- Privilegios — <https://www.postgresql.org/docs/current/ddl-priv.html>
- `ALTER ROLE` — <https://www.postgresql.org/docs/current/sql-alterrole.html>
- Settings de cliente (`statement_timeout`, `default_transaction_read_only`) — <https://www.postgresql.org/docs/current/runtime-config-client.html>
- `SELECT` (privilegios de las cláusulas de bloqueo) — <https://www.postgresql.org/docs/current/sql-select.html>
- psycopg 3, conexiones — <https://www.psycopg.org/psycopg3/docs/api/connections.html>

### Metodología
- Calibración en scikit-learn — <https://scikit-learn.org/stable/modules/calibration.html>

### Herramientas
- `sqlglot` — buscar `tobymao/sqlglot` en GitHub; leer el *expression tree primer*
- Olist dataset — buscar "Brazilian E-Commerce Public Dataset by Olist" en Kaggle

---

## Riesgos conocidos

**El middleware de LangChain se mueve.** Fijar versiones en el lock y esperar
romper algo al actualizar.

**Los falsos positivos son el riesgo real**, no la detección. Un revisor que
manda a reintentar resultados correctos hace el agente lento y caro, y uno
que pregunta de más lo hace inútil.

**Jev no es una barrera de seguridad.** La seguridad es determinista:
permisos de Postgres, `sqlcheck` y timeout. Si el proyecto se presenta como
"Jev protege la base", está mal presentado.

**Nada protege la lectura.** No se impide leer nada que `bonfire_agent` pueda
leer, ni prompt injection dentro de los datos. Ver el threat model del README
(Fase 8).

**Las preguntas donde Jev falla son hallazgo**, no un fracaso del proyecto.
Van al README con el caso concreto.

**Limitaciones publicadas de Jev 1.13.** TypeSafe documenta puntos débiles en
aritmética, fechas, distractores y estado adversarial. Juzgar si un resultado
numérico responde una pregunta de ventana temporal cae dentro de esa zona.

**El corpus de fuentes tiene días de antigüedad.** Todo lo de TypeSafe se
publicó a partir del 15/09/2026. Verificar cada dato antes de construir encima.

---

## Cambios del 24/09/2026 (2): una sola decisión de Jev, después de ejecutar

Decisión del owner.

- Eliminado el gate de riesgo con Jev antes de ejecutar, la pausa de
  aprobación humana (`interrupt()`, `Approval`, `/approve`) y el checkpointer
  que requería. Con eso se van la base `bonfire_state`, el rol `bonfire_app`,
  `STATE_DSN`, `risk_classify.py`, `risk_gate.py` y `test_resume.py`.
- Antes de ejecutar solo hay chequeos deterministas: rol solo `SELECT`,
  `sqlcheck` (ahora entero en la Fase 1, incluidos los joins sin condición) y
  timeout. Eliminado `EXPLAIN` / `COST_MAX`: el timeout cubre lo caro.
- Después de ejecutar, una sola request a Jev (`wrap_tool_call`, verificado
  en la doc de LangChain): `Choice` `answer | retry | ask_user` más un `Noul`
  por trampa de Olist. El `Noul` positivo es el motivo del reintento; el tope
  de intentos lo pone el código.
- Los casos de prueba (Fase 3) apuntan a SQL que corre pero responde mal
  (`customer_id` contra `customer_unique_id`, sumas después de un join que
  duplica filas). El producto cartesiano deja de ser un umbral de Jev.
- Fases renumeradas: los middlewares de riesgo y de loop se unifican en la
  Fase 5; Validación pasa a 6, API a 7, README a 8.
- SSE pasa a "Más adelante". Langfuse se queda (Fase 7).
- Eliminado el encuadre "Jev es la segunda línea de defensa".
- Tests unitarios de nuestra lógica con Jev simulado: obligatorios (Fase 5).
- `ask_user` es respuesta final; la API no guarda estado entre requests
  (Fase 7).
- Lo que ve Jev del resultado lo define `build_review_state()`, una sola
  función para producción y evaluación, dentro del tope de 32k (Fase 4).
- Al menos la mitad de los casos de la Fase 3 salen de correr el LLM real;
  el owner aprueba las etiquetas antes de congelar.

## Cambios del 24/09/2026 (1): el proyecto no es una comparación

Decisión del owner sobre O1 (`PLAN_REVIEW.md`): Bonfire es una aplicación
que usa Jev, no un benchmark de Jev contra un LLM.

- Eliminada la Fase 7 anterior ("Baselines de comparación"): sin LLM juez,
  sin configuraciones `none` / `rules` / `llm` / `jev`, sin `eval/baselines.py`.
- La Fase 8 anterior ("Medición") pasa a ser la **Fase 7 — Validación**: una
  sola configuración, la aplicación completa. Las fases siguientes se
  renumeran: API pasa a 8, README a 9.
- Fase 2: deja de ser "baseline A"; es un paso de construcción.
- Regla general: se elimina "el baseline sin middleware se corre antes". Se
  mantiene congelar los casos de prueba antes de los middlewares.
- D2 resuelta: la verificación de sentencia única de lectura nace en la Fase 1.
- Fase 0 reducida a "Conexión con Jev" (hecha con `main.py`). Eliminados la
  sonda y `notebooks/00_probe.ipynb`: no se evalúa si Jev o la API
  funcionan. La observabilidad y el rendimiento van por Langfuse (Fase 8).

## Cambios respecto de la revisión del 19/09/2026

Aplicados desde `PLAN_REVIEW.md` (22/09/2026). Los números de fase y los
nombres de archivo de esta lista son los de ese momento; varios ítems (B4,
C2, D1 y el gate de riesgo en general) quedaron reemplazados por los cambios
del 24/09/2026.

- **B1** — `before_tool`/`after_tool` reemplazados por `after_model` (gate) y `before_model` + `wrap_model_call` (loop). Fase 5 (título, intro), Fase 6 (título, tareas, fuentes), estructura de archivos.
- **B2** — `gate()` nuevo en dos capas con `SqlCheck` y `Decision`; allow-list de `sqlglot`; discrepancias registradas fuera de `gate()`; `touches_pii` eliminado; tests de las tres ramas que antes daban `ALLOW`. Fase 5 (tareas), Fase 4 (rúbrica), Fase 9 (README, ítem 3).
- **B3** — `stmt_type` reemplazado por `effect` (Choice) + `cartesian` (Noul); `RiskVerdict` nuevo; nota sobre `Score` vs `Noul`. Fase 4 (tareas, fuentes).
- **B4** — Clasificar y pausar separados en `risk_classify.py` y `risk_gate.py`, orden inverso de `after_model`, plan B de cache, `Approval`, `test_resume.py` en el criterio de salida. Fase 5 (tareas, criterio de salida, fuentes), Fase 8 (tareas, trampa documentada), estructura de archivos.
- **B5** — Tres roles y dos bases (`olist`, `bonfire_state`), tres DSN, checkpointer con `bonfire_app`, nuevo punto del criterio de salida. Fase 1 (tareas, criterio de salida), Fase 2 (tareas), estructura de archivos.
- **C1** — Criterio de salida de la Fase 6 reemplazado por uno funcional; eliminado "al menos un orden de magnitud"; latencia, costo y vueltas se miden por pregunta en la Fase 7. Fase 6 (criterio de salida), Fase 7 (tabla y tareas).
- **C2** — Rúbrica de loop `answers_question` + `looks_wrong`; `loop_decision()` con chequeos deterministas primero; mecánica `before_model`/`wrap_model_call`; precedencia `finish`/`continue`; limitaciones de Jev 1.13. Fase 4 (rúbrica), Fase 6 (tareas, fuentes), Riesgos conocidos, Fase 9 (README, ítem 6).
- **M1** — Split dev/test (10/40 preguntas, 20/40 sentencias), estratificación, tag `eval-frozen`, ajuste solo sobre dev, versionado tras la primera corrida sobre test. Regla general, Fase 2 (piloto), Fase 3, Fase 4 (entregable), Fase 5 (criterio de salida sobre dev), estructura de archivos.
- **M2** — Registro de sentencia con `effect`, `cartesian`, `expensive`; Brier por `Noul` con bootstrap, diagrama de 5 bins, matriz de `effect`, ECE con advertencia. Fase 3, Fase 7 (tareas), Fase 9 (README, ítem 6).
- **M3** — Registro de tráfico real, `flag_review.csv`, dos tasas de FP, criterio de salida nuevo (FP ≤ 5% o sección del README). Fase 7 (tareas, tabla, criterio de salida), estructura de archivos.
- **M4** — Registro de pregunta con `acceptable_sql` y `ordered`, comportamiento esperado por categoría, resultado de referencia congelado, `eval/grading.py`. Fase 3, Fase 7 (tareas), estructura de archivos.
- **M5** — k = 3 corridas con intervalos; fórmula de costo con el generador, recalculada con el piloto; registro por corrida. Fase 0 (tareas), Fase 2 (tareas), Fase 7 (tareas).
- **D1** — `full_scan` eliminado; `sqlcheck.estimate` con `EXPLAIN (FORMAT JSON)` sin `ANALYZE`; `COST_MAX` sobre dev; costo débil en Olist en el README. Fase 4, Fase 5 (tareas, fuentes), Fase 9 (README, ítem 6).
- **D2** — `run_sql` re-verifica, abre en read-only, trunca con `fetchmany`; settings por rol (corregido: son defaults de sesión, ver `NOTES.md`); nota sobre `FOR UPDATE`; threat model. Fase 1 (tareas, decisión pendiente, fuentes), Fase 3 (casos límite), Fase 9 (README, ítem 8), Riesgos conocidos.
- **D3** — `MAX_ROWS_TO_JEV`; qué sale del sistema y a quién. Fase 6 (tareas), Fase 9 (README, ítem 9).
- **m1** — Dos límites de tokens (64k y 32k), `MAX_ROWS_TO_JEV` contra el segundo. Fase 0 (tareas, fuentes).
- **m2** — Prueba de 3 vs 5 preguntas movida a la Fase 0; nuevo criterio de salida de la Fase 4: exactitud por pregunta sobre `statements_dev.jsonl`. Fase 0 (tareas), Fase 4 (criterio de salida).
- **m3** — Propósito de `bonfire_admin`: `init.sql`, migraciones y tests de permisos; el eval no ejecuta sentencias. Fase 1 (tareas).
- **m4** — "Los 7 criterios de aceptación" pasa a "cada una de las secciones de arriba"; reproducir el pipeline, no los números. Fase 9 (ítem 7, criterio de salida).
- **m5** — Estructura de archivos actualizada. Estructura final de archivos.

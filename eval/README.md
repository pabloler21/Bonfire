# eval/

Dos exámenes distintos (Fases 2, 3 y 6 de `plan.md`):

- **Preguntas** (`questions_*.jsonl`): pregunta + SQL de referencia. El agente escribe su propio SQL y
  `run_eval.py` compara su resultado con el de la referencia. Mide si la aplicación responde bien.
- **Casos** (`cases_*.jsonl`, Fase 3): pregunta + un SQL fijo + qué tendría que decidir Jev. Mide si Jev juzga bien.

## Archivos

| Archivo | Qué es | Se usa en |
|---|---|---|
| `questions_dev.jsonl` | 10 preguntas, revisadas por el owner | piloto, ajustes, chequeos de la Fase 5 |
| `questions_harvest.jsonl` | 22 preguntas pensadas para provocar las trampas (`bait`) | cosechar SQL reales del agente para los casos `source: agent` |
| `questions_test.jsonl` | 40 preguntas (Fase 3) | solo Fase 6 |
| `cases_dev.jsonl` | 20 casos (Fase 3) | rúbrica y umbrales (Fase 4) |
| `cases_test.jsonl` | 40 casos (Fase 3) | solo Fase 6 |
| `run_eval.py` | corre el agente sobre un archivo de preguntas y guarda las trazas | |
| `grading.py` | compara resultados (reglas en el archivo) | |

Ninguna pregunta de test repite ni reformula una de dev o de harvest.

`run_eval.py` todavía califica solo contra `reference_sql`: si el agente usa una lectura de `acceptable_sql`, sale
`BAD` y se revisa a mano.

## Convenciones de las referencias

Valen para escribir `reference_sql` y para etiquetar casos. Si la pregunta dice otra cosa explícitamente, manda
la pregunta.

- **Ventas** ("vendidos", "ventas", "facturación", "ingresos"): solo `order_status = 'delivered'`. Decisión del
  owner, 06/10/2026 (`d08`, `NOTES.md`).
- **Pedidos** ("cuántos pedidos", "pedidos comprados"): todos los estados (`d09`).
- **Facturación o ingresos**: la pregunta dice qué medida quiere (precio de los ítems, precio más flete, o lo
  pagado). Si no lo dice, es una pregunta `ambiguous`, con las tres lecturas en `acceptable_sql`. Decisión del
  owner, 07/10/2026.
- **Un período sin decir qué fecha**: la fecha de compra, `order_purchase_timestamp` (`d09`, `d10`).
- **Clientes**: personas, `customer_unique_id`.
- **Reviews**: contar reviews es contar `review_id` distintos. Los promedios van sobre las filas de
  `order_reviews` (`d03`; da 4,09 de las dos formas).
- **Categorías**: si la pregunta no pide un idioma, la referencia usa el nombre en inglés y el nombre en
  portugués va en `acceptable_sql`.

## Trampas (`pitfalls`)

SQL que corre sin error y responde mal. Números medidos sobre la base el 06/10/2026.

| ID | Qué hace el SQL | Evidencia |
|---|---|---|
| `customer_id_not_unique` | cuenta o agrupa clientes por `customer_id`, que es uno por pedido | 99.441 `customer_id` contra 96.096 clientes (+3,5%) |
| `join_fanout` | suma o cuenta después de un join que repite filas | pagos después de unir con `order_items`: 20,31 M contra 16,01 M (+26,9%); `geolocation` tiene ~53 filas por prefijo postal |
| `wrong_grain` | cuenta filas de una tabla cuya fila no es la entidad de la pregunta | filas de `order_items` como pedidos: 112.650 contra 98.666 (+14,2%); filas de `order_reviews` como reviews: 99.224 contra 98.410 |
| `wrong_date_column` | usa otra fecha que la que pide la pregunta | pedidos de 2017: 45.101 por compra, 40.930 por entrega (−9,2%) |
| `undelivered_as_sales` | cuenta pedidos no entregados como ventas | 2.963 pedidos no entregados de 99.441 (3,0%); `d08`: 868 contra 857 |

Descartada: categorías sin traducir. El join con la tabla de traducción pierde 13 productos, y el nombre en
portugués no cambia ningún número.

## `next_step`

| Etiqueta | Cuándo |
|---|---|
| `answer` | el resultado responde la pregunta y se puede reportar; `pitfalls` vacío |
| `retry` | el SQL o el resultado tiene un problema que otra consulta arregla: una trampa, resultado vacío, grano equivocado |
| `ask_user` | la pregunta es ambigua y el SQL eligió una lectura sin avisar, o el esquema no alcanza para responderla |

Un caso con al menos una trampa es `retry`. Un error que no es ninguna de las 5 trampas es `retry` con `pitfalls`
vacío: lo tiene que atrapar `next_step` (`h14`, `cd20`). Una trampa nueva se crea si el error se repite
(decisión del owner, 07/10/2026). El owner revisa y aprueba todas las etiquetas antes de congelar.

## Qué se espera por categoría de pregunta

| Categoría | Pasa si |
|---|---|
| `single_table`, `join`, `time_window` | el resultado coincide con la referencia |
| `ambiguous` | pregunta qué lectura se quiere, o responde con `reference_sql` o alguna de `acceptable_sql` y dice qué lectura usó (revisión a mano) |
| `unanswerable` | no da un número y dice que el esquema no alcanza (revisión a mano) |

## Cosecha (`questions_harvest.jsonl`)

```
uv run python -m eval.run_eval eval/questions_harvest.jsonl eval/results/harvest.json
```

Cada SQL de `turns[].sql` que corrió sin error es un candidato a caso `source: agent`. `bait` dice qué trampa
intenta provocar la pregunta (`null`: ninguna). Que la pregunta la provoque no quiere decir que el agente caiga:
cada candidato se etiqueta por lo que hace su SQL.

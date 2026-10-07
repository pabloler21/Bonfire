# eval/

Cómo escribe SQL el LLM generador, todavía sin Jev. Dos archivos de preguntas:

| Archivo | Qué tiene |
|---|---|
| `questions_dev.jsonl` | 10 preguntas normales, sin trampa |
| `questions_traps.jsonl` | 10 preguntas con una trampa de Olist cada una (`bait`, abajo) |

Cada pregunta trae un `reference_sql` escrito a mano. `run_eval.py` le hace cada pregunta al agente, compara su
resultado con el de la referencia (`grading.py`) y guarda todo en `results/`. Cada pregunta deja además una
traza en Langfuse → Tracing, que es donde se revisa la respuesta a mano.

```
uv run python -m eval.run_eval eval/questions_dev.jsonl eval/results/dev.json
uv run python -m eval.run_eval eval/questions_traps.jsonl eval/results/traps.json
```

`run_eval.py` califica solo contra `reference_sql`: si el agente usa una lectura de `acceptable_sql`, sale `BAD`
y se revisa a mano.

## Convenciones de las referencias

Si la pregunta dice otra cosa explícitamente, manda la pregunta.

- **Ventas** ("vendidos", "ventas", "facturación", "ingresos"): solo `order_status = 'delivered'`. Decisión del
  owner, 06/10/2026 (`d08`, `NOTES.md`).
- **Facturación o ingresos**: la pregunta dice qué medida quiere (precio de los ítems, precio más flete, o lo
  pagado). Decisión del owner, 07/10/2026.
- **Pedidos** ("cuántos pedidos", "pedidos comprados"): todos los estados (`d09`).
- **Un período sin decir qué fecha**: la fecha de compra, `order_purchase_timestamp` (`d09`, `d10`).
- **Clientes**: personas, `customer_unique_id`.
- **Reviews**: contar reviews es contar `review_id` distintos. Los promedios van sobre las filas de
  `order_reviews` (`d03`; da 4,09 de las dos formas).
- **Categorías**: si la pregunta no pide un idioma, la referencia usa el nombre en inglés y el nombre en
  portugués va en `acceptable_sql`.

## Trampas

SQL que corre sin error y responde mal. Números medidos sobre la base el 06/10/2026.

| `bait` | Qué hace el SQL | Evidencia |
|---|---|---|
| `customer_id_not_unique` | cuenta o agrupa clientes por `customer_id`, que es uno por pedido | 99.441 `customer_id` contra 96.096 clientes (+3,5%) |
| `join_fanout` | suma o cuenta después de un join que repite filas | pagos después de unir con `order_items`: 20,31 M contra 16,01 M (+26,9%); `geolocation` tiene ~53 filas por prefijo postal |
| `wrong_grain` | cuenta filas de una tabla cuya fila no es la entidad de la pregunta | filas de `order_items` como pedidos: 112.650 contra 98.666 (+14,2%); filas de `order_reviews` como reviews: 99.224 contra 98.410 |
| `wrong_date_column` | usa otra fecha que la que pide la pregunta | pedidos de 2017: 45.101 por compra, 40.930 por entrega (−9,2%) |
| `undelivered_as_sales` | cuenta pedidos no entregados como ventas | 2.963 pedidos no entregados de 99.441 (3,0%); `d08`: 868 contra 857 |

Descartada: categorías sin traducir. El join con la tabla de traducción pierde 13 productos, y el nombre en
portugués no cambia ningún número.

"""Fase 2 — create_agent: modelo, tool run_sql, esquema en el system prompt y límite de llamadas al modelo.
Fase 5 — suma el middleware de revisión.
"""

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel

from src.agent.tools import MAX_ROWS, run_sql

# Modelo generador (el que escribe el SQL): el más barato de OpenAI al 28/09/2026 (US$0.05 / US$0.40 por Mtok,
# https://developers.openai.com/api/docs/pricing). Se cambia con BONFIRE_MODEL en .env, p. ej. "openai:gpt-6-sol".
# Formato "proveedor:modelo" de LangChain; el ID que devuelve la API se registra en cada corrida (eval/run_eval.py).
DEFAULT_MODEL = "openai:gpt-5-nano"

# Red de seguridad contra loops: después de tantas llamadas al modelo, el agente termina (exit_behavior="end").
# El tope real de intentos lo pone el código de la Fase 5 (policy.py, MAX_ATTEMPTS).
MAX_MODEL_CALLS = 8

# Esquema leído de la base real (information_schema y pg_constraint, 28/09/2026). Solo estructura:
# las notas sobre trampas de Olist (customer_id por pedido, joins que duplican filas) son para Jev (Fase 4),
# no para el generador, así la Fase 2 mide al agente sin ayuda.
SCHEMA = """\
customers(customer_id text PK, customer_unique_id text, customer_zip_code_prefix text, customer_city text, customer_state text)
orders(order_id text PK, customer_id text FK -> customers, order_status text, order_purchase_timestamp timestamp,
       order_approved_at timestamp, order_delivered_carrier_date timestamp, order_delivered_customer_date timestamp,
       order_estimated_delivery_date timestamp)
order_items(order_id text FK -> orders, order_item_id integer, product_id text FK -> products, seller_id text FK -> sellers,
            shipping_limit_date timestamp, price numeric, freight_value numeric; PK (order_id, order_item_id))
order_payments(order_id text FK -> orders, payment_sequential integer, payment_type text, payment_installments integer,
               payment_value numeric; PK (order_id, payment_sequential))
order_reviews(review_id text, order_id text FK -> orders, review_score integer, review_comment_title text,
              review_comment_message text, review_creation_date timestamp, review_answer_timestamp timestamp;
              PK (review_id, order_id))
products(product_id text PK, product_category_name text, product_name_lenght integer, product_description_lenght integer,
         product_photos_qty integer, product_weight_g integer, product_length_cm integer, product_height_cm integer,
         product_width_cm integer)
product_category_name_translation(product_category_name text PK, product_category_name_english text)
sellers(seller_id text PK, seller_zip_code_prefix text, seller_city text, seller_state text)
geolocation(geolocation_zip_code_prefix text, geolocation_lat double precision, geolocation_lng double precision,
            geolocation_city text, geolocation_state text)

Values:
- orders.order_status: delivered, shipped, canceled, unavailable, invoiced, processing, created, approved
- order_payments.payment_type: credit_card, boleto, voucher, debit_card, not_defined
- states are two-letter Brazilian codes (SP, RJ, MG, ...); category names are in Portuguese
"""

SYSTEM_PROMPT = f"""You are a data analyst for Olist, a Brazilian e-commerce marketplace.
Answer the user's question by querying the PostgreSQL database with the run_sql tool.

Rules for SQL:
- Send exactly one read-only query per call: SELECT, WITH ... SELECT, or UNION.
- Every join needs a condition (ON or USING).
- At most {MAX_ROWS} rows come back. Aggregate in SQL instead of reading raw rows.
- If a query fails or is rejected, read the message and send a corrected query.

When you have the result, answer in the same language as the question, in one or two sentences, with the numbers.
If the question can be read in more than one way, say which reading you used.
If the database cannot answer the question, say so instead of guessing.

Database schema:
{SCHEMA}"""


def build_agent(model: str | BaseChatModel | None = None):
    """El agente de Bonfire. `model` acepta un string "proveedor:modelo" o una instancia (útil en tests)."""
    return create_agent(
        model or os.environ.get("BONFIRE_MODEL", DEFAULT_MODEL),
        tools=[run_sql],
        system_prompt=SYSTEM_PROMPT,
        middleware=[ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end")],
    )

-- Fase 1 — Base olist: esquema, carga de los CSV y el rol bonfire_agent (solo SELECT).
-- Lo corre la imagen oficial de Postgres, una sola vez, como bonfire_admin
-- (POSTGRES_USER, superusuario), con psql -v ON_ERROR_STOP=1.
-- Los CSV se montan en /data/olist (ver docker-compose.yml).

-- Tablas: mismos nombres de columna que los CSV de Kaggle, typos incluidos
-- (product_name_lenght), así HEADER MATCH detecta si el dataset cambia.

CREATE TABLE customers (
    customer_id              text PRIMARY KEY,   -- one per order, not per person
    customer_unique_id       text NOT NULL,      -- the actual customer
    customer_zip_code_prefix text NOT NULL,      -- text: keeps leading zeros
    customer_city            text NOT NULL,
    customer_state           text NOT NULL
);

CREATE TABLE sellers (
    seller_id              text PRIMARY KEY,
    seller_zip_code_prefix text NOT NULL,
    seller_city            text NOT NULL,
    seller_state           text NOT NULL
);

-- No FK to product_category_name_translation: two categories in products
-- (pc_gamer, portateis_cozinha_e_preparadores_de_alimentos) have no translation.
CREATE TABLE products (
    product_id                 text PRIMARY KEY,
    product_category_name      text,
    product_name_lenght        integer,
    product_description_lenght integer,
    product_photos_qty         integer,
    product_weight_g           integer,
    product_length_cm          integer,
    product_height_cm          integer,
    product_width_cm           integer
);

CREATE TABLE product_category_name_translation (
    product_category_name         text PRIMARY KEY,
    product_category_name_english text NOT NULL
);

CREATE TABLE orders (
    order_id                      text PRIMARY KEY,
    customer_id                   text NOT NULL REFERENCES customers,
    order_status                  text NOT NULL,
    order_purchase_timestamp      timestamp NOT NULL,
    order_approved_at             timestamp,
    order_delivered_carrier_date  timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp NOT NULL
);

CREATE TABLE order_items (
    order_id            text NOT NULL REFERENCES orders,
    order_item_id       integer NOT NULL,
    product_id          text NOT NULL REFERENCES products,
    seller_id           text NOT NULL REFERENCES sellers,
    shipping_limit_date timestamp NOT NULL,
    price               numeric(10, 2) NOT NULL,
    freight_value       numeric(10, 2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE order_payments (
    order_id             text NOT NULL REFERENCES orders,
    payment_sequential   integer NOT NULL,
    payment_type         text NOT NULL,
    payment_installments integer NOT NULL,
    payment_value        numeric(10, 2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- review_id is not unique on its own: the same review can cover several orders.
CREATE TABLE order_reviews (
    review_id               text NOT NULL,
    order_id                text NOT NULL REFERENCES orders,
    review_score            integer NOT NULL,
    review_comment_title    text,
    review_comment_message  text,
    review_creation_date    timestamp NOT NULL,
    review_answer_timestamp timestamp NOT NULL,
    PRIMARY KEY (review_id, order_id)
);

-- No PK: a zip prefix has many rows (one per coordinate).
CREATE TABLE geolocation (
    geolocation_zip_code_prefix text NOT NULL,
    geolocation_lat             double precision NOT NULL,
    geolocation_lng             double precision NOT NULL,
    geolocation_city            text NOT NULL,
    geolocation_state           text NOT NULL
);

-- Carga. Orden: primero las tablas referenciadas.
-- HEADER MATCH falla si las columnas del CSV no coinciden con la tabla.
-- La traducción usa HEADER true: su CSV empieza con un BOM que rompe MATCH.
COPY customers      FROM '/data/olist/olist_customers_dataset.csv'      WITH (FORMAT csv, HEADER MATCH);
COPY sellers        FROM '/data/olist/olist_sellers_dataset.csv'        WITH (FORMAT csv, HEADER MATCH);
COPY products       FROM '/data/olist/olist_products_dataset.csv'       WITH (FORMAT csv, HEADER MATCH);
COPY product_category_name_translation
                    FROM '/data/olist/product_category_name_translation.csv' WITH (FORMAT csv, HEADER true);
COPY orders         FROM '/data/olist/olist_orders_dataset.csv'         WITH (FORMAT csv, HEADER MATCH);
COPY order_items    FROM '/data/olist/olist_order_items_dataset.csv'    WITH (FORMAT csv, HEADER MATCH);
COPY order_payments FROM '/data/olist/olist_order_payments_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY order_reviews  FROM '/data/olist/olist_order_reviews_dataset.csv'  WITH (FORMAT csv, HEADER MATCH);
COPY geolocation    FROM '/data/olist/olist_geolocation_dataset.csv'    WITH (FORMAT csv, HEADER MATCH);

ANALYZE;

-- Rol del agente: conectarse a olist y leer. Nada más.
-- La contraseña viene de la variable de entorno BONFIRE_AGENT_PASSWORD (.env).
\getenv agent_password BONFIRE_AGENT_PASSWORD
CREATE ROLE bonfire_agent LOGIN PASSWORD :'agent_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

REVOKE CONNECT ON DATABASE olist FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
GRANT CONNECT ON DATABASE olist TO bonfire_agent;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO bonfire_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bonfire_agent;

-- Defaults de sesión, no barreras: la sesión puede cambiarlos con SET
-- (NOTES.md, 22/09/2026). La barrera contra "SET ...; SELECT ..." es sqlcheck.
ALTER ROLE bonfire_agent SET default_transaction_read_only = on;
ALTER ROLE bonfire_agent SET statement_timeout = '10s';

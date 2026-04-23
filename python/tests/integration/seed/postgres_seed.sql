-- Integration test seed data for PostgreSQL
-- Schema: e-commerce with analytics

CREATE SCHEMA IF NOT EXISTS ecom;
CREATE SCHEMA IF NOT EXISTS analytics;

-- E-commerce schema
CREATE TABLE ecom.customers (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    country     TEXT NOT NULL DEFAULT 'KZ',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ecom.products (
    id          SERIAL PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price_usd   NUMERIC(10,2) NOT NULL,
    stock_qty   INT NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE ecom.orders (
    id              SERIAL PRIMARY KEY,
    customer_id     INT NOT NULL REFERENCES ecom.customers(id),
    status          TEXT NOT NULL DEFAULT 'pending',
    total_usd       NUMERIC(12,2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    shipped_at      TIMESTAMPTZ
);

CREATE TABLE ecom.order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT NOT NULL REFERENCES ecom.orders(id),
    product_id  INT NOT NULL REFERENCES ecom.products(id),
    quantity    INT NOT NULL,
    unit_price  NUMERIC(10,2) NOT NULL
);

-- Analytics schema
CREATE TABLE analytics.page_views (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    url         TEXT NOT NULL,
    referrer    TEXT,
    country     TEXT,
    viewed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analytics.events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    properties  JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed customers
INSERT INTO ecom.customers (email, full_name, country)
SELECT
    'customer' || i || '@example.com',
    'Customer ' || i,
    (ARRAY['KZ','RU','US','DE','GB'])[1 + (i % 5)]
FROM generate_series(1, 1000) AS i;

-- Seed products
INSERT INTO ecom.products (sku, name, category, price_usd, stock_qty)
VALUES
    ('SKU-001', 'Laptop Pro 15"',   'Electronics',  1299.99, 50),
    ('SKU-002', 'Wireless Mouse',   'Electronics',    29.99, 200),
    ('SKU-003', 'Office Chair',     'Furniture',     349.00, 30),
    ('SKU-004', 'Standing Desk',    'Furniture',     499.00, 15),
    ('SKU-005', 'USB-C Hub',        'Electronics',    49.99, 100),
    ('SKU-006', 'Monitor 27"',      'Electronics',   399.99, 45),
    ('SKU-007', 'Keyboard Mech',    'Electronics',    89.99, 80),
    ('SKU-008', 'Webcam 4K',        'Electronics',   129.99, 60),
    ('SKU-009', 'Headphones NC',    'Electronics',   249.99, 70),
    ('SKU-010', 'Desk Lamp',        'Accessories',    39.99, 150);

-- Seed orders
INSERT INTO ecom.orders (customer_id, status, total_usd, created_at, shipped_at)
SELECT
    1 + (i % 1000),
    (ARRAY['pending','paid','shipped','delivered','cancelled'])[1 + (i % 5)],
    (49.99 + (i * 7.3))::NUMERIC(12,2),
    now() - (i || ' hours')::interval,
    CASE WHEN i % 3 = 0 THEN now() - (i/2 || ' hours')::interval ELSE NULL END
FROM generate_series(1, 5000) AS i;

-- Seed order items
INSERT INTO ecom.order_items (order_id, product_id, quantity, unit_price)
SELECT
    1 + (i % 5000),
    1 + (i % 10),
    1 + (i % 5),
    (29.99 + (i * 2.7))::NUMERIC(10,2)
FROM generate_series(1, 10000) AS i;

-- Seed analytics
INSERT INTO analytics.page_views (session_id, url, country)
SELECT
    'sess-' || (1 + i % 500),
    '/product/' || (1 + i % 10),
    (ARRAY['KZ','RU','US'])[1 + (i % 3)]
FROM generate_series(1, 50000) AS i;

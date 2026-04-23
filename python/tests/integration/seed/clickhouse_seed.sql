-- Integration test seed data for ClickHouse 24.3
-- ClickHouse uses MergeTree engine and has different type names

CREATE TABLE IF NOT EXISTS dialekt_integration.customers (
    id         UInt32,
    email      String,
    full_name  String,
    country    FixedString(2),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY id;

CREATE TABLE IF NOT EXISTS dialekt_integration.products (
    id         UInt32,
    sku        String,
    name       String,
    category   String,
    price_usd  Decimal(10,2),
    stock_qty  Int32  DEFAULT 0,
    active     UInt8  DEFAULT 1
) ENGINE = MergeTree()
ORDER BY id;

CREATE TABLE IF NOT EXISTS dialekt_integration.orders (
    id          UInt32,
    customer_id UInt32,
    status      String DEFAULT 'pending',
    total_usd   Decimal(12,2),
    created_at  DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY id;

CREATE TABLE IF NOT EXISTS dialekt_integration.events (
    id          UInt64,
    session_id  String,
    event_type  String,
    page_url    String,
    country     String,
    occurred_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (occurred_at, id);

-- Seed customers (500 rows)
INSERT INTO dialekt_integration.customers (id, email, full_name, country)
SELECT
    number + 1                                      AS id,
    concat('customer', toString(number + 1), '@example.com') AS email,
    concat('Customer ', toString(number + 1))       AS full_name,
    arrayElement(['KZ','RU','US','DE','GB'], (number % 5) + 1) AS country
FROM numbers(500);

-- Seed products (10 rows)
INSERT INTO dialekt_integration.products (id, sku, name, category, price_usd, stock_qty) VALUES
    (1,  'SKU-001', 'Laptop Pro 15"',  'Electronics',  1299.99, 50),
    (2,  'SKU-002', 'Wireless Mouse',  'Electronics',    29.99, 200),
    (3,  'SKU-003', 'Office Chair',    'Furniture',     349.00, 30),
    (4,  'SKU-004', 'Standing Desk',   'Furniture',     499.00, 15),
    (5,  'SKU-005', 'USB-C Hub',       'Electronics',    49.99, 100),
    (6,  'SKU-006', 'Monitor 27"',     'Electronics',   399.99, 45),
    (7,  'SKU-007', 'Keyboard Mech',   'Electronics',    89.99, 80),
    (8,  'SKU-008', 'Webcam 4K',       'Electronics',   129.99, 60),
    (9,  'SKU-009', 'Headphones NC',   'Electronics',   249.99, 70),
    (10, 'SKU-010', 'Desk Lamp',       'Accessories',    39.99, 150);

-- Seed orders (1000 rows)
INSERT INTO dialekt_integration.orders (id, customer_id, status, total_usd)
SELECT
    number + 1                                      AS id,
    (number % 500) + 1                              AS customer_id,
    arrayElement(['pending','paid','shipped','delivered','cancelled'], (number % 5) + 1) AS status,
    round(49.99 + (number * 7.3), 2)               AS total_usd
FROM numbers(1000);

-- Seed events (10000 rows)
INSERT INTO dialekt_integration.events (id, session_id, event_type, page_url, country)
SELECT
    number + 1                                      AS id,
    concat('sess-', toString((number % 500) + 1))  AS session_id,
    arrayElement(['pageview','click','purchase','search'], (number % 4) + 1) AS event_type,
    concat('/product/', toString((number % 10) + 1)) AS page_url,
    arrayElement(['KZ','RU','US'], (number % 3) + 1) AS country
FROM numbers(10000);

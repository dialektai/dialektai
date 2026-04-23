-- Integration test seed data for MySQL 8.0

CREATE TABLE IF NOT EXISTS customers (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    email      VARCHAR(255) NOT NULL UNIQUE,
    full_name  VARCHAR(255) NOT NULL,
    country    VARCHAR(2)   NOT NULL DEFAULT 'KZ',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    sku        VARCHAR(50)     NOT NULL UNIQUE,
    name       VARCHAR(255)    NOT NULL,
    category   VARCHAR(100)    NOT NULL,
    price_usd  DECIMAL(10,2)   NOT NULL,
    stock_qty  INT             NOT NULL DEFAULT 0,
    active     TINYINT(1)      NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT            NOT NULL,
    status      VARCHAR(20)    NOT NULL DEFAULT 'pending',
    total_usd   DECIMAL(12,2)  NOT NULL,
    created_at  DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shipped_at  DATETIME,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    order_id    INT           NOT NULL,
    product_id  INT           NOT NULL,
    quantity    INT           NOT NULL,
    unit_price  DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Seed customers
INSERT INTO customers (email, full_name, country)
WITH RECURSIVE seq(i) AS (
    SELECT 1
    UNION ALL
    SELECT i + 1 FROM seq WHERE i < 500
)
SELECT
    CONCAT('customer', i, '@example.com'),
    CONCAT('Customer ', i),
    ELT(1 + (i MOD 5), 'KZ','RU','US','DE','GB')
FROM seq;

-- Seed products
INSERT INTO products (sku, name, category, price_usd, stock_qty) VALUES
    ('SKU-001', 'Laptop Pro 15"',  'Electronics',  1299.99, 50),
    ('SKU-002', 'Wireless Mouse',  'Electronics',    29.99, 200),
    ('SKU-003', 'Office Chair',    'Furniture',     349.00, 30),
    ('SKU-004', 'Standing Desk',   'Furniture',     499.00, 15),
    ('SKU-005', 'USB-C Hub',       'Electronics',    49.99, 100),
    ('SKU-006', 'Monitor 27"',     'Electronics',   399.99, 45),
    ('SKU-007', 'Keyboard Mech',   'Electronics',    89.99, 80),
    ('SKU-008', 'Webcam 4K',       'Electronics',   129.99, 60),
    ('SKU-009', 'Headphones NC',   'Electronics',   249.99, 70),
    ('SKU-010', 'Desk Lamp',       'Accessories',    39.99, 150);

-- Seed orders
INSERT INTO orders (customer_id, status, total_usd)
WITH RECURSIVE seq(i) AS (
    SELECT 1
    UNION ALL
    SELECT i + 1 FROM seq WHERE i < 1000
)
SELECT
    1 + (i MOD 500),
    ELT(1 + (i MOD 5), 'pending','paid','shipped','delivered','cancelled'),
    ROUND(49.99 + (i * 7.3), 2)
FROM seq;

-- Seed order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
WITH RECURSIVE seq(i) AS (
    SELECT 1
    UNION ALL
    SELECT i + 1 FROM seq WHERE i < 2000
)
SELECT
    1 + (i MOD 1000),
    1 + (i MOD 10),
    1 + (i MOD 5),
    ROUND(29.99 + (i * 2.7), 2)
FROM seq;

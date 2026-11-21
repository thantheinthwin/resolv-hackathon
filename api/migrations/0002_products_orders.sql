CREATE TABLE products (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    title TEXT GENERATED ALWAYS AS (json_extract(body, '$.title')) VIRTUAL NOT NULL,
    CHECK (json_extract(body, '$.id') IS id)
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    color TEXT NOT NULL,
    size TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    delivered_at TEXT NOT NULL,
    buyer_name TEXT NOT NULL
);
CREATE INDEX orders_by_product ON orders(product_id);

INSERT INTO products(id, body) SELECT id, body FROM listings ORDER BY rowid;

INSERT INTO orders(id, product_id, color, size, quantity, delivered_at, buyer_name)
SELECT 'UJ-' || lower(hex(randomblob(16))), id,
       coalesce(json_extract(body, '$.colors[0]'), ''), coalesce(json_extract(body, '$.sizes[0]'), ''),
       1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'Demo buyer'
FROM listings ORDER BY rowid;

DROP TABLE listings;

ALTER TABLE cases ADD COLUMN order_id TEXT
    GENERATED ALWAYS AS (json_extract(body, '$.order_id')) VIRTUAL REFERENCES orders(id);
ALTER TABLE cases ADD COLUMN status TEXT GENERATED ALWAYS AS (json_extract(body, '$.status')) VIRTUAL;
ALTER TABLE cases ADD COLUMN created_at TEXT GENERATED ALWAYS AS (json_extract(body, '$.created_at')) VIRTUAL;

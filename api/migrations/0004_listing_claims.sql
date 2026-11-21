ALTER TABLE cases ADD COLUMN listing_id TEXT
    GENERATED ALWAYS AS (json_extract(body, '$.listing_id')) VIRTUAL REFERENCES products(id);

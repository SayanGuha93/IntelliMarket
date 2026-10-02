CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,

    product_name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    category TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS product_listings (
    listing_id INTEGER PRIMARY KEY AUTOINCREMENT,

    product_id TEXT NOT NULL,

    source TEXT NOT NULL,
    external_product_id TEXT,

    seller TEXT,

    product_url TEXT,
    image_url TEXT,

    availability TEXT,

    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (product_id)
        REFERENCES products(product_id)
);


CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    listing_id INTEGER NOT NULL,

    price REAL NOT NULL,
    mrp REAL,
    discount REAL,

    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (listing_id)
        REFERENCES product_listings(listing_id)
);
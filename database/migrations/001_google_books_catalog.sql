CREATE TABLE IF NOT EXISTS google_books_catalog (
    volume_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subtitle TEXT,
    authors TEXT NOT NULL DEFAULT '[]',
    publisher TEXT,
    published_date TEXT,
    description TEXT,
    categories TEXT NOT NULL DEFAULT '[]',
    isbn10 TEXT,
    isbn13 TEXT,
    thumbnail_url TEXT,
    preview_url TEXT,
    info_url TEXT,
    sale_country TEXT,
    saleability TEXT,
    is_ebook INTEGER,
    google_list_price REAL,
    google_list_currency TEXT,
    google_retail_price REAL,
    google_retail_currency TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_google_books_catalog_title
    ON google_books_catalog(title);
CREATE INDEX IF NOT EXISTS idx_google_books_catalog_isbn13
    ON google_books_catalog(isbn13);

CREATE TABLE IF NOT EXISTS google_books_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sale_country TEXT,
    saleability TEXT,
    google_list_price REAL,
    google_list_currency TEXT,
    google_retail_price REAL,
    google_retail_currency TEXT,
    FOREIGN KEY (volume_id) REFERENCES google_books_catalog(volume_id)
);
CREATE INDEX IF NOT EXISTS idx_google_books_price_history_volume_time
    ON google_books_price_history(volume_id, observed_at);

CREATE TABLE IF NOT EXISTS crypto_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crypto_market_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    source_exchange TEXT NOT NULL,
    last REAL NOT NULL,
    last_btc REAL,
    lowest REAL,
    highest REAL,
    daily_change_percentage REAL,
    provider_date TEXT NOT NULL,
    collected_at_utc TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES crypto_assets(id),
    UNIQUE (asset_id, source_exchange, provider_date)
);

CREATE INDEX IF NOT EXISTS idx_crypto_history_asset_collected
    ON crypto_market_history(asset_id, collected_at_utc);
CREATE INDEX IF NOT EXISTS idx_crypto_history_exchange_collected
    ON crypto_market_history(source_exchange, collected_at_utc);

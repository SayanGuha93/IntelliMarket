import argparse

from data_sources.fake_store import get_products as get_fake_store_products
from data_sources.mock_api import get_products as get_mock_products
from data_sources.ingestion import save_products
from data_sources.google_books import GoogleBooksError, ingest_books

def main():
    parser = argparse.ArgumentParser(description="Ingest IntelliMarket product sources.")
    parser.add_argument("--google-books-query", help="Also ingest this Google Books search into the catalog.")
    parser.add_argument("--google-books-pages", type=int, default=1, help="Number of Google Books pages to ingest (1-40 results per page).")
    args = parser.parse_args()

    fake_store_products = get_fake_store_products()
    mock_products = get_mock_products()

    products = fake_store_products + mock_products

    print(f"Fetched {len(fake_store_products)} products from Fake Store.")
    print(f"Fetched {len(mock_products)} products from Mock Marketplace.")
    print(f"Total products to process: {len(products)}")

    save_products(products)

    if args.google_books_query:
        try:
            books = ingest_books(args.google_books_query, max_pages=args.google_books_pages)
            print(f"Stored {len(books)} Google Books catalog records.")
        except (GoogleBooksError, ValueError) as error:
            raise SystemExit(f"Google Books ingestion failed: {error}") from error

if __name__ == "__main__":
    main()

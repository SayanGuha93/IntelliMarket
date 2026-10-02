from data_sources.fake_store import get_products as get_fake_store_products
from data_sources.mock_api import get_products as get_mock_products
from data_sources.ingestion import save_products

def main():
    fake_store_products = get_fake_store_products()
    mock_products = get_mock_products()

    products = fake_store_products + mock_products

    print(f"Fetched {len(fake_store_products)} products from Fake Store.")
    print(f"Fetched {len(mock_products)} products from Mock Marketplace.")
    print(f"Total products to process: {len(products)}")

    save_products(products)

if __name__ == "__main__":
    main()
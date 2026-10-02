from datetime import datetime

def get_products():
    return [
        {
            "product_id": "MOCK_1",
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK",
            "category": "electronics",
            "price": 69.99,
            "mrp": 89.99,
            "discount": 22.22,
            "rating": 4.5,
            "review_count": 1200,
            "availability": "Available",
            "seller": "Mock Marketplace",
            "product_url": "https://example.com/mock-1",
            "image_url": None,
            "source": "MOCK_API",
            "timestamp": datetime.now().isoformat()
        },
        {
            "product_id": "MOCK_2",
            "product_name": "SanDisk SSD PLUS 1TB Internal SSD",
            "brand": "SanDisk",
            "model": "SDSSDA-1T00",
            "category": "electronics",
            "price": 99.99,
            "mrp": 129.99,
            "discount": 23.08,
            "rating": 4.6,
            "review_count": 1800,
            "availability": "Available",
            "seller": "Mock Marketplace",
            "product_url": "https://example.com/mock-2",
            "image_url": None,
            "source": "MOCK_API",
            "timestamp": datetime.now().isoformat()
        }
    ]

if __name__ == "__main__":
    products = get_products()
    print(f"Total products fetched: {len(products)}")
    for product in products:
        print(product["product_name"], product["price"])
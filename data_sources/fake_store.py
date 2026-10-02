import requests
from datetime import datetime


API_URL = "https://fakestoreapi.com/products"


def get_products():
    response = requests.get(API_URL)

    response.raise_for_status()

    data = response.json()

    products = []

    for item in data:
        product = {
            "product_id": f"FAKE_{item['id']}",
            "product_name": item["title"],
            "brand": "Unknown",
            "category": item["category"],
            "price": item["price"],
            "mrp": None,
            "discount": None,
            "rating": item["rating"]["rate"],
            "review_count": item["rating"]["count"],
            "availability": "Available",
            "seller": "Fake Store",
            "product_url": None,
            "image_url": item["image"],
            "source": "FAKE_STORE",
            "timestamp": datetime.now().isoformat()
        }

        products.append(product)

    return products


if __name__ == "__main__":

    products = get_products()

    print(f"Total products fetched: {len(products)}")

    for product in products[:5]:
        print("\n------------------------")
        print("Name:", product["product_name"])
        print("Category:", product["category"])
        print("Price:", product["price"])
        print("Rating:", product["rating"])
        print("Source:", product["source"])
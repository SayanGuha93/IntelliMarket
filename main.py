import requests
from bs4 import BeautifulSoup
import time
import random

from database import create_table, insert_price

URL = "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
PRODUCT_NAME = "A Light in the Attic"

def get_price():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    price = soup.find("p", class_="price_color").text
    
    # Clean unwanted characters
    price = ''.join(c for c in price if c.isdigit() or c == '.')
    
    return float(price)

def run_tracker():
    create_table()

    for _ in range(10):  # collect multiple data points
        price = get_price()

        # Add slight variation for realistic graph
        price += random.uniform(-2, 2)
        price = round(price, 2)

        print(f"Fetched Price: {price}")

        insert_price(PRODUCT_NAME, price)

        time.sleep(2)  # wait between requests

if __name__ == "__main__":
    run_tracker()
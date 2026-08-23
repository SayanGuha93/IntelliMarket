import requests
from bs4 import BeautifulSoup
from database import create_table, insert_price

BASE_URL = "http://books.toscrape.com/catalogue/page-{}.html"

def scrape_books():
    create_table()

    for page in range(1, 6):  # scrape first 5 pages
        url = BASE_URL.format(page)

        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        books = soup.find_all("article", class_="product_pod")

        for book in books:
            title = book.h3.a["title"]

            price_text = book.find("p", class_="price_color").text

            # Clean price
            price = ''.join(c for c in price_text if c.isdigit() or c == '.')

            price = float(price)

            print(f"{title} --> £{price}")

            insert_price(title, price, "SCRAPER")

if __name__ == "__main__":
    scrape_books()
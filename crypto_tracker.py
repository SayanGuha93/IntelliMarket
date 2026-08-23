import requests
import time
from database import create_table, insert_price

def get_crypto_prices():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr"
    
    try:
        response = requests.get(url)
        data = response.json()

        # Debug print (optional)
        # print(data)

        if "bitcoin" not in data or "ethereum" not in data:
            print("⚠️ API response issue, retrying...")
            return None, None

        btc_price = data["bitcoin"]["inr"]
        eth_price = data["ethereum"]["inr"]

        return btc_price, eth_price

    except Exception as e:
        print("⚠️ Error fetching data:", e)
        return None, None

def run_tracker():
    create_table()

    for _ in range(10):
        btc, eth = get_crypto_prices()

        if btc is None or eth is None:
            time.sleep(5)
            continue

        print(f"Bitcoin Price: ₹{btc}")
        print(f"Ethereum Price: ₹{eth}")
        print("------------------------")

        insert_price("Bitcoin", btc, "API")
        insert_price("Ethereum", eth, "API")

        time.sleep(5)

if __name__ == "__main__":
    run_tracker()
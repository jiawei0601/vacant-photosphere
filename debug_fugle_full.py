import requests
import os
from dotenv import load_dotenv

load_dotenv()

def debug_fugle_etf(symbol):
    token = os.getenv("FUGLE_API_TOKEN")
    if not token:
        print("Error: No FUGLE_API_TOKEN found.")
        return
    
    headers = {"X-API-KEY": token}
    # TSE, OTC? These are TSE.
    # Actually Fugle v1.0 intraday/quote/SYMBOL should work.
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
    
    print(f"--- Calling Fugle for {symbol} ---")
    resp = requests.get(url, headers=headers)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Response: {resp.json()}")
    else:
        print(f"Error Body: {resp.text}")

if __name__ == "__main__":
    for s in ["00763U", "00708L", "00738U"]:
        debug_fugle_etf(s)

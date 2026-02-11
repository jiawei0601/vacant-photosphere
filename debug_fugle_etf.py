import requests
import os
from dotenv import load_dotenv

load_dotenv()

def check_fugle(symbol):
    token = os.getenv("FUGLE_API_TOKEN")
    if not token:
        print("No token")
        return
    
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
    headers = {"X-API-KEY": token}
    resp = requests.get(url, headers=headers)
    print(f"Fugle {symbol} [{resp.status_code}]: {resp.text[:200]}")

if __name__ == "__main__":
    for s in ["00763U", "00708L", "00738U"]:
        check_fugle(s)

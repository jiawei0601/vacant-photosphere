import requests
import json

def debug_columns():
    url = "https://www.twse.com.tw/zh/exchangeReport/MI_5MINS?response=json"
    resp = requests.get(url)
    data = resp.json()
    fields = data.get("fields", [])
    if "data" in data and len(data["data"]) > 0:
        last_row = data["data"][-1]
        for i, (f, v) in enumerate(zip(fields, last_row)):
            print(f"{i}: {f} -> {v}")

if __name__ == "__main__":
    debug_columns()

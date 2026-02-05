import requests

def check_fields():
    url = "https://www.twse.com.tw/zh/exchangeReport/MI_5MINS?response=json"
    resp = requests.get(url)
    data = resp.json()
    print(data.get("fields"))
    if "data" in data:
        print(data["data"][-1])

if __name__ == "__main__":
    check_fields()

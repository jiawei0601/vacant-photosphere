import requests
from datetime import datetime

def test_twse():
    print("--- 測試證交所 MI_5MINS API ---")
    twse_url = "https://www.twse.com.tw/zh/exchangeReport/MI_5MINS?response=json"
    try:
        resp = requests.get(twse_url, timeout=10)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                last_row = data["data"][-1]
                print(f"最新數據時間: {last_row[0]}")
                print(f"累積委託買進筆數: {last_row[1]}")
                print(f"累積成交數量: {last_row[6]}")
                
                buy_orders = int(last_row[1].replace(",", ""))
                deal_volume = int(last_row[6].replace(",", ""))
                
                if buy_orders > 0:
                    overheat = deal_volume / buy_orders
                    print(f"🔥 計算出的過熱指數: {overheat:,.2f}")
                else:
                    print("錯誤: 買進筆數為 0")
            else:
                print("錯誤: 找不到數據 (可能已過交易時間或 API 格式變更)")
                print(f"API 回傳內容: {data}")
        else:
            print(f"API 請求失敗: {resp.text}")
    except Exception as e:
        print(f"發生異常: {e}")

if __name__ == "__main__":
    test_twse()

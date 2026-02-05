import os
from price_fetcher import PriceFetcher
from dotenv import load_dotenv

# 嘗試載入環境變數
load_dotenv()

def verify():
    fetcher = PriceFetcher()
    print("--- 執行市場數據抓取測試 ---")
    stats = fetcher.get_market_order_stats()
    
    if stats:
        print(f"日期: {stats['date']}")
        print(f"時間: {stats['time']}")
        print(f"買進股數 (Buy Volume): {stats['total_buy_volume']:,}")
        print(f"賣出股數 (Sell Volume): {stats['total_sell_volume']:,}")
        print(f"成交股數 (Deal Volume): {stats['total_deal_volume']:,}")
        
        # 計算過熱指數
        if stats['total_buy_volume'] > 0:
            overheat = (stats['total_deal_volume'] / stats['total_buy_volume']) * 100
            print(f"🔥 當前計算出的過熱指數: {overheat:.2f}%")
        else:
            print("計算失敗: 買進股數為 0")
    else:
        print("❌ 無法獲取市場統計數據。請確認 FUGLE_API_TOKEN 是否正確設定。")

if __name__ == "__main__":
    verify()

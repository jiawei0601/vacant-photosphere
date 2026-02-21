from price_fetcher import PriceFetcher
import asyncio

def test_us_stock():
    fetcher = PriceFetcher()
    test_symbols = ["AAPL", "TSLA", "MSFT", "NVDA"]
    
    print("=== 開始美股價格獲取測試 ===")
    for symbol in test_symbols:
        print(f"\n正在測試 {symbol}...")
        price_data = fetcher.get_last_price(symbol)
        if price_data:
            print(f"✅ 成功! 價格: {price_data['price']}, 來源: {price_data['source']}, 時間: {price_data['time']}")
        else:
            print(f"❌ 失敗: 未能獲取 {symbol} 價格")

    print("\n=== 開始美股歷史數據測試 ===")
    for symbol in ["AAPL"]:
        stats = fetcher.get_five_day_stats(symbol)
        if stats:
            print(f"✅ 成功! 讀取到 {len(stats)} 筆歷史數據")
            for s in stats:
                print(f"  - 日期: {s['date']}, 收盤: {s['close']}, MA20: {s['ma20']}")
        else:
            print(f"❌ 失敗: 未能獲取 {symbol} 歷史數據")

if __name__ == "__main__":
    test_us_stock()

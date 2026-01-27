import os
from price_fetcher import PriceFetcher
from datetime import datetime

def debug_market_order_stats():
    fetcher = PriceFetcher()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Checking data for: {today}")
    
    try:
        df = fetcher.loader.get_data(
            dataset="TaiwanStockStatisticsOfOrderBookAndTrade",
            start_date=today
        )
        
        if df is not None and not df.empty:
            print(f"Found {len(df)} rows for today.")
            print(df.tail(3))
        else:
            print(f"No data for today ({today}). Trying yesterday...")
            # Try to see if ANY data exists in the last few days
            df_recent = fetcher.loader.get_data(
                dataset="TaiwanStockStatisticsOfOrderBookAndTrade",
                start_date="2026-01-24"
            )
            if df_recent is not None and not df_recent.empty:
                print("Recent data available dates:")
                print(df_recent['date'].unique())
            else:
                print("No recent data found at all.")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_market_order_stats()

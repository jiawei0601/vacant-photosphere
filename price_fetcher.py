import os
import requests
from FinMind.data import DataLoader
from dotenv import load_dotenv

load_dotenv()

class PriceFetcher:
    def __init__(self):
        self.api_token = os.getenv("FINMIND_TOKEN", "")
        self.loader = DataLoader()
        if self.api_token:
            self.loader.login_by_token(api_token=self.api_token)

    def get_last_price(self, symbol):
        """
        獲取股票或權證的最新成交價
        """
        try:
            from datetime import datetime, timedelta
            # 取得最近幾天的資料以確保能拿到最後一筆成交價
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            
            df = self.loader.taiwan_stock_daily(
                stock_id=symbol,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and not df.empty:
                # 取得最後一列的收盤價，處理大小寫問題
                if 'Close' in df.columns:
                    return float(df.iloc[-1]['Close'])
                elif 'close' in df.columns:
                    return float(df.iloc[-1]['close'])
                else:
                    print(f"找不到價格欄位。可用欄位: {df.columns.tolist()}")
                    return None
            else:
                # 嘗試另一種介面 (部分權證或即時資料可能在此)
                df = self.loader.taiwan_stock_daily_short(stock_id=symbol)
                if df is not None and not df.empty:
                    if 'close' in df.columns:
                        return float(df.iloc[-1]['close'])
                    elif 'Close' in df.columns:
                        return float(df.iloc[-1]['Close'])
                
                print(f"找不到代碼 {symbol} 的價格資料")
                return None
        except Exception as e:
            print(f"獲取價格時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return None

if __name__ == "__main__":
    # 簡單測試
    fetcher = PriceFetcher()
    test_symbol = "2330" # 台積電
    price = fetcher.get_last_price(test_symbol)
    print(f"[{test_symbol}] 當前價格: {price}")

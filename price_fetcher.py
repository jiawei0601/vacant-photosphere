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
            return None
        except Exception as e:
            print(f"獲取價格時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_full_stats(self, symbol, offset=0):
        """
        獲取股票的完整統計資訊：開盤、收盤、最高、最低、MA20
        offset=0 為最新資料 (當日), offset=1 為前一日資料
        """
        try:
            from datetime import datetime, timedelta
            # 獲取約 60 天的資料以確保計算出 MA20
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=65)).strftime("%Y-%m-%d")
            
            df = self.loader.taiwan_stock_daily(
                stock_id=symbol,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and len(df) > offset:
                # 統一欄位名稱為小寫以方便處理
                df.columns = [c.lower() for c in df.columns]
                
                # 計算 MA20
                df['ma20'] = df['close'].rolling(window=20).mean()
                
                # 取得指定 offset 的資料 (最後一筆是 -1, 前一筆是 -2)
                idx = -1 - offset
                last_row = df.iloc[idx]
                
                date_str = last_row.get('date', '未知日期')
                
                return {
                    "date": date_str,
                    "open": float(last_row.get('open', 0)),
                    "close": float(last_row.get('close', 0)),
                    "high": float(last_row.get('high', 0)),
                    "low": float(last_row.get('low', 0)),
                    "ma20": round(float(last_row.get('ma20', 0)), 2) if last_row.get('ma20') else None
                }
            return None
        except Exception as e:
            print(f"獲取詳細統計資料時發生錯誤: {e}")
            return None

if __name__ == "__main__":
    # 簡單測試
    fetcher = PriceFetcher()
    test_symbol = "2330" # 台積電
    price = fetcher.get_last_price(test_symbol)
    print(f"[{test_symbol}] 當前價格: {price}")

import os
import requests
from FinMind.data import DataLoader
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

class PriceFetcher:
    def __init__(self):
        self.api_token = os.getenv("FINMIND_TOKEN", "").strip()
        self.loader = DataLoader()
        if self.api_token:
            print("正在使用 Token 登入 FinMind...")
            self.loader.login_by_token(api_token=self.api_token)
        else:
            print("⚠️ 警告: 未設定 FINMIND_TOKEN，可能導致 API 存取受限或失敗")

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
            
            if df is not None and not df.empty:
                # 統一欄位名稱為小寫
                df.columns = [c.lower() for c in df.columns]
                cols = df.columns.tolist()
                
                # 確保必要欄位存在
                if 'close' not in cols:
                    print(f"[{symbol}] 缺乏 'close' 欄位。可用欄位: {cols}")
                    return None
                
                # 計算 MA20
                df['ma20'] = df['close'].rolling(window=20).mean()
                
                if len(df) <= offset:
                    print(f"[{symbol}] 資料不足以計算 offset={offset}。總列數: {len(df)}")
                    return None
                    
                # 取得指定 offset 的資料 (最後一筆是 -1, 前一筆是 -2)
                idx = -1 - offset
                last_row = df.iloc[idx]
                
                # 處理漲跌幅
                change_pct = None
                if len(df) > abs(idx - 1):
                    try:
                        prev_close = float(df.iloc[idx - 1]['close'])
                        current_close = float(last_row['close'])
                        if prev_close != 0:
                            change_pct = round(((current_close - prev_close) / prev_close) * 100, 2)
                    except:
                        pass
                
                date_str = last_row.get('date', '未知日期')
                
                # 處理最高/最低欄位 (FinMind 有時用 high/low, 有時用 max/min)
                high_val = last_row.get('max') if 'max' in cols else last_row.get('high', 0)
                low_val = last_row.get('min') if 'min' in cols else last_row.get('low', 0)
                
                return {
                    "date": date_str,
                    "open": float(last_row.get('open', 0)),
                    "close": float(last_row.get('close', 0)),
                    "high": float(high_val),
                    "low": float(low_val),
                    "ma20": round(float(last_row.get('ma20', 0)), 2) if not pd.isna(last_row.get('ma20')) else None,
                    "change_pct": change_pct
                }
            else:
                print(f"[{symbol}] API 未回傳有效資料或資料為空")
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

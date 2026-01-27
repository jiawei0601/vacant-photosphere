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
            print("警告: 未設定 FINMIND_TOKEN，可能導致 API 存取受限或失敗")

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
                # 統一欄位名稱為小寫
                df.columns = [c.lower() for c in df.columns]
                if 'close' in df.columns:
                    # 取得最後一筆非 NaN 的收盤價
                    non_nan_df = df.dropna(subset=['close'])
                    if not non_nan_df.empty:
                        return float(non_nan_df.iloc[-1]['close'])
                
                print(f"[{symbol}] 找不到有效的 'close' 欄位資料。可用欄位: {df.columns.tolist()}")
                return None
            else:
                print(f"[{symbol}] taiwan_stock_daily 未回傳資料。")
                return None
            return None
        except KeyError as e:
            if str(e) == "'data'":
                print(f"[{symbol}] 獲取失敗: API 回傳格式錯誤 (KeyError: 'data')。這通常是因為未設定 FINMIND_TOKEN 或已達 API 使用上限。")
            else:
                print(f"獲取價格時發生 KeyError: {e}")
            return None
        except Exception as e:
            print(f"獲取價格時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_five_day_stats(self, symbol):
        """
        獲取股票最近五個交易日的詳細數據 (含 MA5, MA20)
        """
        try:
            from datetime import datetime, timedelta
            # 獲取約 40 天的資料以確保計算出 MA20
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
            
            df = self.loader.taiwan_stock_daily(
                stock_id=symbol,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and not df.empty:
                # 統一欄位名稱為小寫
                df.columns = [c.lower() for c in df.columns]
                
                # 計算 MA5 與 MA20
                df['ma5'] = df['close'].rolling(window=5).mean()
                df['ma20'] = df['close'].rolling(window=20).mean()
                
                # 取得最後 5 筆
                last_5_days = df.tail(5).copy()
                
                stats_list = []
                cols = df.columns.tolist()
                
                for _, row in last_5_days.iterrows():
                    high_val = row.get('max') if 'max' in cols else row.get('high', 0)
                    low_val = row.get('min') if 'min' in cols else row.get('low', 0)
                    
                    stats_list.append({
                        "date": row.get('date', '未知'),
                        "open": float(row.get('open', 0)),
                        "close": float(row.get('close', 0)),
                        "high": float(high_val),
                        "low": float(low_val),
                        "volume": int(row.get('trading_volume', 0)),
                        "ma5": round(float(row.get('ma5', 0)), 2) if not pd.isna(row.get('ma5')) else None,
                        "ma20": round(float(row.get('ma20', 0)), 2) if not pd.isna(row.get('ma20')) else None
                    })
                
                return stats_list
            return None
        except KeyError as e:
            if str(e) == "'data'":
                print(f"[{symbol}] 獲取失敗: API 回傳格式錯誤 (KeyError: 'data')。這通常是因為未設定 FINMIND_TOKEN 或已達 API 使用上限。")
            else:
                print(f"獲取 5 日統計資料時發生 KeyError: {e}")
            return None
        except Exception as e:
            print(f"獲取 5 日統計資料時發生錯誤: {e}")
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
        except KeyError as e:
            if str(e) == "'data'":
                print(f"[{symbol}] 獲取失敗: API 回傳格式錯誤 (KeyError: 'data')。這通常是因為未設定 FINMIND_TOKEN 或已達 API 使用上限。")
            else:
                print(f"獲取詳細統計資料時發生 KeyError: {e}")
            return None
        except Exception as e:
            print(f"獲取詳細統計資料時發生錯誤: {e}")
            return None

    def get_market_indices(self):
        """
        獲取主要市場指數 (台股、NASDAQ、商品期貨)
        """
        try:
            import yfinance as yf
            
            # 定義要抓取的代碼
            # ^TWII: 台灣加權指數
            # ^IXIC: NASDAQ Composite
            # GC=F: 黃金期貨
            # SI=F: 白銀期貨
            # HG=F: 銅期貨
            tickers = {
                "🇹🇼 台股加權": "^TWII",
                "🇺🇸 NASDAQ": "^IXIC",
                "💰 黃金": "GC=F",
                "🪙 白銀": "SI=F",
                "🔩 銅": "HG=F"
            }
            
            data_list = []
            
            # 一次性抓取以節省請求
            # yfinance 支援多個 tickers 一起抓，但為了處理方便與錯誤隔離，這裡逐一抓取或分批
            # 這裡使用 Tickers 物件一次抓取
            symbols_str = " ".join(tickers.values())
            result = yf.Tickers(symbols_str)
            
            for name, symbol in tickers.items():
                try:
                    ticker = result.tickers[symbol]
                    # fast_info 有時比較快且即時
                    price = ticker.fast_info.last_price
                    prev_close = ticker.fast_info.previous_close
                    
                    if price and prev_close:
                        change_pct = ((price - prev_close) / prev_close) * 100
                        emoji = "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪"
                        
                        data_list.append({
                            "name": name,
                            "price": price,
                            "change_pct": change_pct,
                            "emoji": emoji
                        })
                    else:
                        data_list.append({"name": name, "price": 0, "change_pct": 0, "emoji": "⚠️"})
                        
                except Exception as ex:
                    print(f"抓取 {name} ({symbol}) 失敗: {ex}")
                    data_list.append({"name": name, "price": 0, "change_pct": 0, "emoji": "❌"})
            
            return data_list
            
        except Exception as e:
            print(f"獲取市場指數時發生錯誤: {e}")
            return []

if __name__ == "__main__":
    # 簡單測試
    fetcher = PriceFetcher()
    # test_symbol = "2330" # 台積電
    # price = fetcher.get_last_price(test_symbol)
    # print(f"[{test_symbol}] 當前價格: {price}")
    
    print("--- 市場指數測試 ---")
    indices = fetcher.get_market_indices()
    for item in indices:
        print(f"{item['name']}: {item['price']:.2f} ({item['emoji']} {item['change_pct']:.2f}%)")

import os
import requests
from FinMind.data import DataLoader
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf

load_dotenv()

class PriceFetcher:
    def __init__(self):
        self.api_token = os.getenv("FINMIND_TOKEN", "").strip()
        # 支援多種可能的環境變數名稱，以相容 Railway 上的設定
        self.fugle_token = (os.getenv("FUGLE_API_TOKEN") or 
                            os.getenv("富果API KEY") or 
                            os.getenv("富果API_KEY") or "").strip()
        self.loader = DataLoader()
        if self.api_token:
            print("正在使用 Token 登入 FinMind...")
            self.loader.login_by_token(api_token=self.api_token)
        else:
            print("警告: 未設定 FINMIND_TOKEN，可能導致 API 存取受限或失敗")
        
        # 快取機制設定
        self.price_cache = {} # 格式: {symbol: {"price": float, "time": datetime, "full_stats": dict}}
        self.cache_duration = int(os.getenv("CACHE_DURATION_SECONDS", 300))

    def get_last_price(self, symbol):
        """
        獲取股票或權證的最新成交價 (支援快取)
        回傳: {"price": float, "time": str, "is_cached": bool} 或 None
        """
        from datetime import datetime, timedelta
        
        # 檢查快取
        now = datetime.now()
        if symbol in self.price_cache:
            cache_data = self.price_cache[symbol]
            if now - cache_data['time'] < timedelta(seconds=self.cache_duration):
                return {
                    "price": cache_data['price'],
                    "time": cache_data['time'].strftime("%H:%M:%S"),
                    "is_cached": True
                }

        try:
            # 1. 優先嘗試富果 (由使用者要求)
            if self.fugle_token:
                fugle_data = self._get_fugle_snapshot(symbol)
                if fugle_data:
                    # 更新快取
                    self.price_cache[symbol] = {
                        "price": fugle_data['price'],
                        "time": now
                    }
                    return fugle_data

            # 2. 如果富果未設定或失敗，嘗試 FinMind
            # 取得最近幾天的資料以確保能拿到最後一筆成交價
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
            
            df = self.loader.taiwan_stock_daily(
                stock_id=symbol,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                if 'close' in df.columns:
                    non_nan_df = df.dropna(subset=['close'])
                    if not non_nan_df.empty:
                        price = float(non_nan_df.iloc[-1]['close'])
                        # 更新快取
                        self.price_cache[symbol] = {
                            "price": price,
                            "time": now
                        }
                        return {
                            "price": price,
                            "time": now.strftime("%H:%M:%S"),
                            "is_cached": False,
                            "source": "FinMind"
                        }
                
                print(f"[{symbol}] 找不到有效的 'close' 欄位資料。")
                return None
            else:
                print(f"[{symbol}] FinMind/Fugle 均未回傳資料。")
                return None
        except KeyError as e:
            if str(e) == "'data'":
                print(f"[{symbol}] 獲取失敗: API 回傳格式錯誤 (KeyError: 'data')。這通常是因為未設定 FINMIND_TOKEN 或已達 API 使用上限。")
            else:
                print(f"獲取價格時發生 KeyError: {e}")
            return None
        except Exception as e:
            print(f"獲取價格時發生錯誤: {e}")
            return None

    def _get_fugle_snapshot(self, symbol):
        """
        使用富果 Fugle API 作為備用方案獲取最新行情
        """
        if not self.fugle_token:
            return None
        
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/{symbol}"
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 富果 snapshot 有時在 'last_price' 有時在 'close'
                price = data.get('last_price') or data.get('close')
                if price:
                    return {
                        "price": float(price),
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "is_cached": False,
                        "source": "Fugle"
                    }
            return None
        except Exception as e:
            print(f"[{symbol}] Fugle Snapshot 備援失敗: {e}")
            return None

    def _get_fugle_historical(self, symbol, start_date, end_date):
        """
        使用富果 Fugle API 獲取歷史 K 線資料，並轉換為 DataFrame 格式
        """
        if not self.fugle_token:
            return None
        
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}"
            params = {"from": start_date, "to": end_date, "fields": "open,high,low,close,volume"}
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                candles = data.get('candles', [])
                if not candles:
                    return None
                
                df = pd.DataFrame(candles)
                # 重新命名欄位以符合後續邏輯 (Fugle: date, open, high, low, close, volume)
                df = df.rename(columns={'volume': 'trading_volume'})
                df.columns = [c.lower() for c in df.columns]
                # Fugle 的資料通常是從新到舊，需翻轉
                df = df.iloc[::-1].reset_index(drop=True)
                return df
            return None
        except Exception as e:
            print(f"[{symbol}] Fugle Historical 備援發生錯誤: {e}")
            return None

    def get_five_day_stats(self, symbol):
        """
        獲取股票最近五個交易日的詳細數據 (含 MA5, MA20)
        """
        try:
            from datetime import datetime, timedelta
            # 獲取約 40 天的資料以確保計算出 MA20
            end_date_str = datetime.now().strftime("%Y-%m-%d")
            start_date_str = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
            
            # 1. 優先嘗試富果
            df = None
            if self.fugle_token:
                df = self._get_fugle_historical(symbol, start_date_str, end_date_str)
                if df is not None and not df.empty:
                     source_tag = "Fugle"
            
            # 2. 如果富果失敗或未設定，嘗試 FinMind
            if df is None or df.empty:
                df = self.loader.taiwan_stock_daily(
                    stock_id=symbol,
                    start_date=start_date_str,
                    end_date=end_date_str
                )
                source_tag = "FinMind"

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
                        "ma20": round(float(row.get('ma20', 0)), 2) if not pd.isna(row.get('ma20')) else None,
                        "fetch_time": datetime.now().strftime("%H:%M:%S")
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
            end_date_str = datetime.now().strftime("%Y-%m-%d")
            start_date_str = (datetime.now() - timedelta(days=65)).strftime("%Y-%m-%d")
            
            # 1. 優先嘗試富果
            df = None
            if self.fugle_token:
                df = self._get_fugle_historical(symbol, start_date_str, end_date_str)
            
            # 2. 如果富果失敗或未設定，嘗試 FinMind
            if df is None or df.empty:
                df = self.loader.taiwan_stock_daily(
                    stock_id=symbol,
                    start_date=start_date_str,
                    end_date=end_date_str
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
                    "volume": int(last_row.get('trading_volume', 0)),
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

    def get_api_usage(self):
        """
        獲取 FinMind API 的使用次數與上限
        """
        if not self.api_token:
            return None
            
        try:
            url = "https://api.web.finmindtrade.com/v2/user_info"
            response = requests.get(url, params={"token": self.api_token})
            data = response.json()
            
            if data.get("msg") == "success":
                return {
                    "user_count": data.get("user_count"),
                    "api_request_limit": data.get("api_request_limit")
                }
            return None
        except Exception as e:
            print(f"獲取 API 使用量時發生錯誤: {e}")
            return None

    def get_ticker_ma(self, symbol, window=20):
        """
        使用 yfinance 獲取特定代碼的移動平均線 (例如 MA20)
        """
        try:
            ticker = yf.Ticker(symbol)
            # 抓取足以計算 MA 的歷史長度 (安全起見抓 60 天)
            hist = ticker.history(period="60d")
            if len(hist) < window:
                return None, None
            
            # 計算 MA
            hist['MA'] = hist['Close'].rolling(window=window).mean()
            
            last_price = hist['Close'].iloc[-1]
            last_ma = hist['MA'].iloc[-1]
            
            return round(float(last_price), 2), round(float(last_ma), 2)
        except Exception as e:
            print(f"獲取 {symbol} MA 時發生錯誤: {e}")
            return None, None

    def get_market_order_stats(self):
        """
        獲取台股全市場每 5 秒委託成交統計 (買賣力道)
        資料集: TaiwanStockStatisticsOfOrderBookAndTrade
        """
        try:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 使用通用 get_data 獲取資料
            df = self.loader.get_data(
                dataset="TaiwanStockStatisticsOfOrderBookAndTrade",
                start_date=today
            )
            
            if df is not None and not df.empty:
                # 取得最後一筆 (13:30 收盤後的統計資訊)
                last_row = df.iloc[-1]
                return {
                    "time": last_row.get("time", "---"),
                    "total_buy_order": int(last_row.get("total_buy_order", 0)),
                    "total_sell_order": int(last_row.get("total_sell_order", 0)),
                    "total_buy_volume": int(last_row.get("total_buy_volume", 0)),
                    "total_sell_volume": int(last_row.get("total_sell_volume", 0)),
                }
            return None
        except Exception as e:
            print(f"獲取市場買賣力道時發生錯誤: {e}")
            return None

    def get_market_indices(self):
        """
        獲取主要市場指數 (台股、美股、能源、匯率、加密貨幣)
        使用 yfinance 擷取資料
        """
        try:
            # 定義要抓取的代碼
            # ^TWII: 台灣加權指數
            # ^DJI: 道瓊工業指數
            # ^GSPC: S&P 500
            # ^IXIC: NASDAQ Composite
            # ^SOX: 費城半導體指數
            # GC=F: 黃金期貨
            # CL=F: 原油期貨
            # TWD=X: 美元/台幣 (yfinance 通常是用 1 美元兌換多少台幣)
            # BTC-USD: 比特幣
            tickers_map = {
                "🇹🇼 台股加權": "^TWII",
                "🇺🇸 道瓊": "^DJI",
                "🇺🇸 S&P 500": "^GSPC",
                "🇺🇸 NASDAQ": "^IXIC",
                "🇺🇸 費城半導體": "^SOX",
                "💰 黃金": "GC=F",
                "🛢️ 原油": "CL=F",
                "💵 美元/台幣": "TWD=X",
                "₿ 比特幣": "BTC-USD"
            }
            
            data_list = []
            symbols = list(tickers_map.values())
            
            # 使用 yfinance 批量抓取最新資料 (只抓最近一天的歷史數據來獲取收盤與前收)
            # 這樣可以確保拿到漲跌幅
            data = yf.download(symbols, period="1d", interval="1m", progress=False)
            # 獲取前一日收盤價 (用於計算漲跌)
            # 註: 有些代碼可能不在同一時區，抓取較複雜，這裡簡化處理
            
            for name, symbol in tickers_map.items():
                try:
                    ticker = yf.Ticker(symbol)
                    # 優先使用 fast_info 獲取即時價格
                    info = ticker.fast_info
                    price = info.last_price
                    prev_close = info.previous_close
                    
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
                        # 如果 fast_info 拿不到，嘗試下載最近一筆
                        hist = ticker.history(period="2d")
                        if len(hist) >= 2:
                            current_close = hist['Close'].iloc[-1]
                            last_close = hist['Close'].iloc[-2]
                            change_pct = ((current_close - last_close) / last_close) * 100
                            emoji = "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪"
                            data_list.append({
                                "name": name,
                                "price": current_close,
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

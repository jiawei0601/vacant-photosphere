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

    def _get_taipei_now(self):
        """獲取台北時區的當前時間"""
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=8))
        return datetime.now(tz)

    def get_last_price(self, symbol):
        """
        獲取股票或權證的最新成交價 (支援快取)
        回傳: {"price": float, "time": str, "is_cached": bool} 或 None
        """
        from datetime import datetime, timedelta
        
        # 檢查快取
        now = self._get_taipei_now()
        if symbol in self.price_cache:
            cache_data = self.price_cache[symbol]
            if now.replace(tzinfo=None) - cache_data['time'].replace(tzinfo=None) < timedelta(seconds=self.cache_duration):
                return {
                    "price": cache_data['price'],
                    "time": cache_data['time'].strftime("%H:%M:%S"),
                    "is_cached": True
                }

        try:
            # 1. 優先嘗試富果 (由使用者要求)
            if self.fugle_token:
                fugle_symbol = symbol
                if symbol == "^TWII" or symbol == "TAIEX":
                    fugle_symbol = "IX0001"
                    
                fugle_data = self._get_fugle_snapshot(fugle_symbol)
                if fugle_data:
                    # 更新快取
                    self.price_cache[symbol] = {
                        "price": fugle_data['price'],
                        "time": now
                    }
                    return fugle_data

            # 2. 如果富果未設定或失敗，嘗試 FinMind
            # 取得最近幾天的資料以確保能拿到最後一筆成交價 (擴大到 14 天以應對長假)
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=14)).strftime("%Y-%m-%d")
            
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
                        last_row = non_nan_df.iloc[-1]
                        price = float(last_row['close'])
                        date_str = str(last_row.get('date', ''))
                        
                        # 如果 FinMind 的最新日期不是今天，且現在是交易時間，嘗試用 yfinance 抓更即時的值
                        today_str = now.strftime("%Y-%m-%d")
                        if date_str != today_str and now.hour >= 9:
                            print(f"[{symbol}] FinMind 資料僅更新至 {date_str}，嘗試使用 yfinance 獲取今日即時價...")
                            yf_price = self._get_yfinance_price(symbol)
                            if yf_price:
                                price = yf_price
                                date_str = today_str # 標記為今日

                        # 更新快取
                        self.price_cache[symbol] = {
                            "price": price,
                            "time": now
                        }
                        return {
                            "price": price,
                            "time": now.strftime("%H:%M:%S"),
                            "is_cached": False,
                            "source": "FinMind/yF"
                        }
            
            # 3. 最後備援：直接用 yfinance
            yf_price = self._get_yfinance_price(symbol)
            if yf_price:
                return {
                    "price": yf_price,
                    "time": now.strftime("%H:%M:%S"),
                    "is_cached": False,
                    "source": "yfinance"
                }

            print(f"[{symbol}] 所有來源與備援 yfinance 均未回傳資料。")
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
            # 判斷是否為指數 (IX0001 等)
            is_index = symbol.startswith("IX")
            path_type = "index" if is_index else "stock"
            
            url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/snapshot/{symbol}"
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 富果 API v1.0 使用 camelCase: closePrice, lastPrice, openPrice...
                price = data.get('lastPrice') or data.get('closePrice') or data.get('last_price') or data.get('close')
                
                print(f"🔍 [DEBUG] Fugle Snapshot ({symbol}): 獲取到價格={price} (API原始資料: {data})")
                
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

    def _get_yfinance_price(self, symbol):
        """
        使用 yfinance 獲取即時價格備援
        """
        try:
            # 轉換代碼: yfinance 需要 .TW (上市) 或 .TWO (上櫃)
            # 這裡先簡單嘗試 .TW，如果失敗可再擴充
            ticker_symbol = f"{symbol}.TW"
            if len(symbol) == 4 and symbol.startswith('6'): # 簡略判定上櫃
                ticker_symbol = f"{symbol}.TWO"
                
            ticker = yf.Ticker(ticker_symbol)
            # 取得即時報價資訊
            info = ticker.fast_info
            if hasattr(info, 'last_price') and info.last_price:
                return float(info.last_price)
            
            # 如果 fast_info 失敗，嘗試 history
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist.iloc[-1]['Close'])
            
            # 如果還是失敗，嘗試不帶後綴 (如果是加權指數等)
            if symbol == 'TAIEX':
                ticker = yf.Ticker("^TWII")
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    return float(hist.iloc[-1]['Close'])
                    
            return None
        except Exception as e:
            print(f"[{symbol}] yfinance 獲取失敗: {e}")
            return None

    def _get_fugle_historical(self, symbol, start_date, end_date):
        """
        使用富果 Fugle API 獲取歷史 K 線資料，並轉換為 DataFrame 格式
        """
        if not self.fugle_token:
            return None
        
        try:
            # 判斷是否為指數 (IX0001 等)
            is_index = symbol.startswith("IX")
            path_type = "index" if is_index else "stock"
            
            url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/historical/candles/{symbol}"
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
            source_tag = "Unknown"
            if self.fugle_token:
                fugle_symbol = symbol
                if symbol == "^TWII" or symbol == "TAIEX":
                    fugle_symbol = "IX0001"
                df = self._get_fugle_historical(fugle_symbol, start_date_str, end_date_str)
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
            now = self._get_taipei_now()
            # 獲取約 60 天的資料以確保計算出 MA20
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=65)).strftime("%Y-%m-%d")
            
            # 1. 優先嘗試富果
            df = None
            if self.fugle_token:
                fugle_symbol = symbol
                if symbol == "^TWII" or symbol == "TAIEX":
                    fugle_symbol = "IX0001"
                df = self._get_fugle_historical(fugle_symbol, start_date_str, end_date_str)
            
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

                # --- [強制更新今日即時數據] ---
                today_str = now.strftime("%Y-%m-%d")
                
                # 如果現在是台北時間 09:00 後，嘗試補齊或更新今日數據
                if now.hour >= 9:
                    latest = self.get_last_price(symbol)
                    if latest:
                        history_last_date = str(df.iloc[-1].get('date', ''))
                        
                        if history_last_date != today_str:
                            # 情境 A: 歷史資料還沒今天的列，補一個新列
                            patch_row = df.iloc[-1].copy()
                            patch_row['date'] = today_str
                            patch_row['close'] = latest['price']
                            patch_row['open'] = latest['price']
                            patch_row['high'] = latest['price']
                            patch_row['low'] = latest['price']
                            patch_row['volume'] = 0
                            
                            new_row_df = pd.DataFrame([patch_row])
                            df = pd.concat([df, new_row_df], ignore_index=True)
                            print(f"[{symbol}] 歷史資料無今日紀錄，已補齊 {today_str} 快訊價: {latest['price']}")
                        else:
                            # 情境 B: 歷史資料已有今日列 (但可能是舊的或預開盤價)，強制蓋掉 close
                            # 這是修正「報告顯示 1820 但實時 1805」的關鍵
                            idx_last = df.index[-1]
                            old_close = df.at[idx_last, 'close']
                            df.at[idx_last, 'close'] = latest['price']
                            # 同步更新今日最高最低
                            df.at[idx_last, 'high'] = max(df.at[idx_last, 'high'], latest['price'])
                            df.at[idx_last, 'low'] = min(df.at[idx_last, 'low'], latest['price']) if df.at[idx_last, 'low'] > 0 else latest['price']
                            print(f"[{symbol}] 歷史紀錄已含今日，強制將收盤價從 {old_close} 更新為快訊價: {latest['price']}")

                # 計算 MA20 (在補齊/更新後計算)
                df['ma20'] = df['close'].rolling(window=20).mean()
                
                if len(df) <= offset:
                    print(f"[{symbol}] 資料不足以計算 offset={offset}。總列數: {len(df)}")
                    return None
                    
                # 取得指定 offset 的資料 (最後一筆是 -1, 前一筆是 -2)
                idx = -1 - offset
                last_row = df.iloc[idx]
                date_str = str(last_row.get('date', '未知日期'))
                
                # 處理漲跌幅 (始終與前一筆比較)
                change_pct = None
                if idx - 1 >= -len(df):
                    try:
                        prev_close = float(df.iloc[idx - 1]['close'])
                        current_close = float(last_row['close'])
                        if prev_close != 0:
                            change_pct = round(((current_close - prev_close) / prev_close) * 100, 2)
                    except:
                        pass
                
                # 處理最高/最低欄位
                high_val = last_row.get('max') if 'max' in cols else last_row.get('high', 0)
                low_val = last_row.get('min') if 'min' in cols else last_row.get('low', 0)
                
                return {
                    "date": date_str,
                    "open": float(last_row.get('open', 0)),
                    "close": float(last_row['close']),
                    "high": float(high_val),
                    "low": float(low_val),
                    "volume": int(last_row.get('trading_volume', 0)) if 'trading_volume' in last_row else int(last_row.get('volume', 0)),
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
        獲取特定代碼的移動平均線 (優先使用 Fugle)
        """
        try:
            from datetime import datetime, timedelta
            now = datetime.now()
            # 抓取足以計算 MA 的歷史長度 (安全起見抓 60 天)
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=60)).strftime("%Y-%m-%d")
            
            df = None
            # 1. 優先嘗試富果
            if self.fugle_token:
                # 處理指數轉換 (TAIEX -> IX0001)
                fugle_symbol = symbol
                if symbol == "^TWII" or symbol == "TAIEX":
                    fugle_symbol = "IX0001"
                
                df = self._get_fugle_historical(fugle_symbol, start_date_str, end_date_str)
            
            # 2. 備援使用 yfinance
            if df is None or df.empty:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="60d")
                if not df.empty:
                    df.columns = [c.lower() for c in df.columns]

            if df is None or df.empty or len(df) < window:
                return None, None
            
            # 計算 MA
            df['ma'] = df['close'].rolling(window=window).mean()
            
            last_price = df['close'].iloc[-1]
            last_ma = df['ma'].iloc[-1]
            
            return round(float(last_price), 2), round(float(last_ma), 2)
        except Exception as e:
            print(f"獲取 {symbol} MA 時發生錯誤: {e}")
            return None, None

    def get_market_order_stats(self):
        """
        獲取台股全市場每 5 秒委託成交統計 (買賣力道)
        若當日無資料，自動嘗試獲取最近一筆可用資料
        """
        try:
            from datetime import datetime, timedelta
            now = datetime.now()
            
            # 依序嘗試最近 5 天，直到抓到資料為止 (解決此資料集範圍抓取不穩的問題)
            df = None
            date_to_try = now
            for _ in range(5):
                try:
                    target_date = date_to_try.strftime("%Y-%m-%d")
                    df = self.loader.get_data(
                        dataset="TaiwanStockStatisticsOfOrderBookAndTrade",
                        start_date=target_date,
                        end_date=target_date
                    )
                    if df is not None and not df.empty:
                        break
                except:
                    pass
                date_to_try -= timedelta(days=1)
            
            if df is not None and not df.empty:
                # 統一欄位名稱為小寫
                df.columns = [c.lower() for c in df.columns]
                # 取得最後一筆 (最新可用資料)
                last_row = df.iloc[-1]
                return {
                    "time": last_row.get("time", "---"),
                    "date": last_row.get("date", "---"),
                    "total_buy_order": int(last_row.get("totalbuyorder", 0)),
                    "total_sell_order": int(last_row.get("totalsellorder", 0)),
                    "total_buy_volume": int(last_row.get("totalbuyvolume", 0)),
                    "total_sell_volume": int(last_row.get("totalsellvolume", 0)),
                    "total_deal_volume": int(last_row.get("totaldealvolume", 0)),
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
                    # 如果是台股加權且有富果 Token，優先嘗試富果
                    if (symbol == "^TWII" or name == "🇹🇼 台股加權") and self.fugle_token:
                        fugle_data = self._get_fugle_snapshot("IX0001")
                        if fugle_data:
                            # 獲取前一日收盤以計算漲跌 (Fugle snapshot v1.0 可能不含前收，需額外處理或用 yfinance 補齊)
                            # 簡化作法：從歷史資料抓昨天
                            prev_close = None
                            try:
                                # 抓最近兩天的數據
                                now_dt = self._get_taipei_now()
                                start_dt = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
                                end_dt = now_dt.strftime("%Y-%m-%d")
                                hist_df = self._get_fugle_historical("IX0001", start_dt, end_dt)
                                if hist_df is not None and len(hist_df) >= 2:
                                    # 如果最後一筆是今天，前一筆就是昨天
                                    if str(hist_df.iloc[-1].get('date')) == now_dt.strftime("%Y-%m-%d"):
                                        prev_close = float(hist_df.iloc[-2]['close'])
                                    else:
                                        prev_close = float(hist_df.iloc[-1]['close'])
                            except:
                                pass
                            
                            price = fugle_data['price']
                            if prev_close:
                                change_pct = ((price - prev_close) / prev_close) * 100
                            else:
                                change_pct = 0 # 無法取得前收則設為 0
                                
                            emoji = "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪"
                            data_list.append({
                                "name": name,
                                "price": price,
                                "change_pct": change_pct,
                                "emoji": emoji,
                                "source": "Fugle"
                            })
                            continue

                    # yfinance 備援來源
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

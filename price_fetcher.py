import os
import requests
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta

load_dotenv()

class PriceFetcher:
    def __init__(self):
        # 僅保留富果 API Token
        self.fugle_token = (os.getenv("FUGLE_API_TOKEN") or 
                            os.getenv("富果API KEY") or 
                            os.getenv("富果API_KEY") or "").strip()
        
        if not self.fugle_token:
            print("警告: 未設定 FUGLE_API_TOKEN，台股報價功能將受限")
            
        # 快取機制設定
        self.price_cache = {} # 格式: {symbol: {"price": float, "time": datetime, "source": str}}
        self.cache_duration = int(os.getenv("CACHE_DURATION_SECONDS", 300))

    def _get_taipei_now(self):
        """獲取台北時區的當前時間"""
        tz = timezone(timedelta(hours=8))
        return datetime.now(tz)

    def get_last_price(self, symbol, force=False):
        """
        獲取股票或權證的最新成交價 (優先富果)
        回傳: {"price": float, "time": str, "is_cached": bool, "source": str}
        """
        orig_symbol = str(symbol).upper()
        # 指數代碼對應
        is_tw_index = orig_symbol in ["^TWII", "TAIEX", "加權指數", "IX0001"]
        
        # 檢查快取
        now = self._get_taipei_now()
        if not force and symbol in self.price_cache:
            cache_data = self.price_cache[symbol]
            current_cache_limit = 30 if is_tw_index else self.cache_duration
            
            if now.replace(tzinfo=None) - cache_data['time'].replace(tzinfo=None) < timedelta(seconds=current_cache_limit):
                return {
                    "price": cache_data['price'],
                    "time": cache_data['time'].strftime("%H:%M:%S"),
                    "is_cached": True,
                    "source": cache_data.get('source', 'Cache')
                }

        # 1. 優先嘗試富果 Fugle (台股標的)
        if self.fugle_token:
            fugle_symbol = orig_symbol
            if is_tw_index:
                fugle_symbol = "IX0001"
            
            # 如果是台股代碼 (純數字 4-6 碼) 或已指定 IX 代碼
            if (orig_symbol.isdigit() and 4 <= len(orig_symbol) <= 6) or is_tw_index or "00" in orig_symbol:
                fugle_data = self._get_fugle_snapshot(fugle_symbol)
                if fugle_data:
                    self.price_cache[symbol] = {
                        "price": fugle_data['price'],
                        "time": now,
                        "source": "Fugle"
                    }
                    return fugle_data

        # 2. 第二備援/國際標的：yfinance
        yf_price = self._get_yfinance_price(orig_symbol)
        if yf_price:
            self.price_cache[symbol] = {
                "price": yf_price,
                "time": now,
                "source": "yfinance"
            }
            return {
                "price": yf_price,
                "time": now.strftime("%H:%M:%S"),
                "is_cached": False,
                "source": "yfinance"
            }

        print(f"[{symbol}] 報價獲取失敗。")
        return None

    def _get_fugle_snapshot(self, symbol):
        """獲取富果行情快照"""
        if not self.fugle_token: return None
        try:
            is_index = symbol.startswith("IX")
            path_type = "index" if is_index else "stock"
            url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/snapshot/{symbol}"
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # 優先順序：1. lastTrade (撮合) 2. indexValue (指數) 3. lastPrice 
                last_trade = data.get('lastTrade', {})
                price = last_trade.get('price') if isinstance(last_trade, dict) else None
                
                if not price:
                    price = data.get('indexValue') or data.get('lastPrice') or data.get('closePrice')
                
                if price:
                    return {
                        "price": float(price),
                        "time": self._get_taipei_now().strftime("%H:%M:%S"),
                        "is_cached": False,
                        "source": "Fugle"
                    }
            return None
        except Exception as e:
            print(f"[{symbol}] Fugle Snapshot Error: {e}")
            return None

    def _get_yfinance_price(self, symbol):
        """獲取 yfinance 價格"""
        try:
            yf_symbol = symbol
            if symbol in ["TAIEX", "^TWII", "IX0001"]:
                yf_symbol = "^TWII"
            elif 4 <= len(symbol) <= 6 and not any(c in symbol for c in ['^', '=', '-', '.']): 
                if symbol.startswith(('5', '6', '8')):
                    yf_symbol = f"{symbol}.TWO"
                else:
                    yf_symbol = f"{symbol}.TW"
            
            ticker = yf.Ticker(yf_symbol)
            try:
                info = ticker.fast_info
                if 'last_price' in info and info['last_price'] > 0:
                    return float(info['last_price'])
            except: pass
            
            hist = ticker.history(period="5d", interval="1m")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            
            return None
        except Exception as e:
            print(f"[{symbol}] yfinance Error: {e}")
            return None

    def _normalize_fugle_symbol(self, symbol):
        """標準化標的代碼以符合 Fugle API 要求"""
        s = symbol.upper().split('.')[0] # 移除 .TW 或 .TWO
        if s in ["TAIEX", "^TWII"]: return "IX0001"
        return s

    def _get_fugle_historical(self, symbol, start_date, end_date):
        """獲取富果歷史資料 (蠟燭線)"""
        if not self.fugle_token: return None
        try:
            fugle_sym = self._normalize_fugle_symbol(symbol)
            is_index = fugle_sym.startswith("IX")
            path_type = "index" if is_index else "stock"
            
            url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/historical/candles/{fugle_sym}"
            params = {"from": start_date, "to": end_date, "fields": "open,high,low,close,volume"}
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                candles = data.get('candles', [])
                if not candles: 
                    return None
                
                df = pd.DataFrame(candles)
                if 'volume' in df.columns:
                    df = df.rename(columns={'volume': 'trading_volume'})
                
                # 確保欄位全小寫
                df.columns = [c.lower() for c in df.columns]
                
                # 關鍵修正：確保依日期由舊到新排序 (Ascending)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                
                return df
            return None
        except Exception as e:
            print(f"[{symbol}] Fugle Historical Error: {e}")
            return None

    def get_five_day_stats(self, symbol):
        """獲取近五日歷史數據摘要"""
        try:
            now = self._get_taipei_now()
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=40)).strftime("%Y-%m-%d")
            
            df = self._get_fugle_historical(symbol, start_date_str, end_date_str)
            
            # 備援 yfinance
            if df is None or df.empty:
                yf_sym = symbol
                if symbol == "TAIEX" or symbol == "^TWII": yf_sym = "^TWII"
                elif '.' not in symbol and symbol.isdigit(): 
                    yf_sym = f"{symbol}.TWO" if symbol.startswith(('5','6','8')) else f"{symbol}.TW"
                
                ticker = yf.Ticker(yf_sym)
                df = ticker.history(period="40d")
                if not df.empty:
                    df = df.reset_index()
                    df.columns = [c.lower() for c in df.columns]
                    if 'date' in df.columns:
                        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                    if 'volume' in df.columns:
                        df = df.rename(columns={'volume': 'trading_volume'})
            
            if df is None or df.empty: return None
            
            # 計算 MA5, MA20
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
            
            # 取最後 5 筆
            latest_rows = df.tail(5).copy()
            stats_list = []
            for _, row in latest_rows.iterrows():
                stats_list.append({
                    "date": str(row['date']),
                    "open": float(row.get('open', 0)),
                    "close": float(row['close']),
                    "high": float(row.get('high', row.get('max', 0))),
                    "low": float(row.get('low', row.get('min', 0))),
                    "volume": int(row.get('trading_volume', 0)),
                    "ma5": round(float(row['ma5']), 2) if not pd.isna(row['ma5']) else None,
                    "ma20": round(float(row['ma20']), 2) if not pd.isna(row['ma20']) else None,
                    "fetch_time": now.strftime("%H:%M:%S")
                })
            return stats_list
        except Exception as e:
            print(f"[{symbol}] get_five_day_stats Error: {e}")
            return None

    def get_ticker_ma(self, symbol, window=20):
        """獲取特定代碼的移動平均線"""
        try:
            now = self._get_taipei_now()
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=window + 40)).strftime("%Y-%m-%d")
            
            df = self._get_fugle_historical(symbol, start_date_str, end_date_str)
            
            # 備援 yfinance
            if df is None or df.empty:
                yf_sym = symbol
                if symbol == "TAIEX" or symbol == "^TWII": yf_sym = "^TWII"
                elif '.' not in symbol and symbol.isdigit():
                    yf_sym = f"{symbol}.TWO" if symbol.startswith(('5','6','8')) else f"{symbol}.TW"
                
                ticker = yf.Ticker(yf_sym)
                df = ticker.history(period=f"{window+40}d")
                if not df.empty:
                    df = df.reset_index()
                    df.columns = [c.lower() for c in df.columns]
                    if 'date' in df.columns:
                        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

            if df is None or df.empty or len(df) < window:
                return None, None
            
            df['ma'] = df['close'].rolling(window=window).mean()
            return round(float(df['close'].iloc[-1]), 2), round(float(df['ma'].iloc[-1]), 2)
        except Exception as e:
            print(f"[{symbol}] get_ticker_ma Error: {e}")
            return None, None

    def get_full_stats(self, symbol, offset=0):
        """獲取完整統計資訊 (含 MA20)"""
        try:
            now = self._get_taipei_now()
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=70)).strftime("%Y-%m-%d")
            
            df = self._get_fugle_historical(symbol, start_date_str, end_date_str)
            
            # 備援 yfinance
            if df is None or df.empty:
                yf_sym = symbol
                if symbol in ["TAIEX", "^TWII"]: yf_sym = "^TWII"
                elif '.' not in symbol and symbol.isdigit():
                    yf_sym = f"{symbol}.TWO" if symbol.startswith(('5','6','8')) else f"{symbol}.TW"
                
                ticker = yf.Ticker(yf_sym)
                df = ticker.history(period="70d")
                if not df.empty:
                    df = df.reset_index()
                    df.columns = [c.lower() for c in df.columns]
                    if 'date' in df.columns:
                        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                    if 'volume' in df.columns:
                        df = df.rename(columns={'volume': 'trading_volume'})

            if df is None or df.empty:
                print(f"[{symbol}] 所有資料源均無法獲取歷史數據")
                return None
            
            # 若為今日 (offset=0) 且在盤中，嘗試合併即時價格
            if offset == 0 and 9 <= now.hour < 14:
                latest = self.get_last_price(symbol, force=True)
                if latest:
                    today_str = now.strftime("%Y-%m-%d")
                    if str(df.iloc[-1]['date']) != today_str:
                        new_row = df.iloc[-1].copy()
                        new_row['date'] = today_str
                        new_row['close'] = latest['price']
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    else:
                        df.at[df.index[-1], 'close'] = latest['price']

            df['ma20'] = df['close'].rolling(window=20).mean()
            
            target_idx = -1 - offset
            if abs(target_idx) > len(df):
                print(f"[{symbol}] 資料長度不足 (len={len(df)}, offset={offset})")
                return None
            
            row = df.iloc[target_idx]
            
            # 計算漲跌幅 (與前一交易日比較)
            prev_idx = target_idx - 1
            if abs(prev_idx) <= len(df):
                prev_close = float(df.iloc[prev_idx]['close'])
                change_pct = round(((float(row['close']) - prev_close) / prev_close * 100), 2) if prev_close else 0
            else:
                change_pct = 0
                
            return {
                "date": str(row['date']),
                "open": float(row.get('open', 0)),
                "close": float(row['close']),
                "high": float(row.get('high', row.get('max', 0))),
                "low": float(row.get('low', row.get('min', 0))),
                "volume": int(row.get('trading_volume', 0)),
                "ma20": round(float(row['ma20']), 2) if not pd.isna(row['ma20']) else None,
                "change_pct": change_pct
            }
        except Exception as e:
            print(f"[{symbol}] get_full_stats Error: {e}")
            return None

    def get_market_indices(self):
        """獲取各國市場指數"""
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
        
        results = []
        for name, symbol in tickers_map.items():
            p_data = self.get_last_price(symbol, force=True)
            if p_data:
                price = p_data['price']
                change_pct = 0
                try:
                    ticker = yf.Ticker(symbol if symbol != "^TWII" else "^TWII")
                    prev_c = ticker.fast_info.previous_close
                    if not prev_c:
                         hist = ticker.history(period="5d")
                         if len(hist) >= 2: prev_c = hist['Close'].iloc[-2]
                    if prev_c:
                        change_pct = (price - prev_c) / prev_c * 100
                except: pass
                
                results.append({
                    "name": name, "price": price, "change_pct": change_pct,
                    "emoji": "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪",
                    "source": p_data['source']
                })
        return results

    def get_market_order_stats(self):
        """獲取大盤買賣力道 (透過 Fugle Snapshot Market)"""
        if not self.fugle_token: return None
        try:
            # 獲取上市大盤統計 (TSE)
            url = "https://api.fugle.tw/marketdata/v1.0/stock/snapshot/market/TSE"
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 欄位解析: 
                # totalBuyOrder, totalSellOrder, totalBuyVolume, totalSellVolume, totalDealVolume
                return {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "total_buy_order": data.get("totalBuyOrder", 0),
                    "total_sell_order": data.get("totalSellOrder", 0),
                    "total_buy_volume": data.get("totalBuyVolume", 0),
                    "total_sell_volume": data.get("totalSellVolume", 0),
                    "total_deal_volume": data.get("totalDealVolume", 0),
                }
            return None
        except Exception as e:
            print(f"Fugle Market Stats Error: {e}")
            return None

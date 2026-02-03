import os
import requests
from FinMind.data import DataLoader
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta

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
        self.price_cache = {} # 格式: {symbol: {"price": float, "time": datetime, "source": str}}
        self.cache_duration = int(os.getenv("CACHE_DURATION_SECONDS", 300))

    def _get_taipei_now(self):
        """獲取台北時區的當前時間"""
        tz = timezone(timedelta(hours=8))
        return datetime.now(tz)

    def get_last_price(self, symbol, force=False):
        """
        獲取股票或權證的最新成交價 (支援快取與強制更新)
        回傳: {"price": float, "time": str, "is_cached": bool, "source": str}
        """
        # 標準化代碼
        orig_symbol = str(symbol).upper()
        # 指數代碼對應
        is_tw_index = orig_symbol in ["^TWII", "TAIEX", "加權指數", "IX0001"]
        
        # 檢查快取
        now = self._get_taipei_now()
        if not force and symbol in self.price_cache:
            cache_data = self.price_cache[symbol]
            # 指數類快取上限設為 30 秒；普通標的依照設定
            current_cache_limit = 30 if is_tw_index else self.cache_duration
            
            if now.replace(tzinfo=None) - cache_data['time'].replace(tzinfo=None) < timedelta(seconds=current_cache_limit):
                return {
                    "price": cache_data['price'],
                    "time": cache_data['time'].strftime("%H:%M:%S"),
                    "is_cached": True,
                    "source": cache_data.get('source', 'Cache')
                }

        # 1. 優先嘗試富果 Fugle (即時性最高)
        if self.fugle_token:
            fugle_symbol = orig_symbol
            if is_tw_index:
                fugle_symbol = "IX0001"
            
            fugle_data = self._get_fugle_snapshot(fugle_symbol)
            if fugle_data:
                self.price_cache[symbol] = {
                    "price": fugle_data['price'],
                    "time": now,
                    "source": "Fugle"
                }
                return fugle_data

        # 2. 第二備援：yfinance (國外指數或富果失敗時使用)
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

        # 3. 最後備援：FinMind (限台灣市場，獲取歷史最後一筆)
        try:
            if not is_tw_index: # FinMind Daily 通常不含大盤指數的即時點位
                end_date = now.strftime("%Y-%m-%d")
                start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                df = self.loader.taiwan_stock_daily(stock_id=orig_symbol, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    df.columns = [c.lower() for c in df.columns]
                    last_row = df.dropna(subset=['close']).iloc[-1]
                    price = float(last_row['close'])
                    self.price_cache[symbol] = {"price": price, "time": now, "source": "FinMind"}
                    return {
                        "price": price,
                        "time": now.strftime("%H:%M:%S"),
                        "is_cached": False,
                        "source": "FinMind"
                    }
        except:
            pass

        print(f"[{symbol}] 無法從所有來源獲取報價。")
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
        """獲取 yfinance 即時價格"""
        try:
            # 代碼轉換
            yf_symbol = symbol
            if symbol == "TAIEX" or symbol == "^TWII" or symbol == "IX0001":
                yf_symbol = "^TWII"
            elif len(symbol) == 4 or len(symbol) == 5: # 台股代碼
                if symbol.startswith('6') or symbol.startswith('8'): # 簡略判定上櫃
                    yf_symbol = f"{symbol}.TWO"
                else:
                    yf_symbol = f"{symbol}.TW"
            
            ticker = yf.Ticker(yf_symbol)
            # 使用 fast_info
            info = ticker.fast_info
            if 'last_price' in info and info['last_price']:
                return float(info['last_price'])
            
            # 備援: history
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            return None
        except Exception as e:
            print(f"[{symbol}] yfinance Error: {e}")
            return None

    def _get_fugle_historical(self, symbol, start_date, end_date):
        """獲取富果歷史資料"""
        if not self.fugle_token: return None
        try:
            is_index = symbol.startswith("IX")
            path_type = "index" if is_index else "stock"
            url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/historical/candles/{symbol}"
            params = {"from": start_date, "to": end_date, "fields": "open,high,low,close,volume"}
            headers = {"X-API-KEY": self.fugle_token}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                candles = data.get('candles', [])
                if not candles: return None
                df = pd.DataFrame(candles)
                df = df.rename(columns={'volume': 'trading_volume'})
                df.columns = [c.lower() for c in df.columns]
                return df.iloc[::-1].reset_index(drop=True)
            return None
        except Exception as e:
            print(f"[{symbol}] Fugle Historical Error: {e}")
            return None

    def get_full_stats(self, symbol, offset=0):
        """獲取完整統計資訊 (含 MA20)"""
        try:
            now = self._get_taipei_now()
            end_date_str = now.strftime("%Y-%m-%d")
            start_date_str = (now - timedelta(days=65)).strftime("%Y-%m-%d")
            
            # 使用 Fugle 或 FinMind 獲取歷史
            df = None
            fugle_sym = symbol
            if symbol == "TAIEX" or symbol == "^TWII": fugle_sym = "IX0001"
            
            if self.fugle_token:
                df = self._get_fugle_historical(fugle_sym, start_date_str, end_date_str)
            
            if df is None or df.empty:
                df = self.loader.taiwan_stock_daily(stock_id=symbol, start_date=start_date_str, end_date=end_date_str)
            
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                
                # --- 強制同步今日即時價 ---
                if offset == 0 and now.hour >= 9:
                    latest = self.get_last_price(symbol, force=True)
                    if latest:
                        today_str = now.strftime("%Y-%m-%d")
                        if str(df.iloc[-1].get('date')) != today_str:
                            new_row = df.iloc[-1].copy()
                            new_row['date'] = today_str
                            new_row['close'] = latest['price']
                            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        else:
                            df.at[df.index[-1], 'close'] = latest['price']

                # 計算 MA20
                df['ma20'] = df['close'].rolling(window=20).mean()
                
                idx = -1 - offset
                if abs(idx) > len(df): return None
                
                row = df.iloc[idx]
                prev_close = float(df.iloc[idx-1]['close']) if abs(idx-1) <= len(df) else float(row['close'])
                change_pct = ((float(row['close']) - prev_close) / prev_close * 100) if prev_close else 0
                
                return {
                    "date": str(row.get('date')),
                    "open": float(row.get('open', 0)),
                    "close": float(row['close']),
                    "high": float(row.get('high', row.get('max', 0))),
                    "low": float(row.get('low', row.get('min', 0))),
                    "ma20": round(float(row.get('ma20', 0)), 2) if not pd.isna(row.get('ma20')) else None,
                    "change_pct": round(change_pct, 2)
                }
            return None
        except Exception as e:
            print(f"[{symbol}] get_full_stats Error: {e}")
            return None

    def get_market_indices(self):
        """獲取各國市場指數 (對齊 /check 邏輯)"""
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
        now = self._get_taipei_now()
        
        for name, symbol in tickers_map.items():
            # 強制刷新獲取最即時報價
            p_data = self.get_last_price(symbol, force=True)
            if p_data:
                price = p_data['price']
                change_pct = 0
                
                # 計算漲跌幅 (透過 yfinance 或 Fugle 歷史)
                try:
                    ticker = yf.Ticker(symbol if symbol != "^TWII" else "^TWII")
                    prev_c = ticker.fast_info.previous_close
                    if not prev_c:
                         hist = ticker.history(period="2d")
                         if len(hist) >= 2: prev_c = hist['Close'].iloc[-2]
                    if prev_c:
                        change_pct = (price - prev_c) / prev_c * 100
                except: pass
                
                results.append({
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    "emoji": "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪",
                    "source": p_data['source']
                })
            else:
                results.append({"name": name, "price": 0, "change_pct": 0, "emoji": "❌", "source": "Fail"})
        
        return results

    def get_market_order_stats(self):
        """獲取大盤買賣力道"""
        try:
            now = self._get_taipei_now()
            for i in range(5):
                d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                df = self.loader.get_data(dataset="TaiwanStockStatisticsOfOrderBookAndTrade", start_date=d, end_date=d)
                if df is not None and not df.empty:
                    df.columns = [c.lower() for c in df.columns]
                    row = df.iloc[-1]
                    return {
                        "time": row.get("time", "---"),
                        "date": row.get("date", "---"),
                        "total_buy_order": int(row.get("totalbuyorder", 0)),
                        "total_sell_order": int(row.get("totalsellorder", 0)),
                        "total_buy_volume": int(row.get("totalbuyvolume", 0)),
                        "total_sell_volume": int(row.get("totalsellvolume", 0)),
                    }
            return None
        except Exception as e:
            print(f"Market Order Stats Error: {e}")
            return None

    def get_api_usage(self):
        """FinMind API 使用量"""
        if not self.api_token: return None
        try:
            res = requests.get("https://api.web.finmindtrade.com/v2/user_info", params={"token": self.api_token})
            d = res.json()
            if d.get("msg") == "success":
                return {"user_count": d.get("user_count"), "api_request_limit": d.get("api_request_limit")}
            return None
        except: return None

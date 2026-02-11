import os
import requests
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta

load_dotenv()

class PriceFetcher:
    def __init__(self):
        # 強化 Token 抓取邏輯，支援 Railway 的各種命名方式 (如帶空格或下底線)
        self.fugle_token = (os.getenv("FUGLE_API_TOKEN") or 
                            os.getenv("富果API KEY") or 
                            os.getenv("富果API_KEY") or "").strip()
        
        # 備用方案: 遍歷所有環境變數尋找包含 "FUGLE" 或 "富果" 的值
        if not self.fugle_token:
            for key, value in os.environ.items():
                if "FUGLE" in key.upper() or "富果" in key:
                    self.fugle_token = value.strip()
                    print(f"DEBUG: 從環境變數 {key} 抓取到 Token")
                    break
        
        if not self.fugle_token:
            print("警告: 未設定 FUGLE_API_TOKEN，台股報價與大盤功能將受限")
        else:
            # 僅顯示前 4 碼與長度供除錯，不洩漏完整 Token
            print(f"✅ Fugle Token 已載入 (長度: {len(self.fugle_token)}, 前綴: {self.fugle_token[:4]}...)")
            
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
        if not symbol: return None
        orig_symbol = str(symbol).upper().strip()
        
        # 指數代碼對應
        is_tw_index = orig_symbol in ["^TWII", "TAIEX", "加權指數", "IX0001"]
        
        # 檢查快取
        now = self._get_taipei_now()
        if not force and orig_symbol in self.price_cache:
            cache_data = self.price_cache[orig_symbol]
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
            import re
            # 台股代碼規則: 4-6位數字 + 選用大寫字母 (如 2330, 00763U)
            is_taiwan = bool(re.search(r'^\d{4,7}[A-Z0-9]?$', orig_symbol))
            fugle_symbol = orig_symbol
            if is_tw_index:
                fugle_symbol = "IX0001"
            
            if is_taiwan or is_tw_index:
                fugle_data = self._get_fugle_snapshot(fugle_symbol)
                if fugle_data:
                    self.price_cache[orig_symbol] = {
                        "price": fugle_data['price'],
                        "time": now,
                        "source": "Fugle"
                    }
                    # 若為開發環境可開啟以下日誌
                    # print(f"  [Fugle] {orig_symbol}: {fugle_data['price']}")
                    return fugle_data

        # 2. 第二備援/國際標的：yfinance
        # 當看到 yfinance 的日誌時，代表上面的 Fugle 抓取失敗或不適用
        yf_price = self._get_yfinance_price(orig_symbol)
        if yf_price:
            self.price_cache[orig_symbol] = {
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

        print(f"[{orig_symbol}] 報價獲取失敗 (已嘗試 Fugle & yfinance)。")
        return None

    def _get_fugle_snapshot(self, symbol):
        """獲取富果行情快照 (修正 v1.0 解析邏輯)"""
        if not self.fugle_token: return None
        try:
            s = str(symbol).upper().split('.')[0]
            headers = {"X-API-KEY": self.fugle_token}
            
            # v1.0 官方路徑可能分布在 stock 或 index
            # 對於 00763U 這種期指 ETF，通常在 stock
            for path_type in ["stock", "index"]:
                url = f"https://api.fugle.tw/marketdata/v1.0/{path_type}/intraday/quote/{s}"
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    raw_data = response.json()
                    
                    # 部分 v1.0 接口會嵌套在 'data' 欄位
                    data = raw_data.get('data', raw_data)
                    
                    price = (data.get('lastPrice') or 
                             data.get('indexValue') or 
                             data.get('closePrice') or
                             data.get('openPrice'))
                    
                    if not price and 'lastTrade' in data:
                        price = data['lastTrade'].get('price')
                    
                    if price:
                        return {
                            "price": float(price),
                            "time": self._get_taipei_now().strftime("%H:%M:%S"),
                            "is_cached": False,
                            "source": "Fugle"
                        }
            return None
        except:
            return None

    def _get_yf_symbol(self, symbol):
        """將標的轉換為 yfinance 格式，包含市場後綴判定"""
        s_input = str(symbol).upper().strip()
        if s_input.endswith((".TW", ".TWO", ".HK", ".US")):
            return s_input
            
        s = s_input.split('.')[0]
        if s in ["TAIEX", "^TWII", "IX0001"]: return "^TWII"
        
        # 判斷台股/ETF 代碼 (2330, 0050, 00763U等)
        import re
        # 更加寬鬆的判定：4-8位由數字與字母組成的代碼
        if re.match(r'^[0-9A-Z]{4,8}$', s) and s[0].isdigit():
            # 5, 8 開頭的 4 碼通常是上櫃
            if len(s) == 4 and s.startswith(('5', '8')):
                return f"{s}.TWO"
            return f"{s}.TW"
        return s

    def _get_yfinance_price(self, symbol):
        """獲獲 yfinance 即時價格 (含自動市場切換與備援)"""
        try:
            yf_sym = self._get_yf_symbol(symbol)
            
            def fetch(sym):
                ticker = yf.Ticker(sym)
                try:
                    info = ticker.fast_info
                    # 盡可能嘗試各種屬性抓取價格
                    price = getattr(info, 'last_price', None) or getattr(info, 'lastPrice', None)
                    if price is None:
                        try: price = info['last_price']
                        except: pass
                    
                    if price and price > 0:
                        return float(price)
                except: pass
                
                # 備援：抓取歷史數據（市場關閉時較穩定）
                h = self._safe_history(ticker, period="2d")
                if not h.empty:
                    return float(h['Close'].iloc[-1])
                return None

            price = fetch(yf_sym)
            
            # 如果失敗且帶有 .T 後綴，嘗試切換市場
            if price is None and (".T" in yf_sym):
                retry_sym = yf_sym.replace(".TW", ".TMP").replace(".TWO", ".TW").replace(".TMP", ".TWO")
                price = fetch(retry_sym)
            
            # 如果還是失敗，最後嘗試不帶後綴的原代碼 (針對某些特殊標的)
            if price is None:
                price = fetch(symbol.split('.')[0])
                
            return price
        except:
            return None

    def get_stock_name(self, symbol):
        """
        獲取標的名稱 (透過 yfinance)
        """
        try:
            yf_sym = self._get_yf_symbol(symbol)
            ticker = yf.Ticker(yf_sym)
            # 優先獲取 shortName 或 longName
            name = ticker.info.get('shortName') or ticker.info.get('longName') or symbol
            return name
        except:
            return symbol

    def _normalize_fugle_symbol(self, symbol):
        """標準化標的代碼以符合 Fugle API 要求"""
        s = str(symbol).upper().split('.')[0]
        if s in ["TAIEX", "^TWII"]: return "IX0001"
        return s

    def _safe_history(self, ticker, **kwargs):
        """安靜地獲取歷史資料，防止 stderr 輸出雜訊"""
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                return ticker.history(**kwargs)
            except:
                return pd.DataFrame()

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
                if not candles: return None
                
                df = pd.DataFrame(candles)
                # 統一使用 volume 欄位
                df.columns = [c.lower() for c in df.columns]
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                return df
            return None
        except:
            return None

    def get_five_day_stats(self, symbol):
        """獲取近五日歷史數據摘要"""
        try:
            now = self._get_taipei_now()
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=50)).strftime("%Y-%m-%d")
            
            df = self._get_fugle_historical(symbol, start_date, end_date)
            
            # yfinance 備援
            if df is None or df.empty:
                yf_sym = self._get_yf_symbol(symbol)
                ticker = yf.Ticker(yf_sym)
                df = self._safe_history(ticker, period="50d")
                
                if df.empty and ".T" in yf_sym:
                    retry_sym = yf_sym.replace(".TW", ".TMP").replace(".TWO", ".TW").replace(".TMP", ".TWO")
                    df = yf.Ticker(retry_sym).history(period="50d")
                
                if not df.empty:
                    df = df.reset_index()
                    df.columns = [c.lower() for c in df.columns]
                    if 'date' in df.columns: df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            if df is None or df.empty: return None
            
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
            return df.tail(5).to_dict('records')
        except:
            return None

    def get_ticker_ma(self, symbol, window=20):
        """獲取移動平均線"""
        try:
            stats = self.get_full_stats(symbol, offset=0)
            if stats: return stats['close'], stats['ma20']
            return None, None
        except: return None, None

    def get_full_stats(self, symbol, offset=0):
        """獲取完整統計資訊 (含多源備援與市場修正)"""
        try:
            now = self._get_taipei_now()
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=80)).strftime("%Y-%m-%d")
            
            df = self._get_fugle_historical(symbol, start_date, end_date)
            
            # yfinance 備援
            if df is None or df.empty:
                yf_sym = self._get_yf_symbol(symbol)
                ticker = yf.Ticker(yf_sym)
                df = self._safe_history(ticker, period="80d")
                
                if df.empty and ".T" in yf_sym:
                    retry_sym = yf_sym.replace(".TW", ".TMP").replace(".TWO", ".TW").replace(".TMP", ".TWO")
                    df = yf.Ticker(retry_sym).history(period="80d")
                
                if not df.empty:
                    df = df.reset_index()
                    df.columns = [c.lower() for c in df.columns]
                    if 'date' in df.columns: df['date'] = df['date'].dt.strftime('%Y-%m-%d')

            if df is None or df.empty:
                print(f"[{symbol}] 無法獲取歷史數據 (Fugle & Yahoo 皆失敗)")
                return None

            # 今日盤中數據合併
            if offset == 0 and 9 <= now.hour < 14:
                latest = self.get_last_price(symbol, force=True)
                if latest:
                    today_str = now.strftime("%Y-%m-%d")
                    if str(df.iloc[-1]['date']) != today_str:
                        new_row = df.iloc[-1].copy()
                        new_row['date'], new_row['close'] = today_str, latest['price']
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    else:
                        df.at[df.index[-1], 'close'] = latest['price']

            df['ma20'] = df['close'].rolling(window=20).mean()
            idx = -1 - offset
            if abs(idx) > len(df): return None
            
            row = df.iloc[idx]
            prev_close = float(df.iloc[idx-1]['close']) if abs(idx-1) <= len(df) else float(row['close'])
            change_pct = round(((float(row['close']) - prev_close) / prev_close * 100), 2) if prev_close else 0
                
            return {
                "date": str(row['date']),
                "open": float(row.get('open', 0)),
                "close": float(row['close']),
                "high": float(row.get('high', row.get('max', 0))),
                "low": float(row.get('low', row.get('min', 0))),
                "volume": int(row.get('volume', 0)),
                "ma20": round(float(row['ma20']), 2) if not pd.isna(row['ma20']) else None,
                "change_pct": change_pct
            }
        except Exception as e:
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
        """
        獲取大盤買賣力道 (優先從證交所官網抓取，最準確且不需 Token)
        """
        try:
            # 1. 嘗試證交所 MI_5MINS (每5秒委託成交統計)
            twse_url = "https://www.twse.com.tw/zh/exchangeReport/MI_5MINS?response=json"
            resp = requests.get(twse_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and len(data["data"]) > 0:
                    # 最後一筆紀錄通常是最新數據
                    last_row = data["data"][-1]
                    # 欄位順序: ["時間", "累積委託買進筆數", "累積委託買進數量", "累積委託賣出筆數", "累積委託賣出數量", "累積成交筆數", "累積成交數量", "累積成交金額"]
                    return {
                        "time": last_row[0],
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "total_buy_order": int(last_row[1].replace(",", "")),
                        "total_buy_volume": int(last_row[2].replace(",", "")),
                        "total_sell_volume": int(last_row[4].replace(",", "")),
                        "total_deal_volume": int(last_row[6].replace(",", ""))
                    }

            # 2. 如果證交所失敗，則嘗試 Fugle (作為備援)
            if self.fugle_token:
                # 清理 Token 空格 (避免 Railway 變數帶入空格)
                clean_token = self.fugle_token.replace(" ", "").strip()
                url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/market/TSE"
                params = {"apiToken": clean_token}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    raw_data = response.json()
                    data = raw_data.get("data", {})
                    return {
                        "time": raw_data.get("time", datetime.now().strftime("%H:%M:%S")),
                        "date": raw_data.get("date", datetime.now().strftime("%Y-%m-%d")),
                        "total_buy_order": data.get("buyCount", 0),
                        "total_buy_volume": data.get("buyVolume", 0),
                        "total_sell_volume": data.get("sellVolume", 0),
                        "total_deal_volume": data.get("tradeVolume", 0),
                    }
            return None
        except Exception as e:
            print(f"Market Stats Error (TWSE/Fugle): {e}")
            return None

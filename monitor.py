import os
import time
import asyncio
import json
from datetime import datetime, time as dt_time, timezone, timedelta
from dotenv import load_dotenv

from price_fetcher import PriceFetcher
from notion_helper import NotionHelper
from notifier import Notifier
from report_generator import ReportGenerator

load_dotenv()

class MarketMonitor:
    def __init__(self):
        self.fetcher = PriceFetcher()
        self.notion = NotionHelper()
        self.notifier = Notifier()
        self.generator = ReportGenerator()
        
        # 預設設定 (優先讀取環境變數)
        self.interval = int(os.getenv("CHECK_INTERVAL_SECONDS", 600))
        self.allow_outside = os.getenv("ALLOW_OUTSIDE_MARKET_HOURS", "false").lower() == "true"
        self.config_file = "config.json"
        
        # 載入持久化設定 (覆蓋預設值)
        self.load_config()
        
        self.last_open_date = None
        self.last_close_date = None
        self.last_noon_date = None
        self.last_daily_report_date = None
        self.last_order_stats_date = None
        self.last_check_time = 0
        self.taipei_tz = timezone(timedelta(hours=8))

    def _get_now_taipei(self):
        """獲取目前的台北時間"""
        return datetime.now(self.taipei_tz)

    def is_market_open(self):
        """
        判斷台股是否在交易時段 (週一至週五 09:00 - 13:35)
        日期判定優先於 allow_outside 檢查
        """
        now = self._get_now_taipei()
        # 週六 (5) 與週日 (6) 絕對不開
        if now.weekday() > 4:
            return False
            
        if self.allow_outside:
            return True
            
        market_start = dt_time(9, 0)
        market_end = dt_time(13, 35)
        current_time = now.time()
        
        return market_start <= current_time <= market_end

    def is_us_market_open(self):
        """
        判斷美股是否在交易時段 (台北時間 22:30 - 05:00)
        日期判定優先於 allow_outside 檢查
        """
        now = self._get_now_taipei()
        weekday = now.weekday() # 0=Mon, 5=Sat, 6=Sun
        current_time = now.time()

        # 週日全天與週一開盤前 (22:30 前) 不進行監控
        if weekday == 6:
            return False
        if weekday == 0 and current_time < dt_time(22, 30):
            return False
        # 週六僅在清晨 05:00 前 (美股週五盤) 允許
        if weekday == 5 and current_time > dt_time(5, 0):
            return False

        if self.allow_outside:
            return True
            
        # 週一至週五晚上 22:30 - 23:59
        if 0 <= weekday <= 4 and current_time >= dt_time(22, 30):
            return True
        # 週二至週六凌晨 00:00 - 05:00
        if 1 <= weekday <= 5 and current_time <= dt_time(5, 0):
            return True
            
        return False

    async def check_once(self):
        print(f"[{datetime.now()}] 開始執行價格檢查...")
        
        items = self.notion.get_monitoring_list()
        if not items:
            print("目前沒有要監控的標的。")
            return 0, 0

        success_count = 0
        fail_count = 0
        
        for item in items:
            symbol = item['symbol']
            # 辨識市場 (排除 TAIEX)
            is_us = symbol.isalpha() and "." not in symbol and symbol.upper() != "TAIEX"
            
            # 如果不是交易時段且沒開啟強制檢查，跳過該市場標的
            if not self.allow_outside:
                if is_us:
                    if not self.is_us_market_open():
                        continue
                else:
                    # 台股標的 (含 TAIEX) 僅在台股開盤時檢查
                    if not self.is_market_open():
                        continue

            price_data = self.fetcher.get_last_price(symbol)
            
            if price_data is None:
                fail_count += 1
                continue
            
            price = price_data['price']
            fetch_time = price_data['time']
            is_cached = price_data.get('is_cached', False)
                
            success_count += 1
            cache_tag = " (快取)" if is_cached else ""
            print(f"處理 {item['name']} ({symbol}): 當前價格 {price} {cache_tag}")
            
            status = "正常"
            alert_msg = ""
            
            # 檢查警戒值
            is_triggered = False
            time_info = f"\n(資料時間: {fetch_time}{' 快取' if is_cached else ''})"
            if item['high_alert'] and price >= item['high_alert']:
                is_triggered = True
                status = "警戒"
                alert_msg = f"🔔 持續警報：[{item['name']} ({symbol})] 當前價格 {price} >= 上限 {item['high_alert']}{time_info}\n(回覆 /stop {symbol} 停止警報)"
            elif item['low_alert'] and price <= item['low_alert']:
                is_triggered = True
                status = "警戒"
                alert_msg = f"🔔 持續警報：[{item['name']} ({symbol})] 當前價格 {price} <= 下限 {item['low_alert']}{time_info}\n(回覆 /stop {symbol} 停止警報)"
            
            # 處理持續警報邏輯
            if is_triggered:
                # 只有當使用者還沒說 /stop 時才發送
                if not self.notifier.is_stopped(symbol):
                    await self.notifier.send_message(alert_msg)
                else:
                    print(f"{symbol} 處於警報範圍但已被使用者暫停。")
            else:
                # 如果價格回到正常範圍，自動從停止清單移除，以便下次觸發時能再次通知
                if self.notifier.is_stopped(symbol):
                    self.notifier.stopped_symbols.remove(symbol.upper())
                    print(f"{symbol} 價格已回歸正常，重設警報狀態。")
            
            # 更新 Notion
            self.notion.update_price_and_status(item['page_id'], price, status)
            
        print(f"檢查任務完成。成功: {success_count}, 失敗: {fail_count}")
        return success_count, fail_count

    async def get_summary_callback(self, offset=0):
        """回傳目前所有監控標的的摘要文字"""
        if offset > 0:
            return await self.get_detailed_summary(offset=offset)
            
        items = self.notion.get_monitoring_list()
        if not items:
            return ""
            
        lines = []
        for item in items:
            symbol = item['symbol']
            price = item.get('current_price', '---')
            status = item.get('status', '正常')
            update_time = item.get('last_updated', '---')
            
            # 格式化輸出
            line = f"• **{item['name']}** ({symbol})\n"
            line += f"  價: `{price}` | 限: `{item['low_alert']} ~ {item['high_alert']}`\n"
            line += f"  狀態: {status}{' (已暫停)' if self.notifier.is_stopped(symbol) else ''}\n"
            line += f"  (更新時間: {update_time})"
            lines.append(line)
            
        return "\n\n".join(lines)

    async def change_alert_callback(self, symbol, high=None, low=None):
        """處理來自 Telegram 的警戒值修改請求"""
        # 重新獲取清單以尋找 page_id
        items = self.notion.get_monitoring_list()
        target = next((i for i in items if i['symbol'].upper() == symbol.upper()), None)
        
        if target:
            self.notion.update_alert_prices(target['page_id'], high_alert=high, low_alert=low)
            return True
        return False

    async def get_report_data(self, offset=0):
        """獲取用於報告的結構化數據"""
        items = self.notion.get_monitoring_list()
        stock_list = []
        date_str = "---"
        
        for item in items:
            symbol = item['symbol']
            stats = self.fetcher.get_full_stats(symbol, offset=offset)
            if stats:
                if date_str == "---":
                    date_str = stats['date']
                
                ma_status = "---"
                if stats['close'] and stats['ma20']:
                    ma_status = "📈 站上 MA20" if stats['close'] >= stats['ma20'] else "📉 跌破 MA20"
                
                stock_list.append({
                    "name": item['name'],
                    "symbol": symbol,
                    "close": stats['close'],
                    "change_pct": stats['change_pct'],
                    "ma20_status": ma_status,
                    "open": stats['open'],
                    "high": stats['high'],
                    "low": stats['low'],
                    "volume": stats['volume']
                })
        
        # 獲取市場買賣力道
        sentiment_data = None
        m_stats = self.fetcher.get_market_order_stats()
        if m_stats:
            diff_vol = m_stats['total_buy_volume'] - m_stats['total_sell_volume']
            sentiment = "🐂 偏多" if diff_vol > 0 else "Bearish" # Placeholder logic, will refine in monitor
            overheat_index = (m_stats['total_deal_volume'] / m_stats['total_buy_volume']) * 100 if m_stats['total_buy_volume'] > 0 else 0
            sentiment_data = {
                "date": m_stats['date'],
                "time": m_stats['time'],
                "sentiment": "🐂 偏多" if diff_vol > 0 else "🐻 偏空",
                "diff_vol": diff_vol,
                "overheat_index": overheat_index
            }

        return {
            "date": date_str,
            "stock_list": stock_list,
            "sentiment": sentiment_data
        }

    async def get_detailed_summary(self, offset=0):
        """回傳目前所有監控標的的詳細摘要 (開、收、高、低、MA20)"""
        data = await self.get_report_data(offset=offset)
        if not data['stock_list']:
            return "目前監控清單為空或無法獲取資料。"
            
        lines = [f"📅 基準日期: `{data['date']}`\n"]
        for s in data['stock_list']:
            change_str = "---"
            if s['change_pct'] is not None:
                emoji = "🔴" if s['change_pct'] > 0 else "🟢" if s['change_pct'] < 0 else "⚪"
                change_str = f"{emoji} {s['change_pct']}%"
                
            line = (
                f"• **{s['name']}** ({s['symbol']})\n"
                f"  收: `{s['close']}` ({change_str})\n"
                f"  開: `{s['open']}` / 高: `{s['high']}` / 低: `{s['low']}`\n"
                f"  量: `{s['volume']:,}` / MA20: `{s['ma20_status']}`"
            )
            lines.append(line)
            
        return "\n".join(lines)

    def load_config(self):
        """從檔案載入設定"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.interval = config.get("interval", self.interval)
                    self.allow_outside = config.get("allow_outside", self.allow_outside)
                print(f"✅ 已載入設定: 間隔={self.interval}s, 時段外={self.allow_outside}")
            except Exception as e:
                print(f"❌ 載入設定失敗: {e}")

    def save_config(self):
        """將設定儲存至檔案"""
        try:
            config = {
                "interval": self.interval,
                "allow_outside": self.allow_outside
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            print(f"💾 設定已儲存至 {self.config_file}")
        except Exception as e:
            print(f"❌ 儲存設定失敗: {e}")

    async def change_config_callback(self, interval=None, allow_outside=None):
        """處理來自 Telegram 的系統配置修改請求"""
        changed = False
        if interval is not None:
            self.interval = interval
            print(f"系統檢查間隔已更變為: {self.interval} 秒")
            changed = True
        
        if allow_outside is not None:
            self.allow_outside = allow_outside
            print(f"交易時段外處理已變更為: {self.allow_outside}")
            changed = True
            
        if changed:
            self.save_config()

    async def get_market_callback(self):
        """回傳市場指數資料"""
        return self.fetcher.get_market_indices()

    async def get_api_usage_callback(self):
        """回傳 API 使用量資訊"""
        return self.fetcher.get_api_usage()

    async def get_stock_history_callback(self, symbol):
        """回傳特定股票的五日歷史數據摘要"""
        stats_list = self.fetcher.get_five_day_stats(symbol)
        if not stats_list:
            return None
            
        lines = [f"📈 **{symbol} 歷史成交數據 (近 5 日)**\n"]
        for s in stats_list:
            fetch_info = f" (擷取於 {s['fetch_time']})" if 'fetch_time' in s else ""
            line = (
                f"📅 `{s['date']}`{fetch_info}\n"
                f"  開: `{s['open']}` | 收: `{s['close']}`\n"
                f"  高: `{s['high']}` | 低: `{s['low']}`\n"
                f"  量: `{s['volume']:,}`\n"
                f"  MA5: `{s['ma5'] or '---'}` | MA20: `{s['ma20'] or '---'}`\n"
            )
            lines.append(line)
        return "\n".join(lines)

    async def get_graphical_report_callback(self, offset=0):
        """用於回傳圖形化報告的路徑與說明文字"""
        report_data = await self.get_report_data(offset=offset)
        if not report_data['stock_list']:
            return None, "目前監控清單為空或資料失效。"
            
        try:
            img_path = self.generator.generate_closing_report(report_data['sentiment'], report_data['stock_list'])
            caption = f"數據日期: `{report_data['date']}`"
            return img_path, caption
        except Exception as e:
            print(f"回調產生圖片報告失敗: {e}")
            return None, f"圖片生成失敗: {e}"

    async def get_stock_chart_callback(self, symbol):
        """用於回傳特定股票 K 線圖路徑"""
        stats_list = self.fetcher.get_five_day_stats(symbol)
        if not stats_list:
            return None
            
        try:
            img_path = self.generator.generate_stock_history_chart(symbol, stats_list)
            return img_path
        except Exception as e:
            print(f"回調產生 K 線圖失敗: {e}")
            return None

    async def get_monitoring_limits_callback(self):
        """獲取目前監控清單與警戒上下限摘要"""
        items = self.notion.get_monitoring_list()
        if not items:
            return None
            
        lines = ["📋 **目前追蹤標的與警報設定**\n"]
        for item in items:
            high = f"`{item['high_alert']}`" if item['high_alert'] is not None else "`未設定`"
            low = f"`{item['low_alert']}`" if item['low_alert'] is not None else "`未設定`"
            lines.append(f"• **{item['name']}** ({item['symbol']})\n  上限: {high} / 下限: {low}")
            
        return "\n".join(lines)

    async def test_report_callback(self, report_type):
        """用於測試發送各種自動化報告"""
        today = self._get_now_taipei().date()
        if report_type == "noon":
            price, ma20 = self.fetcher.get_ticker_ma("^TWII", window=20)
            if price and ma20:
                status = "📈 站上 MA20" if price >= ma20 else "📉 跌破 MA20"
                message = (
                    f"🕛 **[測試] 午間台股加權指數報告**\n\n"
                    f"• 目前指數: `{price:,.2f}`\n"
                    f"• 指數 MA20 : `{ma20:,.2f}`\n"
                    f"• 當前狀態: **{status}**\n\n"
                    f"系統持續監控中..."
                )
                await self.notifier.send_message(message)
                return True
        elif report_type == "sentiment":
            stats = self.fetcher.get_market_order_stats()
            if stats:
                diff_vol = stats['total_buy_volume'] - stats['total_sell_volume']
                sentiment = "🐂 偏多" if diff_vol > 0 else "🐻 偏空"
                overheat_index = (stats['total_deal_volume'] / stats['total_buy_volume']) * 100 if stats['total_buy_volume'] > 0 else 0
                message = (
                    f"📊 **[測試] 台股全市場委託成交統計**\n\n"
                    f"• 數據日期: `{stats['date']}`\n"
                    f"• 總委買筆數: `{stats['total_buy_order']:,}`\n"
                    f"• 總委賣筆數: `{stats['total_sell_order']:,}`\n"
                    f"• 總成交量: `{stats['total_deal_volume']:,}`\n"
                    f"• 買賣量差: `{diff_vol:+,}`\n"
                    f"• **過熱指數**: `{overheat_index:.2f}%` (成交/委買)\n"
                    f"• 市場氣氛: **{sentiment}**\n\n"
                    f"(統計時間: {stats['time']})"
                )
                await self.notifier.send_message(message)
                return True
        if report_type == "daily":
            report_data = await self.get_report_data(offset=0)
            try:
                img_path = self.generator.generate_closing_report(report_data['sentiment'], report_data['stock_list'])
                await self.notifier.send_photo(img_path, caption=f"🔔 **[測試] 監控標的盤後綜合報告**")
                return True
            except Exception as e:
                print(f"圖片生成失敗: {e}")
                summary = await self.get_detailed_summary()
                message = f"🔔 **[測試] 監控標的盤後報告**\n\n{summary}"
                await self.notifier.send_message(message)
                return True
        return False

                    
    async def send_noon_report(self):
        """執行午間報告"""
        price, ma20 = self.fetcher.get_ticker_ma("^TWII", window=20)
        if price and ma20:
            status = "📈 站上 MA20" if price >= ma20 else "📉 跌破 MA20"
            message = (
                f"🕛 **午間台股加權指數報告**\n\n"
                f"• 目前指數: `{price:,.2f}`\n"
                f"• 指數 MA20 : `{ma20:,.2f}`\n"
                f"• 當前狀態: **{status}**\n\n"
                f"系統持續監控中..."
            )
            await self.notifier.send_message(message)
            return True
        return False

    async def send_daily_report(self):
        """執行盤後綜合大報告"""
        report_data = await self.get_report_data(offset=0)
        now = self._get_now_taipei()
        today_str = now.strftime("%Y-%m-%d")
        
        # 檢查數據日期是否為今日
        if report_data['date'] != today_str:
            print(f"[{now}] 數據日期 ({report_data['date']}) 與今日 ({today_str}) 不符，判定為休市，跳過盤後報告。")
            return False

        try:
            # 嘗試生成圖片報告
            img_path = self.generator.generate_closing_report(report_data['sentiment'], report_data['stock_list'])
            caption = f"🏁 **台股每日盤後綜合報告 (15:00)**\n\n數據日期: `{report_data['date']}`"
            await self.notifier.send_photo(img_path, caption=caption)
        except Exception as e:
            print(f"圖片報告生成失敗，改發送文字: {e}")
            # 備援發送文字報告
            sentiment_msg = ""
            if report_data['sentiment']:
                s = report_data['sentiment']
                sentiment_msg = f"📊 **市場氣氛: {s['sentiment']}** | 量差: `{s['diff_vol']:+,}` | 過熱: `{s['overheat_index']:.2f}%` \n\n"
            
            summary = await self.get_detailed_summary(offset=0)
            message = f"🏁 **台股每日盤後綜合報告 (15:00)**\n\n{sentiment_msg}📋 **監控標的摘要**\n{summary}"
            await self.notifier.send_message(message)
        return True

    async def send_us_closing_report(self):
        """發送美股收盤報告 (NASDAQ, S&P 500, Dow)"""
        now = self._get_now_taipei()
        # 使用台北時間週二至週六清晨作為美股前一晚的收盤判定
        date_key = now.strftime("%Y-%m-%d")
        
        indices = {
            "NASDAQ": "^IXIC",
            "S&P 500": "^GSPC",
            "道瓊工業": "^DJI"
        }
        
        lines = [f"🇺🇸 **美股收盤行情總結** ({date_key})\n"]
        success = False
        
        for name, symbol in indices.items():
            data = self.fetcher.get_last_price(symbol)
            if data:
                price = data['price']
                change_pct = data.get('change_pct', 0)
                emoji = "🔴" if change_pct > 0 else "🟢" if change_pct < 0 else "⚪"
                lines.append(f"• {name}: `{price:,.2f}` ({emoji} {change_pct:+.2f}%)")
                success = True
            else:
                lines.append(f"• {name}: `---` (獲取失敗)")
        
        if success:
            await self.notifier.send_message("\n".join(lines))
            print("美股收盤報告已發送。")
        else:
            print("無法獲取任何美股指數，不發送報告。")

    async def run_monitor_loop(self):
        """背景執行的監控迴圈 (用於 Bot 模式)"""
        print(f"監控迴圈啟動 (主檢查間隔: {self.interval} 秒，時區: 台北 UTC+8)")
        while True:
            try:
                now = self._get_now_taipei()
                today = now.date()
                curr_time = now.time()
                is_weekday = now.weekday() <= 4

                # 1. 檢查各項定時報告
                if is_weekday:
                    # 09:00 開盤提醒
                    if dt_time(9, 0) <= curr_time < dt_time(9, 15):
                        if self.last_open_date != today:
                            prev_summary = await self.get_detailed_summary(offset=1)
                            message = f"☀️ **台股今日開盤**！\n\n📊 **前一交易日收盤報告**\n{prev_summary}\n\n系統已開始監控..."
                            await self.notifier.send_message(message)
                            self.last_open_date = today
                    
                    # 12:00 中午報告
                    if dt_time(12, 0) <= curr_time < dt_time(12, 15):
                        if self.last_noon_date != today:
                            if await self.send_noon_report():
                                self.last_noon_date = today

                    # 15:00 盤後綜合大報告
                    if dt_time(15, 0) <= curr_time < dt_time(15, 20):
                        if self.last_daily_report_date != today:
                            if await self.send_daily_report():
                                self.last_daily_report_date = today
                            # 無論是否發送成功，都視為已處理完畢今日任務
                            self.last_daily_report_date = today

                # 2. 處理常規價格檢查
                import time as py_time
                current_unix = py_time.time()
                
                # 只要台股或美股其中一個有開，就進入檢查
                if self.is_market_open() or self.is_us_market_open():
                    if current_unix - self.last_check_time >= self.interval:
                        market_status = []
                        if self.is_market_open(): market_status.append("台股(開)")
                        if self.is_us_market_open(): market_status.append("美股(開)")
                        
                        print(f"[{now}] 執行自動價格檢查 ({', '.join(market_status)}, 間隔: {self.interval}s)...")
                        success, fail = await self.check_once()
                        self.last_check_time = current_unix
                        if success > 0 or fail > 0:
                            await self.notifier.send_message(f"✅ 定期價格檢查完成。成功: {success}, 失敗: {fail}")
                else:
                    if current_unix - self.last_check_time >= self.interval:
                        print(f"[{now}] 非交易時段 (台/美均收) 且未開啟全天候監控，跳過自動檢查。")
                        self.last_check_time = current_unix

            except Exception as e:
                print(f"監控迴圈發生錯誤: {e}")
            
            # 迴圈固定每分鐘運行一次，以確保不漏掉定時報告
            await asyncio.sleep(60)

    async def run_once(self, mode):
        """執行單次任務 (模式: check, noon, daily)"""
        print(f"執行單次任務: {mode}")
        if mode == "check":
            # 在 One-shot 模式下，如果檢查到沒開盤則直接退出
            if not self.is_market_open() and not self.is_us_market_open() and not self.allow_outside:
                print("非交易時段且未開啟強制檢查，取消本次任務。")
                return
            await self.check_once()
        elif mode == "noon":
            await self.send_noon_report()
        elif mode == "daily":
            await self.send_daily_report()
        elif mode == "us_daily":
            await self.send_us_closing_report()
        else:
            print(f"不支援的模式: {mode}")

    def run_bot(self):
        """啟動 Telegram 機器人常駐模式 (整合背景監控迴圈)"""
        print("Telegram 機器人常駐模式啟動中...")
        self._setup_callbacks()
        
        app = self.notifier.app
        if not app:
            print("無法獲取 Telegram Application，請檢查 Token。")
            return

        async def post_init(application):
            asyncio.create_task(self.run_monitor_loop())
            print("背景監控任務已啟動。")

        app.post_init = post_init
        app.run_polling()

    def _setup_callbacks(self):
        """集中設定 Telegram 指令回呼"""
        self.notifier.set_data_callback(self.get_summary_callback)
        self.notifier.set_alert_callback(self.change_alert_callback)
        self.notifier.set_config_callback(self.change_config_callback)
        self.notifier.set_market_callback(self.get_market_callback)
        self.notifier.set_check_callback(self.check_once)
        self.notifier.set_api_usage_callback(self.get_api_usage_callback)
        self.notifier.set_stock_history_callback(self.get_stock_history_callback)
        self.notifier.set_test_callback(self.test_report_callback)
        self.notifier.set_report_callback(self.get_graphical_report_callback)
        self.notifier.set_stock_chart_callback(self.get_stock_chart_callback)
        self.notifier.set_monitoring_list_callback(self.get_monitoring_limits_callback)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="台美股監控系統")
    parser.add_argument("--mode", choices=["bot", "check", "noon", "daily", "us_daily"], default="bot",
                        help="執行模式: bot (常駐機器人), check (單次檢查), noon (午間報告), daily (台股盤後), us_daily (美股收盤)")
    args = parser.parse_args()

    monitor = MarketMonitor()
    
    if args.mode == "bot":
        monitor.run_bot()
    else:
        # 單次執行模式
        asyncio.run(monitor.run_once(args.mode))

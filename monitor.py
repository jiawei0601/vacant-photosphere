import os
import time
import asyncio
from datetime import datetime, time as dt_time, timezone, timedelta
from dotenv import load_dotenv

from price_fetcher import PriceFetcher
from notion_helper import NotionHelper
from notifier import Notifier
from report_generator import ReportGenerator
from google_vision_ocr import GoogleVisionOCR

load_dotenv()

class MarketMonitor:
    def __init__(self):
        self.fetcher = PriceFetcher()
        self.notion = NotionHelper()
        self.notifier = Notifier()
        self.generator = ReportGenerator()
        self.ocr = GoogleVisionOCR()
        self.interval = int(os.getenv("CHECK_INTERVAL_SECONDS", 600))
        self.allow_outside = os.getenv("ALLOW_OUTSIDE_MARKET_HOURS", "false").lower() == "true"
        self.last_open_date = None
        self.last_close_date = None
        self.last_noon_date = None
        self.last_daily_report_date = None
        self.last_order_stats_date = None
        self.last_check_time = 0
        self.last_inventory_clear_time = 0 # 記錄上次清空庫存的時間
        self.taipei_tz = timezone(timedelta(hours=8))

    def _get_now_taipei(self):
        """獲取目前的台北時間"""
        return datetime.now(self.taipei_tz)

    def is_market_open(self):
        """
        判斷台股是否在交易時段 (09:00 - 13:30)
        週一至週五
        """
        if self.allow_outside:
            return True
            
        now = self._get_now_taipei()
        # 0 為週一, 4 為週五
        if now.weekday() > 4:
            return False
            
        market_start = dt_time(9, 0)
        market_end = dt_time(13, 35) # 稍微多抓一點緩衝
        current_time = now.time()
        
        return market_start <= current_time <= market_end

    async def check_once(self, force=False):
        print(f"[{datetime.now()}] 開始執行價格檢查...")
        
        items = self.notion.get_monitoring_list()
        if not items:
            print("目前沒有要監控的標的。")
            return 0, 0

        success_count = 0
        fail_count = 0
        
        for item in items:
            symbol = item['symbol']
            price_data = self.fetcher.get_last_price(symbol, force=force)
            
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
                    "close": stats.get('close', 0),
                    "change_pct": stats.get('change_pct', 0),
                    "ma20_status": ma_status,
                    "open": stats.get('open', 0),
                    "high": stats.get('high', 0),
                    "low": stats.get('low', 0),
                    "volume": stats.get('volume', 0)
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

    async def change_config_callback(self, interval=None, allow_outside=None):
        """處理來自 Telegram 的系統配置修改請求"""
        if interval is not None:
            self.interval = interval
            print(f"系統檢查間隔已更變為: {self.interval} 秒")
        
        if allow_outside is not None:
            self.allow_outside = allow_outside
            print(f"交易時段外處理已變更為: {self.allow_outside}")

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

    async def inventory_callback(self, image_path, upload_date=None):
        """處理庫存截圖解析與更新"""
        try:
            # --- 新增：清空資料庫邏輯 ---
            import time as py_time
            now_unix = py_time.time()
            # 如果距離上次清空超過 10 分鐘 (600秒)，執行清空
            if now_unix - self.last_inventory_clear_time > 600:
                print("🧹 偵測到新的一波庫存上傳，正在清空舊有資料...")
                self.notion.clear_inventory_database()
                self.last_inventory_clear_time = now_unix

            stocks = self.ocr.extract_stock_info(image_path)
            results = []
            for s in stocks:
                success = self.notion.upsert_inventory_item(
                    s['symbol'], 
                    s['name'], 
                    quantity=s.get('quantity', 0),
                    avg_price=s.get('avg_price', 0.0),
                    profit=s.get('profit', 0),
                    date_str=upload_date
                )
                results.append({
                    "symbol": s['symbol'],
                    "name": s['name'],
                    "quantity": s.get('quantity', 0),
                    "profit": s.get('profit', 0),
                    "status": "處理成功" if success else "處理失敗"
                })
            return results
            return results
        except Exception as e:
            print(f"庫存回調執行失敗: {e}")
            return []

    async def sync_fubon_inventory_callback(self):
        """從富邦 API 同步庫存並更新 Notion"""
        from fubon_helper import FubonHelper
        fubon = FubonHelper()
        
        if not fubon.is_available():
            return "❌ 系統環境未安裝 Fubon Neo SDK，無法執行 API 同步。\n請聯繫管理員安裝 SDK 並配置憑證。"
            
        print("🔄 啟動富邦 API 庫存同步...")
        stocks = fubon.get_inventory()
        
        if not stocks:
            return "❌ 無法從富邦拉取庫存。請檢查：\n1. API Key/Secret 是否正確\n2. 憑證檔案路徑是否正確\n3. 帳號密碼是否正確"
            
        # 清空舊資料
        print("🧹 同步前清空舊有庫存資料...")
        self.notion.clear_inventory_database()
        self.last_inventory_clear_time = time.time()
        
        results = []
        for s in stocks:
            success = self.notion.upsert_inventory_item(
                s['symbol'], 
                s['name'], 
                quantity=s['quantity'],
                avg_price=s['avg_price'],
                profit=s['profit']
            )
            results.append({
                "symbol": s['symbol'],
                "name": s['name'],
                "status": "同步成功" if success else "同步失敗"
            })
            
        fubon.logout()
        
        summary = "✅ **富邦 API 庫存同步結果**\n\n"
        for r in results:
            summary += f"• {r['name']} ({r['symbol']}) - {r['status']}\n"
            
        return summary

    async def get_ocr_usage_report(self):
        """獲取 OCR 使用量報告"""
        if self.ocr:
            return self.ocr.get_monthly_usage_report()
        return "⚠️ OCR 引擎尚未啟動"

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

    async def run_monitor_loop(self):
        """背景執行的監控迴圈"""
        print(f"監控迴圈啟動 (主檢查間隔: {self.interval} 秒，時區: 台北 UTC+8)")
        while True:
            try:
                now = self._get_now_taipei()
                today = now.date()
                curr_time = now.time()
                is_weekday = now.weekday() <= 4

                # 1. 檢查各項定時報告 (不論是否開盤，只要是工作日)
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
                                self.last_noon_date = today

                    # 15:00 盤後綜合大報告 (包含收盤總結、買賣力道、詳細標的數據)
                    if dt_time(15, 0) <= curr_time < dt_time(15, 20):
                        if self.last_daily_report_date != today:
                            report_data = await self.get_report_data(offset=0)
                            
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
                                
                            self.last_daily_report_date = today
                            self.last_close_date = today
                            self.last_order_stats_date = today

                # 2. 處理常規價格檢查
                import time as py_time
                current_unix = py_time.time()
                
                if self.is_market_open():
                    if current_unix - self.last_check_time >= self.interval:
                        print(f"[{now}] 執行自動價格檢查 (間隔: {self.interval}s)...")
                        success, fail = await self.check_once()
                        self.last_check_time = current_unix
                        # 自動檢查完成後發送訊息
                        await self.notifier.send_message(f"✅ 定期價格檢查完成。成功: {success}, 失敗: {fail}")
                else:
                    # 如果不是交易時段，且有記錄過上次檢查時間，則靜默跳過
                    if current_unix - self.last_check_time >= self.interval:
                        print(f"[{now}] 非交易時段且未開啟全天候監控，跳過自動檢查。")
                        self.last_check_time = current_unix

            except Exception as e:
                print(f"監控迴圈發生錯誤: {e}")
            
            # 迴圈固定每分鐘運行一次，以確保不漏掉定時報告
            await asyncio.sleep(60)

    def run(self):
        """啟動程式 (整合 Telegram run_polling)"""
        print("監控系統與 Telegram 機器人啟動中...")
        
        # 串接指令回呼
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
        self.notifier.set_inventory_callback(self.inventory_callback)
        self.notifier.set_ocr_usage_callback(self.get_ocr_usage_report)
        self.notifier.set_fubon_sync_callback(self.sync_fubon_inventory_callback)
        
        # 獲取 Telegram Application
        app = self.notifier.app
        if not app:
            print("無法獲取 Telegram Application，請檢查 Token。")
            return

        # 使用 post_init 來啟動背景監控任務
        async def post_init(application):
            asyncio.create_task(self.run_monitor_loop())
            print("背景監控任務已啟動。")

        # 啟動 Telegram 機器人 (這會阻塞並處理所有事件)
        app.post_init = post_init
        app.run_polling()

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()
